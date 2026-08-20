from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Any, Protocol, cast

from polysia.adapters.polymarket.copytrading_source import PolymarketCopyTradingSource
from polysia.adapters.polymarket.diagnostics import VenueErrorCategory
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
from polysia.adapters.polymarket.request_scheduling import (
    DISCOVERY_BUDGET_PER_10_SECONDS,
    MAX_TRADES_ATTEMPTS_PER_10_SECONDS,
    MAX_TRADES_IN_FLIGHT,
    RESERVED_TRADES_BUDGET_PER_10_SECONDS,
    TradesSourceUnavailableError,
)
from polysia.adapters.polymarket.secure import (
    PolymarketSecureAdapter,
    PolymarketSecureAdapterError,
)
from polysia.application.ports.copytrading import (
    LeaderMarketMetadata,
    LeaderReadPurpose,
    LeaderTradeCheckpoint,
    LeaderTradeSourcePort,
)
from polysia.config.settings import AppSettings, TradingMode
from polysia.domain.copytrading import (
    CopyExperimentState,
    EntryQuote,
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
    MAXIMUM_COMPLETED_LIVE_CYCLES,
    MAXIMUM_ENTRY_DEBIT,
    MAXIMUM_EXPERIMENT_ENTRY_COST,
    MAXIMUM_TOTAL_ENTRY_ATTEMPTS,
    TERMINAL_STATES,
)
from polysia.domain.market import MarketDetails, MarketOrderBookSnapshot
from polysia.execution.intents import OrderIntent
from polysia.execution.live_broker import (
    LiveBroker,
    LiveOrderRejectedError,
    PreparedLimitOrder,
)
from polysia.risk.checks import RiskContext, RiskEngine
from polysia.risk.kill_switch import KillSwitch
from polysia.risk.limits import RiskLimits
from polysia.storage.copytrading import (
    DISCOVERY_ROTATION_STEP,
    CopyDiscoveryState,
    CopyExperimentRepository,
)
from polysia.storage.db import SQLiteDatabase
from polysia.strategies.btc_15m_favorite_take_profit import (
    Btc15mFavoriteTakeProfitStrategy,
)

PREVIOUS_RUN_ID = "tiny-live-copy-20260729T054315Z"
STRATEGY_ID = "polymarket-copytrading"
APPROVED_SDK_VERSION = "0.6.0"
AUTHORIZATION_ID_PREFIX = "POLYSIA-TINY-LIVE-COPY-"
DRY_RUN_AUTHORIZATION_PREFIX = "DRY-RUN:"
BASE_UNITS = Decimal("1000000")
POLL_INTERVAL_SECONDS = 6
POLL_OVERLAP_SECONDS = 20
BASELINE_OVERLAP_SECONDS = 120
DISCOVERY_ROTATION_MINUTES = 30
SOURCE_OUTAGE_LIMIT_SECONDS = 120
MAXIMUM_BOOK_AGE_MS = 5_000
MAXIMUM_HEARTBEAT_GAP_SECONDS = 60
TINY_LIVE_COPY_MINIMUM_SECONDS_TO_END = 240

Clock = Callable[[], datetime]
Sleeper = Callable[[float], Awaitable[None]]


def utc_now() -> datetime:
    return datetime.now(UTC)


def _valid_authorization_id(value: str) -> bool:
    suffix = value.removeprefix(AUTHORIZATION_ID_PREFIX)
    return value.startswith(AUTHORIZATION_ID_PREFIX) and len(suffix) == 3 and suffix.isdigit()


class TinyLiveCopyError(RuntimeError):
    """Fail-closed error for the owner-bounded Copy Trading experiment."""


class CopySignalSkip(TinyLiveCopyError):
    """A proven local signal ineligibility that consumes no venue attempt."""


