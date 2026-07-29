from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Any, Protocol, cast

from polysia.adapters.polymarket.copytrading_source import PolymarketCopyTradingSource
from polysia.adapters.polymarket.geoblock import (
    GeoblockStatus,
    PreLiveOrderGeoblockCheck,
    PreLiveOrderGeoblockError,
)
from polysia.adapters.polymarket.lifecycle_monitoring import (
    PolymarketServerTimeReader,
    evaluate_clock_drift,
)
from polysia.adapters.polymarket.public import PolymarketPublicAdapter
from polysia.adapters.polymarket.secure import PolymarketSecureAdapter
from polysia.application.ports.copytrading import LeaderTradeSourcePort
from polysia.config.settings import AppSettings, TradingMode
from polysia.domain.copytrading import (
    CopyExperimentState,
    LeaderPositionEffect,
    LeaderTradeAction,
    LeaderTradeEvent,
    calculate_entry_quote,
    calculate_realized_pnl,
    calculate_take_profit_price,
    load_candidate_bank,
    signal_is_fresh,
)
from polysia.domain.copytrading.live_experiment import (
    EXPECTED_CANDIDATE_COUNT,
    MAXIMUM_ACCOUNT_BALANCE,
    MAXIMUM_COMPLETED_LIVE_CYCLES,
    MAXIMUM_ENTRY_DEBIT,
    MAXIMUM_TOTAL_ENTRY_ATTEMPTS,
    TERMINAL_STATES,
)
from polysia.domain.market import MarketDetails, MarketOrderBookSnapshot
from polysia.execution.intents import OrderIntent
from polysia.execution.live_broker import LiveBroker
from polysia.risk.checks import RiskContext, RiskEngine
from polysia.risk.kill_switch import KillSwitch
from polysia.risk.limits import RiskLimits
from polysia.storage.copytrading import CopyExperimentRepository
from polysia.storage.db import SQLiteDatabase
from polysia.strategies.btc_15m_favorite_take_profit import (
    Btc15mFavoriteTakeProfitStrategy,
)

AUTHORIZATION_ID = "POLYSIA-TINY-LIVE-COPY-001"
STRATEGY_ID = "polymarket-copytrading"
APPROVED_SDK_VERSION = "0.2.0"
BASE_UNITS = Decimal("1000000")
POLL_INTERVAL_SECONDS = 6
POLL_OVERLAP_SECONDS = 20
BASELINE_OVERLAP_SECONDS = 120
BASELINE_RATE_COOLDOWN_SECONDS = 10
MAXIMUM_BOOK_AGE_MS = 5_000
MAXIMUM_HEARTBEAT_GAP_SECONDS = 60

Clock = Callable[[], datetime]
Sleeper = Callable[[float], Awaitable[None]]


def utc_now() -> datetime:
    return datetime.now(UTC)


class TinyLiveCopyError(RuntimeError):
    """Fail-closed error for the owner-bounded Copy Trading experiment."""


class CopySignalSkip(TinyLiveCopyError):
    """A proven local signal ineligibility that consumes no venue attempt."""


class CopyMarketPort(Protocol):
    async def get_market_by_slug(self, slug: str) -> MarketDetails: ...

    async def get_order_book(self, token_id: str) -> MarketOrderBookSnapshot: ...


class CopyExecutionPort(Protocol):
    @property
    def is_connected(self) -> bool: ...

    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def read_clock_drift(self) -> Decimal: ...

    def identity(self) -> Any: ...

    async def get_balance_allowance(
        self,
        *,
        asset_type: str,
        token_id: str | None = None,
    ) -> Any: ...

    async def get_open_orders(
        self,
        *,
        token_id: str | None = None,
        order_id: str | None = None,
        market: str | None = None,
    ) -> list[Any]: ...

    async def get_order(self, *, order_id: str) -> Any | None: ...

    async def list_positions(
        self,
        *,
        market: tuple[str, ...] | None = None,
        size_threshold: float | None = None,
    ) -> list[Any]: ...

    async def list_account_trades(
        self,
        *,
        token_id: str | None = None,
        market: str | None = None,
    ) -> list[Any]: ...

    async def place_limit_order(
        self,
        *,
        token_id: str,
        side: str,
        price: Decimal,
        size: Decimal,
        post_only: bool = False,
        expiration: int | None = None,
        builder_code: str | None = None,
    ) -> Any: ...

    async def place_market_order(
        self,
        *,
        token_id: str,
        side: str,
        amount: Decimal | None = None,
        shares: Decimal | None = None,
        max_spend: Decimal | None = None,
        max_price: Decimal | None = None,
        min_price: Decimal | None = None,
        order_type: str = "FAK",
        builder_code: str | None = None,
    ) -> Any: ...

    async def cancel_order(self, *, order_id: str) -> Any: ...

    async def cancel_all(self) -> Any: ...

    async def probe_user_stream(self, *, market: str | None = None) -> None: ...


class CopyGeoblockPort(Protocol):
    async def check(self) -> GeoblockStatus: ...


class _BrokerGeoblock:
    def __init__(self, source: CopyGeoblockPort) -> None:
        self._source = source

    async def assert_allowed(self) -> GeoblockStatus:
        status = await self._source.check()
        if status.status != "allowed" or status.blocked is not False:
            raise PreLiveOrderGeoblockError(
                "Official Polymarket geoblock did not allow live order placement."
            )
        return status


@dataclass(frozen=True, slots=True)
class TinyLiveCopyConfig:
    settings: AppSettings
    project_root: Path
    output_dir: Path
    database_path: Path
    candidate_file: Path
    run_id: str
    dry_run: bool = True
    acknowledgement: bool = False
    verified_ci_commit: str | None = None
    signal_window_hours: int = 12
    poll_interval_seconds: int = POLL_INTERVAL_SECONDS
    maximum_poll_cycles: int | None = None
    delete_candidate_file_on_terminal: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.startswith("tiny-live-copy-"):
            raise ValueError("run_id must use the tiny-live-copy timestamp prefix")
        if self.signal_window_hours != 12:
            raise ValueError("signal window is fixed at 12 hours")
        if self.poll_interval_seconds < POLL_INTERVAL_SECONDS:
            raise ValueError("poll interval must preserve the bounded official API rate")
        if self.maximum_poll_cycles is not None and self.maximum_poll_cycles < 1:
            raise ValueError("maximum_poll_cycles must be positive when supplied")


@dataclass(slots=True)
class TinyLiveCopyReport:
    run_id: str
    git_commit: str | None
    started_at: datetime
    signal_window_end: datetime
    state: str
    classification: str
    starting_account_balance: Decimal | None
    final_account_balance: Decimal | None
    geoblock_status: str
    total_entry_attempts: int
    completed_live_cycles: int
    signal_count: int
    event_count: int
    duplicate_count: int
    current_order_or_fill_exists: bool
    emergency_cancel_status: str
    websocket_health: str
    heartbeat_health: str
    candidate_runtime_file_deleted: bool
    stop_reason: str | None
    candidate_summary: dict[str, object]
    attempts: tuple[dict[str, object], ...] = ()
    api_errors: int = 0
    decisions: list[dict[str, object]] = field(default_factory=list)
    orderbook_snapshots: list[dict[str, object]] = field(default_factory=list)
    sanitized_events: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "api_errors": self.api_errors,
            "attempts": list(self.attempts),
            "candidate_summary": self.candidate_summary,
            "candidate_runtime_file_deleted": self.candidate_runtime_file_deleted,
            "classification": self.classification,
            "completed_live_cycles": self.completed_live_cycles,
            "current_order_or_fill_exists": self.current_order_or_fill_exists,
            "duplicate_count": self.duplicate_count,
            "emergency_cancel_status": self.emergency_cancel_status,
            "event_count": self.event_count,
            "final_account_balance": (
                None
                if self.final_account_balance is None
                else str(self.final_account_balance)
            ),
            "geoblock_status": self.geoblock_status,
            "heartbeat_health": self.heartbeat_health,
            "git_commit": self.git_commit,
            "maximum_account_balance_usd": str(MAXIMUM_ACCOUNT_BALANCE),
            "maximum_completed_live_cycles": MAXIMUM_COMPLETED_LIVE_CYCLES,
            "maximum_entry_debit_usd": str(MAXIMUM_ENTRY_DEBIT),
            "maximum_total_entry_attempts": MAXIMUM_TOTAL_ENTRY_ATTEMPTS,
            "maximum_actual_loss_usd": self._maximum_actual_loss(),
            "no_fourth_entry_possible": self.total_entry_attempts <= 3,
            "no_more_than_one_active_position_or_order": True,
            "owner_prompt_preserved_by_design": True,
            "run_id": self.run_id,
            "signal_count": self.signal_count,
            "signal_window_end": self.signal_window_end.isoformat(),
            "started_at": self.started_at.isoformat(),
            "starting_account_balance": (
                None
                if self.starting_account_balance is None
                else str(self.starting_account_balance)
            ),
            "state": self.state,
            "stop_reason": self.stop_reason,
            "used_leader_aliases": sorted(
                {
                    str(attempt["leader_alias"])
                    for attempt in self.attempts
                    if attempt.get("leader_alias") is not None
                }
            ),
            "websocket_health": self.websocket_health,
        }

    def _maximum_actual_loss(self) -> str | None:
        losses = [
            -Decimal(str(attempt["net_pnl"]))
            for attempt in self.attempts
            if attempt.get("net_pnl") is not None
            and Decimal(str(attempt["net_pnl"])) < 0
        ]
        return None if not losses else str(max(losses))


