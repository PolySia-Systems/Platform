"""Concrete disabled-by-default operational wiring for the standard CTF V2 route.

All real I/O is behind SessionNetwork. The owning deployment entry point must
verify run authority before importing/calling this module. No account setup,
credential derivation, approvals, redemption, transfers or fallback account.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from functools import partial
from importlib.metadata import version as distribution_version
from typing import Any
from urllib.parse import urlsplit

import httpx
from polymarket import ApiKeyCreds, AsyncSecureClient
from pydantic import TypeAdapter

from polysia.adapters.polymarket.diagnostics import ReadRetryPolicy
from polysia.adapters.polymarket.geoblock import GeoblockStatus
from polysia.adapters.polymarket.mappers import PolymarketMarketMapper
from polysia.adapters.polymarket.secure import PolymarketSecureAdapter
from polysia.adapters.polymarket.session_account import (
    ExactAccountMapping,
    ExactSessionAccountReader,
)
from polysia.adapters.polymarket.session_chain import CTFChainReader, ReadOnlyRPC
from polysia.adapters.polymarket.session_network import SessionNetwork, SessionPublicJSON
from polysia.adapters.polymarket.session_sdk import (
    assert_exact_prepared,
    confine_sdk_http,
    require_sdk_scope,
)
from polysia.adapters.polymarket.session_source import CorroboratedSessionSource
from polysia.application.ports.cancellation import OrderTradeEvidence
from polysia.application.ports.financial_session import RequestCharge
from polysia.application.services.cohort_intents import admit_cohort_opportunity
from polysia.application.services.financial_session import (
    FinancialSessionCoordinator,
    session_ledger,
)
from polysia.application.services.follower_qualification import (
    FollowerSample,
    estimate_forward_price,
    produce_qualification,
)
from polysia.application.services.source_cohort import SharedCohortSelection
from polysia.config.settings import AppSettings, TradingMode
from polysia.control.scoped_operations import ScopedPreview
from polysia.control.service import ControlService
from polysia.deployment.financial_session_runtime import (
    SessionRuntimeConfig,
    publish_redacted,
    read_bound_json,
    validate_capacity_record,
)
from polysia.deployment.session_supervision import CheckpointPublisher
from polysia.domain.copytrading.continuous_shadow import calculate_verified_taker_fee
from polysia.domain.copytrading.financial_allocation import pending_entry_debit
from polysia.domain.financial_session import (
    ConfirmedSessionFill,
    PositionTrigger,
    SessionAuthorization,
    SessionBlocked,
    SessionMode,
    SessionOpportunity,
    digest,
)
from polysia.domain.wallet_intelligence.source_cohort import qualification_reasons
from polysia.execution.cancellation_finality import CancellationFinalityConfig
from polysia.execution.financial_session import LiveSessionExecution
from polysia.execution.live_broker import LiveBroker
from polysia.monitoring.financial_session import financial_session_view
from polysia.monitoring.latency_intelligence.contract import RuntimeIdentity
from polysia.monitoring.latency_intelligence.policy import LatencyPolicy
from polysia.monitoring.latency_intelligence.recorder import LatencyRecorder
from polysia.monitoring.latency_intelligence.report import (
    build_latency_performance_intelligence,
    financial_session_latency_view,
)
from polysia.monitoring.operational_session import operational_capabilities
from polysia.monitoring.process_capacity import ProcessCapacity
from polysia.monitoring.session_incidents import SessionIncidents
from polysia.risk.checks import RiskEngine
from polysia.security.session_authority import SessionCustody
from polysia.storage.atomic_files import read_publication_bytes
from polysia.storage.console_commands import ConsoleCommandStore
from polysia.storage.financial_session import FinancialSessionJournal
from polysia.storage.latency_telemetry import LatencyTelemetryStore

ZERO = Decimal("0")


class _OptionalInputUnavailable(SessionBlocked):
    """An input failed before a decision reached the financial coordinator."""


def _qualification_ready(
    selection: SharedCohortSelection,
    samples: tuple[FollowerSample, ...],
    authority: SessionAuthorization,
    confidence: Decimal,
) -> bool:
    policy = selection.selection_policy
    if policy is None or not selection.selected_wallet_ids:
        return False
    for wallet in selection.selected_wallet_ids:
        evidence = next(
            (row for row in selection.qualification_evidence if row.wallet_id == wallet), None
        )
        if evidence is None or qualification_reasons(evidence, policy, now=selection.selected_at):
            return False
        try:
            recomputed = produce_qualification(
                samples,
                wallet=wallet,
                selection_start=evidence.selection_start,
                selection_end=evidence.selection_end,
                available_at=evidence.available_at,
                evaluation_start=evidence.evaluation_start,
                confidence=confidence,
            )
            estimates = [
                estimate_forward_price(
                    samples,
                    wallet=wallet,
                    token=instrument.token,
                    selection_end=evidence.selection_end,
                    available_at=evidence.available_at,
                    confidence=confidence,
                    minimum_samples=policy.minimum_samples,
                )
                for instrument in authority.instruments
            ]
        except SessionBlocked:
            return False
        if recomputed != evidence or any(row.fair_price is None for row in estimates):
            return False
    return True


class _OperationalSettings(AppSettings):
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Any,
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        # The signed frozen configuration, rather than ambient dotenv overrides,
        # owns financial settings. Secret references are resolved separately.
        return (init_settings,)


class _ExactOperationalAdapter(PolymarketSecureAdapter):
    def __init__(self, *args: Any, config: SessionRuntimeConfig, **kwargs: Any) -> None:
        self.session_config = config
        super().__init__(*args, **kwargs)

    async def prepare_limit_order(self, **request: Any) -> Any:
        if request.get("builder_code") is not None:
            raise SessionBlocked("builder_fee_route_not_in_session_scope")
        prepared = await super().prepare_limit_order(**request)
        assert_exact_prepared(
            prepared,
            exchange=self.session_config.exchange,
            signer=self.session_config.account_mapping.signer,
            funder=self.session_config.account_mapping.funder,
            request=request,
        )
        return prepared


class _BudgetedExecution(LiveSessionExecution):
    def __init__(self, *args: Any, network: SessionNetwork, **kwargs: Any) -> None:
        self.network = network
        super().__init__(*args, **kwargs)

    def register_bound(self, action: str, charge: RequestCharge) -> None:
        self.network.register_bound(action, charge)

    async def observe_account(self, instrument: Any) -> Any:
        with self.network.action("ACCOUNT"):
            return await super().observe_account(instrument)

    async def submit(self, *args: Any, **kwargs: Any) -> Any:
        financial_action = "ENTRY" if args[0].request.side == "BUY" else "REDUCE"
        deadline = min(
            args[0].approved_at, args[1].market_observed_at, args[2].observed_at
        ) + timedelta(milliseconds=self.max_evidence_age_ms)
        with self.network.action("SUBMIT", financial_action, evidence_deadline=deadline):
            return await super().submit(*args, **kwargs)

    async def cancel(self, order_id: str, *, before_cancel: Callable[[], None]) -> None:
        with self.network.action("CANCEL", "CANCEL"):
            await super().cancel(order_id, before_cancel=before_cancel)


class _CancellationReader:
    def __init__(
        self,
        adapter: PolymarketSecureAdapter,
        account: ExactSessionAccountReader,
        network: SessionNetwork,
    ) -> None:
        self.adapter, self.account, self.network = adapter, account, network

    async def observe_open_orders(self, *, order_id: str | None = None) -> Any:
        with self.network.action("CANCELLATION_READ"):
            return await self.adapter.observe_open_orders(order_id=order_id)

    async def observe_order_detail(self, *, order_id: str) -> Any:
        with self.network.action("CANCELLATION_READ"):
            return await self.adapter.observe_order_detail(order_id=order_id)

    async def observe_order_trades(self, *, order_id: str, token_id: str) -> Any:
        with self.network.action("CANCELLATION_READ"):
            block = await self.account.chain.finalized()
            fills = await self.account.chain.fills(
                self.account.mapping.funder, block=block, observed_at=self.account.clock()
            )
            return tuple(
                OrderTradeEvidence(
                    fill.occurrence.identity,
                    order_id,
                    token_id,
                    "CONFIRMED",
                    fill.shares,
                    fill.collateral / fill.shares,
                )
                for fill in fills
                if fill.order_hash == order_id.lower()
                and fill.occurrence.instrument.token == token_id
            )

    async def observe_position_size(self, *, token_id: str) -> Decimal:
        with self.network.action("CANCELLATION_READ"):
            block = await self.account.chain.finalized()
            return await self.account.chain.token_balance(
                self.account.mapping.funder, token_id, block=block
            )


class _Eligibility:
    def __init__(self, client: httpx.AsyncClient, clock: Callable[[], datetime]) -> None:
        self.client, self.clock = client, clock

    async def assert_allowed(self) -> GeoblockStatus:
        response = await self.client.get("https://polymarket.com/api/geoblock")
        response.raise_for_status()
        body = response.json()
        if body.get("blocked") is not False:
            raise SessionBlocked("venue_geography_ineligible_or_unknown")
        return GeoblockStatus("allowed", self.clock(), False)

    async def read_clock_drift(self) -> Decimal:
        before = self.clock()
        response = await self.client.get("https://clob.polymarket.com/time")
        response.raise_for_status()
        return (
            Decimal(str(response.json()))
            - (Decimal(str(before.timestamp())) + Decimal(str(self.clock().timestamp()))) / 2
        )


class OperationalSession:
    def __init__(
        self,
        config: SessionRuntimeConfig,
        coordinator: FinancialSessionCoordinator,
        network: SessionNetwork,
        client: Any,
        http: httpx.AsyncClient,
        account: ExactSessionAccountReader,
        source: CorroboratedSessionSource,
        selection: SharedCohortSelection,
        samples: tuple[FollowerSample, ...],
        custody: SessionCustody,
        clock: Callable[[], datetime],
    ) -> None:
        self.config, self.coordinator, self.network = config, coordinator, network
        self.client, self.http, self.account, self.source = client, http, account, source
        self.selection, self.samples, self.custody, self.clock = selection, samples, custody, clock
        self.mapper = PolymarketMarketMapper()
        self.cancellation_evidence: Any = None
        self.discovery_retry_at: datetime | None = None
        self.discovery_failures = 0
        self.input_status = "UNKNOWN"
        self.process_capacity = ProcessCapacity()
        self.capacity_evidence: dict[str, Any] = {}
        self.incidents = SessionIncidents(config.incident_path, clock=clock)
        self.incidents.initialize()
        self.source_verified_at: datetime | None = None
        self.capacity_verified = False
        self.qualification_verified = _qualification_ready(
            selection, samples, coordinator.authority, config.estimator_confidence
        )
        self.commands = ConsoleCommandStore(config.commands_path)
        self.commands.retire_scoped_claims(
            targets=frozenset({coordinator.authority.run_id + ":drain"})
        )

    async def start(self) -> None:
        await self.reconcile()
        self._supervise()
        self.coordinator.set_mode(
            SessionMode.RUNNING
            if (
                not self.coordinator.journal.read().get("entry_stop_latched")
                and self.clock() < self.coordinator.authority.expires_at
            )
            else SessionMode.DRAIN
        )

    def process_controls(self) -> None:
        target = self.coordinator.authority.run_id + ":drain"

        def execute(preview: ScopedPreview) -> dict[str, Any]:
            if preview.operation != "session.drain" or preview.target != target:
                raise SessionBlocked("worker_control_scope_denied")
            self.coordinator.drain_entries(receipt=preview.fingerprint)
            return {"effect": "OBSERVED", "mode": "DRAIN", "entry_stop_latched": True}

        for key in self.commands.pending_scoped(
            targets=frozenset({target}), operations=frozenset({"session.drain"})
        ):
            ControlService.execute_scoped(
                self.commands, idempotency_key=key, now=self.clock(), execute=execute
            )

    def _supervise(self) -> None:
        coordinator = self.coordinator
        row = self.custody.require_current(
            coordinator.authority, now=self.clock(), checkpoint=coordinator.journal.checkpoint()
        )
        coordinator.supervise(
            evidence_id=digest((row["supervised_at"], row["checkpoint"])), healthy=True
        )

    async def reconcile(self) -> None:
        coordinator = self.coordinator
        coordinator._charge("ACCOUNT", protective=True)
        with coordinator.latency.stage("account_reconciliation"):
            observation = await coordinator.execution.observe_account(
                coordinator.authority.instruments[0]
            )
        orders = coordinator.journal.read()["orders"]
        bound = [(identity, row) for identity, row in orders.items() if row["order_id"]]
        for identity, row in bound:
            fills = self._confirmed(identity, row)
            quantity = sum((fill.shares for fill in fills), ZERO)
            finality = "CONFIRMED_FILL" if quantity == Decimal(row["shares"]) else "OPEN"
            coordinator.apply_order_evidence(
                identity,
                order_id=row["order_id"],
                fills=fills,
                finality=finality,
                evidence_id=observation.evidence_id,
                account=observation,
                _defer_account_reconciliation=True,
            )
        for identity, row in coordinator.journal.read()["orders"].items():
            if row["state"] in {"ACCEPTED", "PARTIAL_FILL"} and row["order_id"] not in (
                observation.open_order_ids or ()
            ):
                coordinator.begin_finality_observation(identity)
                row = coordinator.journal.read()["orders"][identity]
            if row["state"] == "CANCEL_PENDING":
                await coordinator.reconcile_cancellation(
                    identity,
                    evidence=self.cancellation_evidence,
                    config=CancellationFinalityConfig(
                        maximum_observations=2,
                        required_clean_observations=2,
                        observation_interval_seconds=0,
                        timeout_seconds=self.config.request_timeout_seconds,
                    ),
                    sleeper=asyncio.sleep,
                    confirmed_fills=partial(self._confirmed, identity, row),
                )
        observation = self.account.last_observation or observation
        for event in self.account.last_redemptions:
            coordinator.observe_redemption(event, observation)
        coordinator.reconcile(observation)

    async def cancel_draining_orders(self) -> None:
        state = self.coordinator.journal.read()
        if state["mode"] != "RUNNING" or self.clock() >= self.coordinator.authority.expires_at:
            for identity, row in state["orders"].items():
                if row["state"] in {"ACCEPTED", "PARTIAL_FILL"}:
                    await self.coordinator.cancel(identity)

    def _confirmed(self, identity: str, row: dict[str, Any]) -> tuple[ConfirmedSessionFill, ...]:
        return tuple(
            ConfirmedSessionFill(
                fill.occurrence.identity,
                identity,
                row["order_id"],
                fill.occurrence.instrument.token,
                fill.occurrence.side,
                fill.collateral / fill.shares,
                fill.shares,
                fill.fee,
                fill.occurrence.occurred_at,
                fill.collateral,
                chain_order=fill.chain_order,
            )
            for fill in self.account.last_fills
            if fill.order_hash == row["order_id"].lower()
        )

    async def tick(self) -> dict[str, Any]:
        coordinator = self.coordinator
        try:
            self.process_controls()
            self._supervise()
            await self.reconcile()
            await self.cancel_draining_orders()
            # Protective work is examined before discovery and remains monitored
            # even when a leader is absent from new entry selection.
            await self.position_triggers()
            state = coordinator.journal.read()
            if (
                state["mode"] == "RUNNING"
                and self.clock() < coordinator.authority.expires_at
                and (self.discovery_retry_at is None or self.clock() >= self.discovery_retry_at)
            ):
                try:
                    await self._source_entries()
                except _OptionalInputUnavailable:
                    # Prove mandatory persistence and independent custody are
                    # still current before classifying an input-only failure.
                    coordinator.journal.read()
                    self.network.guard()
                    self.source_verified_at = None
                    self.discovery_failures += 1
                    self.discovery_retry_at = self.clock() + timedelta(
                        seconds=min(30, 2 ** min(5, self.discovery_failures))
                    )
                    self.input_status = "DEGRADED_SOURCE_ENTRIES_SHED"
                else:
                    self.discovery_failures = 0
                    self.discovery_retry_at = None
                    self.input_status = "VERIFIED"
        except Exception as error:
            self.source_verified_at = None
            with suppress(OSError, sqlite3.Error):
                self.incidents.record(
                    "financial_ambiguity",
                    scope=coordinator.authority.run_id,
                    reason_code=type(error).__name__,
                    next_action="Inspect exact account/custody evidence; do not resend",
                )
            with suppress(Exception):
                coordinator.set_mode(SessionMode.DRAIN)
            raise SessionBlocked("operational_tick_blocked:" + type(error).__name__) from error
        return self.publish()

    async def _source_entries(self) -> None:
        coordinator = self.coordinator
        now = self.clock()
        start = max(
            self.selection.selected_at,
            now - timedelta(seconds=coordinator.authority.max_evidence_age_seconds),
        )
        for wallet_id, wallet in self.config.source_wallets:
            try:
                coordinator._charge("SOURCE", protective=False)
                with self.network.action("SOURCE"):
                    fills = await self.source.read(
                        wallet=wallet, wallet_id=wallet_id, start=start, end=now
                    )
            except (httpx.HTTPError, ValueError, KeyError, SessionBlocked) as error:
                raise _OptionalInputUnavailable("source_window_unavailable") from error
            self.source_verified_at = self.clock()
            for fill in fills:
                event = fill.occurrence
                if event.side != "BUY":
                    # Mirror reductions require an independently evidenced leader
                    # baseline, not absolute leader shares. See mirror_reduction.
                    await self.mirror_reduction(fill)
                    continue
                if not self.qualification_verified:
                    continue
                opportunity = await self._entry_opportunity(event)
                if opportunity is not None:
                    await coordinator.submit(
                        admit_cohort_opportunity(self.selection, opportunity, now=self.clock())
                    )

    async def _market(self, instrument: Any, *, protective: bool) -> tuple[Any, Any]:
        self.coordinator._charge("MARKET", protective=protective)
        with self.network.action("MARKET"):
            raw_market = await self.client.get_market(id=instrument.market, include_tag=True)
            raw_book = await self.client.get_order_book(asset_id=instrument.token)
        market, book = self.mapper.to_details(raw_market), self.mapper.to_order_book(raw_book)
        if (
            market.condition_id != instrument.market
            or book.token_id != instrument.token
            or market.active is not True
            or market.closed is not False
            or market.accepting_orders is not True
            or book.negative_risk
            or not any(item.token_id == instrument.token for item in market.outcomes)
            or market.end_date is None
            or book.best_ask is None
            or book.best_bid is None
            or not 0
            <= (self.clock() - book.timestamp).total_seconds()
            <= self.coordinator.authority.max_evidence_age_seconds
        ):
            raise SessionBlocked("fresh_exact_market_or_route_unavailable")
        return market, book

    async def _entry_opportunity(self, event: Any) -> SessionOpportunity | None:
        try:
            market, book = await self._market(event.instrument, protective=False)
        except (httpx.HTTPError, ValueError, KeyError, SessionBlocked) as error:
            raise _OptionalInputUnavailable("entry_market_unavailable") from error
        evidence = next(
            (
                item
                for item in self.selection.qualification_evidence
                if item.wallet_id == event.wallet
            ),
            None,
        )
        if evidence is None:
            return None
        estimate = estimate_forward_price(
            self.samples,
            wallet=event.wallet,
            token=event.instrument.token,
            selection_end=evidence.selection_end,
            available_at=evidence.available_at,
            confidence=self.config.estimator_confidence,
            minimum_samples=self.selection.selection_policy.minimum_samples
            if self.selection.selection_policy
            else 20,
        )
        price = book.best_ask.price
        fee = calculate_verified_taker_fee(market, price=price, size=Decimal(1))
        if fee.amount is None:
            raise SessionBlocked("policy_fee_unknown")
        fee_bound = price * self.coordinator.authority.fee_rate
        if fee.amount > fee_bound:
            raise SessionBlocked("verified_entry_fee_exceeds_authorized_reservation")
        state = self.coordinator.journal.read()
        ledger = session_ledger(state)
        reserved = pending_entry_debit(state)
        entered = any(
            row["wallet"] == event.wallet
            and row["token"] == event.instrument.token
            and row["side"] == "BUY"
            for row in state["orders"].values()
        )
        shares = self.config.policy.entry_size(
            cash=ledger.cash,
            reserved_debit=reserved,
            price=price,
            fee_per_share=fee_bound,
            share_quantum=self.config.policy.quantity_quantum,
            minimum_shares=book.minimum_order_size,
            depth=book.best_ask.size,
            entered_before=entered,
        )
        if not shares:
            return None
        return SessionOpportunity(
            event,
            self.config.policy.version,
            self.config.policy.version,
            price,
            shares,
            estimate.fair_price,
            estimate.uncertainty,
            fee_bound,
            book.best_ask.size,
            book.best_bid.size,
            book.timestamp,
            market.end_date,
            True,
            False,
            "frozen empirical forward-price policy; Risk retains final authority",
            policy_digest=self.config.policy.fingerprint,
        )

    async def mirror_reduction(self, fill: Any) -> None:
        # A baseline is required from the exact previous block plus all preceding
        # CTF transfers in the block; account/route ambiguity denies advice.
        event = fill.occurrence
        before = fill.leader_position_before
        if before is None or before <= 0:
            raise SessionBlocked("leader_reduction_baseline_unknown")
        await self._exit_for_owner(
            event.wallet, event.instrument, leader_fill=fill, leader_before=before
        )

    async def position_triggers(self) -> None:
        for owner in self.coordinator.allocation_view().values():
            if owner["quantity"] > 0:
                instrument = next(
                    item
                    for item in self.coordinator.authority.instruments
                    if item.token == owner["token"]
                )
                await self._exit_for_owner(owner["wallet"], instrument)

    async def _exit_for_owner(
        self,
        wallet: str,
        instrument: Any,
        *,
        leader_fill: Any = None,
        leader_before: Decimal | None = None,
    ) -> None:
        owner = next(
            (
                row
                for row in self.coordinator.allocation_view().values()
                if row["wallet"] == wallet
                and row["token"] == instrument.token
                and row["policy"] == self.config.policy.fingerprint
            ),
            None,
        )
        if owner is None or owner["quantity"] <= 0:
            return
        market, book = await self._market(instrument, protective=True)
        fee = calculate_verified_taker_fee(market, price=book.best_bid.price, size=Decimal(1))
        if fee.amount is None:
            raise SessionBlocked("protective_fee_unknown")
        fee_bound = book.best_bid.price * self.coordinator.authority.fee_rate
        if fee.amount > fee_bound:
            raise SessionBlocked("verified_exit_fee_exceeds_authorized_reservation")
        trigger, shares = self.config.policy.exit_decision(
            held=owner["quantity"],
            reserved_sell=owner["pending_sell"],
            cost_basis=owner["cost_basis"],
            bid=book.best_bid.price,
            exit_fee_per_share=fee_bound,
            entry_fees=owner["fees"],
            opened_at=datetime.fromisoformat(owner["opened_at"]),
            now=self.clock(),
            leader_before=leader_before,
            leader_reduction=None if leader_fill is None else leader_fill.shares,
            share_quantum=self.config.policy.quantity_quantum,
        )
        if not shares:
            return
        quantum = self.config.policy.quantity_quantum
        executable_shares = (min(shares, book.best_bid.size) / quantum).to_integral_value(
            rounding=ROUND_DOWN
        ) * quantum
        if executable_shares < book.minimum_order_size or executable_shares <= 0:
            return
        event = (
            leader_fill.occurrence
            if trigger == "LEADER_REDUCTION"
            else PositionTrigger(
                digest((owner["account"], owner["token"], owner["wallet"], owner["opened_at"])),
                self.config.policy.fingerprint,
                trigger,
                wallet,
                instrument,
                self.clock(),
                self.clock(),
                self.clock(),
                digest((book.book_hash, book.timestamp)),
                position_revision=digest((owner["quantity"], owner["cost_basis"])),
            )
        )
        opportunity = SessionOpportunity(
            event,
            self.config.policy.version,
            self.config.policy.version,
            book.best_bid.price,
            executable_shares,
            book.best_bid.price,
            ZERO,
            fee_bound,
            book.best_ask.size,
            book.best_bid.size,
            book.timestamp,
            market.end_date,
            True,
            trigger == "LEADER_REDUCTION",
            "attempted bounded policy exit",
            exit_trigger=trigger,
            policy_digest=self.config.policy.fingerprint,
            leader_position_before=leader_before,
            leader_reduced_shares=None if leader_fill is None else leader_fill.shares,
        )
        await self.coordinator.submit(opportunity)

    def publish(self) -> dict[str, Any]:
        latency = None
        recorder = self.coordinator.latency.recorder
        if recorder is not None:
            # Optional diagnostics have a separate fixed disk/buffer allocation.
            # At its ceiling, the existing bounded recorder drops samples.
            with suppress(OSError, ValueError, sqlite3.Error):
                if shutil.disk_usage(
                    recorder.store.path.parent
                ).free >= self.config.minimum_free_disk_bytes + 16_777_216 and (
                    not recorder.store.path.exists()
                    or recorder.store.path.stat().st_size < 16_777_216
                ):
                    recorder.flush()
                    latency = financial_session_latency_view(
                        build_latency_performance_intelligence(
                            recorder.store,
                            now=self.clock(),
                            health=recorder.health(),
                            session_run_id=self.coordinator.authority.run_id,
                        )
                    )
        view = financial_session_view(
            self.coordinator.journal.read(),
            self.coordinator.authority,
            now=self.clock(),
            trading_mode=TradingMode.LIVE,
            latency=latency,
            discovery_counts={
                "discovered": len(self.selection.candidates),
                "qualified": len(self.selection.selected_wallet_ids),
                "monitored": len(self.config.source_wallets) if self.source_verified_at else 0,
            },
            sources=[
                {
                    "source": "V2 discovery plus finalized CTF occurrences",
                    "status": self.input_status,
                    "phase": "BOUNDED_POLLING",
                    "age_seconds": None
                    if self.source_verified_at is None
                    else (self.clock() - self.source_verified_at).total_seconds(),
                    "gaps": [],
                    "next_action": "Qualify retained follower evidence; "
                    "missing edge remains unknown",
                }
            ],
        )
        now = self.clock()
        state = self.coordinator.journal.read()
        custody = self.custody.snapshot(self.coordinator.authority.fingerprint)
        if custody["stopped"] or custody["revoked"]:
            view["status"] = "STOP"
            view["new_entries"] = "BLOCKED"
        publication: dict[str, Any] = {
            "version": "operational-session-publication/v1",
            "financial_session": view,
            "selection": self.selection.to_console_dict(),
            "capacity": self.network.observation(),
            "process_resources": self.process_capacity.observation(
                self.config.financial_path.parent
            ),
            "capacity_qualification": self.capacity_evidence,
            "backup": {
                "mode": "SEPARATE_FINANCIAL_RECOVERY"
                if custody["reason"] == "supervisor_checks_passed"
                else "UNPROTECTED_OR_UNKNOWN",
                "last_verified_at": custody["supervised_at"],
                "independent_restore": "CHECKED_BY_SUPERVISOR"
                if custody["reason"] == "supervisor_checks_passed"
                else "UNKNOWN",
            },
            "source_status": {
                "status": self.input_status,
                "retry_at": self.discovery_retry_at,
                "failures": self.discovery_failures,
                "cohort_changed": False,
            },
            "published_at": now.isoformat(),
            "last_attempt": now.isoformat(),
            "status": "STOPPED"
            if custody["stopped"]
            else ("DRAINING" if state["mode"] != "RUNNING" else "OBSERVING"),
            "capabilities": operational_capabilities(
                state,
                self.coordinator.authority,
                custody,
                now=now,
                capacity_verified=self.capacity_verified,
                source_verified_at=self.source_verified_at,
                capacity_observed_at=datetime.fromisoformat(self.capacity_evidence["observed_at"]),
                capacity_expires_at=datetime.fromisoformat(self.capacity_evidence["expires_at"]),
                qualification_verified=self.qualification_verified
                and self.selection.selection_policy is not None
                and self.clock() - self.selection.selected_at
                <= self.selection.selection_policy.freshness,
                qualification_observed_at=self.selection.selected_at,
            ),
            "active_account": {
                "identity": self.coordinator.binding.account,
                "status": "VERIFIED" if state["reconciliation_ok"] else "UNKNOWN",
                "observed_at": state["reconciled_at"],
            },
            "copy_policy": {
                "effective": asdict(self.config.policy),
                "staged": None,
                "digest": self.config.policy.fingerprint,
            },
            "incidents": self.incidents.projection(),
        }
        publication["selection"]["monitored_count"] = (
            len(self.config.source_wallets) if (self.source_verified_at is not None) else None
        )
        with suppress(OSError, ValueError):
            publication["shadow_lab"] = json.loads(
                read_publication_bytes(
                    self.config.publication_path.parent / "shadow-lab.json", maximum_bytes=100_000
                )
            )
        try:
            publish_redacted(self.config.publication_path, publication)
            publish_redacted(
                self.config.publication_path.parent / "publisher-status.json",
                {
                    "status": "OK",
                    "checked_at": now.isoformat(),
                    "scope": self.coordinator.authority.run_id,
                },
            )
            publication["publication_status"] = "PUBLISHED"
        except OSError:
            publication["publication_status"] = "FAILED_OPTIONAL_VIEW"
        return publication

    async def close(self) -> None:
        try:
            await self.client.close()
            await self.http.aclose()
        finally:
            self.coordinator.journal.close()


async def create_live_session(
    config: SessionRuntimeConfig,
    authority: SessionAuthorization,
    custody: SessionCustody,
    *,
    clock: Callable[[], datetime],
) -> OperationalSession:
    capacity_record = validate_capacity_record(config, now=clock())
    if distribution_version("polymarket-client") != "0.13.0":
        raise SessionBlocked("composed_SDK_contract_requires_reviewed_0_13_0")
    mapping = ExactAccountMapping(**asdict(config.account_mapping))
    require_sdk_scope(config, authority.instruments)
    selection = SharedCohortSelection.from_dict(
        read_bound_json(config.cohort_path, config.cohort_file_digest)
    )
    selection.require_integrity()
    if frozenset(selection.selected_wallet_ids) != authority.wallets:
        raise SessionBlocked("authority_cohort_mismatch")
    sample_payload = read_bound_json(
        config.follower_samples_path, config.follower_samples_file_digest
    )
    samples = TypeAdapter(tuple[FollowerSample, ...]).validate_python(
        sample_payload.get("samples") if isinstance(sample_payload, dict) else sample_payload,
        extra="forbid",
    )
    journal = FinancialSessionJournal(config.financial_path, config.witness_root, authority)
    publisher = CheckpointPublisher(
        authority,
        custody,
        config.outbox_path,
        clock=clock,
        timeout_seconds=config.checkpoint_handshake_seconds,
    )
    journal.after_commit = publisher.publish
    journal.open(checkpoint=custody.recovery_checkpoint(authority))
    http = client = None
    try:

        def guard() -> None:
            if config.fingerprint != authority.binding.configuration:
                raise SessionBlocked("active_configuration_changed")
            if (
                not datetime.fromisoformat(capacity_record["observed_at"])
                <= clock()
                < (datetime.fromisoformat(capacity_record["expires_at"]))
            ):
                raise SessionBlocked("capacity_qualification_expired")
            custody.require_current(authority, now=clock(), checkpoint=journal.checkpoint())

        rpc = urlsplit(config.rpc_url)
        if rpc.scheme != "https" or rpc.username or rpc.password or rpc.query:
            raise SessionBlocked("explicit_nonsecret_HTTPS_RPC_required")
        origins = frozenset(
            {
                "https://data-api.polymarket.com",
                "https://gamma-api.polymarket.com",
                "https://clob.polymarket.com",
                "https://polymarket.com",
                f"https://{rpc.netloc}",
            }
        )
        network = SessionNetwork(
            journal,
            allowed_origins=origins,
            maximum_response_bytes=config.maximum_response_bytes,
            maximum_queued=config.maximum_queued,
            timeout_seconds=config.request_timeout_seconds,
            guard=guard,
            clock=clock,
            rpc_url=config.rpc_url,
            minimum_free_disk_bytes=config.minimum_free_disk_bytes,
        )
        http = httpx.AsyncClient(
            transport=network.transport(),
            follow_redirects=False,
            timeout=config.request_timeout_seconds,
        )
        # Read secrets only after every financial/authority/identity/custody gate.
        private_key = os.environ.get(config.private_key_reference)
        credentials_json = os.environ.get(config.api_credentials_reference)
        if not private_key or not credentials_json:
            raise SessionBlocked("preprovisioned_account_credentials_missing")
        try:
            credentials = ApiKeyCreds.model_validate(json.loads(credentials_json))
        except ValueError, TypeError:
            raise SessionBlocked("preprovisioned_account_credentials_invalid") from None
        # Pinned SDK private bootstrap intentionally skips credential derivation,
        # validation network and automatic wallet setup. Contract-tested on upgrades.
        try:
            client = await AsyncSecureClient._create(
                private_key=private_key,
                wallet=mapping.funder,
                credentials=credentials,
                validate_credentials=False,
            )
        except Exception:
            raise SessionBlocked("mapped_SDK_bootstrap_failed") from None
        await confine_sdk_http(
            client,
            network.transport,
            rpc_url=config.rpc_url,
            timeout=config.request_timeout_seconds,
        )
        chain = CTFChainReader(
            ReadOnlyRPC(http, config.rpc_url),
            exchange=config.exchange,
            ctf=config.ctf,
            collateral=mapping.collateral,
            instruments=authority.instruments,
        )
        account = ExactSessionAccountReader(
            client,
            chain,
            mapping,
            maximum_pages=config.maximum_pages,
            maximum_age_seconds=authority.max_evidence_age_seconds,
            clock=clock,
            collateral_adapter=config.collateral_adapter,
            recognition_since=authority.starts_at,
        )
        account.require_identity()
        eligibility = _Eligibility(http, clock)

        async def factory(*, private_key: str, wallet: str | None) -> Any:
            return client

        adapter = _ExactOperationalAdapter(
            config=config,
            client_factory=factory,
            private_key_env=config.private_key_reference,
            funder_address_env="",
            wallet_address_env="",
            signature_type_env="",
            read_retry_policy=ReadRetryPolicy(1),
            server_time_reader=eligibility,
        )
        await adapter.connect()
        settings = _OperationalSettings(
            trading_mode=TradingMode.LIVE,
            live_trading_enabled=True,
            polymarket_live_token_allowlist=tuple(chain.instruments),
            polymarket_live_max_order_size=config.maximum_order_shares,
            polymarket_live_max_order_notional=authority.max_order_all_in,
            polymarket_live_max_open_orders=authority.max_concurrent_orders,
        )
        risk = RiskEngine(limits=config.risk_limits)
        broker = LiveBroker(
            adapter=adapter,
            risk_engine=risk,
            settings=settings,
            allowed_token_ids=tuple(chain.instruments),
            geoblock_check=eligibility,
            clock=clock,
        )

        async def protective_eligibility(order_id: str) -> bool:
            guard()
            account.require_identity()
            await eligibility.assert_allowed()
            return True

        charges = {
            name: RequestCharge(count, count * config.maximum_response_bytes, ZERO)
            for name, count in config.per_action_requests
        }
        execution = _BudgetedExecution(
            broker,
            account_reader=account.observe,
            charges={
                key: charges[key] for key in ("ACCOUNT", "SUBMIT", "CANCEL", "CANCELLATION_READ")
            },
            acknowledgement=True,
            clock=clock,
            max_evidence_age_ms=authority.max_evidence_age_seconds * 1000,
            protective_eligibility=protective_eligibility,
            network=network,
        )
        execution.charges.update(charges)
        coordinator = FinancialSessionCoordinator(
            journal,
            execution,
            risk,
            binding=authority.binding,
            clock=clock,
            trading_mode=TradingMode.LIVE,
            independent_guard=guard,
            copy_policy=config.policy,
            telemetry=LatencyRecorder(
                LatencyTelemetryStore(config.incident_path.with_suffix(".latency.sqlite3")),
                RuntimeIdentity(
                    host_id=config.host,
                    deploy_sha=config.release,
                    configuration_version=config.fingerprint,
                    policy_version=config.policy.fingerprint,
                    venue_id="polymarket",
                ),
                policy=LatencyPolicy(buffer_capacity=128, flush_batch_size=64),
                wall_clock=clock,
            ),
        )
        session = OperationalSession(
            config,
            coordinator,
            network,
            client,
            http,
            account,
            CorroboratedSessionSource(
                SessionPublicJSON(http), chain, maximum_pages=config.maximum_pages, clock=clock
            ),
            selection,
            samples,
            custody,
            clock,
        )
        session.cancellation_evidence = _CancellationReader(adapter, account, network)
        session.capacity_evidence = capacity_record
        session.capacity_verified = True
        return session
    except BaseException:
        if client is not None:
            await client.close()
        if http is not None:
            await http.aclose()
        journal.close()
        raise