class LocalPostOnlyCrossing(CopySignalSkip):
    """The final local BUY quote would cross the current best ask."""


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

    async def prepare_limit_order(
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

    async def post_prepared_limit_order(self, prepared_order: Any) -> Any: ...

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
    authorization_id: str | None = None
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
        if self.authorization_id is not None and not _valid_authorization_id(self.authorization_id):
            raise ValueError("authorization id must use the protected Tiny Live Copy format")
        if not self.dry_run and self.authorization_id is None:
            raise ValueError("live execution requires a runtime authorization id")
        if not self.dry_run and not self.acknowledgement:
            raise ValueError("live execution requires a matching runtime acknowledgement")


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
    cumulative_entry_cost: Decimal
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
    authorization_id: str = "NOT_CLAIMED_DRY_RUN"
    source_availability: str = "available"
    request_metrics: dict[str, object] = field(default_factory=dict)
    active_management_priority_cycles: int = 0
    preflight_venue_mutation: bool = False
    market_time_validation: str = "slug_eventStartTime_endDate"
    attempts: tuple[dict[str, object], ...] = ()
    api_errors: int = 0
    decisions: list[dict[str, object]] = field(default_factory=list)
    orderbook_snapshots: list[dict[str, object]] = field(default_factory=list)
    sanitized_events: list[dict[str, object]] = field(default_factory=list)
    signal_latency_metrics: list[dict[str, object]] = field(default_factory=list)
    poll_batch_metrics: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "api_errors": self.api_errors,
            "active_management_priority_cycles": (self.active_management_priority_cycles),
            "attempts": list(self.attempts),
            "authorization_id": self.authorization_id,
            "candidate_summary": self.candidate_summary,
            "candidate_runtime_file_deleted": self.candidate_runtime_file_deleted,
            "classification": self.classification,
            "completed_live_cycles": self.completed_live_cycles,
            "current_order_or_fill_exists": self.current_order_or_fill_exists,
            "duplicate_count": self.duplicate_count,
            "emergency_cancel_status": self.emergency_cancel_status,
            "event_count": self.event_count,
            "final_account_balance": (
                None if self.final_account_balance is None else str(self.final_account_balance)
            ),
            "geoblock_status": self.geoblock_status,
            "heartbeat_health": self.heartbeat_health,
            "git_commit": self.git_commit,
            "cumulative_entry_cost_usd": str(self.cumulative_entry_cost),
            "maximum_completed_live_cycles": MAXIMUM_COMPLETED_LIVE_CYCLES,
            "maximum_entry_debit_usd": str(MAXIMUM_ENTRY_DEBIT),
            "maximum_experiment_entry_cost_usd": str(MAXIMUM_EXPERIMENT_ENTRY_COST),
            "maximum_total_entry_attempts": MAXIMUM_TOTAL_ENTRY_ATTEMPTS,
            "maximum_actual_loss_usd": self._maximum_actual_loss(),
            "no_fourth_entry_possible": self.total_entry_attempts <= 3,
            "no_more_than_one_active_position_or_order": True,
            "owner_prompt_preserved_by_design": True,
            "preflight_venue_mutation": self.preflight_venue_mutation,
            "market_time_validation": self.market_time_validation,
            "request_metrics": self.request_metrics,
            "signal_latency_metrics": self.signal_latency_metrics,
            "poll_batch_metrics": self.poll_batch_metrics,
            "maximum_signal_age_seconds": 10,
            "minimum_market_time_remaining_seconds": (TINY_LIVE_COPY_MINIMUM_SECONDS_TO_END),
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
            "source_availability": self.source_availability,
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
            if attempt.get("net_pnl") is not None and Decimal(str(attempt["net_pnl"])) < 0
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


@dataclass(frozen=True, slots=True)
class _ObservedLeaderEvent:
    event: LeaderTradeEvent
    metadata: LeaderMarketMetadata


@dataclass(frozen=True, slots=True)
class _PollBatch:
    events: tuple[_ObservedLeaderEvent, ...]
    unavailable: TradesSourceUnavailableError | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    response_count: int = 0


PollResultHandler = Callable[[_PollBatch], Awaitable[None]]


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
                timeout_seconds=float(config.settings.polymarket_server_time_timeout_seconds),
                max_attempts=config.settings.polymarket_read_max_attempts,
                backoff_seconds=float(config.settings.polymarket_read_backoff_seconds),
            )
        ),
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
        cumulative_entry_cost=Decimal("0"),
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
        authorization_id=(
            "NOT_CLAIMED_DRY_RUN" if config.dry_run else cast(str, config.authorization_id)
        ),
    )
    runtime = _Runtime(report=report, last_poll_at=started_at)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    with SQLiteDatabase(config.database_path) as database:
        repository = CopyExperimentRepository(database.connection)
        existing = repository.get(config.run_id)
        runtime_authorization_id = (
            f"{DRY_RUN_AUTHORIZATION_PREFIX}{config.run_id}"
            if config.dry_run
            else cast(str, config.authorization_id)
        )
        if existing is None:
            repository.create(
                run_id=config.run_id,
                authorization_id=runtime_authorization_id,
                started_at=started_at,
                signal_window_end=signal_window_end,
                payload={
                    "candidate_digest": bank.source_digest,
                    "candidate_count": EXPECTED_CANDIDATE_COUNT,
                    "maximum_completed_live_cycles": MAXIMUM_COMPLETED_LIVE_CYCLES,
                    "maximum_entry_debit": str(MAXIMUM_ENTRY_DEBIT),
                    "maximum_experiment_entry_cost": str(MAXIMUM_EXPERIMENT_ENTRY_COST),
                    "maximum_total_entry_attempts": MAXIMUM_TOTAL_ENTRY_ATTEMPTS,
                    "minimum_market_time_remaining_seconds": (
                        TINY_LIVE_COPY_MINIMUM_SECONDS_TO_END
                    ),
                },
            )
        else:
            if repository.authorization_id(config.run_id) != runtime_authorization_id:
                raise TinyLiveCopyError("restart authorization does not match durable state")
            signal_window_end = repository.signal_window_end(config.run_id)
            report.signal_window_end = signal_window_end
        priority_aliases = tuple(
            alias
            for alias in repository.aliases_with_seen_events(PREVIOUS_RUN_ID)
            if alias in bank.aliases
        )
        ordered_aliases = _ordered_discovery_aliases(
            bank.aliases,
            priority_aliases=priority_aliases,
        )
        discovery = repository.initialize_discovery(
            run_id=config.run_id,
            ordered_aliases=ordered_aliases,
            initialized_at=started_at,
        )
        _update_discovery_report(report, discovery)
        await _restore_source_circuit(active_source, discovery)

        try:
            await _preflight(
                config,
                execution_port=active_execution_port,
                geoblock_port=active_geoblock,
                kill_switch=active_kill_switch,
                report=report,
                git_commit=git_commit,
                restart_snapshot=existing,
                now=_aware(clock()),
            )
            _refresh_report(repository, config.run_id, report)
            write_tiny_live_copy_reports(report, config.output_dir)
            if existing is not None and existing.state is CopyExperimentState.FAILED_SAFE:
                await _emergency_cancel_if_needed(
                    active_execution_port,
                    repository=repository,
                    run_id=config.run_id,
                    report=report,
                    clock=clock,
                )
                report.classification = "FAILED_SAFE"
                report.stop_reason = "restarted failed-safe run reconciled without new action"
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
            if existing is not None and repository.release_orphaned_signal_reservation(
                config.run_id
            ):
                runtime.report.decisions.append(
                    {
                        "action": "ORPHANED_SIGNAL_RESERVATION_RELEASED",
                        "timestamp": _aware(clock()).isoformat(),
                    }
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
                        await active_execution_port.get_balance_allowance(asset_type="COLLATERAL")
                    )
                    report.final_account_balance = _base_units(final_collateral.get("balance"))
                except Exception:
                    report.api_errors += 1
            snapshot = repository.get(config.run_id)
            _refresh_source_report(active_source, report)
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
                and (
                    (
                        config.dry_run
                        and snapshot.entry_order_id is None
                        and snapshot.exit_order_id is None
                        and snapshot.position_size == 0
                    )
                    or snapshot.state is CopyExperimentState.REDEEMABLE
                    or (
                        snapshot.state in TERMINAL_STATES
                        and snapshot.entry_order_id is None
                        and snapshot.exit_order_id is None
                        and snapshot.position_size == 0
                    )
                )
            ):
                config.candidate_file.unlink(missing_ok=True)
                report.candidate_runtime_file_deleted = not config.candidate_file.exists()
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
    now: datetime,
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
    collateral = _mapping(await execution_port.get_balance_allowance(asset_type="COLLATERAL"))
    balance = _base_units(collateral.get("balance"))
    allowances = collateral.get("allowances")
    if not isinstance(allowances, dict) or not allowances:
        raise TinyLiveCopyError("collateral allowance is unreadable")
    if balance <= 0 and restart_snapshot is None:
        raise TinyLiveCopyError("account has no usable collateral for the bounded experiment")
    open_orders = await execution_port.get_open_orders()
    positions = await execution_port.list_positions(size_threshold=0)
    if restart_snapshot is None:
        if open_orders:
            raise TinyLiveCopyError("unrelated open orders exist in the dedicated test account")
        if _positions_requiring_isolation(positions, now=now):
            raise TinyLiveCopyError(
                "unrelated active, positive-value, mergeable, or ambiguous positions exist"
            )
    else:
        _assert_restart_account_scope(
            restart_snapshot,
            open_orders=open_orders,
            positions=positions,
            now=now,
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
    del sleeper
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
    baseline_end = _aware(clock())
    for alias in bank_aliases:
        repository.save_read_checkpoint(
            run_id=config.run_id,
            leader_alias=alias,
            window_start=baseline_end - timedelta(seconds=BASELINE_OVERLAP_SECONDS),
            window_end=baseline_end,
            checkpoint_value=None,
            last_successful_at=baseline_end,
            updated_at=baseline_end,
        )
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
        if (
            now >= runtime.report.signal_window_end
            and snapshot.position_size == 0
            and snapshot.entry_order_id is None
        ):
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
            await _manage_active(
                config,
                market_port=market_port,
                execution_port=execution_port,
                geoblock_port=geoblock_port,
                kill_switch=kill_switch,
                repository=repository,
                runtime=runtime,
                clock=clock,
                cancel_pending_for_leader_close=False,
            )
            runtime.report.active_management_priority_cycles += 1
            refreshed = repository.get(config.run_id)
            assert refreshed is not None
            if (
                refreshed.position_size > 0 or refreshed.entry_order_id is not None
            ) and refreshed.active_leader_alias is not None:
                discovery = repository.discovery_state(config.run_id)
                active_batch: _PollBatch | None = None
                if discovery.outage_started_at is None or discovery.next_probe_at is None:
                    active_batch = await _poll_aliases(
                        source,
                        repository=repository,
                        run_id=config.run_id,
                        aliases=(refreshed.active_leader_alias,),
                        start_at=now - timedelta(seconds=POLL_OVERLAP_SECONDS),
                        end_at=now,
                        purpose=LeaderReadPurpose.SELECTED_LEADER,
                        clock=clock,
                    )
                elif now >= discovery.next_probe_at:
                    active_batch = await _poll_aliases(
                        source,
                        repository=repository,
                        run_id=config.run_id,
                        aliases=(refreshed.active_leader_alias,),
                        start_at=now - timedelta(seconds=POLL_OVERLAP_SECONDS),
                        end_at=now,
                        purpose=LeaderReadPurpose.RECOVERY,
                        clock=clock,
                    )
                if active_batch is not None:
                    _record_poll_batch(
                        runtime.report,
                        active_batch,
                        purpose=(
                            LeaderReadPurpose.SELECTED_LEADER
                            if discovery.outage_started_at is None
                            else LeaderReadPurpose.RECOVERY
                        ),
                    )
                    if active_batch.unavailable is not None:
                        _ingest_events(
                            config,
                            repository=repository,
                            events=active_batch.events,
                            runtime=runtime,
                            allow_signals=False,
                        )
                        _record_source_outage(
                            repository,
                            run_id=config.run_id,
                            error=active_batch.unavailable,
                            report=runtime.report,
                            now=now,
                            exposure_exists=True,
                        )
                    else:
                        _clear_source_outage(
                            repository,
                            run_id=config.run_id,
                            report=runtime.report,
                            now=now,
                        )
                        _ingest_events(
                            config,
                            repository=repository,
                            events=active_batch.events,
                            runtime=runtime,
                            allow_signals=False,
                        )
                refreshed = repository.get(config.run_id)
                assert refreshed is not None
                leader_closed = bool(
                    refreshed.active_leader_alias
                    and refreshed.active_market_id
                    and refreshed.active_token_id
                    and repository.inventory(
                        run_id=config.run_id,
                        leader_alias=refreshed.active_leader_alias,
                        market_reference=refreshed.active_market_id,
                        outcome_reference=refreshed.active_token_id,
                    )
                    == 0
                )
                if leader_closed and refreshed.entry_order_id is not None:
                    await _manage_active(
                        config,
                        market_port=market_port,
                        execution_port=execution_port,
                        geoblock_port=geoblock_port,
                        kill_switch=kill_switch,
                        repository=repository,
                        runtime=runtime,
                        clock=clock,
                        cancel_pending_for_leader_close=True,
                    )
                elif leader_closed and refreshed.position_size > 0:
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
            discovery = repository.discovery_state(config.run_id)
            if discovery.outage_started_at is not None:
                outage_age = (now - discovery.outage_started_at).total_seconds()
                if outage_age >= SOURCE_OUTAGE_LIMIT_SECONDS:
                    repository.set_state(
                        config.run_id,
                        CopyExperimentState.FINALIZED,
                        updated_at=now,
                        signal_acceptance_open=False,
                    )
                    runtime.report.classification = "INCONCLUSIVE_DATA_SOURCE"
                    runtime.report.source_availability = "unavailable"
                    runtime.report.stop_reason = (
                        "public /trades source unavailable for 120 seconds while flat"
                    )
                    return
            elif now - discovery.rotated_at >= timedelta(minutes=DISCOVERY_ROTATION_MINUTES):
                discovery = repository.rotate_discovery(
                    run_id=config.run_id,
                    rotated_at=now,
                )
                runtime.report.decisions.append(
                    {
                        "action": "DISCOVERY_WINDOW_ROTATED",
                        "active_aliases": list(discovery.active_aliases),
                        "cursor": discovery.cursor,
                        "subset_digest": discovery.subset_digest,
                        "timestamp": now.isoformat(),
                    }
                )
            _update_discovery_report(runtime.report, discovery)

            batch: _PollBatch | None = None
            streamed_discovery = False
            streamed_outage = False
            entry_selected = False

            async def process_discovery_result(partial: _PollBatch) -> None:
                nonlocal entry_selected, streamed_outage
                if partial.unavailable is not None:
                    streamed_outage = True
                if await _process_discovery_events(
                    config,
                    events=partial.events,
                    allow_signals=not streamed_outage and not entry_selected,
                    market_port=market_port,
                    execution_port=execution_port,
                    geoblock_port=geoblock_port,
                    kill_switch=kill_switch,
                    repository=repository,
                    runtime=runtime,
                    clock=clock,
                ):
                    entry_selected = True

            if discovery.outage_started_at is None:
                streamed_discovery = True
                batch = await _poll_aliases(
                    source,
                    repository=repository,
                    run_id=config.run_id,
                    aliases=discovery.active_aliases,
                    start_at=now - timedelta(seconds=POLL_OVERLAP_SECONDS),
                    end_at=now,
                    purpose=LeaderReadPurpose.DISCOVERY,
                    clock=clock,
                    on_result=process_discovery_result,
                )
            elif discovery.next_probe_at is not None and now >= discovery.next_probe_at:
                batch = await _poll_aliases(
                    source,
                    repository=repository,
                    run_id=config.run_id,
                    aliases=(discovery.active_aliases[0],),
                    start_at=now - timedelta(seconds=POLL_OVERLAP_SECONDS),
                    end_at=now,
                    purpose=LeaderReadPurpose.RECOVERY,
                    clock=clock,
                )
            if batch is not None:
                _record_poll_batch(
                    runtime.report,
                    batch,
                    purpose=(
                        LeaderReadPurpose.DISCOVERY
                        if streamed_discovery
                        else LeaderReadPurpose.RECOVERY
                    ),
                )
                if batch.unavailable is not None:
                    if not streamed_discovery:
                        _ingest_events(
                            config,
                            repository=repository,
                            events=batch.events,
                            runtime=runtime,
                            allow_signals=False,
                        )
                    post_batch = repository.get(config.run_id)
                    assert post_batch is not None
                    _record_source_outage(
                        repository,
                        run_id=config.run_id,
                        error=batch.unavailable,
                        report=runtime.report,
                        now=_aware(clock()),
                        exposure_exists=(
                            post_batch.entry_order_id is not None or post_batch.position_size > 0
                        ),
                    )
                else:
                    _clear_source_outage(
                        repository,
                        run_id=config.run_id,
                        report=runtime.report,
                        now=_aware(clock()),
                    )
                    if not streamed_discovery:
                        await _process_discovery_events(
                            config,
                            events=batch.events,
                            allow_signals=True,
                            market_port=market_port,
                            execution_port=execution_port,
                            geoblock_port=geoblock_port,
                            kill_switch=kill_switch,
                            repository=repository,
                            runtime=runtime,
                            clock=clock,
                        )
        runtime.last_poll_at = now
        _refresh_source_report(source, runtime.report)
        _refresh_report(repository, config.run_id, runtime.report)
        write_tiny_live_copy_reports(runtime.report, config.output_dir)
        await sleeper(float(config.poll_interval_seconds))


def _ingest_events(
    config: TinyLiveCopyConfig,
    *,
    repository: CopyExperimentRepository,
    events: tuple[_ObservedLeaderEvent, ...],
    runtime: _Runtime,
    allow_signals: bool = True,
) -> list[_ObservedLeaderEvent]:
    signals: list[_ObservedLeaderEvent] = []
    used = repository.used_leaders(config.run_id)
    ordered = sorted(
        events,
        key=lambda item: (
            item.event.executed_at,
            item.event.leader_id,
            item.event.event_id,
        ),
    )
    for observed in ordered:
        event = observed.event
        metadata = observed.metadata
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
            effect = LeaderPositionEffect.OPEN if current == 0 else LeaderPositionEffect.INCREASE
            next_size = current + event.executed_size
        elif event.executed_size < current:
            effect = LeaderPositionEffect.REDUCE
            next_size = current - event.executed_size
        elif event.executed_size == current and current > 0:
            effect = LeaderPositionEffect.CLOSE
            next_size = Decimal("0")
        if not repository.apply_event_if_unseen(
            run_id=config.run_id,
            event_id=event.event_id,
            leader_alias=event.leader_id,
            observed_at=event.observed_at,
            market_reference=event.market_reference,
            outcome_reference=event.outcome_reference,
            next_size=next_size,
        ):
            runtime.report.duplicate_count += 1
            continue
        runtime.report.event_count += 1
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
            allow_signals
            and effect is LeaderPositionEffect.OPEN
            and event.trade_action is LeaderTradeAction.BUY
            and event.leader_id not in used
            and signal_is_fresh(
                executed_at=event.executed_at,
                observed_at=event.observed_at,
                market_end=metadata.ends_at,
                minimum_seconds_to_end=TINY_LIVE_COPY_MINIMUM_SECONDS_TO_END,
            )
        ):
            signals.append(observed)
            runtime.report.signal_count += 1
    repository.clear_pending_read_events(
        run_id=config.run_id,
        event_ids=tuple(observed.event.event_id for observed in events),
    )
    return signals