@dataclass(slots=True)
class _Runtime:
    report: TinyLiveCopyReport
    last_poll_at: datetime
    active_attempt_number: int | None = None
    active_market: MarketDetails | None = None
    active_token_id: str | None = None
    active_entry_price: Decimal | None = None
    active_entry_fee: Decimal = Decimal("0")
    active_fill_price: Decimal | None = None
    active_fill_size: Decimal = Decimal("0")
    active_cancel_at: datetime | None = None
    leader_close_exit_submitted: bool = False


async def run_tiny_live_copy(
    config: TinyLiveCopyConfig,
    *,
    source: LeaderTradeSourcePort | None = None,
    market_port: CopyMarketPort | None = None,
    execution_port: CopyExecutionPort | None = None,
    geoblock_port: CopyGeoblockPort | None = None,
    kill_switch: KillSwitch | None = None,
    clock: Clock = utc_now,
    sleeper: Sleeper = asyncio.sleep,
) -> TinyLiveCopyReport:
    """Run or safely resume the exact owner-authorized detached experiment."""

    candidate_text = config.candidate_file.read_text(encoding="utf-8")
    bank = load_candidate_bank(candidate_text)
    active_source = source or PolymarketCopyTradingSource(bank.as_protected_mapping())
    active_market_port = market_port or PolymarketPublicAdapter()
    active_execution_port: CopyExecutionPort = execution_port or cast(
        CopyExecutionPort,
        PolymarketSecureAdapter(
            server_time_reader=PolymarketServerTimeReader(
                timeout_seconds=float(
                    config.settings.polymarket_server_time_timeout_seconds
                ),
                max_attempts=config.settings.polymarket_read_max_attempts,
                backoff_seconds=float(config.settings.polymarket_read_backoff_seconds),
            )
        )
    )
    active_geoblock = geoblock_port or PreLiveOrderGeoblockCheck()
    active_kill_switch = kill_switch or KillSwitch()
    started_at = _aware(clock())
    signal_window_end = started_at + timedelta(hours=config.signal_window_hours)
    git_commit = _deployed_commit(config.project_root)
    report = TinyLiveCopyReport(
        run_id=config.run_id,
        git_commit=git_commit,
        started_at=started_at,
        signal_window_end=signal_window_end,
        state=CopyExperimentState.PREFLIGHT.value,
        classification="RUNNING",
        starting_account_balance=None,
        final_account_balance=None,
        geoblock_status="not_checked",
        total_entry_attempts=0,
        completed_live_cycles=0,
        signal_count=0,
        event_count=0,
        duplicate_count=0,
        current_order_or_fill_exists=False,
        emergency_cancel_status="available_not_invoked",
        websocket_health="not_checked",
        heartbeat_health="starting",
        candidate_runtime_file_deleted=False,
        stop_reason=None,
        candidate_summary=bank.to_safe_dict(),
    )
    runtime = _Runtime(report=report, last_poll_at=started_at)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    with SQLiteDatabase(config.database_path) as database:
        repository = CopyExperimentRepository(database.connection)
        existing = repository.get(config.run_id)
        if existing is None:
            repository.create(
                run_id=config.run_id,
                authorization_id=AUTHORIZATION_ID,
                started_at=started_at,
                signal_window_end=signal_window_end,
                payload={
                    "candidate_digest": bank.source_digest,
                    "candidate_count": EXPECTED_CANDIDATE_COUNT,
                    "maximum_completed_live_cycles": MAXIMUM_COMPLETED_LIVE_CYCLES,
                    "maximum_entry_debit": str(MAXIMUM_ENTRY_DEBIT),
                    "maximum_total_entry_attempts": MAXIMUM_TOTAL_ENTRY_ATTEMPTS,
                },
            )
        else:
            signal_window_end = repository.signal_window_end(config.run_id)
            report.signal_window_end = signal_window_end

        try:
            await _preflight(
                config,
                execution_port=active_execution_port,
                geoblock_port=active_geoblock,
                kill_switch=active_kill_switch,
                report=report,
                git_commit=git_commit,
                restart_snapshot=existing,
            )
            _refresh_report(repository, config.run_id, report)
            write_tiny_live_copy_reports(report, config.output_dir)
            if (
                existing is not None
                and existing.state is CopyExperimentState.FAILED_SAFE
            ):
                await _emergency_cancel_if_needed(
                    active_execution_port,
                    repository=repository,
                    run_id=config.run_id,
                    report=report,
                    clock=clock,
                )
                report.classification = "FAILED_SAFE"
                report.stop_reason = (
                    "restarted failed-safe run reconciled without new action"
                )
                return report
            await _baseline_if_needed(
                config,
                source=active_source,
                repository=repository,
                bank_aliases=bank.aliases,
                runtime=runtime,
                clock=clock,
                sleeper=sleeper,
            )
            _refresh_report(repository, config.run_id, report)
            write_tiny_live_copy_reports(report, config.output_dir)
            await _reconcile_restart(
                config,
                repository=repository,
                market_port=active_market_port,
                execution_port=active_execution_port,
                runtime=runtime,
                clock=clock,
            )
            if existing is not None:
                runtime.report.decisions.append(
                    {
                        "action": "RESTART_RECONCILED",
                        "completed_live_cycles": existing.completed_live_cycles,
                        "prior_state": existing.state.value,
                        "timestamp": _aware(clock()).isoformat(),
                        "total_entry_attempts": existing.total_entry_attempts,
                    }
                )
            restored = repository.get(config.run_id)
            assert restored is not None
            if (
                restored.state is CopyExperimentState.POSITION_OPEN
                and restored.position_size > 0
                and restored.exit_order_id is None
            ):
                await _place_take_profit(
                    config,
                    execution_port=active_execution_port,
                    market_port=active_market_port,
                    geoblock_port=active_geoblock,
                    kill_switch=active_kill_switch,
                    repository=repository,
                    runtime=runtime,
                    clock=clock,
                )
            await _monitor(
                config,
                source=active_source,
                market_port=active_market_port,
                execution_port=active_execution_port,
                geoblock_port=active_geoblock,
                kill_switch=active_kill_switch,
                repository=repository,
                aliases=bank.aliases,
                runtime=runtime,
                clock=clock,
                sleeper=sleeper,
            )
        except asyncio.CancelledError:
            await _emergency_cancel_if_needed(
                active_execution_port,
                repository=repository,
                run_id=config.run_id,
                report=report,
                clock=clock,
            )
            raise
        except Exception as error:
            report.stop_reason = _safe_error(error)
            report.classification = "FAILED_SAFE"
            report.state = CopyExperimentState.FAILED_SAFE.value
            repository.set_state(
                config.run_id,
                CopyExperimentState.FAILED_SAFE,
                updated_at=_aware(clock()),
                signal_acceptance_open=False,
                payload={"safe_error": report.stop_reason},
            )
            await _emergency_cancel_if_needed(
                active_execution_port,
                repository=repository,
                run_id=config.run_id,
                report=report,
                clock=clock,
            )
        finally:
            if active_execution_port.is_connected:
                try:
                    final_collateral = _mapping(
                        await active_execution_port.get_balance_allowance(
                            asset_type="COLLATERAL"
                        )
                    )
                    report.final_account_balance = _base_units(
                        final_collateral.get("balance")
                    )
                except Exception:
                    report.api_errors += 1
            snapshot = repository.get(config.run_id)
            _refresh_report(repository, config.run_id, report)
            report.attempts = _safe_attempts(repository.attempts(config.run_id))
            write_tiny_live_copy_reports(report, config.output_dir)
            try:
                await active_execution_port.close()
            except Exception:
                report.api_errors += 1
            if (
                config.delete_candidate_file_on_terminal
                and snapshot is not None
                and snapshot.state in TERMINAL_STATES
                and (
                    snapshot.state is CopyExperimentState.REDEEMABLE
                    or (
                        snapshot.entry_order_id is None
                        and snapshot.exit_order_id is None
                        and snapshot.position_size == 0
                    )
                )
            ):
                config.candidate_file.unlink(missing_ok=True)
                report.candidate_runtime_file_deleted = (
                    not config.candidate_file.exists()
                )
            write_tiny_live_copy_reports(report, config.output_dir)
    return report


