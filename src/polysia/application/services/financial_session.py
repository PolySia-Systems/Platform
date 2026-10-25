"""One account, one bounded financial session; no authority issuer or scheduler."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict, replace
from datetime import datetime
from decimal import Decimal
from time import monotonic_ns
from typing import Any

from polysia.application.ports.cancellation import CancellationEvidencePort
from polysia.application.ports.financial_session import (
    BudgetedCancellationEvidence,
    SessionExecutionPort,
)
from polysia.config.settings import TradingMode
from polysia.domain.financial_session import (
    AccountObservation,
    ApprovedSessionLimit,
    ConfirmedSessionFill,
    RuntimeBinding,
    SessionAuthorization,
    SessionBlocked,
    SessionLimitRequest,
    SessionMode,
    SessionOpportunity,
    decimal_value,
    digest,
    utc,
)
from polysia.domain.orders.models import OrderIntent
from polysia.execution.cancellation_finality import (
    CancellationFinalityConfig,
    CancellationFinalityGate,
    CancellationFinalityOutcome,
    CancellationFinalityResult,
    CancellationTarget,
    cancellation_operation_id,
)
from polysia.execution.order_state import PaperFill
from polysia.monitoring.latency_intelligence.recorder import LatencyRecorder
from polysia.monitoring.latency_intelligence.session import SessionLatency
from polysia.portfolio.pnl import calculate_portfolio_pnl
from polysia.portfolio.positions import PositionLedger
from polysia.risk.checks import RiskEngine
from polysia.risk.evidence import MeasuredDecimal, MeasuredInt, VerifiedLiveRiskSnapshot
from polysia.storage.financial_session import (
    FinancialSessionJournal,
    SessionCancellationCheckpoints,
)

ZERO = Decimal("0")
TERMINAL = {"REJECTED", "CANCELLED", "FINALIZED"}


def session_ledger(state: dict[str, Any]) -> PositionLedger:
    """Replay confirmed fills through the existing Decimal accounting owner."""
    ledger = PositionLedger(cash=Decimal(state["opening"]["cash"]))
    for row in state["fills"]:
        ledger.apply_fill(
            PaperFill(
                fill_id=row["fill_id"],
                order_id=row["order_id"],
                token_id=row["token"],
                side=row["side"],
                price=Decimal(row["price"]),
                size=Decimal(row["shares"]),
                fee=Decimal(row["fee"]),
                created_at=datetime.fromisoformat(row["confirmed_at"]),
            )
        )
    return ledger


class FinancialSessionCoordinator:
    def __init__(
        self,
        journal: FinancialSessionJournal,
        execution: SessionExecutionPort,
        risk: RiskEngine,
        *,
        binding: RuntimeBinding,
        clock: Callable[[], datetime],
        monotonic: Callable[[], int] = monotonic_ns,
        trading_mode: TradingMode = TradingMode.DATA_ONLY,
        telemetry: LatencyRecorder | None = None,
    ) -> None:
        self.journal, self.execution, self.risk = journal, execution, risk
        self.binding, self.clock, self.monotonic = binding, clock, monotonic
        self.mode = trading_mode
        self._operation = asyncio.Lock()
        self._supervision_tick: int | None = None
        self.latency = SessionLatency(telemetry, clock=clock, monotonic=monotonic)
        self._submitted_ticks: dict[str, int] = {}

    @property
    def authority(self) -> SessionAuthorization:
        return self.journal.authority

    def supervise(self, *, evidence_id: str, healthy: bool) -> None:
        """Called by a trusted independent supervisor, not a browser command."""
        now = utc(self.clock())
        if not evidence_id or type(healthy) is not bool:
            raise SessionBlocked("supervision_evidence_required")

        def update(state: dict[str, Any]) -> None:
            if healthy:
                state["supervised_at"] = now.isoformat()
            else:
                state["supervised_at"] = None
                state["mode"] = "DRAIN"
                state["incidents"].append({"reason": "mandatory_supervision_lost", "at": now})

        self.journal.mutate("SUPERVISION", {"evidence_id": evidence_id, "healthy": healthy}, update)
        self._supervision_tick = self.monotonic() if healthy else None

    def set_mode(self, mode: SessionMode) -> None:
        if not isinstance(mode, SessionMode):
            raise SessionBlocked("invalid_session_mode")

        def update(state: dict[str, Any]) -> None:
            if mode is SessionMode.RUNNING:
                self.authority.assert_action(self.binding, self.clock(), "ENTRY")
                self._supervised(state)
                if not state["reconciliation_ok"] or state["incidents"]:
                    raise SessionBlocked("unresolved_financial_incident")
            state["mode"] = mode.value

        self.journal.mutate("MODE", {"mode": mode.value}, update)

    def _supervised(self, state: dict[str, Any]) -> None:
        now = utc(self.clock())
        stamp = state["supervised_at"]
        elapsed = (
            None if self._supervision_tick is None else self.monotonic() - self._supervision_tick
        )
        timeout = self.authority.supervision_timeout_seconds
        if (
            stamp is None
            or elapsed is None
            or not 0 <= elapsed <= timeout * 1_000_000_000
            or not 0 <= (now - datetime.fromisoformat(stamp)).total_seconds() <= timeout
        ):
            raise SessionBlocked("mandatory_supervision_expired")

    def reconcile(self, observation: AccountObservation) -> bool:
        observation.require_complete(
            self.binding.account,
            now=self.clock(),
            max_age=self.authority.max_evidence_age_seconds,
        )
        matched = False

        def update(state: dict[str, Any]) -> None:
            nonlocal matched
            matched = self._account_matches(state, observation)
            state["reconciled_at"] = observation.observed_at.isoformat()
            state["last_account"] = asdict(observation)
            state["reconciliation_ok"] = matched
            if not matched:
                state["incidents"].append(
                    {
                        "reason": "unmatched_external_account_activity",
                        "evidence": asdict(observation),
                    }
                )
                state["mode"] = "DRAIN"

        self.journal.mutate("ACCOUNT_RECONCILIATION", asdict(observation), update)
        return matched

    def record_valuation(
        self,
        marks: dict[str, Decimal],
        *,
        observed_at: datetime,
        method: str,
    ) -> None:
        if method not in {"conservative_bid", "confirmed_resolution"}:
            raise SessionBlocked("explicit_conservative_valuation_method_required")
        if (
            not 0
            <= (utc(self.clock()) - utc(observed_at)).total_seconds()
            <= (self.authority.max_evidence_age_seconds)
        ):
            raise SessionBlocked("valuation_stale_or_future")
        for value in marks.values():
            if decimal_value(value) > 1:
                raise SessionBlocked("invalid_binary_position_mark")

        def update(state: dict[str, Any]) -> None:
            ledger = session_ledger(state)
            pnl = calculate_portfolio_pnl(ledger, marks)
            if state["equity"] and observed_at < datetime.fromisoformat(state["equity"][-1]["at"]):
                raise SessionBlocked("valuation_cannot_rewrite_prior_window")
            state["equity"].append(
                {
                    "at": observed_at,
                    "method": method,
                    "marks": marks,
                    "value": str(pnl.total_equity) if pnl.valuation_complete else None,
                    "net_pnl": str(pnl.net_pnl) if pnl.valuation_complete else None,
                    "complete": pnl.valuation_complete,
                }
            )
            if pnl.valuation_complete and pnl.net_pnl <= -self.authority.max_total_loss:
                state["mode"] = "DRAIN"
                state["incidents"].append({"reason": "marked_total_loss_limit", "at": self.clock()})

        self.journal.mutate("VALUATION", {"at": observed_at, "method": method}, update)

    def _account_matches(self, state: dict[str, Any], observation: AccountObservation) -> bool:
        ledger = session_ledger(state)
        orders = state["orders"].values()
        unknown = any(row["state"] == "UNCERTAIN_SUBMIT" for row in orders)
        expected_open = frozenset(
            row["order_id"]
            for row in orders
            if row["state"] not in TERMINAL
            and row["order_id"] is not None
            and row["state"] != "FILLED"
        )
        expected_positions = {key: position.size for key, position in ledger.positions.items()}
        actual_positions = {key: value for key, value in observation.positions or () if value != 0}
        return (
            not unknown
            and not state["quarantined_fills"]
            and not state["quarantined_finality"]
            and ledger.cash == observation.cash
            and expected_positions == actual_positions
            and expected_open == observation.open_order_ids
            and Decimal(state["opening"]["cumulative_fees"]) + ledger.fees
            == observation.cumulative_fees
        )

    def _charge(self, action: str, *, protective: bool) -> None:
        charge = self.execution.charge_bound(action)
        if (
            type(charge.requests) is not int
            or charge.requests <= 0
            or type(charge.response_bytes) is not int
            or charge.response_bytes < 0
        ):
            raise SessionBlocked("unbounded_request_charge")
        decimal_value(charge.source_cost)

        def update(state: dict[str, Any]) -> None:
            reserve = 0 if protective else self.authority.protective_request_reserve
            if state["requests"] + charge.requests > self.authority.max_requests - reserve:
                raise SessionBlocked("request_budget_exhausted")
            if state["response_bytes"] + charge.response_bytes > self.authority.max_response_bytes:
                raise SessionBlocked("response_budget_exhausted")
            if Decimal(state["source_cost"]) + charge.source_cost > self.authority.max_source_cost:
                raise SessionBlocked("source_cost_budget_exhausted")
            state["requests"] += charge.requests
            state["response_bytes"] += charge.response_bytes
            state["source_cost"] = str(Decimal(state["source_cost"]) + charge.source_cost)

        self.journal.mutate("REQUEST_RESERVED", {"action": action, **asdict(charge)}, update)

    async def _snapshot(self, opportunity: SessionOpportunity) -> VerifiedLiveRiskSnapshot:
        self._charge("ACCOUNT", protective=opportunity.event.side != "BUY")
        with self.latency.stage("account_reconciliation"):
            observation = await self.execution.observe_account(opportunity.event.instrument)
        if not self.reconcile(observation):
            raise SessionBlocked("account_reconciliation_blocked")
        state = self.journal.read()
        ledger = session_ledger(state)
        instrument = opportunity.event.instrument
        market_tokens = {
            i.token for i in self.authority.instruments if i.market == instrument.market
        }
        return VerifiedLiveRiskSnapshot(
            current_position=MeasuredDecimal.verified(
                ledger.get(instrument.token).size,
                observed_at=observation.observed_at,
            ),
            current_market_position=MeasuredDecimal.verified(
                sum((ledger.get(token).size for token in market_tokens), ZERO),
                observed_at=observation.observed_at,
            ),
            daily_pnl=MeasuredDecimal.verified(
                ledger.daily_net_pnl(self.clock()),
                observed_at=observation.observed_at,
            ),
            open_order_count=MeasuredInt.verified(
                len(observation.open_order_ids or ()),
                observed_at=observation.observed_at,
            ),
            market_data_observed_at=opportunity.market_observed_at,
            account_source_id=observation.account,
            observed_at=observation.observed_at,
        )

    async def submit(self, opportunity: SessionOpportunity) -> str:
        # Bounded admission instead of an unbounded queue of waiting financial tasks.
        if self._operation.locked():
            raise SessionBlocked("account_operation_busy")
        async with self._operation:
            identity = digest((self.authority.run_id, opportunity.event.identity))
            self.latency.bind(run_id=self.authority.run_id, intent_id=identity)
            if self._remember(identity, opportunity):
                return identity
            try:
                if self.mode not in {TradingMode.PAPER, TradingMode.LIVE}:
                    raise SessionBlocked("DATA_ONLY_blocks_financial_session")
                edge = opportunity.validate(self.authority, now=self.clock())
                self.latency.record(
                    "source_to_observation",
                    int(
                        (
                            opportunity.event.observed_at - opportunity.event.occurred_at
                        ).total_seconds()
                        * 1_000_000_000
                    ),
                    status="source_clock_quality_unknown",
                )
                action = "ENTRY" if opportunity.event.side == "BUY" else "REDUCE"
                self._guard(self.journal.read(), action)
                snapshot = await self._snapshot(opportunity)
                self._decision_phase(identity, timely=True, eligible=True)
                intent = OrderIntent(
                    strategy_id=opportunity.strategy,
                    token_id=opportunity.event.instrument.token,
                    side=opportunity.event.side,
                    price=opportunity.price,
                    size=opportunity.shares,
                    reason=opportunity.reason,
                    confidence=ZERO,
                )
                canonical = SessionLimitRequest(
                    intent.strategy_id,
                    intent.token_id,
                    intent.side,
                    intent.price,
                    intent.size,
                    int(
                        min(
                            self.authority.expires_at
                            if intent.side == "BUY"
                            else self.authority.protective_until,
                            opportunity.market_expires_at,
                        ).timestamp()
                    ),
                    False,
                )
                context = snapshot.to_risk_context(
                    trading_mode=self.mode,
                    live_trading_enabled=self.mode is TradingMode.LIVE,
                    now=self.clock(),
                    max_stale_data_age_ms=self.authority.max_evidence_age_seconds * 1000,
                    edge=edge,
                )
                with self.latency.stage("decision_to_risk"):
                    decision = self.risk.evaluate(
                        canonical.as_intent(),
                        context,
                    )
                self._decision_phase(identity, risk=asdict(decision))
                if not decision.approved:
                    raise SessionBlocked("risk_rejected:" + decision.reason)
                if (
                    decision.adjusted_size is None
                    or not ZERO < decision.adjusted_size <= intent.size
                ):
                    raise SessionBlocked("risk_approved_quantity_invalid")
                approved = ApprovedSessionLimit(
                    replace(canonical, shares=decision.adjusted_size),
                    risk_reason=decision.reason,
                    approved_at=self.clock(),
                )
                self._reserve(identity, opportunity, approved)
                self._charge("SUBMIT", protective=action != "ENTRY")

                refreshed = False
                latest_snapshot = snapshot

                async def refresh() -> VerifiedLiveRiskSnapshot:
                    nonlocal refreshed, latest_snapshot
                    latest_snapshot = await self._snapshot(opportunity)
                    refreshed = True
                    return latest_snapshot

                claimed = False

                def claim() -> None:
                    nonlocal claimed
                    if claimed:
                        raise SessionBlocked("duplicate_submit_claim")
                    if not refreshed:
                        raise SessionBlocked("final_account_refresh_required")
                    opportunity.validate(self.authority, now=self.clock())
                    final_context = latest_snapshot.to_risk_context(
                        trading_mode=self.mode,
                        live_trading_enabled=self.mode is TradingMode.LIVE,
                        now=self.clock(),
                        max_stale_data_age_ms=self.authority.max_evidence_age_seconds * 1000,
                        edge=edge,
                    )
                    final_decision = self.risk.evaluate(
                        approved.request.as_intent(),
                        final_context,
                    )
                    if (
                        not final_decision.approved
                        or final_decision.adjusted_size != approved.request.shares
                    ):
                        raise SessionBlocked("final_risk_request_changed_or_rejected")
                    self._transition(identity, "UNCERTAIN_SUBMIT", action=action)
                    self._submitted_ticks[identity] = self.monotonic()
                    claimed = True

                with self.latency.stage("submit_to_ack"):
                    receipt = await self.execution.submit(
                        approved,
                        opportunity,
                        snapshot,
                        before_submit=claim,
                        refresh=refresh,
                        edge=edge,
                    )
                if not claimed or not receipt.evidence_id:
                    raise SessionBlocked("execution_receipt_without_durable_claim")
                if receipt.definitively_rejected and receipt.order_id is None:
                    self._transition(identity, "REJECTED")
                elif receipt.order_id and not receipt.definitively_rejected:
                    self._transition(identity, "ACCEPTED", order_id=receipt.order_id)
                else:
                    raise SessionBlocked("ambiguous_submit_receipt")
            except BaseException as error:
                # Preserve cancellation/timeout uncertainty, including task cancellation.
                # A durable claim is never refunded or automatically resent.
                reason = str(error) if isinstance(error, SessionBlocked) else type(error).__name__
                self._reject_or_pause(identity, reason)
                raise
            return identity

    def _remember(self, identity: str, opportunity: SessionOpportunity) -> bool:
        duplicate = False
        conflict = False

        def update(state: dict[str, Any]) -> None:
            nonlocal duplicate, conflict
            duplicate = identity in state["decisions"]
            provenance = json_safe(asdict(opportunity.event))
            if duplicate:
                original = state["decisions"][identity]["evidence"]["event"]
                conflict = any(
                    original[field] != provenance[field] for field in ("side", "instrument")
                )
                if (
                    original["finalized"] is True
                    and provenance["finalized"] is False
                    and provenance["observed_at"] >= original["observed_at"]
                ):
                    conflict = True
                if conflict:
                    state["mode"] = "DRAIN"
                    state["reconciliation_ok"] = False
                    state["incidents"].append(
                        {
                            "reason": "conflicting_occurrence_evidence",
                            "intent": identity,
                        }
                    )
                sources = state["decisions"][identity]["sources"]
                if provenance not in sources:
                    sources.append(provenance)
            else:
                state["decisions"][identity] = {
                    "evidence": asdict(opportunity),
                    "evidence_digest": opportunity.evidence_digest,
                    "sources": [provenance],
                    "result": "OBSERVED",
                    "reason": None,
                    "decision_at": self.clock(),
                    "eligible": False,
                    "timely": False,
                    "risk": None,
                }

        self.journal.mutate("DECISION_OBSERVED", {"intent_id": identity}, update)
        if conflict:
            raise SessionBlocked("conflicting_occurrence_evidence")
        return duplicate

    def _decision_phase(self, identity: str, **values: object) -> None:
        def update(state: dict[str, Any]) -> None:
            state["decisions"][identity].update(values)

        self.journal.mutate("DECISION_PHASE", {"intent_id": identity, **values}, update)

    def _guard(self, state: dict[str, Any], action: str) -> None:
        self.authority.assert_action(self.binding, self.clock(), action)
        if self.risk.kill_switch.is_active() or state["mode"] == "STOP":
            raise SessionBlocked("STOP_or_kill_switch")
        self._supervised(state)
        if action == "ENTRY" and (
            state["mode"] != "RUNNING" or not state["reconciliation_ok"] or state["incidents"]
        ):
            raise SessionBlocked("new_entry_drained_or_unreconciled")
        if action == "ENTRY" and any(
            row["state"] == "UNCERTAIN_SUBMIT" for row in state["orders"].values()
        ):
            raise SessionBlocked("uncertain_submission_requires_reconciliation")

    def _reserve(
        self, identity: str, opportunity: SessionOpportunity, approved: ApprovedSessionLimit
    ) -> None:
        action = "ENTRY" if approved.request.side == "BUY" else "REDUCE"

        def update(state: dict[str, Any]) -> None:
            self._guard(state, action)
            ledger = session_ledger(state)
            active = [o for o in state["orders"].values() if o["state"] not in TERMINAL]
            if identity in state["orders"] or state["attempts"] >= self.authority.max_attempts:
                raise SessionBlocked("duplicate_or_attempt_budget_exhausted")
            if len(active) >= self.authority.max_concurrent_orders:
                raise SessionBlocked("concurrent_order_limit")
            shares = approved.request.shares
            notional = shares * opportunity.price
            all_in = notional * (1 + self.authority.fee_rate)
            if all_in > self.authority.max_order_all_in:
                raise SessionBlocked("all_in_order_limit")
            if Decimal(state["turnover"]) + all_in > self.authority.max_turnover:
                raise SessionBlocked("turnover_limit")
            if action == "ENTRY":
                reserved = sum((Decimal(o["reservation"]) for o in active), ZERO)
                position_cost = sum((p.size * p.avg_price for p in ledger.positions.values()), ZERO)
                exposure = position_cost + reserved + all_in
                if exposure > self.authority.max_open_exposure or ledger.cash - reserved < all_in:
                    raise SessionBlocked("aggregate_exposure_or_cash_limit")
                # Worst-case held capital also consumes loss authority; absent marks
                # cannot conceal losses or reset a budget at midnight.
                if (
                    exposure + max(ZERO, ledger.fees - ledger.realized_pnl)
                    > self.authority.max_total_loss
                ):
                    raise SessionBlocked("total_loss_limit")
                if (
                    exposure + max(ZERO, -ledger.daily_net_pnl(self.clock()))
                    > self.authority.max_daily_loss
                ):
                    raise SessionBlocked("daily_loss_limit")
                token = opportunity.event.instrument.token
                if (
                    token not in ledger.positions
                    and len(ledger.positions) >= self.authority.max_positions
                ):
                    raise SessionBlocked("position_concurrency_limit")
                for field, limit in (
                    ("market", self.authority.max_market_exposure),
                    ("wallet", self.authority.max_wallet_exposure),
                ):
                    key = (
                        opportunity.event.instrument.market
                        if field == "market"
                        else opportunity.event.wallet
                    )
                    used = sum((Decimal(o["reservation"]) for o in active if o[field] == key), ZERO)
                    held = self._attributed_cost(state, ledger, field, key)
                    if held + used + all_in > limit:
                        raise SessionBlocked(field + "_concentration_limit")
            else:
                if opportunity.exit_trigger == "MAX_HOLDING":
                    opened_at = self._position_opened_at(state, opportunity.event.instrument.token)
                    if (
                        opened_at is None
                        or (self.clock() - opened_at).total_seconds()
                        < self.authority.max_holding_seconds
                    ):
                        raise SessionBlocked("maximum_holding_exit_not_due")
                reserved_shares = sum(
                    (
                        Decimal(o["shares"])
                        for o in active
                        if o["side"] == "SELL" and o["token"] == opportunity.event.instrument.token
                    ),
                    ZERO,
                )
                if shares + reserved_shares > ledger.get(opportunity.event.instrument.token).size:
                    raise SessionBlocked("exit_exceeds_unreserved_holdings")
            state["orders"][identity] = {
                "state": "RESERVED",
                "order_id": None,
                "side": approved.request.side,
                "token": opportunity.event.instrument.token,
                "market": opportunity.event.instrument.market,
                "wallet": opportunity.event.wallet,
                "shares": str(shares),
                "price": str(opportunity.price),
                "reservation": str(all_in if action == "ENTRY" else ZERO),
                "approved": asdict(approved),
                "approved_digest": digest(asdict(approved)),
                "evidence_digest": opportunity.evidence_digest,
                "created_at": self.clock(),
                "timeline": {"risk": approved.approved_at},
                "fill_state": "NONE",
                "settlement_state": "UNCONFIRMED",
            }
            state["attempts"] += 1
            state["turnover"] = str(Decimal(state["turnover"]) + all_in)
            state["decisions"][identity]["result"] = "RISK_APPROVED"
            state["decisions"][identity]["eligible"] = True

        self.journal.mutate("ATTEMPT_AND_RESERVATION", {"intent_id": identity}, update)

    @staticmethod
    def _position_opened_at(state: dict[str, Any], token: str) -> datetime | None:
        quantity, opened = ZERO, None
        for fill in state["fills"]:
            if fill["token"] != token:
                continue
            if quantity == ZERO and fill["side"] == "BUY":
                opened = datetime.fromisoformat(fill["confirmed_at"])
            quantity += Decimal(fill["shares"]) * (1 if fill["side"] == "BUY" else -1)
            if quantity == ZERO:
                opened = None
        return opened

    @staticmethod
    def _attributed_cost(
        state: dict[str, Any], ledger: PositionLedger, field: str, key: str
    ) -> Decimal:
        tokens = {
            o["token"] for o in state["orders"].values() if o[field] == key and o["side"] == "BUY"
        }
        return sum((ledger.get(t).size * ledger.get(t).avg_price for t in tokens), ZERO)

    def _transition(
        self,
        identity: str,
        target: str,
        *,
        action: str | None = None,
        order_id: str | None = None,
    ) -> None:
        allowed = {
            "RESERVED": {"UNCERTAIN_SUBMIT"},
            "UNCERTAIN_SUBMIT": {"ACCEPTED", "REJECTED"},
            "ACCEPTED": {"CANCEL_PENDING"},
            "PARTIAL_FILL": {"CANCEL_PENDING"},
        }

        def update(state: dict[str, Any]) -> None:
            if action is not None:
                self._guard(state, action)
            row = state["orders"][identity]
            already_observed = (
                target == "ACCEPTED"
                and row["state"] in {"PARTIAL_FILL", "FILLED", "FINALIZED"}
                and row["order_id"] == order_id
            )
            if already_observed:
                row["timeline"]["ACCEPTED"] = self.clock()
                return
            if target not in allowed.get(row["state"], set()):
                raise SessionBlocked("invalid_order_state_transition")
            if order_id is not None:
                if any(o["order_id"] == order_id for o in state["orders"].values()):
                    raise SessionBlocked("duplicate_venue_order_identity")
                row["order_id"] = order_id
            row["state"] = target
            row["timeline"][target] = self.clock()
            if target == "CANCEL_PENDING":
                row["cancel_position_baseline"] = str(session_ledger(state).get(row["token"]).size)
                row["cancel_fill_baseline"] = str(
                    sum(
                        (
                            Decimal(f["shares"])
                            for f in state["fills"]
                            if f["intent_id"] == identity
                        ),
                        ZERO,
                    )
                )
                if Decimal(row["cancel_fill_baseline"]) >= Decimal(row["shares"]):
                    raise SessionBlocked("fully_filled_order_requires_confirmation_not_cancel")
                row["cancel_notional_baseline"] = str(
                    sum(
                        (
                            Decimal(f["price"]) * Decimal(f["shares"])
                            for f in state["fills"]
                            if f["intent_id"] == identity
                        ),
                        ZERO,
                    )
                )

        self.journal.mutate("ORDER_STATE", {"intent_id": identity, "state": target}, update)

    def _reject_or_pause(self, identity: str, reason: str) -> None:
        def update(state: dict[str, Any]) -> None:
            decision = state["decisions"][identity]
            row = state["orders"].get(identity)
            if row is None or row["state"] == "RESERVED":
                if row is not None:
                    row["state"] = "REJECTED"
                decision["result"] = "REJECTED"
            else:
                state["mode"] = "DRAIN"
                state["reconciliation_ok"] = False
                decision["result"] = "UNKNOWN"
            decision["reason"] = reason

        self.journal.mutate("DECISION_RESULT", {"intent_id": identity, "reason": reason}, update)

    async def cancel(self, identity: str) -> None:
        if self._operation.locked():
            raise SessionBlocked("account_operation_busy")
        async with self._operation:
            self._guard(self.journal.read(), "CANCEL")
            row = self.journal.read()["orders"][identity]
            if row["state"] not in {"ACCEPTED", "PARTIAL_FILL"} or not row["order_id"]:
                raise SessionBlocked("cancel_requires_known_open_order")
            self._charge("CANCEL", protective=True)
            await self.execution.cancel(
                row["order_id"],
                before_cancel=lambda: self._transition(
                    identity,
                    "CANCEL_PENDING",
                    action="CANCEL",
                ),
            )
            # ACK never finalizes or releases a reservation. The existing
            # cancellation finality gate supplies subsequent read-only evidence.

    def apply_order_evidence(
        self,
        identity: str,
        *,
        order_id: str,
        fills: tuple[ConfirmedSessionFill, ...],
        finality: str,
        evidence_id: str,
        account: AccountObservation,
    ) -> None:
        """Trusted adapter evidence, including late fills, is durable before release.

        finality is OPEN / CONFIRMED_FILL / CONFIRMED_NO_FILL / CONFIRMED_PARTIAL.
        Cancellation finality outcomes map at the execution boundary; an ACK,
        matched trade, missing page, or 404 alone must never call a terminal case.
        """
        if (
            not order_id
            or not evidence_id
            or finality
            not in {
                "OPEN",
                "CONFIRMED_FILL",
                "CONFIRMED_NO_FILL",
                "CONFIRMED_PARTIAL",
            }
        ):
            raise SessionBlocked("unverified_order_finality")
        self.latency.bind(run_id=self.authority.run_id, intent_id=identity)
        try:
            account.require_complete(
                self.binding.account,
                now=self.clock(),
                max_age=self.authority.max_evidence_age_seconds,
            )
        except SessionBlocked:

            def quarantine(state: dict[str, Any]) -> None:
                known = {f["fill_id"] for f in state["fills"] + state["quarantined_fills"]}
                for fill in fills:
                    if fill.fill_id not in known:
                        state["quarantined_fills"].append(json_safe(asdict(fill)))
                        known.add(fill.fill_id)
                state["mode"] = "DRAIN"
                state["reconciliation_ok"] = False
                state["incidents"].append(
                    {
                        "reason": "confirmed_evidence_account_unavailable",
                        "intent": identity,
                    }
                )
                state["orders"][identity]["state"] = "RECONCILIATION_BLOCKED"

            self.journal.mutate(
                "UNRECONCILED_ORDER_EVIDENCE",
                {
                    "intent_id": identity,
                    "account": asdict(account),
                },
                quarantine,
            )
            raise

        def update(state: dict[str, Any]) -> None:
            row = state["orders"][identity]
            previous_state = row["state"]
            if previous_state == "RESERVED":
                raise SessionBlocked("unsubmitted_order_cannot_acquire_external_fills")
            if row["order_id"] not in {None, order_id}:
                raise SessionBlocked("order_identity_mismatch")
            if any(
                o["order_id"] == order_id for key, o in state["orders"].items() if key != identity
            ):
                raise SessionBlocked("order_identity_already_bound")
            row["order_id"] = order_id
            known = {f["fill_id"]: f for f in state["fills"] + state["quarantined_fills"]}
            new_fill = False
            trial_ledger = session_ledger(state)
            for fill in fills:
                if (
                    fill.intent_id != identity
                    or fill.order_id != order_id
                    or fill.token != row["token"]
                    or fill.side != row["side"]
                    or fill.confirmed_at > self.clock()
                ):
                    raise SessionBlocked("fill_evidence_identity_mismatch")
                encoded = json_safe(asdict(fill))
                if fill.fill_id in known:
                    if known[fill.fill_id] != encoded:
                        raise SessionBlocked("conflicting_duplicate_fill")
                    continue
                try:
                    trial_ledger.apply_fill(
                        PaperFill(
                            fill.fill_id,
                            fill.order_id,
                            fill.token,
                            fill.side,
                            fill.price,
                            fill.shares,
                            fill.confirmed_at,
                            fill.fee,
                        )
                    )
                except ValueError:
                    state["quarantined_fills"].append(encoded)
                    state["incidents"].append(
                        {
                            "reason": "confirmed_fill_requires_reconciliation",
                            "intent": identity,
                            "fill_id": fill.fill_id,
                        }
                    )
                else:
                    state["fills"].append(encoded)
                known[fill.fill_id] = encoded
                new_fill = True
            state["last_account"] = asdict(account)
            if state["quarantined_fills"]:
                state["mode"] = "DRAIN"
                state["reconciliation_ok"] = False
                row["state"] = "RECONCILIATION_BLOCKED"
                row["settlement_state"] = "CONFIRMED_EXTERNAL_UNRECONCILED"
                state["decisions"][identity]["result"] = "UNKNOWN"
                return
            ledger = session_ledger(state)
            linked = [f for f in state["fills"] if f["intent_id"] == identity]
            quantity = sum((Decimal(f["shares"]) for f in linked), ZERO)
            if quantity > Decimal(row["shares"]):
                state["incidents"].append(
                    {"reason": "fill_exceeds_approved_quantity", "intent": identity}
                )
            actual_spend = sum(
                (Decimal(f["price"]) * Decimal(f["shares"]) + Decimal(f["fee"]) for f in linked),
                ZERO,
            )
            if row["side"] == "BUY" and actual_spend > Decimal(row["reservation"]):
                state["incidents"].append(
                    {"reason": "fill_exceeds_all_in_reservation", "intent": identity}
                )
            if any(
                (
                    Decimal(f["price"]) > Decimal(row["price"])
                    if row["side"] == "BUY"
                    else Decimal(f["price"]) < Decimal(row["price"])
                )
                for f in linked
            ):
                state["incidents"].append(
                    {"reason": "fill_outside_approved_price", "intent": identity}
                )
            if previous_state in TERMINAL and new_fill:
                state["incidents"].append(
                    {"reason": "late_fill_after_financial_finality", "intent": identity}
                )
            contradiction = (
                (finality == "CONFIRMED_NO_FILL" and quantity != 0)
                or (finality == "CONFIRMED_FILL" and quantity < Decimal(row["shares"]))
                or (finality == "CONFIRMED_PARTIAL" and not 0 < quantity < Decimal(row["shares"]))
            )
            if contradiction:
                state["quarantined_finality"].append(
                    {
                        "intent_id": identity,
                        "finality": finality,
                        "evidence_id": evidence_id,
                        "confirmed_quantity": str(quantity),
                        "account": asdict(account),
                    }
                )
                state["incidents"].append(
                    {
                        "reason": "confirmed_fills_and_order_finality_conflict",
                        "intent": identity,
                    }
                )
                state["mode"] = "DRAIN"
                state["reconciliation_ok"] = False
                row["state"] = "RECONCILIATION_BLOCKED"
                state["decisions"][identity]["result"] = "UNKNOWN"
                return
            row["state"] = (
                "FINALIZED"
                if finality in {"CONFIRMED_FILL", "CONFIRMED_PARTIAL"}
                else "CANCELLED"
                if finality == "CONFIRMED_NO_FILL"
                else "PARTIAL_FILL"
                if quantity
                else "ACCEPTED"
            )
            if previous_state in TERMINAL and finality == "OPEN":
                row["state"] = previous_state
            if previous_state == "CANCEL_PENDING" and finality == "OPEN":
                row["state"] = "CANCEL_PENDING"
            row["fill_state"] = (
                "FILLED"
                if quantity >= Decimal(row["shares"])
                else "PARTIAL_FILL"
                if quantity
                else "NONE"
            )
            row["settlement_state"] = "CONFIRMED" if finality != "OPEN" else "UNCONFIRMED"
            row["timeline"]["order_evidence"] = self.clock()
            if finality != "OPEN":
                row["timeline"]["finality"] = self.clock()
            matched = self._account_matches(state, account)
            state["reconciliation_ok"] = matched
            state["reconciled_at"] = account.observed_at.isoformat()
            state["decisions"][identity]["result"] = row["state"]
            if not matched:
                state["mode"] = "DRAIN"
                state["incidents"].append(
                    {"reason": "unmatched_external_account_activity", "evidence": asdict(account)}
                )
            if ledger.cash < 0:
                state["incidents"].append({"reason": "negative_account_cash"})
            if state["incidents"]:
                state["mode"] = "DRAIN"

        self.journal.mutate(
            "CONFIRMED_ORDER_EVIDENCE",
            {
                "intent_id": identity,
                "order_id": order_id,
                "finality": finality,
                "evidence_id": evidence_id,
                "account": asdict(account),
            },
            update,
        )
        started = self._submitted_ticks.get(identity)
        elapsed = None if started is None else self.monotonic() - started
        self.latency.record(
            "submit_to_fill" if finality == "OPEN" else "submit_to_finality",
            elapsed,
            status="censored_across_restart" if started is None else "ok",
        )

    async def reconcile_cancellation(
        self,
        identity: str,
        *,
        evidence: CancellationEvidencePort,
        config: CancellationFinalityConfig,
        sleeper: Callable[[float], Awaitable[None]],
        confirmed_fills: tuple[ConfirmedSessionFill, ...] = (),
    ) -> CancellationFinalityResult:
        """Reuse the existing bounded gate; never send a second cancellation."""
        if self._operation.locked():
            raise SessionBlocked("account_operation_busy")
        async with self._operation:
            row = self.journal.read()["orders"][identity]
            if row["state"] != "CANCEL_PENDING":
                raise SessionBlocked("cancellation_finality_requires_pending_checkpoint")
            operation_id = cancellation_operation_id(
                self.authority.run_id, identity, (row["order_id"],)
            )
            gate = CancellationFinalityGate(
                evidence_port=BudgetedCancellationEvidence(
                    evidence,
                    lambda: self._charge("CANCELLATION_READ", protective=True),
                ),
                checkpoints=SessionCancellationCheckpoints(self.journal),
                run_id=self.authority.run_id,
                clock=self.clock,
                sleeper=sleeper,
                config=config,
            )
            result = await gate.run(
                operation_id=operation_id,
                targets=(
                    CancellationTarget(
                        row["order_id"],
                        row["token"],
                        row["side"],
                        Decimal(row["shares"]) - Decimal(row["cancel_fill_baseline"]),
                        Decimal(row["cancel_fill_baseline"]),
                        Decimal(row["cancel_notional_baseline"]),
                    ),
                ),
                position_baselines={row["token"]: Decimal(row["cancel_position_baseline"])},
                mutation=None,
            )
            outcomes = {
                CancellationFinalityOutcome.CONFIRMED_NO_FILL: "CONFIRMED_NO_FILL",
                CancellationFinalityOutcome.FULL_FILL_DETECTED: "CONFIRMED_FILL",
                CancellationFinalityOutcome.PARTIAL_FILL_DETECTED: "CONFIRMED_PARTIAL",
            }
            if result.outcome not in outcomes:
                self._reject_or_pause(identity, "cancellation_finality_unknown")
                return result
            instrument = next(
                item for item in self.authority.instruments if item.token == row["token"]
            )
            self._charge("ACCOUNT", protective=True)
            account = await self.execution.observe_account(instrument)
            # A gate without fee-aware confirmed fills cannot invent accounting.
            self.apply_order_evidence(
                identity,
                order_id=row["order_id"],
                fills=confirmed_fills,
                finality=(
                    "CONFIRMED_PARTIAL"
                    if result.outcome is CancellationFinalityOutcome.CONFIRMED_NO_FILL
                    and Decimal(row["cancel_fill_baseline"]) > 0
                    else outcomes[result.outcome]
                ),
                evidence_id=operation_id,
                account=account,
            )
            return result


def json_safe(value: object) -> Any:
    import json

    from polysia.domain.financial_session import canonical_json

    return json.loads(canonical_json(value))