async def _process_discovery_events(
    config: TinyLiveCopyConfig,
    *,
    events: tuple[_ObservedLeaderEvent, ...],
    allow_signals: bool,
    market_port: CopyMarketPort,
    execution_port: CopyExecutionPort,
    geoblock_port: CopyGeoblockPort,
    kill_switch: KillSwitch,
    repository: CopyExperimentRepository,
    runtime: _Runtime,
    clock: Clock,
) -> bool:
    signals = _ingest_events(
        config,
        repository=repository,
        events=events,
        runtime=runtime,
        allow_signals=allow_signals,
    )
    snapshot = repository.get(config.run_id)
    assert snapshot is not None
    if not snapshot.signal_acceptance_open or not allow_signals:
        return repository.signal_reservation(config.run_id) is not None
    for signal in signals:
        event = signal.event
        metadata = signal.metadata
        evaluated_at = _aware(clock())
        metric: dict[str, object] = {
            "event_id": event.event_id,
            "leader_alias": event.leader_id,
            "evaluated_at": evaluated_at.isoformat(),
            "executed_to_observed_ms": _elapsed_ms(
                event.executed_at,
                event.observed_at,
            ),
            "observed_to_evaluation_ms": _elapsed_ms(
                event.observed_at,
                evaluated_at,
            ),
            "market_time_remaining_at_evaluation_ms": _elapsed_ms(
                evaluated_at,
                metadata.ends_at,
            ),
        }
        runtime.report.signal_latency_metrics.append(metric)
        if not signal_is_fresh(
            executed_at=event.executed_at,
            observed_at=evaluated_at,
            market_end=metadata.ends_at,
            minimum_seconds_to_end=TINY_LIVE_COPY_MINIMUM_SECONDS_TO_END,
        ):
            runtime.report.decisions.append(
                {
                    "action": "SIGNAL_REJECTED_STALE_AT_EVALUATION",
                    "event_id": event.event_id,
                    "leader_alias": event.leader_id,
                    "timestamp": evaluated_at.isoformat(),
                }
            )
            continue
        reserved_at = _aware(clock())
        if not repository.reserve_signal(
            run_id=config.run_id,
            event_id=event.event_id,
            leader_alias=event.leader_id,
            reserved_at=reserved_at,
        ):
            metric["reservation"] = "rejected"
            return repository.signal_reservation(config.run_id) is not None
        metric["reserved_at"] = reserved_at.isoformat()
        metric["evaluation_to_reservation_ms"] = _elapsed_ms(
            evaluated_at,
            reserved_at,
        )
        try:
            selected = await _attempt_entry(
                config,
                event=event,
                metadata=metadata,
                market_port=market_port,
                execution_port=execution_port,
                geoblock_port=geoblock_port,
                kill_switch=kill_switch,
                repository=repository,
                runtime=runtime,
                clock=clock,
                latency_metric=metric,
            )
        finally:
            repository.release_signal_reservation(
                run_id=config.run_id,
                event_id=event.event_id,
            )
        if selected:
            return True
    return repository.signal_reservation(config.run_id) is not None