async def _preflight(
    config: TinyLiveCopyConfig,
    *,
    execution_port: CopyExecutionPort,
    geoblock_port: CopyGeoblockPort,
    kill_switch: KillSwitch,
    report: TinyLiveCopyReport,
    git_commit: str | None,
    restart_snapshot: Any | None,
) -> None:
    if distribution_version("polymarket-client") != APPROVED_SDK_VERSION:
        raise TinyLiveCopyError("approved Polymarket SDK version is not installed")
    if kill_switch.is_active():
        raise TinyLiveCopyError("kill switch is active")
    if not config.dry_run:
        if config.settings.trading_mode is not TradingMode.LIVE:
            raise TinyLiveCopyError("live experiment requires TRADING_MODE=LIVE")
        if not config.settings.live_trading_enabled:
            raise TinyLiveCopyError("live experiment requires LIVE_TRADING_ENABLED=true")
        if not config.acknowledgement:
            raise TinyLiveCopyError("owner acknowledgement does not match the experiment")
        _assert_synchronized_main(config, git_commit)
    if config.settings.polymarket_private_key is None:
        raise TinyLiveCopyError("authenticated read preflight requires test credentials")
    if not execution_port.is_connected:
        await execution_port.connect()
    identity = _mapping(execution_port.identity())
    _assert_identity(identity)
    drift = await evaluate_clock_drift(
        execution_port,
        threshold_seconds=config.settings.polymarket_max_clock_drift_seconds,
    )
    if drift.status != "pass":
        raise TinyLiveCopyError("server clock preflight failed")
    geoblock = await geoblock_port.check()
    report.geoblock_status = geoblock.status
    if geoblock.status != "allowed" or geoblock.blocked is not False:
        raise TinyLiveCopyError("official geoblock preflight did not allow trading")
    await execution_port.probe_user_stream()
    report.websocket_health = "authenticated_probe_passed"
    collateral = _mapping(
        await execution_port.get_balance_allowance(asset_type="COLLATERAL")
    )
    balance = _base_units(collateral.get("balance"))
    allowances = collateral.get("allowances")
    if not isinstance(allowances, dict) or not allowances:
        raise TinyLiveCopyError("collateral allowance is unreadable")
    if balance > MAXIMUM_ACCOUNT_BALANCE or (
        balance <= 0 and restart_snapshot is None
    ):
        raise TinyLiveCopyError(
            "account balance is outside the owner-authorized range"
        )
    open_orders = await execution_port.get_open_orders()
    positions = await execution_port.list_positions(size_threshold=0)
    if restart_snapshot is None:
        if open_orders:
            raise TinyLiveCopyError(
                "unrelated open orders exist in the dedicated test account"
            )
        if any(_position_size(position) > 0 for position in positions):
            raise TinyLiveCopyError(
                "unrelated positions exist in the dedicated test account"
            )
    else:
        _assert_restart_account_scope(
            restart_snapshot,
            open_orders=open_orders,
            positions=positions,
        )
    if not callable(getattr(execution_port, "cancel_all", None)):
        raise TinyLiveCopyError("emergency cancel-all is unavailable")
    report.starting_account_balance = balance


async def _baseline_if_needed(
    config: TinyLiveCopyConfig,
    *,
    source: LeaderTradeSourcePort,
    repository: CopyExperimentRepository,
    bank_aliases: tuple[str, ...],
    runtime: _Runtime,
    clock: Clock,
    sleeper: Sleeper,
) -> None:
    if repository.baselined_count(config.run_id) == EXPECTED_CANDIDATE_COUNT:
        snapshot = repository.get(config.run_id)
        if snapshot is not None and snapshot.state in {
            CopyExperimentState.PREFLIGHT,
            CopyExperimentState.BASELINING,
        }:
            repository.set_state(
                config.run_id,
                CopyExperimentState.MONITORING,
                updated_at=_aware(clock()),
            )
        return
    repository.set_state(
        config.run_id,
        CopyExperimentState.BASELINING,
        updated_at=_aware(clock()),
        signal_acceptance_open=False,
    )
    semaphore = asyncio.Semaphore(10)

    async def baseline(alias: str) -> None:
        async with semaphore:
            snapshot = await source.read_inventory(alias)
            for (market_reference, outcome_reference), size in snapshot.positions.items():
                repository.set_inventory(
                    run_id=config.run_id,
                    leader_alias=alias,
                    market_reference=market_reference,
                    outcome_reference=outcome_reference,
                    size=size,
                    updated_at=snapshot.observed_at,
                )
            repository.mark_baselined(
                run_id=config.run_id,
                leader_alias=alias,
                baseline_digest=snapshot.evidence_digest,
                baselined_at=snapshot.observed_at,
            )

    await asyncio.gather(*(baseline(alias) for alias in bank_aliases))
    # The inventory baseline already consumes at least one request per leader.
    # Keep the subsequent 102-leader trade checkpoint in a separate official
    # Data API rate window.
    await sleeper(float(BASELINE_RATE_COOLDOWN_SECONDS))
    baseline_end = _aware(clock())
    pages = await _poll_aliases(
        source,
        aliases=bank_aliases,
        start_at=baseline_end - timedelta(seconds=BASELINE_OVERLAP_SECONDS),
        end_at=baseline_end,
    )
    for event in pages:
        repository.mark_seen(
            run_id=config.run_id,
            event_id=event.event_id,
            leader_alias=event.leader_id,
            observed_at=event.observed_at,
        )
    await sleeper(float(BASELINE_RATE_COOLDOWN_SECONDS))
    runtime.last_poll_at = baseline_end
    repository.set_state(
        config.run_id,
        CopyExperimentState.MONITORING,
        updated_at=baseline_end,
        signal_acceptance_open=True,
    )


async def _monitor(
    config: TinyLiveCopyConfig,
    *,
    source: LeaderTradeSourcePort,
    market_port: CopyMarketPort,
    execution_port: CopyExecutionPort,
    geoblock_port: CopyGeoblockPort,
    kill_switch: KillSwitch,
    repository: CopyExperimentRepository,
    aliases: tuple[str, ...],
    runtime: _Runtime,
    clock: Clock,
    sleeper: Sleeper,
) -> None:
    cycles = 0
    while True:
        now = _aware(clock())
        if runtime.last_poll_at != runtime.report.started_at and not _heartbeat_is_fresh(
            runtime.last_poll_at,
            now,
        ):
            runtime.report.heartbeat_health = "failed"
            raise TinyLiveCopyError("collector heartbeat exceeded the safe gap")
        runtime.report.heartbeat_health = "healthy"
        snapshot = repository.get(config.run_id)
        assert snapshot is not None
        if snapshot.state in TERMINAL_STATES:
            runtime.report.classification = _terminal_classification(snapshot, now, runtime)
            runtime.report.stop_reason = _terminal_stop_reason(snapshot, now, runtime)
            return
        if now >= runtime.report.signal_window_end and snapshot.position_size == 0:
            repository.set_state(
                config.run_id,
                CopyExperimentState.FINALIZED,
                updated_at=now,
                signal_acceptance_open=False,
            )
            runtime.report.classification = (
                "NO_SIGNAL_INCONCLUSIVE"
                if snapshot.total_entry_attempts == 0
                else "SIGNAL_WINDOW_ENDED"
            )
            runtime.report.stop_reason = "12-hour signal window ended"
            return
        if config.maximum_poll_cycles is not None and cycles >= config.maximum_poll_cycles:
            runtime.report.classification = "DRY_RUN_BOUNDED_COMPLETE"
            return
        cycles += 1

        if snapshot.position_size > 0 or snapshot.entry_order_id is not None:
            active_alias = snapshot.active_leader_alias
            if active_alias is not None:
                active_events = await _poll_aliases(
                    source,
                    aliases=(active_alias,),
                    start_at=runtime.last_poll_at - timedelta(seconds=POLL_OVERLAP_SECONDS),
                    end_at=now,
                )
                runtime.last_poll_at = now
                _ingest_events(
                    config,
                    source=source,
                    repository=repository,
                    events=active_events,
                    runtime=runtime,
                )
            refreshed_before_manage = repository.get(config.run_id)
            assert refreshed_before_manage is not None
            leader_closed = bool(
                refreshed_before_manage.active_leader_alias
                and refreshed_before_manage.active_market_id
                and refreshed_before_manage.active_token_id
                and repository.inventory(
                    run_id=config.run_id,
                    leader_alias=refreshed_before_manage.active_leader_alias,
                    market_reference=refreshed_before_manage.active_market_id,
                    outcome_reference=refreshed_before_manage.active_token_id,
                )
                == 0
            )
            await _manage_active(
                config,
                market_port=market_port,
                execution_port=execution_port,
                geoblock_port=geoblock_port,
                kill_switch=kill_switch,
                repository=repository,
                runtime=runtime,
                clock=clock,
                cancel_pending_for_leader_close=leader_closed,
            )
            refreshed = repository.get(config.run_id)
            assert refreshed is not None
            if (
                refreshed.position_size > 0
                and refreshed.active_leader_alias is not None
                and refreshed.active_market_id is not None
                and refreshed.active_token_id is not None
                and repository.inventory(
                    run_id=config.run_id,
                    leader_alias=refreshed.active_leader_alias,
                    market_reference=refreshed.active_market_id,
                    outcome_reference=refreshed.active_token_id,
                )
                == 0
            ):
                await _handle_leader_close(
                    config,
                    market_port=market_port,
                    execution_port=execution_port,
                    geoblock_port=geoblock_port,
                    kill_switch=kill_switch,
                    repository=repository,
                    runtime=runtime,
                    clock=clock,
                )
        else:
            events = await _poll_aliases(
                source,
                aliases=aliases,
                start_at=runtime.last_poll_at - timedelta(seconds=POLL_OVERLAP_SECONDS),
                end_at=now,
            )
            runtime.last_poll_at = now
            signals = _ingest_events(
                config,
                source=source,
                repository=repository,
                events=events,
                runtime=runtime,
            )
            snapshot = repository.get(config.run_id)
            assert snapshot is not None
            if snapshot.signal_acceptance_open and signals:
                for signal in signals:
                    if await _attempt_entry(
                        config,
                        event=signal,
                        source=source,
                        market_port=market_port,
                        execution_port=execution_port,
                        geoblock_port=geoblock_port,
                        kill_switch=kill_switch,
                        repository=repository,
                        runtime=runtime,
                        clock=clock,
                    ):
                        break
        _refresh_report(repository, config.run_id, runtime.report)
        write_tiny_live_copy_reports(runtime.report, config.output_dir)
        await sleeper(float(config.poll_interval_seconds))