async def _attempt_entry(
    config: TinyLiveCopyConfig,
    *,
    event: LeaderTradeEvent,
    metadata: LeaderMarketMetadata,
    market_port: CopyMarketPort,
    execution_port: CopyExecutionPort,
    geoblock_port: CopyGeoblockPort,
    kill_switch: KillSwitch,
    repository: CopyExperimentRepository,
    runtime: _Runtime,
    clock: Clock,
    latency_metric: dict[str, object] | None = None,
) -> bool:
    now = _aware(clock())
    if not signal_is_fresh(
        executed_at=event.executed_at,
        observed_at=now,
        market_end=metadata.ends_at,
        minimum_seconds_to_end=TINY_LIVE_COPY_MINIMUM_SECONDS_TO_END,
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
            expected_outcome_label=metadata.outcome_label,
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
            minimum_seconds_to_end=TINY_LIVE_COPY_MINIMUM_SECONDS_TO_END,
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
            minimum_seconds_to_end=TINY_LIVE_COPY_MINIMUM_SECONDS_TO_END,
        )
        calculate_take_profit_price(quote.price, tick_size=book.tick_size)
        if (
            repository.cumulative_entry_cost(config.run_id) + quote.maximum_debit
            > MAXIMUM_EXPERIMENT_ENTRY_COST
        ):
            raise CopySignalSkip("entry would exceed the 10.00 USD cumulative experiment-cost cap")
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
        now=now,
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
    claim: dict[str, object] = {}
    submission: dict[str, object] = {}

    async def refresh_before_submit() -> PreparedLimitOrder:
        final_market = await market_port.get_market_by_slug(metadata.external_slug)
        final_book = await market_port.get_order_book(event.outcome_reference)
        final_checked_at = _aware(clock())
        try:
            _assert_market_mapping(
                final_market,
                expected_slug=metadata.external_slug,
                expected_condition=event.market_reference,
                token_id=event.outcome_reference,
                expected_outcome_label=metadata.outcome_label,
                expected_start=metadata.starts_at,
                expected_end=metadata.ends_at,
                now=final_checked_at,
            )
            if not signal_is_fresh(
                executed_at=event.executed_at,
                observed_at=final_checked_at,
                market_end=metadata.ends_at,
                minimum_seconds_to_end=TINY_LIVE_COPY_MINIMUM_SECONDS_TO_END,
            ):
                raise CopySignalSkip("signal is stale at the final pre-submit recheck")
            if (
                final_book.best_ask is None
                or _book_age_ms(final_book, final_checked_at) > MAXIMUM_BOOK_AGE_MS
            ):
                raise CopySignalSkip("final orderbook is empty or stale")
            if quote.price >= final_book.best_ask.price:
                runtime.report.orderbook_snapshots.append(
                    _safe_book_snapshot(
                        final_book,
                        event=event,
                        quote=quote,
                        captured_at=final_checked_at,
                    )
                )
                raise LocalPostOnlyCrossing(
                    "final BUY price is equal to or above the current best ask"
                )
            final_preliminary_quote = calculate_entry_quote(
                leader_fill_price=event.executed_price,
                minimum_order_size=final_book.minimum_order_size,
                tick_size=final_book.tick_size,
                best_ask=final_book.best_ask.price,
                expected_fee=Decimal("0"),
                now=final_checked_at,
                market_end=metadata.ends_at,
                minimum_seconds_to_end=TINY_LIVE_COPY_MINIMUM_SECONDS_TO_END,
            )
            final_expected_fee = Btc15mFavoriteTakeProfitStrategy.expected_fee(
                final_market,
                price=final_preliminary_quote.price,
                size=final_book.minimum_order_size,
            )
            final_quote = calculate_entry_quote(
                leader_fill_price=event.executed_price,
                minimum_order_size=final_book.minimum_order_size,
                tick_size=final_book.tick_size,
                best_ask=final_book.best_ask.price,
                expected_fee=final_expected_fee,
                now=final_checked_at,
                market_end=metadata.ends_at,
                minimum_seconds_to_end=TINY_LIVE_COPY_MINIMUM_SECONDS_TO_END,
            )
            if final_quote.price >= final_book.best_ask.price:
                raise LocalPostOnlyCrossing(
                    "final BUY price is equal to or above the current best ask"
                )
            if final_quote.price != quote.price or final_quote.quantity != quote.quantity:
                raise CopySignalSkip(
                    "final quote changed after local order preparation"
                )
            calculate_take_profit_price(final_quote.price, tick_size=final_book.tick_size)
            if (
                repository.cumulative_entry_cost(config.run_id) + final_quote.maximum_debit
                > MAXIMUM_EXPERIMENT_ENTRY_COST
            ):
                raise CopySignalSkip(
                    "entry would exceed the 10.00 USD cumulative experiment-cost cap"
                )
        except LocalPostOnlyCrossing:
            raise
        except CopySignalSkip:
            raise
        except ValueError as error:
            raise CopySignalSkip(str(error)) from error
        final_intent = OrderIntent(
            strategy_id=STRATEGY_ID,
            token_id=event.outcome_reference,
            side="BUY",
            price=final_quote.price,
            size=final_quote.quantity,
            reason=f"copy proven OPEN from {event.leader_id}",
            confidence=Decimal("1"),
        )
        final_risk_context = RiskContext(
            trading_mode=TradingMode.LIVE,
            live_trading_enabled=True,
            current_position=Decimal("0"),
            current_market_position=Decimal("0"),
            daily_pnl=Decimal("0"),
            open_orders_count=0,
            market_data_age_ms=_book_age_ms(final_book, final_checked_at),
        )
        submission.update(
            {
                "book": final_book,
                "checked_at": final_checked_at,
                "market": final_market,
                "quote": final_quote,
            }
        )
        runtime.report.orderbook_snapshots.append(
            _safe_book_snapshot(
                final_book,
                event=event,
                quote=final_quote,
                captured_at=final_checked_at,
            )
        )
        return PreparedLimitOrder(
            intent=final_intent,
            context=final_risk_context,
            expiration=quote.venue_expiration,
        )

    def persist_attempt() -> None:
        submission_checked_at = _aware(clock())
        final_quote = submission.get("quote")
        if not isinstance(final_quote, EntryQuote):
            raise TinyLiveCopyError("final pre-submit quote evidence is unavailable")
        if latency_metric is not None:
            reserved_at = datetime.fromisoformat(str(latency_metric["reserved_at"]))
            latency_metric["submission_checked_at"] = submission_checked_at.isoformat()
            latency_metric["reservation_to_submission_ms"] = _elapsed_ms(
                reserved_at,
                submission_checked_at,
            )
            latency_metric["market_time_remaining_at_submission_ms"] = _elapsed_ms(
                submission_checked_at,
                metadata.ends_at,
            )
        if not signal_is_fresh(
            executed_at=event.executed_at,
            observed_at=submission_checked_at,
            market_end=metadata.ends_at,
            minimum_seconds_to_end=TINY_LIVE_COPY_MINIMUM_SECONDS_TO_END,
        ):
            raise CopySignalSkip("signal is stale immediately before submission")
        attempt = repository.claim_entry_attempt(
            run_id=config.run_id,
            leader_alias=event.leader_id,
            event_id=event.event_id,
            market_id=event.market_reference,
            market_slug=metadata.external_slug,
            token_id=event.outcome_reference,
            entry_price=final_quote.price,
            entry_quantity=final_quote.quantity,
            entry_debit=final_quote.maximum_debit,
            entry_fee=final_quote.expected_fee,
            entry_cancel_at=final_quote.cancel_at,
            leader_latency_ms=max(
                0,
                int((submission_checked_at - event.executed_at).total_seconds() * 1000),
            ),
            leader_price_difference=final_quote.price - event.executed_price,
            claimed_at=submission_checked_at,
            reserved_event_id=event.event_id,
        )
        if attempt is None:
            raise TinyLiveCopyError("duplicate prevention blocked the entry attempt")
        claim["number"] = attempt
        claim["claimed_at"] = submission_checked_at
        runtime.report.decisions.append(
            {
                "action": "ENTRY_FINAL_RECHECK_PASSED",
                "event_id": event.event_id,
                "leader_alias": event.leader_id,
                "maximum_debit": str(final_quote.maximum_debit),
                "price": str(final_quote.price),
                "quantity": str(final_quote.quantity),
                "timestamp": submission_checked_at.isoformat(),
            }
        )

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
        try:
            await refresh_before_submit()
        except LocalPostOnlyCrossing as error:
            runtime.report.decisions.append(
                {
                    "action": "SIGNAL_REJECTED_POST_ONLY_LOCAL",
                    "event_id": event.event_id,
                    "leader_alias": event.leader_id,
                    "reason": str(error),
                    "timestamp": _aware(clock()).isoformat(),
                }
            )
            return False
        except CopySignalSkip as error:
            action = (
                "SIGNAL_REJECTED_STALE_BEFORE_SUBMISSION"
                if "stale" in str(error).casefold()
                else "SIGNAL_REJECTED_FINAL_LOCAL_INELIGIBILITY"
            )
            runtime.report.decisions.append(
                {
                    "action": action,
                    "event_id": event.event_id,
                    "leader_alias": event.leader_id,
                    "reason": str(error),
                    "timestamp": _aware(clock()).isoformat(),
                }
            )
            return False
        if latency_metric is not None:
            latency_metric["submission"] = "final_recheck_passed_no_attempt_dry_run"
        runtime.report.decisions.append(
            {
                "action": "ENTRY_FINAL_RECHECK_PASSED_DRY_RUN",
                "event_id": event.event_id,
                "leader_alias": event.leader_id,
                "timestamp": _aware(clock()).isoformat(),
            }
        )
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
            refresh_before_submit=refresh_before_submit,
            before_submit=persist_attempt,
        )
    except LocalPostOnlyCrossing as error:
        runtime.report.decisions.append(
            {
                "action": "SIGNAL_REJECTED_POST_ONLY_LOCAL",
                "event_id": event.event_id,
                "leader_alias": event.leader_id,
                "reason": str(error),
                "timestamp": _aware(clock()).isoformat(),
            }
        )
        return False
    except CopySignalSkip as error:
        action = (
            "SIGNAL_REJECTED_STALE_BEFORE_SUBMISSION"
            if "stale" in str(error).casefold()
            else "SIGNAL_REJECTED_FINAL_LOCAL_INELIGIBILITY"
        )
        runtime.report.decisions.append(
            {
                "action": action,
                "event_id": event.event_id,
                "leader_alias": event.leader_id,
                "reason": str(error),
                "timestamp": _aware(clock()).isoformat(),
            }
        )
        return False
    except Exception as error:
        if "number" in claim:
            attempt_number = cast(int, claim["number"])
            if _is_definitive_post_only_rejection(error):
                try:
                    await _reconcile_definitive_post_only_rejection(
                        execution_port,
                        event=event,
                        claimed_at=cast(datetime, claim["claimed_at"]),
                        now=_aware(clock()),
                    )
                except Exception as reconciliation_error:
                    repository.record_ambiguous_entry_submission(
                        run_id=config.run_id,
                        attempt_number=attempt_number,
                        updated_at=_aware(clock()),
                    )
                    runtime.report.decisions.append(
                        {
                            "action": "ENTRY_SUBMISSION_OUTCOME_AMBIGUOUS",
                            "attempt_number": attempt_number,
                            "event_id": event.event_id,
                            "leader_alias": event.leader_id,
                            "timestamp": _aware(clock()).isoformat(),
                        }
                    )
                    raise TinyLiveCopyError(
                        "Post-only rejection reconciliation could not prove zero mutation"
                    ) from reconciliation_error
                rejection_count = repository.record_definitive_post_only_rejection(
                    run_id=config.run_id,
                    attempt_number=attempt_number,
                    updated_at=_aware(clock()),
                )
                runtime.report.decisions.append(
                    {
                        "action": "ENTRY_POST_ONLY_REJECTED_DEFINITIVE",
                        "attempt_number": attempt_number,
                        "event_id": event.event_id,
                        "leader_alias": event.leader_id,
                        "run_post_only_rejection_count": rejection_count,
                        "timestamp": _aware(clock()).isoformat(),
                    }
                )
                if rejection_count >= 2:
                    raise TinyLiveCopyError(
                        "second definitive Post-only rejection in the same run"
                    ) from error
                return False
            if _is_definitive_venue_rejection(error):
                repository.record_definitive_entry_rejection(
                    run_id=config.run_id,
                    attempt_number=attempt_number,
                    terminal_reason=_definitive_rejection_reason(error),
                    updated_at=_aware(clock()),
                )
            else:
                repository.record_ambiguous_entry_submission(
                    run_id=config.run_id,
                    attempt_number=attempt_number,
                    updated_at=_aware(clock()),
                )
        raise
    order_id = _order_id(result.response)
    attempt_number = cast(int, claim["number"])
    repository.record_entry_submission(
        run_id=config.run_id,
        attempt_number=attempt_number,
        venue_order_id=order_id,
        state="ENTRY_PENDING",
        updated_at=_aware(clock()),
    )
    runtime.active_attempt_number = attempt_number
    final_market = submission.get("market")
    final_quote = submission.get("quote")
    if not isinstance(final_market, MarketDetails) or not isinstance(final_quote, EntryQuote):
        raise TinyLiveCopyError("final submission evidence is unavailable after acceptance")
    runtime.active_market = final_market
    runtime.active_token_id = event.outcome_reference
    runtime.active_entry_price = final_quote.price
    runtime.active_entry_fee = final_quote.expected_fee
    runtime.active_cancel_at = final_quote.cancel_at
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
                attempt_number=(runtime.active_attempt_number or snapshot.total_entry_attempts),
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
    entry_cost = (runtime.active_fill_price * snapshot.position_size) + runtime.active_entry_fee
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
    now: datetime,
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
    if _positions_requiring_isolation(
        await execution_port.list_positions(size_threshold=0),
        now=now,
    ):
        raise TinyLiveCopyError("a position appeared before entry")
    collateral = _mapping(await execution_port.get_balance_allowance(asset_type="COLLATERAL"))
    balance = _base_units(collateral.get("balance"))
    if balance < required_debit:
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


async def _reconcile_definitive_post_only_rejection(
    execution_port: CopyExecutionPort,
    *,
    event: LeaderTradeEvent,
    claimed_at: datetime,
    now: datetime,
) -> None:
    """Prove that a definitive Post-only rejection produced no account mutation."""

    open_orders = await execution_port.get_open_orders()
    positions = await execution_port.list_positions(size_threshold=0)
    trades = await execution_port.list_account_trades(
        token_id=event.outcome_reference,
        market=event.market_reference,
    )
    if open_orders:
        raise TinyLiveCopyError("rejected Post-only submission left an open order")
    if _positions_requiring_isolation(positions, now=now):
        raise TinyLiveCopyError("rejected Post-only submission left nonzero exposure")
    if any(
        _trade_may_follow_submission(
            trade,
            event=event,
            claimed_at=claimed_at,
        )
        for trade in trades
    ):
        raise TinyLiveCopyError("rejected Post-only submission has unexpected fill evidence")


def _trade_may_follow_submission(
    trade: Any,
    *,
    event: LeaderTradeEvent,
    claimed_at: datetime,
) -> bool:
    matched_at = _trade_matched_at(trade)
    if matched_at is not None:
        return matched_at >= _aware(claimed_at) - timedelta(seconds=1)
    return (
        str(_read(trade, "token_id", _read(trade, "asset_id", "")))
        == event.outcome_reference
        or str(_read(trade, "condition_id", _read(trade, "market", "")))
        == event.market_reference
    )