def _ingest_events(
    config: TinyLiveCopyConfig,
    *,
    source: LeaderTradeSourcePort,
    repository: CopyExperimentRepository,
    events: tuple[LeaderTradeEvent, ...],
    runtime: _Runtime,
) -> list[LeaderTradeEvent]:
    signals: list[LeaderTradeEvent] = []
    used = repository.used_leaders(config.run_id)
    for event in sorted(events, key=lambda item: (item.executed_at, item.leader_id, item.event_id)):
        if not repository.mark_seen(
            run_id=config.run_id,
            event_id=event.event_id,
            leader_alias=event.leader_id,
            observed_at=event.observed_at,
        ):
            runtime.report.duplicate_count += 1
            continue
        runtime.report.event_count += 1
        current = repository.inventory(
            run_id=config.run_id,
            leader_alias=event.leader_id,
            market_reference=event.market_reference,
            outcome_reference=event.outcome_reference,
        )
        if current is None:
            if not repository.is_baselined(
                run_id=config.run_id,
                leader_alias=event.leader_id,
            ):
                continue
            current = Decimal("0")
        effect = LeaderPositionEffect.UNKNOWN
        next_size = current
        if event.trade_action is LeaderTradeAction.BUY:
            effect = (
                LeaderPositionEffect.OPEN
                if current == 0
                else LeaderPositionEffect.INCREASE
            )
            next_size = current + event.executed_size
        elif event.executed_size < current:
            effect = LeaderPositionEffect.REDUCE
            next_size = current - event.executed_size
        elif event.executed_size == current and current > 0:
            effect = LeaderPositionEffect.CLOSE
            next_size = Decimal("0")
        repository.set_inventory(
            run_id=config.run_id,
            leader_alias=event.leader_id,
            market_reference=event.market_reference,
            outcome_reference=event.outcome_reference,
            size=next_size,
            updated_at=event.observed_at,
        )
        metadata = source.market_metadata(
            event.market_reference,
            event.outcome_reference,
        )
        safe_event: dict[str, object] = {
            "event_id": event.event_id,
            "leader_alias": event.leader_id,
            "market_reference": event.market_reference,
            "outcome_label": metadata.outcome_label,
            "position_effect": effect.value,
            "trade_action": event.trade_action.value,
            "executed_at": event.executed_at.isoformat(),
            "observed_at": event.observed_at.isoformat(),
        }
        runtime.report.sanitized_events.append(safe_event)
        if (
            effect is LeaderPositionEffect.OPEN
            and event.trade_action is LeaderTradeAction.BUY
            and event.leader_id not in used
            and signal_is_fresh(
                executed_at=event.executed_at,
                observed_at=event.observed_at,
                market_end=metadata.ends_at,
            )
        ):
            signals.append(event)
            runtime.report.signal_count += 1
    return signals


async def _attempt_entry(
    config: TinyLiveCopyConfig,
    *,
    event: LeaderTradeEvent,
    source: LeaderTradeSourcePort,
    market_port: CopyMarketPort,
    execution_port: CopyExecutionPort,
    geoblock_port: CopyGeoblockPort,
    kill_switch: KillSwitch,
    repository: CopyExperimentRepository,
    runtime: _Runtime,
    clock: Clock,
) -> bool:
    now = _aware(clock())
    metadata = source.market_metadata(event.market_reference, event.outcome_reference)
    if not signal_is_fresh(
        executed_at=event.executed_at,
        observed_at=now,
        market_end=metadata.ends_at,
    ):
        runtime.report.decisions.append(
            {
                "action": "SIGNAL_REJECTED_STALE_AT_SUBMISSION",
                "event_id": event.event_id,
                "leader_alias": event.leader_id,
                "timestamp": now.isoformat(),
            }
        )
        return False
    market = await market_port.get_market_by_slug(metadata.external_slug)
    book = await market_port.get_order_book(event.outcome_reference)
    try:
        _assert_market_mapping(
            market,
            expected_slug=metadata.external_slug,
            expected_condition=event.market_reference,
            token_id=event.outcome_reference,
            expected_start=metadata.starts_at,
            expected_end=metadata.ends_at,
            now=now,
        )
        if book.best_ask is None or _book_age_ms(book, now) > MAXIMUM_BOOK_AGE_MS:
            raise CopySignalSkip("orderbook is empty or stale")
        preliminary_quote = calculate_entry_quote(
            leader_fill_price=event.executed_price,
            minimum_order_size=book.minimum_order_size,
            tick_size=book.tick_size,
            best_ask=book.best_ask.price,
            expected_fee=Decimal("0"),
            now=now,
            market_end=metadata.ends_at,
        )
        expected_fee = Btc15mFavoriteTakeProfitStrategy.expected_fee(
            market,
            price=preliminary_quote.price,
            size=book.minimum_order_size,
        )
        quote = calculate_entry_quote(
            leader_fill_price=event.executed_price,
            minimum_order_size=book.minimum_order_size,
            tick_size=book.tick_size,
            best_ask=book.best_ask.price,
            expected_fee=expected_fee,
            now=now,
            market_end=metadata.ends_at,
        )
        calculate_take_profit_price(quote.price, tick_size=book.tick_size)
    except (CopySignalSkip, ValueError) as error:
        runtime.report.decisions.append(
            {
                "action": "SIGNAL_SKIPPED_LOCAL_INELIGIBILITY",
                "event_id": event.event_id,
                "leader_alias": event.leader_id,
                "reason": str(error),
                "timestamp": now.isoformat(),
            }
        )
        return False
    await _refresh_safety_gates(
        execution_port=execution_port,
        geoblock_port=geoblock_port,
        kill_switch=kill_switch,
        token_id=event.outcome_reference,
        required_size=quote.quantity,
        required_debit=quote.maximum_debit,
        settings=config.settings,
    )
    intent = OrderIntent(
        strategy_id=STRATEGY_ID,
        token_id=event.outcome_reference,
        side="BUY",
        price=quote.price,
        size=quote.quantity,
        reason=f"copy proven OPEN from {event.leader_id}",
        confidence=Decimal("1"),
    )
    broker = _broker_for(
        config.settings,
        execution_port,
        geoblock_port=geoblock_port,
        kill_switch=kill_switch,
        token_id=event.outcome_reference,
        maximum_position=quote.quantity,
        maximum_order_notional=MAXIMUM_ENTRY_DEBIT,
    )
    risk_context = RiskContext(
        trading_mode=TradingMode.LIVE,
        live_trading_enabled=True,
        current_position=Decimal("0"),
        current_market_position=Decimal("0"),
        daily_pnl=Decimal("0"),
        open_orders_count=0,
        market_data_age_ms=_book_age_ms(book, now),
    )
    claim: dict[str, int] = {}

    def persist_attempt() -> None:
        attempt = repository.claim_entry_attempt(
            run_id=config.run_id,
            leader_alias=event.leader_id,
            event_id=event.event_id,
            market_id=event.market_reference,
            market_slug=metadata.external_slug,
            token_id=event.outcome_reference,
            entry_price=quote.price,
            entry_quantity=quote.quantity,
            entry_debit=quote.maximum_debit,
            entry_fee=quote.expected_fee,
            entry_cancel_at=quote.cancel_at,
            leader_latency_ms=max(
                0,
                int((now - event.executed_at).total_seconds() * 1000),
            ),
            leader_price_difference=quote.price - event.executed_price,
            claimed_at=_aware(clock()),
        )
        if attempt is None:
            raise TinyLiveCopyError("duplicate prevention blocked the entry attempt")
        claim["number"] = attempt

    runtime.report.orderbook_snapshots.append(
        _safe_book_snapshot(book, event=event, quote=quote, captured_at=now)
    )
    runtime.report.decisions.append(
        {
            "action": "ENTRY_APPROVED",
            "leader_alias": event.leader_id,
            "event_id": event.event_id,
            "maximum_debit": str(quote.maximum_debit),
            "price": str(quote.price),
            "quantity": str(quote.quantity),
            "timestamp": now.isoformat(),
        }
    )
    if config.dry_run:
        runtime.report.classification = "DRY_RUN_APPROVED_NO_SUBMISSION"
        return True
    try:
        result = await broker.place_limit_order(
            intent,
            risk_context,
            i_understand_this_places_real_orders=True,
            dry_run=False,
            post_only=True,
            expiration=quote.venue_expiration,
            before_submit=persist_attempt,
        )
    except Exception:
        if "number" in claim:
            repository.record_entry_submission(
                run_id=config.run_id,
                attempt_number=claim["number"],
                venue_order_id=None,
                state="SUBMISSION_REJECTED_OR_UNKNOWN",
                updated_at=_aware(clock()),
            )
        raise
    order_id = _order_id(result.response)
    attempt_number = claim["number"]
    repository.record_entry_submission(
        run_id=config.run_id,
        attempt_number=attempt_number,
        venue_order_id=order_id,
        state="ENTRY_PENDING",
        updated_at=_aware(clock()),
    )
    runtime.active_attempt_number = attempt_number
    runtime.active_market = market
    runtime.active_token_id = event.outcome_reference
    runtime.active_entry_price = quote.price
    runtime.active_entry_fee = expected_fee
    runtime.active_cancel_at = quote.cancel_at
    runtime.report.current_order_or_fill_exists = True
    return True


async def _manage_active(
    config: TinyLiveCopyConfig,
    *,
    market_port: CopyMarketPort,
    execution_port: CopyExecutionPort,
    geoblock_port: CopyGeoblockPort,
    kill_switch: KillSwitch,
    repository: CopyExperimentRepository,
    runtime: _Runtime,
    clock: Clock,
    cancel_pending_for_leader_close: bool = False,
) -> None:
    snapshot = repository.get(config.run_id)
    assert snapshot is not None
    now = _aware(clock())
    if snapshot.entry_order_id is not None:
        try:
            await _refresh_active_health(
                execution_port=execution_port,
                geoblock_port=geoblock_port,
                kill_switch=kill_switch,
                settings=config.settings,
            )
        except Exception:
            await execution_port.cancel_order(order_id=snapshot.entry_order_id)
            await _confirm_not_open(execution_port, snapshot.entry_order_id)
            repository.record_no_fill(
                run_id=config.run_id,
                attempt_number=(
                    runtime.active_attempt_number or snapshot.total_entry_attempts
                ),
                updated_at=now,
                signal_window_open=False,
            )
            raise
        fill_size, fill_price = await _confirmed_fill(
            execution_port,
            order_id=snapshot.entry_order_id,
            token_id=runtime.active_token_id,
        )
        if fill_size > 0:
            await execution_port.cancel_order(order_id=snapshot.entry_order_id)
            await _confirm_not_open(execution_port, snapshot.entry_order_id)
            position_size = await _account_position(
                execution_port,
                runtime.active_token_id,
            )
            if position_size <= 0 or position_size > fill_size:
                raise TinyLiveCopyError("partial/full fill position reconciliation failed")
            attempt_number = runtime.active_attempt_number or snapshot.total_entry_attempts
            if runtime.active_market is None:
                raise TinyLiveCopyError("active market is unavailable after fill")
            entry_fee = Btc15mFavoriteTakeProfitStrategy.expected_fee(
                runtime.active_market,
                price=fill_price,
                size=position_size,
            )
            repository.record_fill(
                run_id=config.run_id,
                attempt_number=attempt_number,
                position_size=position_size,
                fill_price=fill_price,
                entry_fee=entry_fee,
                updated_at=now,
            )
            runtime.active_fill_size = position_size
            runtime.active_fill_price = fill_price
            runtime.active_entry_fee = entry_fee
            await _place_take_profit(
                config,
                execution_port=execution_port,
                market_port=market_port,
                geoblock_port=geoblock_port,
                kill_switch=kill_switch,
                repository=repository,
                runtime=runtime,
                clock=clock,
            )
            return
        if (
            cancel_pending_for_leader_close
            or runtime.active_cancel_at is None
            or now >= runtime.active_cancel_at
        ):
            await execution_port.cancel_order(order_id=snapshot.entry_order_id)
            await _confirm_not_open(execution_port, snapshot.entry_order_id)
            attempt_number = runtime.active_attempt_number or snapshot.total_entry_attempts
            repository.record_no_fill(
                run_id=config.run_id,
                attempt_number=attempt_number,
                updated_at=now,
                signal_window_open=now < runtime.report.signal_window_end,
            )
            runtime.report.decisions.append(
                {
                    "action": (
                        "ENTRY_CANCELLED_ON_PROVEN_LEADER_CLOSE"
                        if cancel_pending_for_leader_close
                        else "ENTRY_UNFILLED_CANCELLED"
                    ),
                    "attempt_number": attempt_number,
                    "timestamp": now.isoformat(),
                }
            )
            return

    snapshot = repository.get(config.run_id)
    assert snapshot is not None
    if snapshot.position_size <= 0:
        return
    position_size = await _account_position(execution_port, runtime.active_token_id)
    if position_size == 0:
        exit_size = Decimal("0")
        exit_price = Decimal("0")
        exit_fee = Decimal("0")
        if snapshot.exit_order_id is not None:
            exit_size, observed_exit_price = await _confirmed_fill(
                execution_port,
                order_id=snapshot.exit_order_id,
                token_id=runtime.active_token_id,
            )
            if exit_size > 0:
                exit_price = observed_exit_price
                if runtime.active_market is None:
                    raise TinyLiveCopyError("active market is unavailable at exit")
                exit_fee = Btc15mFavoriteTakeProfitStrategy.expected_fee(
                    runtime.active_market,
                    price=exit_price,
                    size=exit_size,
                )
            await execution_port.cancel_order(order_id=snapshot.exit_order_id)
            await _confirm_not_open(execution_port, snapshot.exit_order_id)
        if exit_size == snapshot.position_size and runtime.active_fill_price is not None:
            gross_pnl, net_pnl = calculate_realized_pnl(
                entry_price=runtime.active_fill_price,
                exit_price=exit_price,
                quantity=snapshot.position_size,
                entry_fee=runtime.active_entry_fee,
                exit_fee=exit_fee,
            )
            repository.record_terminal_pnl(
                run_id=config.run_id,
                exit_price=exit_price,
                exit_fee=exit_fee,
                gross_pnl=gross_pnl,
                net_pnl=net_pnl,
                terminal_reason="POSITION_CLOSED_RECONCILED",
                updated_at=now,
            )
        else:
            runtime.report.decisions.append(
                {
                    "action": "POSITION_CLOSED_WITH_UNPRICED_EXTERNAL_INTERVENTION",
                    "timestamp": now.isoformat(),
                }
            )
        repository.complete_cycle(
            run_id=config.run_id,
            updated_at=now,
            signal_window_open=now < runtime.report.signal_window_end,
        )
        runtime.report.decisions.append(
            {"action": "POSITION_CLOSED_RECONCILED", "timestamp": now.isoformat()}
        )
        return
    if position_size > snapshot.position_size:
        raise TinyLiveCopyError("venue position exceeds the confirmed follower position")
    if runtime.active_market is not None and runtime.active_market.end_date is not None:
        market_end = _aware(runtime.active_market.end_date)
        if now >= market_end:
            if snapshot.exit_order_id is not None:
                await execution_port.cancel_order(order_id=snapshot.exit_order_id)
                await _confirm_not_open(execution_port, snapshot.exit_order_id)
                repository.clear_exit_order(
                    run_id=config.run_id,
                    state=CopyExperimentState.AWAITING_RESOLUTION,
                    updated_at=now,
                )
            if runtime.active_market.slug is None:
                raise TinyLiveCopyError("active market slug is unavailable at resolution")
            refreshed = await market_port.get_market_by_slug(runtime.active_market.slug)
            selected = next(
                (
                    outcome
                    for outcome in refreshed.outcomes
                    if outcome.token_id == runtime.active_token_id
                ),
                None,
            )
            if selected is not None and selected.price in {Decimal("0"), Decimal("1")}:
                if runtime.active_fill_price is None:
                    raise TinyLiveCopyError("fill price is unavailable at resolution")
                gross_pnl, net_pnl = calculate_realized_pnl(
                    entry_price=runtime.active_fill_price,
                    exit_price=selected.price,
                    quantity=snapshot.position_size,
                    entry_fee=runtime.active_entry_fee,
                    exit_fee=Decimal("0"),
                )
                terminal_reason = (
                    "RESOLUTION_WIN_REDEEMABLE"
                    if selected.price == Decimal("1")
                    else "RESOLUTION_FULL_ENTRY_DEBIT_LOSS"
                )
                repository.record_terminal_pnl(
                    run_id=config.run_id,
                    exit_price=selected.price,
                    exit_fee=Decimal("0"),
                    gross_pnl=gross_pnl,
                    net_pnl=net_pnl,
                    terminal_reason=terminal_reason,
                    updated_at=now,
                )
                runtime.report.decisions.append(
                    {
                        "action": (
                            "RESOLUTION_WIN_REDEEMABLE"
                            if selected.price == Decimal("1")
                            else "RESOLUTION_FULL_ENTRY_DEBIT_LOSS"
                        ),
                        "gross_pnl": str(gross_pnl),
                        "net_pnl": str(net_pnl),
                        "quantity": str(snapshot.position_size),
                        "timestamp": now.isoformat(),
                    }
                )
                if selected.price == Decimal("1"):
                    repository.complete_redeemable_cycle(
                        run_id=config.run_id,
                        updated_at=now,
                    )
                else:
                    repository.complete_cycle(
                        run_id=config.run_id,
                        updated_at=now,
                        signal_window_open=now < runtime.report.signal_window_end,
                    )


async def _place_take_profit(
    config: TinyLiveCopyConfig,
    *,
    execution_port: CopyExecutionPort,
    market_port: CopyMarketPort,
    geoblock_port: CopyGeoblockPort,
    kill_switch: KillSwitch,
    repository: CopyExperimentRepository,
    runtime: _Runtime,
    clock: Clock,
) -> None:
    if (
        runtime.active_token_id is None
        or runtime.active_market is None
        or runtime.active_fill_price is None
        or runtime.active_fill_size <= 0
    ):
        raise TinyLiveCopyError("confirmed fill context is incomplete")
    book = await market_port.get_order_book(runtime.active_token_id)
    if runtime.active_fill_size < book.minimum_order_size:
        repository.set_state(
            config.run_id,
            CopyExperimentState.AWAITING_RESOLUTION,
            updated_at=_aware(clock()),
            signal_acceptance_open=False,
        )
        return
    target = calculate_take_profit_price(
        runtime.active_fill_price,
        tick_size=book.tick_size,
    )
    intent = OrderIntent(
        strategy_id=STRATEGY_ID,
        token_id=runtime.active_token_id,
        side="SELL",
        price=target,
        size=runtime.active_fill_size,
        reason="10% take-profit from confirmed follower weighted-average fill",
        confidence=Decimal("1"),
    )
    broker = _broker_for(
        config.settings,
        execution_port,
        geoblock_port=geoblock_port,
        kill_switch=kill_switch,
        token_id=runtime.active_token_id,
        maximum_position=runtime.active_fill_size,
        maximum_order_notional=runtime.active_fill_size,
    )
    result = await broker.place_limit_order(
        intent,
        RiskContext(
            trading_mode=TradingMode.LIVE,
            live_trading_enabled=True,
            current_position=runtime.active_fill_size,
            current_market_position=runtime.active_fill_size,
            open_orders_count=0,
            market_data_age_ms=_book_age_ms(book, _aware(clock())),
        ),
        i_understand_this_places_real_orders=True,
        dry_run=False,
    )
    order_id = _order_id(result.response)
    exit_fee = Btc15mFavoriteTakeProfitStrategy.expected_fee(
        runtime.active_market,
        price=target,
        size=runtime.active_fill_size,
    )
    repository.record_exit_order(
        run_id=config.run_id,
        order_id=order_id,
        exit_price=target,
        exit_fee=exit_fee,
        updated_at=_aware(clock()),
    )
    runtime.report.decisions.append(
        {
            "action": "TAKE_PROFIT_SUBMITTED",
            "order_id_digest": _digest(order_id),
            "price": str(target),
            "quantity": str(runtime.active_fill_size),
            "timestamp": _aware(clock()).isoformat(),
        }
    )