def _trade_matched_at(trade: Any) -> datetime | None:
    value = _read(
        trade,
        "matched_at",
        _read(trade, "match_time", _read(trade, "timestamp")),
    )
    if isinstance(value, datetime):
        return None if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, int | float) and not isinstance(value, bool):
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds /= 1000
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        try:
            if value.isdigit():
                seconds = int(value)
                if seconds > 10_000_000_000:
                    seconds /= 1000
                return datetime.fromtimestamp(seconds, tz=UTC)
            parsed = datetime.fromisoformat(value)
            return None if parsed.tzinfo is None else parsed.astimezone(UTC)
        except (OSError, OverflowError, ValueError):
            return None
    return None


def _is_definitive_post_only_rejection(error: BaseException) -> bool:
    if isinstance(error, LiveOrderRejectedError):
        return error.code == "post_only_would_cross" or (
            error.venue_message.casefold()
            == "invalid post-only order: order crosses book"
        )
    if not isinstance(error, PolymarketSecureAdapterError) or error.diagnostic is None:
        return False
    return (
        error.diagnostic.status_code == 400
        and error.diagnostic.category is VenueErrorCategory.POST_ONLY_WOULD_CROSS
    )


def _is_definitive_venue_rejection(error: BaseException) -> bool:
    if isinstance(error, LiveOrderRejectedError):
        return True
    if not isinstance(error, PolymarketSecureAdapterError) or error.diagnostic is None:
        return False
    return error.diagnostic.status_code is not None and (
        400 <= error.diagnostic.status_code < 500
        and error.diagnostic.status_code not in {408, 409, 429}
    )


def _definitive_rejection_reason(error: BaseException) -> str:
    if isinstance(error, LiveOrderRejectedError):
        return error.code
    if isinstance(error, PolymarketSecureAdapterError) and error.diagnostic is not None:
        return error.diagnostic.category.value
    return "DEFINITIVE_VENUE_REJECTION"


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
        entry_orders = await execution_port.get_open_orders(order_id=snapshot.entry_order_id)
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
        runtime.active_market = await market_port.get_market_by_slug(snapshot.active_market_slug)
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
                signal_window_open=(_aware(clock()) < repository.signal_window_end(config.run_id)),
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
            exits = await execution_port.get_open_orders(order_id=snapshot.exit_order_id)
            if len(exits) > 1:
                raise TinyLiveCopyError("restart reconciliation found duplicate related exits")
            if not exits and actual == snapshot.position_size:
                repository.clear_exit_order(
                    run_id=config.run_id,
                    state=CopyExperimentState.POSITION_OPEN,
                    updated_at=_aware(clock()),
                )
            elif not exits and actual not in {Decimal("0"), snapshot.position_size}:
                raise TinyLiveCopyError("restart found an ambiguous partially closed position")


async def _poll_aliases(
    source: LeaderTradeSourcePort,
    *,
    repository: CopyExperimentRepository,
    run_id: str,
    aliases: tuple[str, ...],
    start_at: datetime,
    end_at: datetime,
    purpose: LeaderReadPurpose,
    clock: Clock = utc_now,
    on_result: PollResultHandler | None = None,
) -> _PollBatch:
    semaphore = asyncio.Semaphore(10)
    started_at = _aware(clock())

    async def read(
        alias: str,
    ) -> tuple[tuple[_ObservedLeaderEvent, ...], TradesSourceUnavailableError | None]:
        events: list[_ObservedLeaderEvent] = [
            _event_from_pending_payload(payload)
            for payload in repository.pending_read_events(
                run_id=run_id,
                leader_alias=alias,
            )
        ]
        try:
            async with semaphore:
                durable = repository.read_checkpoint(
                    run_id=run_id,
                    leader_alias=alias,
                )
                if durable is not None and durable.checkpoint_value is not None:
                    window_start = durable.window_start
                    window_end = durable.window_end
                    checkpoint: LeaderTradeCheckpoint | None = LeaderTradeCheckpoint(
                        value=durable.checkpoint_value
                    )
                else:
                    latest_success = None if durable is None else durable.last_successful_at
                    window_start = (
                        start_at
                        if latest_success is None
                        else latest_success - timedelta(seconds=POLL_OVERLAP_SECONDS)
                    )
                    window_end = end_at
                    checkpoint = None
                pages = 0
                while pages < 5:
                    page = await source.read_page(
                        alias,
                        start_at=window_start,
                        end_at=window_end,
                        page_size=100,
                        checkpoint=checkpoint,
                        purpose=purpose,
                    )
                    observed_page = tuple(
                        _ObservedLeaderEvent(
                            event=event,
                            metadata=source.market_metadata(
                                event.market_reference,
                                event.outcome_reference,
                            ),
                        )
                        for event in page.events
                    )
                    events.extend(observed_page)
                    checkpoint = page.next_checkpoint
                    pages += 1
                    repository.stage_read_page(
                        run_id=run_id,
                        leader_alias=alias,
                        window_start=window_start,
                        window_end=window_end,
                        checkpoint_value=(None if checkpoint is None else checkpoint.value),
                        last_successful_at=(window_end if checkpoint is None else latest_success),
                        event_payloads=tuple(
                            _event_to_pending_payload(observed) for observed in observed_page
                        ),
                        staged_at=end_at,
                    )
                    if checkpoint is None:
                        break
                if checkpoint is not None:
                    raise TinyLiveCopyError("leader trade pagination exceeded the safe bound")
                return tuple(events), None
        except TradesSourceUnavailableError as error:
            return tuple(events), error

    async def timed_read(
        alias: str,
    ) -> tuple[
        tuple[_ObservedLeaderEvent, ...],
        TradesSourceUnavailableError | None,
        datetime,
    ]:
        events, read_error = await read(alias)
        return events, read_error, _aware(clock())

    tasks = [asyncio.create_task(timed_read(alias)) for alias in aliases]
    batches: list[
        tuple[
            tuple[_ObservedLeaderEvent, ...],
            TradesSourceUnavailableError | None,
            datetime,
        ]
    ] = []
    try:
        for completed in asyncio.as_completed(tasks):
            events, read_error, completed_at = await completed
            batches.append((events, read_error, completed_at))
            if on_result is not None:
                await on_result(
                    _PollBatch(
                        events=events,
                        unavailable=read_error,
                        started_at=started_at,
                        completed_at=completed_at,
                        response_count=1,
                    )
                )
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    unavailable_errors = [error for _, error, _ in batches if error is not None]
    completed_at = max(
        (completed for _, _, completed in batches),
        default=started_at,
    )
    return _PollBatch(
        events=tuple(event for batch, _, _ in batches for event in batch),
        unavailable=(
            None
            if not unavailable_errors
            else max(unavailable_errors, key=lambda error: error.retry_at)
        ),
        started_at=started_at,
        completed_at=completed_at,
        response_count=len(batches),
    )


def _event_to_pending_payload(observed: _ObservedLeaderEvent) -> dict[str, object]:
    event = observed.event
    metadata = observed.metadata
    return {
        "event_id": event.event_id,
        "executed_at": event.executed_at.isoformat(),
        "executed_price": str(event.executed_price),
        "executed_size": str(event.executed_size),
        "external_evidence_reference": event.external_evidence_reference,
        "leader_id": event.leader_id,
        "market_reference": event.market_reference,
        "observed_at": event.observed_at.isoformat(),
        "outcome_reference": event.outcome_reference,
        "position_effect": event.position_effect.value,
        "source_id": event.source_id,
        "trade_action": event.trade_action.value,
        "verified_market": {
            "ends_at": metadata.ends_at.isoformat(),
            "external_slug": metadata.external_slug,
            "market_reference": metadata.market_reference,
            "outcome_label": metadata.outcome_label,
            "outcome_reference": metadata.outcome_reference,
            "starts_at": metadata.starts_at.isoformat(),
        },
    }


def _event_from_pending_payload(payload: dict[str, object]) -> _ObservedLeaderEvent:
    event = LeaderTradeEvent(
        event_id=str(payload["event_id"]),
        source_id=str(payload["source_id"]),
        leader_id=str(payload["leader_id"]),
        market_reference=str(payload["market_reference"]),
        outcome_reference=str(payload["outcome_reference"]),
        trade_action=LeaderTradeAction(str(payload["trade_action"])),
        position_effect=LeaderPositionEffect(str(payload["position_effect"])),
        executed_price=Decimal(str(payload["executed_price"])),
        executed_size=Decimal(str(payload["executed_size"])),
        executed_at=datetime.fromisoformat(str(payload["executed_at"])),
        observed_at=datetime.fromisoformat(str(payload["observed_at"])),
        external_evidence_reference=(
            None
            if payload.get("external_evidence_reference") is None
            else str(payload["external_evidence_reference"])
        ),
    )
    raw_metadata = payload.get("verified_market")
    if not isinstance(raw_metadata, dict):
        raise TinyLiveCopyError("pending event is missing verified market metadata")
    metadata = LeaderMarketMetadata(
        market_reference=str(raw_metadata["market_reference"]),
        outcome_reference=str(raw_metadata["outcome_reference"]),
        external_slug=str(raw_metadata["external_slug"]),
        outcome_label=str(raw_metadata["outcome_label"]),
        starts_at=_aware(datetime.fromisoformat(str(raw_metadata["starts_at"]))),
        ends_at=_aware(datetime.fromisoformat(str(raw_metadata["ends_at"]))),
    )
    if (
        metadata.market_reference != event.market_reference
        or metadata.outcome_reference != event.outcome_reference
    ):
        raise TinyLiveCopyError("pending event market metadata identity mismatch")
    return _ObservedLeaderEvent(event=event, metadata=metadata)


def _record_source_outage(
    repository: CopyExperimentRepository,
    *,
    run_id: str,
    error: TradesSourceUnavailableError,
    report: TinyLiveCopyReport,
    now: datetime,
    exposure_exists: bool,
) -> None:
    state = repository.discovery_state(run_id)
    outage_started_at = state.outage_started_at or error.outage_started_at
    next_probe_at = max(error.retry_at, now + timedelta(seconds=1))
    cooldown_attempt = state.cooldown_attempt + 1
    repository.set_discovery_cooldown(
        run_id=run_id,
        outage_started_at=outage_started_at,
        next_probe_at=next_probe_at,
        cooldown_attempt=cooldown_attempt,
        updated_at=now,
    )
    report.source_availability = (
        "degraded_active_management_continues" if exposure_exists else "cooldown_flat"
    )
    report.decisions.append(
        {
            "action": "PUBLIC_TRADES_COOLDOWN",
            "active_follower_management_continues": exposure_exists,
            "cooldown_attempt": cooldown_attempt,
            "discovery_paused": True,
            "next_probe_at": next_probe_at.isoformat(),
            "timestamp": now.isoformat(),
        }
    )


def _clear_source_outage(
    repository: CopyExperimentRepository,
    *,
    run_id: str,
    report: TinyLiveCopyReport,
    now: datetime,
) -> None:
    state = repository.discovery_state(run_id)
    repository.clear_discovery_cooldown(
        run_id=run_id,
        successful_at=now,
    )
    if state.outage_started_at is not None:
        report.decisions.append(
            {
                "action": "PUBLIC_TRADES_SOURCE_RECOVERED",
                "outage_seconds": max(
                    0,
                    int((now - state.outage_started_at).total_seconds()),
                ),
                "stale_events_rejected": True,
                "timestamp": now.isoformat(),
            }
        )
    report.source_availability = "available"


def _ordered_discovery_aliases(
    aliases: tuple[str, ...],
    *,
    priority_aliases: tuple[str, ...],
) -> tuple[str, ...]:
    priority = tuple(sorted(set(priority_aliases)))
    if any(alias not in aliases for alias in priority):
        raise ValueError("priority discovery aliases must belong to the candidate bank")
    priority_set = set(priority)
    return priority + tuple(alias for alias in aliases if alias not in priority_set)