async def _handle_leader_close(
    config: TinyLiveCopyConfig,
    *,
    market_port: CopyMarketPort,
    execution_port: CopyExecutionPort,
    geoblock_port: CopyGeoblockPort,
    kill_switch: KillSwitch,
    repository: CopyExperimentRepository,
    runtime: _Runtime,
    clock: Clock,
) -> None:
    snapshot = repository.get(config.run_id)
    assert snapshot is not None
    if runtime.leader_close_exit_submitted:
        return
    if (
        snapshot.position_size <= 0
        or snapshot.active_token_id is None
        or runtime.active_market is None
        or runtime.active_fill_price is None
    ):
        return
    book = await market_port.get_order_book(snapshot.active_token_id)
    best_bid = book.best_bid
    if best_bid is None or best_bid.size < snapshot.position_size:
        runtime.report.decisions.append(
            {
                "action": "LEADER_CLOSE_HOLD_TP_INSUFFICIENT_BID_DEPTH",
                "timestamp": _aware(clock()).isoformat(),
            }
        )
        return
    exit_fee = Btc15mFavoriteTakeProfitStrategy.expected_fee(
        runtime.active_market,
        price=best_bid.price,
        size=snapshot.position_size,
    )
    entry_cost = (
        runtime.active_fill_price * snapshot.position_size
    ) + runtime.active_entry_fee
    net_exit = (best_bid.price * snapshot.position_size) - exit_fee
    if net_exit < entry_cost:
        runtime.report.decisions.append(
            {
                "action": "LEADER_CLOSE_NET_LOSS_HOLD_TO_TP_OR_RESOLUTION",
                "estimated_net_pnl": str(net_exit - entry_cost),
                "timestamp": _aware(clock()).isoformat(),
            }
        )
        return
    if snapshot.exit_order_id is not None:
        await execution_port.cancel_order(order_id=snapshot.exit_order_id)
        await _confirm_not_open(execution_port, snapshot.exit_order_id)
        repository.clear_exit_order(
            run_id=config.run_id,
            state=CopyExperimentState.POSITION_OPEN,
            updated_at=_aware(clock()),
        )
    intent = OrderIntent(
        strategy_id=STRATEGY_ID,
        token_id=snapshot.active_token_id,
        side="SELL",
        price=best_bid.price,
        size=snapshot.position_size,
        reason="proven leader CLOSE with non-negative follower net PnL",
        confidence=Decimal("1"),
    )
    broker = _broker_for(
        config.settings,
        execution_port,
        geoblock_port=geoblock_port,
        kill_switch=kill_switch,
        token_id=snapshot.active_token_id,
        maximum_position=snapshot.position_size,
        maximum_order_notional=snapshot.position_size,
    )
    result = await broker.place_market_order(
        intent,
        RiskContext(
            trading_mode=TradingMode.LIVE,
            live_trading_enabled=True,
            current_position=snapshot.position_size,
            current_market_position=snapshot.position_size,
            open_orders_count=0,
            market_data_age_ms=_book_age_ms(book, _aware(clock())),
        ),
        i_understand_this_places_real_orders=True,
        dry_run=False,
        shares=snapshot.position_size,
        min_price=best_bid.price,
        order_type="FOK",
    )
    order_id = _order_id(result.response)
    repository.record_exit_order(
        run_id=config.run_id,
        order_id=order_id,
        exit_price=best_bid.price,
        exit_fee=exit_fee,
        updated_at=_aware(clock()),
    )
    runtime.leader_close_exit_submitted = True
    runtime.report.decisions.append(
        {
            "action": "LEADER_CLOSE_NON_NEGATIVE_FOK_EXIT_SUBMITTED",
            "order_id_digest": _digest(order_id),
            "timestamp": _aware(clock()).isoformat(),
        }
    )
    await asyncio.sleep(1)
    remaining = await _account_position(execution_port, snapshot.active_token_id)
    if remaining == snapshot.position_size:
        repository.clear_exit_order(
            run_id=config.run_id,
            state=CopyExperimentState.POSITION_OPEN,
            updated_at=_aware(clock()),
        )
        await _place_take_profit(
            config,
            execution_port=execution_port,
            market_port=market_port,
            geoblock_port=geoblock_port,
            kill_switch=kill_switch,
            repository=repository,
            runtime=runtime,
            clock=clock,
        )
        runtime.report.decisions.append(
            {
                "action": "LEADER_CLOSE_FOK_NO_FILL_TAKE_PROFIT_RESTORED",
                "timestamp": _aware(clock()).isoformat(),
            }
        )
    elif remaining != 0:
        raise TinyLiveCopyError("leader-close FOK produced ambiguous partial position")


async def _refresh_safety_gates(
    *,
    execution_port: CopyExecutionPort,
    geoblock_port: CopyGeoblockPort,
    kill_switch: KillSwitch,
    token_id: str,
    required_size: Decimal,
    required_debit: Decimal,
    settings: AppSettings,
) -> None:
    if kill_switch.is_active():
        raise TinyLiveCopyError("kill switch activated before entry")
    drift = await evaluate_clock_drift(
        execution_port,
        threshold_seconds=settings.polymarket_max_clock_drift_seconds,
    )
    if drift.status != "pass":
        raise TinyLiveCopyError("clock drift failed immediately before entry")
    geoblock = await geoblock_port.check()
    if geoblock.status != "allowed" or geoblock.blocked is not False:
        raise TinyLiveCopyError("geoblock failed immediately before entry")
    await execution_port.probe_user_stream()
    if await execution_port.get_open_orders():
        raise TinyLiveCopyError("an open order appeared before entry")
    if any(
        _position_size(position) > 0
        for position in await execution_port.list_positions(size_threshold=0)
    ):
        raise TinyLiveCopyError("a position appeared before entry")
    collateral = _mapping(
        await execution_port.get_balance_allowance(asset_type="COLLATERAL")
    )
    balance = _base_units(collateral.get("balance"))
    if balance > MAXIMUM_ACCOUNT_BALANCE or balance < required_debit:
        raise TinyLiveCopyError("collateral balance fails the bounded debit gate")
    conditional = _mapping(
        await execution_port.get_balance_allowance(
            asset_type="CONDITIONAL",
            token_id=token_id,
        )
    )
    allowances = conditional.get("allowances")
    if not isinstance(allowances, dict) or not allowances:
        raise TinyLiveCopyError("outcome-token allowance is unreadable")
    if min(_base_units(value) for value in allowances.values()) < required_size:
        raise TinyLiveCopyError("existing outcome-token allowance cannot support the exit")


async def _refresh_active_health(
    *,
    execution_port: CopyExecutionPort,
    geoblock_port: CopyGeoblockPort,
    kill_switch: KillSwitch,
    settings: AppSettings,
) -> None:
    if kill_switch.is_active():
        raise TinyLiveCopyError("kill switch activated while entry was pending")
    drift = await evaluate_clock_drift(
        execution_port,
        threshold_seconds=settings.polymarket_max_clock_drift_seconds,
    )
    if drift.status != "pass":
        raise TinyLiveCopyError("clock drift failed while entry was pending")
    geoblock = await geoblock_port.check()
    if geoblock.status != "allowed" or geoblock.blocked is not False:
        raise TinyLiveCopyError("geoblock failed while entry was pending")
    await execution_port.probe_user_stream()


async def _reconcile_restart(
    config: TinyLiveCopyConfig,
    *,
    repository: CopyExperimentRepository,
    market_port: CopyMarketPort,
    execution_port: CopyExecutionPort,
    runtime: _Runtime,
    clock: Clock,
) -> None:
    snapshot = repository.get(config.run_id)
    assert snapshot is not None
    if snapshot.state in {
        CopyExperimentState.PREFLIGHT,
        CopyExperimentState.BASELINING,
    }:
        repository.set_state(
            config.run_id,
            CopyExperimentState.MONITORING,
            updated_at=_aware(clock()),
            signal_acceptance_open=True,
        )
        return
    if snapshot.state is CopyExperimentState.ENTRY_SUBMITTING:
        raise TinyLiveCopyError(
            "restart found an ambiguous entry submission; attempt remains consumed"
        )
    entry_orders: list[Any] | None = None
    if snapshot.entry_order_id is not None:
        entry_orders = await execution_port.get_open_orders(
            order_id=snapshot.entry_order_id
        )
        if len(entry_orders) > 1:
            raise TinyLiveCopyError("restart reconciliation found duplicate entry orders")
        runtime.active_attempt_number = snapshot.total_entry_attempts
    runtime.active_token_id = snapshot.active_token_id
    runtime.active_entry_price = snapshot.entry_price
    runtime.active_entry_fee = snapshot.entry_fee
    runtime.active_cancel_at = snapshot.entry_cancel_at
    runtime.active_fill_price = snapshot.fill_price
    runtime.active_fill_size = snapshot.position_size
    if snapshot.active_market_id is not None:
        attempts = repository.attempts(config.run_id)
        market_id = str(attempts[-1]["market_id"]) if attempts else snapshot.active_market_id
        if market_id != snapshot.active_market_id:
            raise TinyLiveCopyError("restart market identity evidence is inconsistent")
        if snapshot.active_market_slug is None:
            raise TinyLiveCopyError("restart market slug evidence is unavailable")
        runtime.active_market = await market_port.get_market_by_slug(
            snapshot.active_market_slug
        )
        if snapshot.fill_price is not None and snapshot.position_size > 0:
            runtime.active_entry_fee = Btc15mFavoriteTakeProfitStrategy.expected_fee(
                runtime.active_market,
                price=snapshot.fill_price,
                size=snapshot.position_size,
            )
    if snapshot.entry_order_id is not None and entry_orders == []:
        fill_size, fill_price = await _confirmed_fill(
            execution_port,
            order_id=snapshot.entry_order_id,
            token_id=snapshot.active_token_id,
        )
        if fill_size == 0:
            repository.record_no_fill(
                run_id=config.run_id,
                attempt_number=snapshot.total_entry_attempts,
                updated_at=_aware(clock()),
                signal_window_open=(
                    _aware(clock()) < repository.signal_window_end(config.run_id)
                ),
            )
            return
        actual = await _account_position(execution_port, snapshot.active_token_id)
        if actual <= 0 or actual > fill_size:
            raise TinyLiveCopyError("restart entry-fill reconciliation failed")
        repository.record_fill(
            run_id=config.run_id,
            attempt_number=snapshot.total_entry_attempts,
            position_size=actual,
            fill_price=fill_price,
            entry_fee=(
                Btc15mFavoriteTakeProfitStrategy.expected_fee(
                    runtime.active_market,
                    price=fill_price,
                    size=actual,
                )
                if runtime.active_market is not None
                else snapshot.entry_fee
            ),
            updated_at=_aware(clock()),
        )
        runtime.active_fill_price = fill_price
        runtime.active_fill_size = actual
        if runtime.active_market is None:
            raise TinyLiveCopyError("restart market context is unavailable after fill")
        runtime.active_entry_fee = Btc15mFavoriteTakeProfitStrategy.expected_fee(
            runtime.active_market,
            price=fill_price,
            size=actual,
        )
        snapshot = repository.get(config.run_id)
        assert snapshot is not None
    if snapshot.position_size > 0:
        actual = await _account_position(execution_port, None)
        if actual < 0 or actual > snapshot.position_size:
            raise TinyLiveCopyError("restart position reconciliation failed")
        if snapshot.exit_order_id is not None:
            exits = await execution_port.get_open_orders(
                order_id=snapshot.exit_order_id
            )
            if len(exits) > 1:
                raise TinyLiveCopyError(
                    "restart reconciliation found duplicate related exits"
                )
            if not exits and actual == snapshot.position_size:
                repository.clear_exit_order(
                    run_id=config.run_id,
                    state=CopyExperimentState.POSITION_OPEN,
                    updated_at=_aware(clock()),
                )
            elif not exits and actual not in {Decimal("0"), snapshot.position_size}:
                raise TinyLiveCopyError(
                    "restart found an ambiguous partially closed position"
                )


async def _poll_aliases(
    source: LeaderTradeSourcePort,
    *,
    aliases: tuple[str, ...],
    start_at: datetime,
    end_at: datetime,
) -> tuple[LeaderTradeEvent, ...]:
    semaphore = asyncio.Semaphore(10)

    async def read(alias: str) -> tuple[LeaderTradeEvent, ...]:
        async with semaphore:
            page = await source.read_page(
                alias,
                start_at=start_at,
                end_at=end_at,
                page_size=100,
            )
            events = list(page.events)
            checkpoint = page.next_checkpoint
            pages = 1
            while checkpoint is not None and pages < 5:
                next_page = await source.read_page(
                    alias,
                    start_at=start_at,
                    end_at=end_at,
                    page_size=100,
                    checkpoint=checkpoint,
                )
                events.extend(next_page.events)
                checkpoint = next_page.next_checkpoint
                pages += 1
            if checkpoint is not None:
                raise TinyLiveCopyError("leader trade pagination exceeded the safe bound")
            return tuple(events)

    batches = await asyncio.gather(*(read(alias) for alias in aliases))
    return tuple(event for batch in batches for event in batch)


async def _confirmed_fill(
    execution_port: CopyExecutionPort,
    *,
    order_id: str,
    token_id: str | None,
) -> tuple[Decimal, Decimal]:
    trades = await execution_port.list_account_trades(token_id=token_id)
    size = Decimal("0")
    notional = Decimal("0")
    for trade in trades:
        if str(_read(trade, "status", "")).upper() not in {"CONFIRMED", "MINED"}:
            continue
        trade_price = _decimal(_read(trade, "price", "0"))
        if str(_read(trade, "taker_order_id", "")) == order_id:
            trade_size = _decimal(_read(trade, "size", "0"))
            size += trade_size
            notional += trade_size * trade_price
        for maker in _read(trade, "maker_orders", ()) or ():
            if str(_read(maker, "order_id", "")) != order_id:
                continue
            maker_size = _decimal(_read(maker, "matched_amount", "0"))
            maker_price = _decimal(_read(maker, "price", trade_price))
            size += maker_size
            notional += maker_size * maker_price
    return size, (notional / size if size > 0 else Decimal("0"))


async def _account_position(
    execution_port: CopyExecutionPort,
    token_id: str | None,
) -> Decimal:
    positions = await execution_port.list_positions(size_threshold=0)
    return sum(
        (
            _position_size(position)
            for position in positions
            if token_id is None or str(_read(position, "token_id", "")) == token_id
        ),
        Decimal("0"),
    )


async def _confirm_not_open(
    execution_port: CopyExecutionPort,
    order_id: str,
) -> None:
    if await execution_port.get_open_orders(order_id=order_id):
        raise TinyLiveCopyError("order cancellation was not confirmed")


async def _emergency_cancel_if_needed(
    execution_port: CopyExecutionPort,
    *,
    repository: CopyExperimentRepository,
    run_id: str,
    report: TinyLiveCopyReport,
    clock: Clock,
) -> None:
    if not execution_port.is_connected:
        return
    try:
        open_orders = await execution_port.get_open_orders()
        if not open_orders:
            report.emergency_cancel_status = "not_needed_no_open_orders"
            return
        await execution_port.cancel_all()
        if await execution_port.get_open_orders():
            report.emergency_cancel_status = "invoked_unconfirmed"
            raise TinyLiveCopyError("emergency cancel-all was not confirmed")
        snapshot = repository.get(run_id)
        remaining = await _account_position(
            execution_port,
            None if snapshot is None else snapshot.active_token_id,
        )
        report.emergency_cancel_status = "invoked_confirmed"
        repository.record_emergency_cancellation(
            run_id=run_id,
            remaining_position=remaining,
            updated_at=_aware(clock()),
        )
    except Exception as error:
        report.emergency_cancel_status = "failed_or_ambiguous"
        raise TinyLiveCopyError("emergency cancellation failed or is ambiguous") from error


def _broker_for(
    settings: AppSettings,
    execution_port: CopyExecutionPort,
    *,
    geoblock_port: CopyGeoblockPort,
    kill_switch: KillSwitch,
    token_id: str,
    maximum_position: Decimal,
    maximum_order_notional: Decimal,
) -> LiveBroker:
    return LiveBroker(
        adapter=execution_port,  # type: ignore[arg-type]
        risk_engine=RiskEngine(
            kill_switch=kill_switch,
            limits=RiskLimits(
                max_order_notional=maximum_order_notional,
                max_position_per_token=maximum_position,
                max_position_per_market=maximum_position,
                max_daily_loss=MAXIMUM_ENTRY_DEBIT,
                max_open_orders=1,
                max_stale_data_age_ms=MAXIMUM_BOOK_AGE_MS,
                allow_live_trading=True,
            ),
        ),
        settings=settings,
        allowed_token_ids=(token_id,),
        geoblock_check=_BrokerGeoblock(geoblock_port),
    )


def _assert_synchronized_main(
    config: TinyLiveCopyConfig,
    git_commit: str | None,
) -> None:
    branch = _git(config.project_root, "branch", "--show-current")
    if branch is not None:
        if branch != "main":
            raise TinyLiveCopyError("live execution requires the main branch")
        remote = _git(config.project_root, "rev-parse", "origin/main")
        status = _git(
            config.project_root,
            "status",
            "--porcelain",
            "--untracked-files=no",
        )
        if git_commit is None or git_commit != remote or status:
            raise TinyLiveCopyError("repository is not clean synchronized main")
    elif git_commit in {None, "", "unknown"}:
        raise TinyLiveCopyError("deployed image has no verifiable build commit")
    if config.verified_ci_commit != git_commit:
        raise TinyLiveCopyError("green CI evidence does not match the deployed commit")


def _assert_identity(identity: dict[str, object]) -> None:
    if identity.get("signer_configured") is not True:
        raise TinyLiveCopyError("signer identity is not configured")
    if identity.get("funder_configured") is not True:
        raise TinyLiveCopyError("funder identity is not configured")
    if identity.get("active_wallet_source") != "funder":
        raise TinyLiveCopyError("funder is not the active wallet source")
    if identity.get("signature_type_matches_sdk") is not True:
        raise TinyLiveCopyError("wallet signature semantics are inconsistent")