def _update_discovery_report(
    report: TinyLiveCopyReport,
    state: CopyDiscoveryState,
) -> None:
    report.candidate_summary.update(
        {
            "active_alias_count": len(state.active_aliases),
            "active_aliases": list(state.active_aliases),
            "discovery_cursor": state.cursor,
            "discovery_ordering_version": state.ordering_version,
            "discovery_rotation_minutes": DISCOVERY_ROTATION_MINUTES,
            "discovery_rotation_step": DISCOVERY_ROTATION_STEP,
            "full_bank_coverage_minutes": 60,
            "last_rotation_at": state.rotated_at.isoformat(),
            "subset_digest": state.subset_digest,
        }
    )


def _record_poll_batch(
    report: TinyLiveCopyReport,
    batch: _PollBatch,
    *,
    purpose: LeaderReadPurpose,
) -> None:
    if batch.started_at is None or batch.completed_at is None:
        return
    report.poll_batch_metrics.append(
        {
            "purpose": purpose.value,
            "response_count": batch.response_count,
            "started_at": batch.started_at.isoformat(),
            "completed_at": batch.completed_at.isoformat(),
            "full_batch_completion_ms": _elapsed_ms(
                batch.started_at,
                batch.completed_at,
            ),
        }
    )
    del report.poll_batch_metrics[:-120]


def _refresh_source_report(
    source: LeaderTradeSourcePort,
    report: TinyLiveCopyReport,
) -> None:
    telemetry_reader = getattr(source, "request_telemetry", None)
    if callable(telemetry_reader):
        report.request_metrics = dict(telemetry_reader())
    elif not report.request_metrics:
        report.request_metrics = {
            "budgets": {
                "discovery_attempts_per_10_seconds": (DISCOVERY_BUDGET_PER_10_SECONDS),
                "maximum_trades_attempts_per_10_seconds": (MAX_TRADES_ATTEMPTS_PER_10_SECONDS),
                "maximum_trades_in_flight": MAX_TRADES_IN_FLIGHT,
                "reserved_trades_attempts_per_10_seconds": (RESERVED_TRADES_BUDGET_PER_10_SECONDS),
            }
        }


async def _restore_source_circuit(
    source: LeaderTradeSourcePort,
    state: CopyDiscoveryState,
) -> None:
    if state.outage_started_at is None or state.next_probe_at is None:
        return
    restorer = getattr(source, "restore_trades_circuit", None)
    if callable(restorer):
        await restorer(
            outage_started_at=state.outage_started_at,
            retry_at=state.next_probe_at,
            cooldown_attempt=state.cooldown_attempt,
        )


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
    now: datetime,
) -> None:
    allowed_order_ids = {
        order_id
        for order_id in (snapshot.entry_order_id, snapshot.exit_order_id)
        if order_id is not None
    }
    observed_order_ids = {
        str(_read(order, "id") or _read(order, "order_id") or "") for order in open_orders
    }
    if "" in observed_order_ids or not observed_order_ids <= allowed_order_ids:
        raise TinyLiveCopyError("restart found an unrelated or unidentified open order")
    if len(observed_order_ids) > 1:
        raise TinyLiveCopyError("restart found more than one related open order")

    positive_positions = _positions_requiring_isolation(positions, now=now)
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
    expected_outcome_label: str,
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
    if (
        market.end_date is None
        or (_aware(market.end_date) - now).total_seconds() < TINY_LIVE_COPY_MINIMUM_SECONDS_TO_END
    ):
        raise CopySignalSkip("market has fewer than four minutes remaining")
    if (
        len(market.outcomes) != 2
        or {outcome.label.casefold() for outcome in market.outcomes} != {"up", "down"}
        or len({outcome.token_id for outcome in market.outcomes}) != 2
    ):
        raise CopySignalSkip("market binary Up/Down mapping is inconsistent")
    matching_outcomes = [outcome for outcome in market.outcomes if outcome.token_id == token_id]
    if len(matching_outcomes) != 1:
        raise CopySignalSkip("leader outcome token is not mapped to the market")
    if matching_outcomes[0].label.casefold() != expected_outcome_label.casefold():
        raise CopySignalSkip("leader outcome label does not match the selected token")
    if (
        market.end_date is None
        or abs((_aware(market.end_date) - _aware(expected_end)).total_seconds()) > 1
    ):
        raise CopySignalSkip("market end metadata mapping failed")
    slug_epoch = expected_slug.removeprefix("btc-updown-15m-")
    if (
        not slug_epoch.isdigit()
        or abs(
            (
                datetime.fromtimestamp(int(slug_epoch), tz=UTC) - _aware(expected_start)
            ).total_seconds()
        )
        > 1
    ):
        raise CopySignalSkip("market slug interval start mapping failed")
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
            "active_aliases": report.candidate_summary.get("active_aliases", []),
            "authorization_id": report.authorization_id,
            "completed_live_cycles": report.completed_live_cycles,
            "discovery_cursor": report.candidate_summary.get("discovery_cursor"),
            "run_id": report.run_id,
            "state": report.state,
            "subset_digest": report.candidate_summary.get("subset_digest"),
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
    lines = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}" for path in artifacts]
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
    report.cumulative_entry_cost = repository.cumulative_entry_cost(run_id)
    report.current_order_or_fill_exists = bool(
        snapshot.entry_order_id or snapshot.exit_order_id or snapshot.position_size > 0
    )
    report.attempts = _safe_attempts(repository.attempts(run_id))
    _update_discovery_report(report, repository.discovery_state(run_id))


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise TinyLiveCopyError("runtime clock must be timezone-aware")
    return value.astimezone(UTC)


def _elapsed_ms(start: datetime, end: datetime) -> int:
    return max(0, int((_aware(end) - _aware(start)).total_seconds() * 1000))


def _heartbeat_is_fresh(last_seen: datetime, now: datetime) -> bool:
    return (
        timedelta(0)
        <= _aware(now) - _aware(last_seen)
        <= timedelta(seconds=MAXIMUM_HEARTBEAT_GAP_SECONDS)
    )


def _book_age_ms(book: MarketOrderBookSnapshot, now: datetime) -> int:
    return max(0, int((now - _aware(book.timestamp)).total_seconds() * 1000))


def _base_units(value: object) -> Decimal:
    return _decimal(value) / BASE_UNITS


def _position_size(value: Any) -> Decimal:
    return _decimal(_read(value, "size", "0"))


def _positions_requiring_isolation(
    positions: list[Any],
    *,
    now: datetime,
) -> list[Any]:
    return [
        position
        for position in positions
        if _position_size(position) > 0 and not _is_closed_zero_value_position(position, now=now)
    ]


def _is_closed_zero_value_position(value: Any, *, now: datetime) -> bool:
    current_value = _read(
        value,
        "current_value",
        _read(value, "currentValue"),
    )
    current_price = _read(
        value,
        "cur_price",
        _read(value, "curPrice"),
    )
    redeemable = _read(value, "redeemable")
    mergeable = _read(value, "mergeable")
    end_value = _read(value, "end_date", _read(value, "endDate"))
    if (
        current_value is None
        or current_price is None
        or _decimal(current_value) != 0
        or _decimal(current_price) != 0
        or redeemable is None
        or mergeable is not False
    ):
        return False
    end_date = _position_end_date(end_value)
    return end_date is not None and end_date < _aware(now).date()


def _position_end_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return _aware(value).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


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
    "AUTHORIZATION_ID_PREFIX",
    "TinyLiveCopyConfig",
    "TinyLiveCopyError",
    "TinyLiveCopyReport",
    "run_tiny_live_copy",
    "write_tiny_live_copy_reports",
]