def _assert_restart_account_scope(
    snapshot: Any,
    *,
    open_orders: list[Any],
    positions: list[Any],
) -> None:
    allowed_order_ids = {
        order_id
        for order_id in (snapshot.entry_order_id, snapshot.exit_order_id)
        if order_id is not None
    }
    observed_order_ids = {
        str(_read(order, "id") or _read(order, "order_id") or "")
        for order in open_orders
    }
    if "" in observed_order_ids or not observed_order_ids <= allowed_order_ids:
        raise TinyLiveCopyError("restart found an unrelated or unidentified open order")
    if len(observed_order_ids) > 1:
        raise TinyLiveCopyError("restart found more than one related open order")

    positive_positions = [
        position for position in positions if _position_size(position) > 0
    ]
    if not positive_positions:
        return
    if snapshot.active_token_id is None:
        raise TinyLiveCopyError("restart found an unrelated positive position")
    if any(
        str(_read(position, "token_id", "")) != snapshot.active_token_id
        for position in positive_positions
    ):
        raise TinyLiveCopyError("restart found a position outside the active token")
    actual = sum(
        (_position_size(position) for position in positive_positions),
        Decimal("0"),
    )
    maximum = max(
        snapshot.position_size,
        snapshot.entry_quantity or Decimal("0"),
    )
    if actual > maximum:
        raise TinyLiveCopyError("restart position exceeds durable authorized quantity")


def _assert_market_mapping(
    market: MarketDetails,
    *,
    expected_slug: str,
    expected_condition: str,
    token_id: str,
    expected_start: datetime,
    expected_end: datetime,
    now: datetime,
) -> None:
    if market.slug != expected_slug or market.condition_id != expected_condition:
        raise CopySignalSkip("strict market identity mapping failed")
    if not market.slug.startswith("btc-updown-15m-"):
        raise CopySignalSkip("market is not exact BTC Up/Down 15-minute")
    if market.active is not True or market.closed is not False:
        raise CopySignalSkip("market is not active")
    if market.accepting_orders is not True or market.enable_order_book is not True:
        raise CopySignalSkip("market is not accepting orderbook orders")
    if market.end_date is None or (_aware(market.end_date) - now).total_seconds() < 420:
        raise CopySignalSkip("market has fewer than seven minutes remaining")
    if token_id not in {outcome.token_id for outcome in market.outcomes}:
        raise CopySignalSkip("leader outcome token is not mapped to the market")
    if (
        market.start_date is None
        or market.end_date is None
        or abs((_aware(market.start_date) - _aware(expected_start)).total_seconds()) > 1
        or abs((_aware(market.end_date) - _aware(expected_end)).total_seconds()) > 1
    ):
        raise CopySignalSkip("market start/end metadata mapping failed")
    if market.fee_schedule is None:
        raise CopySignalSkip("market fee configuration is unreadable")


def _safe_book_snapshot(
    book: MarketOrderBookSnapshot,
    *,
    event: LeaderTradeEvent,
    quote: Any,
    captured_at: datetime,
) -> dict[str, object]:
    return {
        "best_ask": None if book.best_ask is None else str(book.best_ask.price),
        "best_bid": None if book.best_bid is None else str(book.best_bid.price),
        "captured_at": captured_at.isoformat(),
        "entry_price": str(quote.price),
        "event_id": event.event_id,
        "leader_alias": event.leader_id,
        "minimum_order_size": str(book.minimum_order_size),
        "tick_size": str(book.tick_size),
    }


def write_tiny_live_copy_reports(
    report: TinyLiveCopyReport,
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "status.json"
    summary_path = output_dir / "summary.json"
    decisions_path = output_dir / "decisions.jsonl"
    books_path = output_dir / "orderbook_snapshots.jsonl"
    events_path = output_dir / "sanitized_events.jsonl"
    checkpoint_path = output_dir / "checkpoint.json"
    checksum_path = output_dir / "checksum.sha256"
    _atomic_json(status_path, report.to_dict())
    _atomic_json(summary_path, report.to_dict())
    _atomic_json(
        checkpoint_path,
        {
            "completed_live_cycles": report.completed_live_cycles,
            "run_id": report.run_id,
            "state": report.state,
            "total_entry_attempts": report.total_entry_attempts,
        },
    )
    _atomic_jsonl(decisions_path, report.decisions)
    _atomic_jsonl(books_path, report.orderbook_snapshots)
    _atomic_jsonl(events_path, report.sanitized_events)
    artifacts = (
        status_path,
        summary_path,
        decisions_path,
        books_path,
        events_path,
        checkpoint_path,
    )
    lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
        for path in artifacts
    ]
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "status": status_path,
        "summary": summary_path,
        "decisions": decisions_path,
        "orderbooks": books_path,
        "events": events_path,
        "checkpoint": checkpoint_path,
        "checksum": checksum_path,
    }


def _terminal_classification(
    snapshot: Any,
    now: datetime,
    runtime: _Runtime,
) -> str:
    if snapshot.state is CopyExperimentState.FAILED_SAFE:
        return "FAILED_SAFE"
    if snapshot.state is CopyExperimentState.REDEEMABLE:
        return "WINNING_TOKENS_REDEEMABLE"
    if snapshot.total_entry_attempts == 3 and snapshot.completed_live_cycles == 0:
        return "THREE_ATTEMPTS_NO_FILL"
    if snapshot.completed_live_cycles == 3:
        return "THREE_FILLED_CYCLES_COMPLETED"
    if now >= runtime.report.signal_window_end:
        return "NO_SIGNAL_INCONCLUSIVE"
    return "FINALIZED"


def _terminal_stop_reason(
    snapshot: Any,
    now: datetime,
    runtime: _Runtime,
) -> str:
    if snapshot.state is CopyExperimentState.FAILED_SAFE:
        return runtime.report.stop_reason or "safety gate failed"
    if snapshot.state is CopyExperimentState.REDEEMABLE:
        return "winning tokens require the existing manual redemption path"
    if snapshot.total_entry_attempts >= MAXIMUM_TOTAL_ENTRY_ATTEMPTS:
        return "maximum total entry attempts reached"
    if snapshot.completed_live_cycles >= MAXIMUM_COMPLETED_LIVE_CYCLES:
        return "maximum completed live cycles reached"
    if now >= runtime.report.signal_window_end:
        return "12-hour signal window ended"
    return runtime.report.stop_reason or "experiment finalized"


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _atomic_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, sort_keys=True, default=str) + "\n" for row in rows),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _git(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ("git", *args),
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip()


def _deployed_commit(root: Path) -> str | None:
    git_commit = _git(root, "rev-parse", "HEAD")
    if git_commit is not None:
        return git_commit
    build_commit = root / "BUILD_COMMIT"
    if not build_commit.is_file():
        return None
    value = build_commit.read_text(encoding="utf-8").strip()
    return value or None


def _refresh_report(
    repository: CopyExperimentRepository,
    run_id: str,
    report: TinyLiveCopyReport,
) -> None:
    snapshot = repository.get(run_id)
    if snapshot is None:
        return
    report.state = snapshot.state.value
    report.total_entry_attempts = snapshot.total_entry_attempts
    report.completed_live_cycles = snapshot.completed_live_cycles
    report.current_order_or_fill_exists = bool(
        snapshot.entry_order_id
        or snapshot.exit_order_id
        or snapshot.position_size > 0
    )
    report.attempts = _safe_attempts(repository.attempts(run_id))


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise TinyLiveCopyError("runtime clock must be timezone-aware")
    return value.astimezone(UTC)


def _heartbeat_is_fresh(last_seen: datetime, now: datetime) -> bool:
    return (
        timedelta(0) <= _aware(now) - _aware(last_seen)
        <= timedelta(seconds=MAXIMUM_HEARTBEAT_GAP_SECONDS)
    )


def _book_age_ms(book: MarketOrderBookSnapshot, now: datetime) -> int:
    return max(0, int((now - _aware(book.timestamp)).total_seconds() * 1000))


def _base_units(value: object) -> Decimal:
    return _decimal(value) / BASE_UNITS


def _position_size(value: Any) -> Decimal:
    return _decimal(_read(value, "size", "0"))


def _order_id(value: Any) -> str:
    order_id = str(_read(value, "order_id", ""))
    if not order_id:
        raise TinyLiveCopyError("accepted order response has no durable order id")
    return order_id


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="python")
        if isinstance(dumped, dict):
            return dumped
    return {
        name: getattr(value, name)
        for name in dir(value)
        if not name.startswith("_") and not callable(getattr(value, name))
    }


def _read(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _safe_attempts(
    attempts: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "attempt_number": attempt["attempt_number"],
            "claimed_at": attempt["claimed_at"],
            "event_id": attempt["event_id"],
            "leader_alias": attempt["leader_alias"],
            "entry_debit": attempt["entry_debit"],
            "entry_fee": attempt["entry_fee"],
            "entry_quantity": attempt["entry_quantity"],
            "exit_fee": attempt["exit_fee"],
            "exit_price": attempt["exit_price"],
            "fill_price": attempt["fill_price"],
            "fill_size": attempt["fill_size"],
            "gross_pnl": attempt["gross_pnl"],
            "leader_latency_ms": attempt["leader_latency_ms"],
            "leader_price_difference": attempt["leader_price_difference"],
            "market_reference_digest": _digest(str(attempt["market_id"])),
            "net_pnl": attempt["net_pnl"],
            "state": attempt["state"],
            "terminal_reason": attempt["terminal_reason"],
            "updated_at": attempt["updated_at"],
            "venue_order_id_digest": (
                None
                if attempt["venue_order_id"] is None
                else _digest(str(attempt["venue_order_id"]))
            ),
        }
        for attempt in attempts
    )


def _safe_error(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"


__all__ = [
    "AUTHORIZATION_ID",
    "TinyLiveCopyConfig",
    "TinyLiveCopyError",
    "TinyLiveCopyReport",
    "run_tiny_live_copy",
    "write_tiny_live_copy_reports",
]
