from __future__ import annotations

import asyncio
import subprocess
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from polysia.adapters.polymarket.geoblock import GeoblockStatus, PreLiveOrderGeoblockCheck
from polysia.adapters.polymarket.public import (
    PolymarketPublicAdapter,
    PolymarketPublicAdapterError,
)
from polysia.adapters.polymarket.secure import (
    MarketOrderType,
    OrderSide,
    PolymarketSecureAdapter,
    PolymarketSecureAdapterError,
)
from polysia.config.settings import AppSettings, TradingMode
from polysia.domain.ledger import LedgerEvent
from polysia.domain.market import MarketDetails, MarketOrderBookSnapshot, MarketSummary
from polysia.domain.strategy import StrategyRun
from polysia.execution.intents import OrderIntent
from polysia.portfolio.live_admission import (
    PortfolioAdmissionContext,
    PortfolioAdmissionDecision,
    SingleStrategyPortfolioAdmission,
)
from polysia.reconciliation import (
    ActualAccountState,
    InternalExpectedState,
    OrderSnapshot,
    PositionSnapshot,
    ReconciliationInput,
    ReconciliationManager,
    ReconciliationResult,
)
from polysia.reconciliation.safety_pause import KillSwitchSafetyPause
from polysia.risk.bounded_live import BoundedLiveRiskContext, BoundedLiveRiskEngine
from polysia.risk.checks import RiskContext, RiskDecision, RiskEngine
from polysia.risk.kill_switch import KillSwitch
from polysia.risk.limits import RiskLimits
from polysia.storage.db import SQLiteDatabase
from polysia.storage.repositories import (
    FillRepository,
    LedgerEventRepository,
    LiveEntryAttemptRepository,
    LiveOrderCheckpointRepository,
    OrderRepository,
    PositionRepository,
    StrategyRegistryRepository,
)
from polysia.strategies.btc_15m_favorite_take_profit import (
    STRATEGY_ID,
    STRATEGY_VERSION,
    Btc15mFavoriteTakeProfitStrategy,
    FavoriteDecision,
    FavoriteTakeProfitConfig,
)
from polysia.strategies.registry import StrategyRegistry

RoundTripResult = Literal[
    "COMPLETED_ROUND_TRIP",
    "ENTRY_FILLED_EXIT_OPEN",
    "ENTRY_FILLED_EXIT_REJECTED",
    "ENTRY_NOT_FILLED",
    "NO_TRADE",
    "SAFETY_STOP",
    "EXECUTION_ERROR",
]
Clock = Callable[[], datetime]
Sleeper = Callable[[float], Awaitable[None]]
GitReader = Callable[[Path, tuple[str, ...]], str]

AUTHORIZATION_ID = "POLYSIA-LIVE-001"
MAXIMUM_ENTRY_NOTIONAL = Decimal("1.00")
BASE_UNITS = Decimal("1000000")
APPROVED_SDK_VERSION = "0.1.0b11"


def utc_now() -> datetime:
    return datetime.now(UTC)


class TinyLiveRoundTripError(RuntimeError):
    """Raised for a fail-closed round-trip condition."""


class RoundTripMarketPort(Protocol):
    async def search_markets(self, query: str, page_size: int = 20) -> list[MarketSummary]: ...

    async def get_market_by_slug(self, slug: str) -> MarketDetails: ...

    async def get_order_book(self, token_id: str) -> MarketOrderBookSnapshot: ...


class RoundTripExecutionPort(Protocol):
    @property
    def is_connected(self) -> bool: ...

    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    def identity(self) -> Any: ...

    async def get_balance_allowance(
        self,
        *,
        asset_type: Literal["COLLATERAL", "CONDITIONAL"],
        token_id: str | None = None,
    ) -> Any: ...

    async def get_open_orders(
        self,
        *,
        token_id: str | None = None,
        order_id: str | None = None,
        market: str | None = None,
    ) -> list[Any]: ...

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

    async def place_market_order(
        self,
        *,
        token_id: str,
        side: OrderSide,
        amount: Decimal | None = None,
        shares: Decimal | None = None,
        max_spend: Decimal | None = None,
        max_price: Decimal | None = None,
        min_price: Decimal | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> Any: ...

    async def place_limit_order(
        self,
        *,
        token_id: str,
        side: OrderSide,
        price: Decimal,
        size: Decimal,
        post_only: bool = False,
        expiration: int | None = None,
        builder_code: str | None = None,
    ) -> Any: ...


class RoundTripGeoblockPort(Protocol):
    async def check(self) -> GeoblockStatus: ...


@dataclass(frozen=True, slots=True)
class TinyLiveRoundTripConfig:
    settings: AppSettings
    project_root: Path
    output_dir: Path
    database_path: Path
    dry_run: bool = True
    acknowledgement: bool = False
    verified_ci_commit: str | None = None
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    maximum_entry_notional: Decimal = MAXIMUM_ENTRY_NOTIONAL
    minimum_remaining_seconds: int = 180
    maximum_book_age_ms: int = 5_000
    maximum_spread: Decimal = Decimal("0.10")
    fill_poll_attempts: int = 10
    fill_poll_interval_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.maximum_entry_notional != MAXIMUM_ENTRY_NOTIONAL:
            raise ValueError("maximum_entry_notional is fixed at 1.00")
        if self.minimum_remaining_seconds < 180:
            raise ValueError("minimum_remaining_seconds must be at least 180")
        if self.maximum_book_age_ms < 0 or self.maximum_spread <= 0:
            raise ValueError("book freshness and spread limits must be positive")
        if self.fill_poll_attempts < 1 or self.fill_poll_interval_seconds < 0:
            raise ValueError("fill polling configuration is invalid")
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")


@dataclass(frozen=True, slots=True)
class AccountPreflight:
    identity: dict[str, object]
    balance: Decimal
    reserved_balance: Decimal
    available_balance: Decimal
    allowance: Decimal
    open_order_count: int
    position_count: int
    outcome_token_state: dict[str, dict[str, str]]
    checked_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "allowance": str(self.allowance),
            "available_balance": str(self.available_balance),
            "balance": str(self.balance),
            "checked_at": self.checked_at.isoformat(),
            "identity": self.identity,
            "maximum_expected_bounded_loss": str(MAXIMUM_ENTRY_NOTIONAL),
            "open_order_count": self.open_order_count,
            "outcome_token_state": self.outcome_token_state,
            "position_count": self.position_count,
            "reserved_balance": str(self.reserved_balance),
        }


@dataclass(frozen=True, slots=True)
class FilledEntry:
    order_id: str
    size: Decimal
    weighted_average_price: Decimal
    fee: Decimal
    trade_count: int
    confirmed_at: datetime
    fee_rate_bps: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "fee": str(self.fee),
            "fee_rate_bps": list(self.fee_rate_bps),
            "order_id": self.order_id,
            "size": str(self.size),
            "trade_count": self.trade_count,
            "weighted_average_price": str(self.weighted_average_price),
            "confirmed_at": self.confirmed_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class FilledExit:
    order_id: str
    size: Decimal
    weighted_average_price: Decimal
    fee: Decimal
    trade_count: int
    confirmed_at: datetime
    fee_rate_bps: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "confirmed_at": self.confirmed_at.isoformat(),
            "fee": str(self.fee),
            "fee_rate_bps": list(self.fee_rate_bps),
            "order_id": self.order_id,
            "size": str(self.size),
            "trade_count": self.trade_count,
            "weighted_average_price": str(self.weighted_average_price),
        }


@dataclass(frozen=True, slots=True)
class TinyLiveRoundTripReport:
    run_id: str
    generated_at: datetime
    git_commit: str | None
    dry_run: bool
    final_result: RoundTripResult
    strategy: dict[str, object]
    registry: dict[str, object]
    account_snapshot: dict[str, object]
    market_snapshot: dict[str, object]
    strategy_decision: dict[str, object]
    portfolio_decision: dict[str, object]
    risk_decision: dict[str, object]
    entry_order: dict[str, object]
    exit_order: dict[str, object]
    fees: dict[str, object]
    position_state: dict[str, object]
    reconciliation: dict[str, object]
    ledger_entries: tuple[dict[str, object], ...]
    live_entry_attempt_count: int
    errors: tuple[str, ...]
    stop_reason: str | None
    evidence_references: tuple[str, ...]
    no_retry_statement: str = "No entry retry or replacement entry is implemented."

    def to_dict(self) -> dict[str, object]:
        return {
            "account_snapshot": self.account_snapshot,
            "dry_run": self.dry_run,
            "entry_order": self.entry_order,
            "errors": list(self.errors),
            "evidence_references": list(self.evidence_references),
            "exit_order": self.exit_order,
            "fees": self.fees,
            "final_result": self.final_result,
            "generated_at": self.generated_at.isoformat(),
            "git_commit": self.git_commit,
            "live_entry_attempt_count": self.live_entry_attempt_count,
            "ledger_entries": list(self.ledger_entries),
            "market_snapshot": self.market_snapshot,
            "no_retry_statement": self.no_retry_statement,
            "portfolio_decision": self.portfolio_decision,
            "position_state": self.position_state,
            "reconciliation": self.reconciliation,
            "registry": self.registry,
            "risk_decision": self.risk_decision,
            "run_id": self.run_id,
            "stop_reason": self.stop_reason,
            "strategy": self.strategy,
            "strategy_decision": self.strategy_decision,
        }


class RoundTripOrderManager:
    """Persistent one-entry/one-exit manager; no retry or replacement methods exist."""

    def __init__(
        self,
        *,
        adapter: RoundTripExecutionPort,
        attempts: LiveEntryAttemptRepository,
        checkpoints: LiveOrderCheckpointRepository,
        authorization_id: str,
        run_id: str,
        strategy_id: str,
        market_id: str,
        clock: Clock,
    ) -> None:
        self._adapter = adapter
        self._attempts = attempts
        self._checkpoints = checkpoints
        self._authorization_id = authorization_id
        self._run_id = run_id
        self._strategy_id = strategy_id
        self._market_id = market_id
        self._clock = clock
        self.entry_client_order_id = f"{run_id}:entry"
        self.exit_client_order_id = f"{run_id}:exit"
        self.entry_attempts = 0
        self.exit_attempts = 0

    async def submit_entry(self, intent: OrderIntent) -> Any:
        if self.entry_attempts != 0:
            raise TinyLiveRoundTripError("one-entry-attempt invariant violated")
        claimed = self._attempts.claim(
            authorization_id=self._authorization_id,
            run_id=self._run_id,
            strategy_id=self._strategy_id,
            market_id=self._market_id,
            attempted_at=self._clock(),
        )
        if not claimed:
            raise TinyLiveRoundTripError("owner authorization already has an entry attempt")
        self.entry_attempts = 1
        try:
            response = await self._adapter.place_market_order(
                token_id=intent.token_id,
                side="BUY",
                amount=MAXIMUM_ENTRY_NOTIONAL,
                max_spend=MAXIMUM_ENTRY_NOTIONAL,
                max_price=intent.price,
                order_type="FOK",
            )
        except Exception as error:
            self._attempts.update_state(
                self._authorization_id,
                "ENTRY_SUBMIT_ERROR",
                updated_at=self._clock(),
            )
            raise TinyLiveRoundTripError(
                "entry submission failed after the persistent attempt claim"
            ) from error
        persisted_at = self._clock()
        try:
            self._checkpoints.upsert(
                run_id=self._run_id,
                phase="ENTRY_RESPONSE",
                client_order_id=self.entry_client_order_id,
                venue_order_id=_safe(_read(response, "order_id")),
                payload=_mapping(response),
                persisted_at=persisted_at,
            )
            self._attempts.update_state(
                self._authorization_id,
                "ENTRY_SUBMITTED",
                updated_at=persisted_at,
            )
        except Exception as error:
            raise TinyLiveRoundTripError(
                "entry response could not be checkpointed; no next external step is allowed"
            ) from error
        return response

    async def submit_exit(self, *, token_id: str, price: Decimal, size: Decimal) -> Any:
        if self.entry_attempts != 1:
            raise TinyLiveRoundTripError("exit requires exactly one prior entry attempt")
        if self.exit_attempts != 0:
            raise TinyLiveRoundTripError("one-exit-order invariant violated")
        if size <= 0:
            raise TinyLiveRoundTripError("exit size must be positive")
        self.exit_attempts = 1
        try:
            response = await self._adapter.place_limit_order(
                token_id=token_id,
                side="SELL",
                price=price,
                size=size,
                post_only=False,
            )
        except Exception as error:
            self._attempts.update_state(
                self._authorization_id,
                "EXIT_SUBMIT_ERROR",
                updated_at=self._clock(),
            )
            raise TinyLiveRoundTripError(
                "exit submission failed; no replacement exit is permitted"
            ) from error
        persisted_at = self._clock()
        try:
            self._checkpoints.upsert(
                run_id=self._run_id,
                phase="EXIT_RESPONSE",
                client_order_id=self.exit_client_order_id,
                venue_order_id=_safe(_read(response, "order_id")),
                payload=_mapping(response),
                persisted_at=persisted_at,
            )
            self._attempts.update_state(
                self._authorization_id,
                "EXIT_SUBMITTED",
                updated_at=persisted_at,
            )
        except Exception as error:
            raise TinyLiveRoundTripError(
                "exit response could not be checkpointed; no replacement exit is allowed"
            ) from error
        return response


async def run_tiny_live_round_trip(
    config: TinyLiveRoundTripConfig,
    *,
    market_port: RoundTripMarketPort | None = None,
    execution_port: RoundTripExecutionPort | None = None,
    geoblock_port: RoundTripGeoblockPort | None = None,
    kill_switch: KillSwitch | None = None,
    clock: Clock = utc_now,
    sleeper: Sleeper = asyncio.sleep,
    git_reader: GitReader | None = None,
) -> TinyLiveRoundTripReport:
    """Run a real-data dry-run or the single authorized bounded live attempt."""

    active_market_port = market_port or PolymarketPublicAdapter()
    active_execution_port = execution_port or PolymarketSecureAdapter()
    active_geoblock = geoblock_port or PreLiveOrderGeoblockCheck()
    active_kill_switch = kill_switch or KillSwitch()
    started_at = clock()
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)

    result: RoundTripResult = "NO_TRADE"
    errors: list[str] = []
    stop_reason: str | None = None
    market: MarketDetails | None = None
    books: tuple[MarketOrderBookSnapshot, ...] = ()
    decision: FavoriteDecision | None = None
    portfolio_decision = PortfolioAdmissionDecision(False, "not evaluated")
    risk_decision = RiskDecision(False, "not evaluated")
    account: AccountPreflight | None = None
    geoblock: dict[str, object] = {"status": "not_checked", "blocked": None}
    entry_order: dict[str, object] = {}
    exit_order: dict[str, object] = {}
    fee_evidence: dict[str, object] = {}
    position_state: dict[str, object] = {}
    reconciliation_payload: dict[str, object] = {}
    ledger_entries: list[dict[str, object]] = []
    live_attempt_count = 0
    api_connectivity_verified = False
    git_commit = _git_value(config.project_root, ("git", "rev-parse", "HEAD"), git_reader)
    evidence_references = (
        str(config.output_dir / "tiny-live-round-trip.json"),
        str(config.output_dir / "tiny-live-round-trip.md"),
        str(config.database_path),
    )

    strategy = Btc15mFavoriteTakeProfitStrategy(
        FavoriteTakeProfitConfig(
            maximum_entry_notional=config.maximum_entry_notional,
            maximum_data_age_ms=config.maximum_book_age_ms,
            maximum_spread=config.maximum_spread,
        )
    )

    with SQLiteDatabase(config.database_path) as database:
        registry_store = StrategyRegistryRepository(database.connection)
        registry = StrategyRegistry(registry_store)
        definition = registry.get(STRATEGY_ID, STRATEGY_VERSION)
        if definition is None:
            definition = registry.register(strategy.definition(created_at=started_at))
        performance = registry.performance(STRATEGY_ID, STRATEGY_VERSION)
        attempt_repository = LiveEntryAttemptRepository(database.connection)
        checkpoint_repository = LiveOrderCheckpointRepository(database.connection)

        try:
            _assert_sdk_compatible()
            _assert_runtime_settings(config, active_kill_switch)
            _assert_git_and_ci(config, git_commit=git_commit, git_reader=git_reader)
            market, books, decision = await _select_market_and_decide(
                active_market_port,
                strategy,
                config=config,
                clock=clock,
            )
            if not active_execution_port.is_connected:
                await active_execution_port.connect()
            api_connectivity_verified = active_execution_port.is_connected
            account, open_orders, positions = await _read_account_preflight(
                active_execution_port,
                token_ids=tuple(book.token_id for book in books),
                checked_at=_aware_datetime(clock()),
            )
            geoblock_status = await active_geoblock.check()
            geoblock = geoblock_status.to_safe_dict()
            _assert_identity(account.identity)
            _assert_geoblock(geoblock_status)
            _assert_account_funded(
                account,
                selected_token_id=decision.selected_token_id,
                expected_exit_size=decision.entry_size,
            )
            if decision.status != "TRADE":
                stop_reason = decision.reason
                raise TinyLiveRoundTripError(decision.reason)
            market, books, decision = await _refresh_selected_market_and_decide(
                active_market_port,
                strategy,
                market=market,
                original_books=books,
                config=config,
                now=_aware_datetime(clock()),
            )
            if decision.status != "TRADE":
                stop_reason = decision.reason
                raise TinyLiveRoundTripError(decision.reason)
            account, open_orders, positions = await _read_account_preflight(
                active_execution_port,
                token_ids=tuple(book.token_id for book in books),
                checked_at=_aware_datetime(clock()),
            )
            geoblock_status = await active_geoblock.check()
            geoblock = geoblock_status.to_safe_dict()
            _assert_identity(account.identity)
            _assert_geoblock(geoblock_status)
            _assert_account_funded(
                account,
                selected_token_id=decision.selected_token_id,
                expected_exit_size=decision.entry_size,
            )

            intent = decision.to_intent()
            selected_book = next(book for book in books if book.token_id == intent.token_id)
            exit_target = normalize_exit_target(
                intent.price,
                tick_size=selected_book.tick_size,
            )
            expected_fee = strategy.expected_fee(
                market,
                price=intent.price,
                size=intent.size,
            )
            fee_evidence = _fee_evidence(market, expected_fee=expected_fee)

            conflicting_orders = _conflicting_orders(open_orders, market, books)
            conflicting_positions = _conflicting_positions(positions, market, books)
            pre_entry_reconciliation = _reconcile_snapshots(
                open_orders=conflicting_orders,
                positions=conflicting_positions,
                internal_orders=(),
                internal_positions=(),
                clock=clock,
                kill_switch=active_kill_switch,
            )
            reconciliation_payload = _reconciliation_to_dict(
                pre_entry_reconciliation
            )
            portfolio_decision = SingleStrategyPortfolioAdmission().evaluate(
                intent,
                PortfolioAdmissionContext(
                    available_balance=account.available_balance,
                    reserved_balance=account.reserved_balance,
                    existing_market_positions=len(conflicting_positions),
                    conflicting_open_orders=len(conflicting_orders),
                    current_market_exposure=_position_total(conflicting_positions),
                    exit_path_available=exit_target is not None,
                ),
                expected_fee=expected_fee,
            )
            if not portfolio_decision.admitted:
                stop_reason = portfolio_decision.reason
                raise TinyLiveRoundTripError(portfolio_decision.reason)

            base_risk = RiskEngine(
                kill_switch=active_kill_switch,
                limits=RiskLimits(
                    allow_live_trading=True,
                    max_open_orders=1,
                    max_order_notional=min(
                        MAXIMUM_ENTRY_NOTIONAL,
                        config.settings.polymarket_live_max_order_notional,
                    ),
                    max_position_per_market=config.settings.polymarket_live_max_order_size,
                    max_position_per_token=config.settings.polymarket_live_max_order_size,
                    max_stale_data_age_ms=config.maximum_book_age_ms,
                ),
            )
            risk_checked_at = _aware_datetime(clock())
            risk_decision = BoundedLiveRiskEngine(base_risk).evaluate_entry(
                intent,
                RiskContext(
                    trading_mode=TradingMode.LIVE,
                    live_trading_enabled=True,
                    current_position=Decimal("0"),
                    current_market_position=Decimal("0"),
                    daily_pnl=Decimal("0"),
                    open_orders_count=len(conflicting_orders),
                    market_data_age_ms=max(
                        _data_age_ms(quote.timestamp, risk_checked_at)
                        for quote in decision.quotes
                    ),
                ),
                BoundedLiveRiskContext(
                    entry_attempt_count=(
                        1 if attempt_repository.get(AUTHORIZATION_ID) is not None else 0
                    ),
                    selected_market_count=1,
                    existing_position_count=len(conflicting_positions),
                    available_balance=account.available_balance,
                    expected_fee=expected_fee,
                    order_price_valid=_price_is_tick_aligned(
                        intent.price,
                        selected_book.tick_size,
                    ),
                    order_size_valid=(
                        intent.size >= selected_book.minimum_order_size
                        and intent.size <= selected_book.best_ask.size
                        if selected_book.best_ask is not None
                        else False
                    ),
                    market_tradeable=True,
                    geoblock_allowed=True,
                    duplicate_free=not conflicting_orders,
                    exit_path_available=exit_target is not None,
                    owner_authorized=True,
                    account_identity_consistent=True,
                    signer_funder_compatible=True,
                    reconciliation_available=(
                        not pre_entry_reconciliation.trading_should_pause
                    ),
                    token_allowlisted=(
                        intent.token_id
                        in config.settings.polymarket_live_token_allowlist
                    ),
                ),
            )
            if not risk_decision.approved:
                stop_reason = risk_decision.reason
                raise TinyLiveRoundTripError(risk_decision.reason)

            entry_order = {
                "actual_fill": None,
                "attempted": False,
                "maximum_spend": str(MAXIMUM_ENTRY_NOTIONAL),
                "order_type": "FOK",
                "requested_notional": str(intent.price * intent.size),
                "requested_price": str(intent.price),
                "requested_size": str(intent.size),
                "status": "DRY_RUN_APPROVED" if config.dry_run else "READY",
            }
            exit_order = {
                "attempted": False,
                "normalized_target": str(exit_target),
                "order_type": "GTC",
                "raw_target_formula": "actual_weighted_average_fill_price * 1.10",
                "status": "NOT_APPLICABLE_DRY_RUN" if config.dry_run else "PENDING_ENTRY_FILL",
            }

            if config.dry_run:
                result = "NO_TRADE"
                stop_reason = "dry-run preflight passed; no live order authorized by dry-run mode"
            else:
                manager = RoundTripOrderManager(
                    adapter=active_execution_port,
                    attempts=attempt_repository,
                    checkpoints=checkpoint_repository,
                    authorization_id=AUTHORIZATION_ID,
                    run_id=config.run_id,
                    strategy_id=STRATEGY_ID,
                    market_id=market.id,
                    clock=clock,
                )
                try:
                    try:
                        response = await manager.submit_entry(intent)
                    except TinyLiveRoundTripError as error:
                        reconciliation_result = await _reconcile_without_entry(
                            active_execution_port,
                            market=market,
                            token_ids=tuple(book.token_id for book in books),
                            clock=clock,
                            kill_switch=active_kill_switch,
                        )
                        reconciliation_payload = _reconciliation_to_dict(
                            reconciliation_result
                        )
                        result = "SAFETY_STOP"
                        stop_reason = str(error)
                        raise
                finally:
                    live_attempt_count = manager.entry_attempts
                entry_order = _safe_order_response(response, attempted=True)
                entry_order.update(
                    {
                        "client_correlation_id": config.run_id,
                        "client_order_id": manager.entry_client_order_id,
                        "client_order_id_sent_to_venue": False,
                        "maximum_spend": str(MAXIMUM_ENTRY_NOTIONAL),
                        "order_type": "FOK",
                        "requested_notional": str(intent.price * intent.size),
                        "requested_price": str(intent.price),
                        "requested_size": str(intent.size),
                        "submitted_at": clock().isoformat(),
                    }
                )
                _persist_entry_order_state(
                    database.connection,
                    entry_order=entry_order,
                    token_id=intent.token_id,
                    timestamp=clock(),
                )
                if entry_order.get("accepted") is not True:
                    stop_reason = str(entry_order.get("rejection_reason") or "entry rejected")
                    attempt_repository.update_state(
                        AUTHORIZATION_ID,
                        "ENTRY_REJECTED",
                        updated_at=clock(),
                    )
                    reconciliation_result = await _reconcile_without_entry(
                        active_execution_port,
                        market=market,
                        token_ids=tuple(book.token_id for book in books),
                        clock=clock,
                        kill_switch=active_kill_switch,
                    )
                    reconciliation_payload = _reconciliation_to_dict(
                        reconciliation_result
                    )
                    result = (
                        "SAFETY_STOP"
                        if reconciliation_result.trading_should_pause
                        else "ENTRY_NOT_FILLED"
                    )
                else:
                    order_id = _required_order_id(response)
                    fill = await _wait_for_confirmed_entry(
                        active_execution_port,
                        token_id=intent.token_id,
                        order_id=order_id,
                        market_fee=market,
                        attempts=config.fill_poll_attempts,
                        interval_seconds=config.fill_poll_interval_seconds,
                        sleeper=sleeper,
                        clock=clock,
                    )
                    if fill is None:
                        stop_reason = "entry produced no confirmed fill; no retry or exit"
                        attempt_repository.update_state(
                            AUTHORIZATION_ID,
                            "ENTRY_NOT_FILLED",
                            updated_at=clock(),
                        )
                        reconciliation_result = await _reconcile_without_entry(
                            active_execution_port,
                            market=market,
                            token_ids=tuple(book.token_id for book in books),
                            clock=clock,
                            kill_switch=active_kill_switch,
                        )
                        reconciliation_payload = _reconciliation_to_dict(
                            reconciliation_result
                        )
                        result = (
                            "SAFETY_STOP"
                            if reconciliation_result.trading_should_pause
                            else "ENTRY_NOT_FILLED"
                        )
                    else:
                        entry_order["actual_fill"] = fill.to_dict()
                        entry_order["status"] = "CONFIRMED_FILL"
                        fee_evidence["actual_entry_fee"] = str(fill.fee)
                        fee_evidence["actual_fee_source"] = (
                            "confirmed fill size/price and verified market fee schedule; "
                            "venue fee_rate_bps retained when supplied"
                        )
                        entry_ledger_entries = _entry_ledger_entries(
                            run_id=config.run_id,
                            token_id=intent.token_id,
                            fill=fill,
                        )
                        ledger_entries.extend(entry_ledger_entries)
                        checkpoint_repository.upsert(
                            run_id=config.run_id,
                            phase="ENTRY_FILL_CONFIRMED",
                            client_order_id=manager.entry_client_order_id,
                            venue_order_id=fill.order_id,
                            payload=fill.to_dict(),
                            persisted_at=fill.confirmed_at,
                        )
                        _persist_entry_order_state(
                            database.connection,
                            entry_order=entry_order,
                            token_id=intent.token_id,
                            timestamp=fill.confirmed_at,
                        )
                        _persist_fill_state(
                            database.connection,
                            run_id=config.run_id,
                            side="BUY",
                            token_id=intent.token_id,
                            fill=fill.to_dict(),
                            order_id=fill.order_id,
                            timestamp=fill.confirmed_at,
                        )
                        _persist_ledger_entries(
                            database.connection,
                            run_id=config.run_id,
                            entries=entry_ledger_entries,
                        )
                        attempt_repository.update_state(
                            AUTHORIZATION_ID,
                            "ENTRY_FILLED",
                            updated_at=fill.confirmed_at,
                        )
                        try:
                            reconciled_size, _ = await _reconciled_position_size(
                                active_execution_port,
                                market=market,
                                token_id=intent.token_id,
                                expected_size=fill.size,
                            )
                        except TinyLiveRoundTripError as error:
                            reconciliation_result = (
                                await _reconcile_position_without_exit(
                                    active_execution_port,
                                    market=market,
                                    token_id=intent.token_id,
                                    expected_position=fill.size,
                                    clock=clock,
                                    kill_switch=active_kill_switch,
                                )
                            )
                            reconciliation_payload = _reconciliation_to_dict(
                                reconciliation_result
                            )
                            result = "SAFETY_STOP"
                            stop_reason = str(error)
                            raise
                        position_state = {
                            "available_size": str(reconciled_size),
                            "entry_fill_size": str(fill.size),
                            "token_id": intent.token_id,
                        }
                        position_checked_at = clock()
                        checkpoint_repository.upsert(
                            run_id=config.run_id,
                            phase="ENTRY_POSITION_RECONCILED",
                            client_order_id=manager.entry_client_order_id,
                            venue_order_id=fill.order_id,
                            payload=position_state,
                            persisted_at=position_checked_at,
                        )
                        _persist_position_state(
                            database.connection,
                            market_id=market.id,
                            position_state=position_state,
                            average_entry_price=fill.weighted_average_price,
                            timestamp=position_checked_at,
                        )
                        actual_exit_target = normalize_exit_target(
                            fill.weighted_average_price,
                            tick_size=selected_book.tick_size,
                        )
                        if actual_exit_target is None:
                            result = "SAFETY_STOP"
                            stop_reason = "actual fill cannot produce a valid 10% exit target"
                            reconciliation_result = (
                                await _reconcile_position_without_exit(
                                    active_execution_port,
                                    market=market,
                                    token_id=intent.token_id,
                                    expected_position=reconciled_size,
                                    clock=clock,
                                    kill_switch=active_kill_switch,
                                )
                            )
                            reconciliation_payload = _reconciliation_to_dict(
                                reconciliation_result
                            )
                        else:
                            try:
                                exit_response = await manager.submit_exit(
                                    token_id=intent.token_id,
                                    price=actual_exit_target,
                                    size=reconciled_size,
                                )
                            except TinyLiveRoundTripError as error:
                                reconciliation_result = (
                                    await _reconcile_position_without_exit(
                                        active_execution_port,
                                        market=market,
                                        token_id=intent.token_id,
                                        expected_position=reconciled_size,
                                        clock=clock,
                                        kill_switch=active_kill_switch,
                                    )
                                )
                                reconciliation_payload = _reconciliation_to_dict(
                                    reconciliation_result
                                )
                                result = "SAFETY_STOP"
                                stop_reason = str(error)
                                raise
                            exit_order = _safe_order_response(exit_response, attempted=True)
                            exit_order.update(
                                {
                                    "client_order_id": manager.exit_client_order_id,
                                    "client_order_id_sent_to_venue": False,
                                    "normalized_target": str(actual_exit_target),
                                    "raw_target": str(
                                        fill.weighted_average_price * Decimal("1.10")
                                    ),
                                    "sell_quantity": str(reconciled_size),
                                    "submitted_at": clock().isoformat(),
                                    "target_formula": "actual_weighted_average_fill_price * 1.10",
                                }
                            )
                            _persist_exit_order_state(
                                database.connection,
                                exit_order=exit_order,
                                token_id=intent.token_id,
                                timestamp=clock(),
                            )
                            if exit_order.get("accepted") is not True:
                                stop_reason = str(
                                    exit_order.get("rejection_reason") or "exit rejected"
                                )
                                attempt_repository.update_state(
                                    AUTHORIZATION_ID,
                                    "EXIT_REJECTED",
                                    updated_at=clock(),
                                )
                                reconciliation_result = (
                                    await _reconcile_position_without_exit(
                                        active_execution_port,
                                        market=market,
                                        token_id=intent.token_id,
                                        expected_position=reconciled_size,
                                        clock=clock,
                                        kill_switch=active_kill_switch,
                                    )
                                )
                                reconciliation_payload = _reconciliation_to_dict(
                                    reconciliation_result
                                )
                                result = (
                                    "SAFETY_STOP"
                                    if reconciliation_result.trading_should_pause
                                    else "ENTRY_FILLED_EXIT_REJECTED"
                                )
                            else:
                                (
                                    result,
                                    reconciliation_result,
                                    exit_fill,
                                    remaining_position,
                                ) = await _classify_and_reconcile_exit(
                                    active_execution_port,
                                    market=market,
                                    token_id=intent.token_id,
                                    exit_order_id=_required_order_id(exit_response),
                                    expected_position=reconciled_size,
                                    clock=clock,
                                    kill_switch=active_kill_switch,
                                )
                                reconciliation_payload = _reconciliation_to_dict(
                                    reconciliation_result
                                )
                                if exit_fill is not None:
                                    exit_order["actual_fill"] = exit_fill.to_dict()
                                    exit_order["status"] = (
                                        "CONFIRMED_FILL"
                                        if remaining_position == 0
                                        else "PARTIALLY_FILLED_OPEN"
                                        if result == "ENTRY_FILLED_EXIT_OPEN"
                                        else "PARTIALLY_FILLED_UNKNOWN"
                                    )
                                    fee_evidence["actual_exit_fee"] = str(exit_fill.fee)
                                    fee_evidence["actual_total_fees"] = str(
                                        fill.fee + exit_fill.fee
                                    )
                                    position_state["available_size"] = str(
                                        remaining_position
                                    )
                                    position_state["exit_filled_size"] = str(
                                        exit_fill.size
                                    )
                                    allocated_entry_fee = (
                                        fill.fee * exit_fill.size / fill.size
                                    )
                                    position_state["realized_pnl"] = str(
                                        (exit_fill.weighted_average_price * exit_fill.size)
                                        - exit_fill.fee
                                        - (fill.weighted_average_price * exit_fill.size)
                                        - allocated_entry_fee
                                    )
                                    exit_ledger_entries = _exit_ledger_entries(
                                        run_id=config.run_id,
                                        token_id=intent.token_id,
                                        fill=exit_fill,
                                    )
                                    ledger_entries.extend(exit_ledger_entries)
                                    checkpoint_repository.upsert(
                                        run_id=config.run_id,
                                        phase="EXIT_FILL_CONFIRMED",
                                        client_order_id=manager.exit_client_order_id,
                                        venue_order_id=exit_fill.order_id,
                                        payload=exit_fill.to_dict(),
                                        persisted_at=exit_fill.confirmed_at,
                                    )
                                    _persist_exit_order_state(
                                        database.connection,
                                        exit_order=exit_order,
                                        token_id=intent.token_id,
                                        timestamp=exit_fill.confirmed_at,
                                    )
                                    _persist_fill_state(
                                        database.connection,
                                        run_id=config.run_id,
                                        side="SELL",
                                        token_id=intent.token_id,
                                        fill=exit_fill.to_dict(),
                                        order_id=exit_fill.order_id,
                                        timestamp=exit_fill.confirmed_at,
                                    )
                                    _persist_ledger_entries(
                                        database.connection,
                                        run_id=config.run_id,
                                        entries=exit_ledger_entries,
                                    )
                                    position_checked_at = clock()
                                    checkpoint_repository.upsert(
                                        run_id=config.run_id,
                                        phase="EXIT_POSITION_RECONCILED",
                                        client_order_id=manager.exit_client_order_id,
                                        venue_order_id=exit_fill.order_id,
                                        payload=position_state,
                                        persisted_at=position_checked_at,
                                    )
                                    _persist_position_state(
                                        database.connection,
                                        market_id=market.id,
                                        position_state=position_state,
                                        average_entry_price=fill.weighted_average_price,
                                        timestamp=position_checked_at,
                                    )
                                if reconciliation_result.trading_should_pause:
                                    result = "SAFETY_STOP"
                                    stop_reason = "reconciliation mismatch activated safety stop"
                                attempt_repository.update_state(
                                    AUTHORIZATION_ID,
                                    result,
                                    updated_at=clock(),
                                )
        except TinyLiveRoundTripError as error:
            errors.append(str(error))
            if stop_reason is None:
                stop_reason = str(error)
            if live_attempt_count > 0 and result == "NO_TRADE":
                result = "SAFETY_STOP"
        except (
            PolymarketPublicAdapterError,
            PolymarketSecureAdapterError,
            OSError,
            subprocess.SubprocessError,
            ValueError,
        ) as error:
            errors.append(f"{type(error).__name__}: {error}")
            stop_reason = "execution or preflight error"
            result = "EXECUTION_ERROR" if live_attempt_count > 0 else "NO_TRADE"
        finally:
            try:
                await active_execution_port.close()
            except Exception as error:
                errors.append(f"close error: {type(error).__name__}")
                if stop_reason is None:
                    stop_reason = "authenticated adapter cleanup failed"

        ended_at = clock()
        report = TinyLiveRoundTripReport(
            run_id=config.run_id,
            generated_at=ended_at,
            git_commit=git_commit,
            dry_run=config.dry_run,
            final_result=result,
            strategy={
                "category": definition.category,
                "lifecycle_status": definition.lifecycle_status.value,
                "name": definition.name,
                "risk_class": definition.risk_class,
                "strategy_id": definition.strategy_id,
                "version": definition.version,
            },
            registry={
                "definition_count": len(registry.list()),
                "evidence_sufficiency": performance.evidence_sufficiency,
                "score_status": performance.score_status,
            },
            account_snapshot=(
                {
                    **account.to_dict(),
                    "api_connectivity_verified": api_connectivity_verified,
                    "clock_utc_aware": ended_at.tzinfo is not None,
                    "emergency_control_active": active_kill_switch.is_active(),
                    "sdk_version": APPROVED_SDK_VERSION,
                }
                if account is not None
                else {}
            ),
            market_snapshot=_market_snapshot(
                market,
                books,
                geoblock,
                as_of=ended_at,
            ),
            strategy_decision=(
                {
                    **decision.to_dict(),
                    "confidence_classification": (
                        "relative executable-price separation; not alpha evidence"
                    ),
                    "parameters": {
                        "exit_target_multiple": "1.10",
                        "maximum_book_age_ms": config.maximum_book_age_ms,
                        "maximum_entry_notional": str(
                            config.maximum_entry_notional
                        ),
                        "maximum_spread": str(config.maximum_spread),
                    },
                }
                if decision is not None
                else {}
            ),
            portfolio_decision=portfolio_decision.to_dict(),
            risk_decision=_risk_to_dict(risk_decision),
            entry_order=entry_order,
            exit_order=exit_order,
            fees=fee_evidence,
            position_state=position_state,
            reconciliation=reconciliation_payload,
            ledger_entries=tuple(ledger_entries),
            live_entry_attempt_count=live_attempt_count,
            errors=tuple(errors),
            stop_reason=stop_reason,
            evidence_references=evidence_references,
        )
        registry.record_run(
            StrategyRun(
                strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION,
                run_id=config.run_id,
                runtime_mode="paper" if config.dry_run else "limited_live",
                venue="polymarket",
                market=market.id if market is not None else None,
                started_at=started_at,
                ended_at=ended_at,
                parameters={
                    "maximum_entry_attempts": 1,
                    "maximum_entry_notional": str(MAXIMUM_ENTRY_NOTIONAL),
                    "maximum_markets": 1,
                    "maximum_positions": 1,
                    "exit_target_multiple": "1.10",
                },
                decision=report.strategy_decision,
                risk_result=report.risk_decision,
                orders=tuple(
                    item for item in (report.entry_order, report.exit_order) if item
                ),
                fills=tuple(
                    cast(dict[str, Any], fill_payload)
                    for fill_payload in (
                        report.entry_order.get("actual_fill"),
                        report.exit_order.get("actual_fill"),
                    )
                    if isinstance(fill_payload, dict)
                ),
                fees=(
                    _decimal_or_zero(report.fees.get("actual_entry_fee"))
                    + _decimal_or_zero(report.fees.get("actual_exit_fee"))
                ),
                position_outcome=report.position_state,
                reconciliation_result=report.reconciliation,
                errors=report.errors,
                stop_reason=report.stop_reason,
                evidence_references=report.evidence_references,
            )
        )
        _persist_execution_evidence(database.connection, report)
        return report


async def _select_market_and_decide(
    market_port: RoundTripMarketPort,
    strategy: Btc15mFavoriteTakeProfitStrategy,
    *,
    config: TinyLiveRoundTripConfig,
    clock: Clock,
) -> tuple[MarketDetails, tuple[MarketOrderBookSnapshot, ...], FavoriteDecision]:
    markets = await market_port.search_markets("Bitcoin Up or Down 15m", page_size=40)
    discovery_checked_at = _aware_datetime(clock())
    candidates = [
        market
        for market in markets
        if _is_candidate(market, config=config, now=discovery_checked_at)
    ]
    candidates.sort(key=lambda market: market.end_date or datetime.max.replace(tzinfo=UTC))
    if not candidates:
        raise TinyLiveRoundTripError("no active BTC Up/Down 15m market")
    first_rejection: (
        tuple[MarketDetails, tuple[MarketOrderBookSnapshot, ...], FavoriteDecision]
        | None
    ) = None
    for summary in candidates:
        if summary.slug is None:
            continue
        market = await market_port.get_market_by_slug(summary.slug)
        market_checked_at = _aware_datetime(clock())
        try:
            _assert_market_ready(market, config=config, now=market_checked_at)
        except TinyLiveRoundTripError as error:
            candidate = (
                market,
                (),
                strategy.no_trade_decision(
                    market,
                    now=market_checked_at,
                    reason=str(error),
                ),
            )
            first_rejection = first_rejection or candidate
            continue
        token_ids = tuple(
            outcome.token_id
            for outcome in market.outcomes
            if outcome.token_id is not None
        )
        if len(token_ids) != 2 or len(set(token_ids)) != 2:
            candidate = (
                market,
                (),
                strategy.no_trade_decision(
                    market,
                    now=market_checked_at,
                    reason="two distinct token ids are required",
                ),
            )
            first_rejection = first_rejection or candidate
            continue
        books = tuple(
            [await market_port.get_order_book(token_id) for token_id in token_ids]
        )
        decision = strategy.decide(
            market,
            books,
            now=_aware_datetime(clock()),
        )
        if decision.status == "TRADE":
            return market, books, decision
        first_rejection = first_rejection or (market, books, decision)
    if first_rejection is not None:
        return first_rejection
    raise TinyLiveRoundTripError("no readable BTC Up/Down 15m market candidate")


async def _refresh_selected_market_and_decide(
    market_port: RoundTripMarketPort,
    strategy: Btc15mFavoriteTakeProfitStrategy,
    *,
    market: MarketDetails,
    original_books: tuple[MarketOrderBookSnapshot, ...],
    config: TinyLiveRoundTripConfig,
    now: datetime,
) -> tuple[MarketDetails, tuple[MarketOrderBookSnapshot, ...], FavoriteDecision]:
    if market.slug is None:
        raise TinyLiveRoundTripError("selected market slug became unreadable")
    refreshed = await market_port.get_market_by_slug(market.slug)
    if refreshed.id != market.id or refreshed.condition_id != market.condition_id:
        raise TinyLiveRoundTripError("selected market identity changed during preflight")
    _assert_market_ready(refreshed, config=config, now=now)
    token_ids = tuple(
        outcome.token_id for outcome in refreshed.outcomes if outcome.token_id is not None
    )
    original_token_ids = {book.token_id for book in original_books}
    if len(token_ids) != 2 or set(token_ids) != original_token_ids:
        raise TinyLiveRoundTripError("selected market outcome mapping changed during preflight")
    books = tuple([await market_port.get_order_book(token_id) for token_id in token_ids])
    return refreshed, books, strategy.decide(refreshed, books, now=now)


def _is_candidate(
    market: MarketSummary,
    *,
    config: TinyLiveRoundTripConfig,
    now: datetime,
) -> bool:
    if market.slug is None or not market.slug.startswith("btc-updown-15m-"):
        return False
    if market.active is not True or market.closed is not False:
        return False
    if market.accepting_orders is not True or market.end_date is None:
        return False
    end = (
        market.end_date
        if market.end_date.tzinfo is not None
        else market.end_date.replace(tzinfo=UTC)
    )
    return end > now + timedelta(seconds=config.minimum_remaining_seconds)


def _assert_market_ready(
    market: MarketDetails,
    *,
    config: TinyLiveRoundTripConfig,
    now: datetime,
) -> None:
    if not market.slug or not market.slug.startswith("btc-updown-15m-"):
        raise TinyLiveRoundTripError("market is not BTC Up/Down 15m")
    if market.active is not True or market.closed is not False:
        raise TinyLiveRoundTripError("market is not active and open")
    if market.accepting_orders is not True or market.enable_order_book is not True:
        raise TinyLiveRoundTripError("market is paused or order-book trading is disabled")
    if market.archived is True:
        raise TinyLiveRoundTripError("market is archived")
    if market.condition_id is None or len(market.outcomes) != 2:
        raise TinyLiveRoundTripError("market condition or outcomes are incomplete")
    if market.end_date is None:
        raise TinyLiveRoundTripError("market end time is unreadable")
    end = (
        market.end_date
        if market.end_date.tzinfo is not None
        else market.end_date.replace(tzinfo=UTC)
    )
    if end <= now + timedelta(seconds=config.minimum_remaining_seconds):
        raise TinyLiveRoundTripError("market has insufficient remaining time")
    if market.fee_schedule is None:
        raise TinyLiveRoundTripError("market fee applicability is unreadable")


async def _read_account_preflight(
    adapter: RoundTripExecutionPort,
    *,
    token_ids: tuple[str, ...],
    checked_at: datetime,
) -> tuple[AccountPreflight, list[Any], list[Any]]:
    identity = _safe_identity(adapter.identity())
    collateral = _mapping(await adapter.get_balance_allowance(asset_type="COLLATERAL"))
    balance = _base_units_to_decimal(collateral.get("balance"))
    allowance_values = collateral.get("allowances")
    if not isinstance(allowance_values, dict) or not allowance_values:
        raise TinyLiveRoundTripError("collateral allowances are unreadable")
    allowance = min(_base_units_to_decimal(value) for value in allowance_values.values())
    open_orders = await adapter.get_open_orders()
    positions = await adapter.list_positions(size_threshold=0)
    outcome_token_state: dict[str, dict[str, str]] = {}
    for token_id in token_ids:
        conditional = _mapping(
            await adapter.get_balance_allowance(
                asset_type="CONDITIONAL",
                token_id=token_id,
            )
        )
        token_balance = _base_units_to_decimal(conditional.get("balance"))
        raw_allowances = conditional.get("allowances")
        if not isinstance(raw_allowances, dict) or not raw_allowances:
            raise TinyLiveRoundTripError("outcome-token allowances are unreadable")
        token_allowance = min(
            _base_units_to_decimal(value) for value in raw_allowances.values()
        )
        outcome_token_state[token_id] = {
            "allowance": str(token_allowance),
            "balance": str(token_balance),
        }
    reserved = sum((_reserved_notional(order) for order in open_orders), Decimal("0"))
    available = balance - reserved
    return (
        AccountPreflight(
            identity=identity,
            balance=balance,
            reserved_balance=reserved,
            available_balance=available,
            allowance=allowance,
            open_order_count=len(open_orders),
            position_count=len(
                [position for position in positions if _position_size(position) > 0]
            ),
            outcome_token_state=outcome_token_state,
            checked_at=checked_at,
        ),
        open_orders,
        positions,
    )


def _assert_account_funded(
    account: AccountPreflight,
    *,
    selected_token_id: str | None,
    expected_exit_size: Decimal | None,
) -> None:
    if account.balance <= 0 or account.allowance < MAXIMUM_ENTRY_NOTIONAL:
        raise TinyLiveRoundTripError("collateral balance or allowance is insufficient")
    if account.available_balance < MAXIMUM_ENTRY_NOTIONAL:
        raise TinyLiveRoundTripError(
            "available collateral after reservations is insufficient"
        )
    if selected_token_id is None or expected_exit_size is None:
        return
    selected = account.outcome_token_state.get(selected_token_id)
    if selected is None:
        raise TinyLiveRoundTripError("selected outcome-token state is unreadable")
    if _decimal(selected.get("allowance")) < expected_exit_size:
        raise TinyLiveRoundTripError(
            "selected outcome-token allowance cannot support the planned exit"
        )


def _assert_identity(identity: dict[str, object]) -> None:
    if identity.get("signer_configured") is not True:
        raise TinyLiveRoundTripError("signer identity is not configured")
    if identity.get("funder_configured") is not True:
        raise TinyLiveRoundTripError("funder identity is not configured")
    if identity.get("active_wallet_source") != "funder":
        raise TinyLiveRoundTripError("configured funder is not the active SDK wallet source")
    if identity.get("wallet_type") not in {
        "DEPOSIT_WALLET",
        "EOA",
        "GNOSIS_SAFE",
        "POLY_PROXY",
    }:
        raise TinyLiveRoundTripError("SDK wallet type is unreadable or unsupported")
    if identity.get("sdk_signature_type") is None:
        raise TinyLiveRoundTripError("SDK wallet signature type is unreadable")
    if identity.get("configured_signature_type") is None:
        raise TinyLiveRoundTripError("configured signature type is unreadable")
    if identity.get("signature_type_matches_sdk") is not True:
        raise TinyLiveRoundTripError("configured signature type does not match SDK wallet type")


def _assert_geoblock(status: GeoblockStatus) -> None:
    if status.status == "allowed" and status.blocked is False:
        return
    if status.status == "blocked" or status.blocked is True:
        raise TinyLiveRoundTripError("official Polymarket geoblock denied trading")
    raise TinyLiveRoundTripError("official Polymarket geoblock was unreadable")


def _assert_runtime_settings(config: TinyLiveRoundTripConfig, kill_switch: KillSwitch) -> None:
    if kill_switch.is_active():
        raise TinyLiveRoundTripError(f"kill switch is active: {kill_switch.reason or 'unknown'}")
    if config.dry_run:
        return
    if config.settings.trading_mode != TradingMode.LIVE:
        raise TinyLiveRoundTripError("real run requires TRADING_MODE=LIVE")
    if not config.settings.live_trading_enabled:
        raise TinyLiveRoundTripError("real run requires LIVE_TRADING_ENABLED=true")
    if not config.acknowledgement:
        raise TinyLiveRoundTripError("real run requires POLYSIA-LIVE-001 acknowledgement")
    if config.settings.polymarket_private_key is None:
        raise TinyLiveRoundTripError("real run requires configured test signer")
    if not config.settings.polymarket_funder_address:
        raise TinyLiveRoundTripError("real run requires configured test funder")


def _assert_git_and_ci(
    config: TinyLiveRoundTripConfig,
    *,
    git_commit: str | None,
    git_reader: GitReader | None,
) -> None:
    if config.dry_run:
        return
    branch = _git_value(config.project_root, ("git", "branch", "--show-current"), git_reader)
    remote = _git_value(config.project_root, ("git", "rev-parse", "origin/main"), git_reader)
    tracked = _git_value(
        config.project_root,
        ("git", "status", "--porcelain", "--untracked-files=no"),
        git_reader,
    )
    if branch != "main" or git_commit is None or git_commit != remote:
        raise TinyLiveRoundTripError("repository is not synchronized main")
    if tracked:
        raise TinyLiveRoundTripError("tracked working tree is not clean")
    if config.verified_ci_commit is None or config.verified_ci_commit != git_commit:
        raise TinyLiveRoundTripError("green CI evidence does not match current main")


def _assert_sdk_compatible() -> None:
    installed = distribution_version("polymarket-client")
    if installed != APPROVED_SDK_VERSION:
        raise TinyLiveRoundTripError(
            f"approved polymarket-client {APPROVED_SDK_VERSION} required; found {installed}"
        )


def normalize_exit_target(fill_price: Decimal, *, tick_size: Decimal) -> Decimal | None:
    if fill_price <= 0 or tick_size <= 0:
        return None
    raw = fill_price * Decimal("1.10")
    ticks = (raw / tick_size).to_integral_value(rounding=ROUND_CEILING)
    normalized = ticks * tick_size
    maximum = Decimal("1") - tick_size
    if normalized > maximum or normalized <= fill_price:
        return None
    return normalized


async def _wait_for_confirmed_entry(
    adapter: RoundTripExecutionPort,
    *,
    token_id: str,
    order_id: str,
    market_fee: MarketDetails,
    attempts: int,
    interval_seconds: float,
    sleeper: Sleeper,
    clock: Clock,
) -> FilledEntry | None:
    for attempt in range(attempts):
        trades = await adapter.list_account_trades(token_id=token_id)
        matching = [trade for trade in trades if _trade_matches_order(trade, order_id)]
        confirmed = [
            trade
            for trade in matching
            if str(_read(trade, "status") or "").upper() == "CONFIRMED"
        ]
        failed = [
            trade
            for trade in matching
            if str(_read(trade, "status") or "").upper() == "FAILED"
        ]
        if failed:
            raise TinyLiveRoundTripError("entry trade reached terminal FAILED state")
        if confirmed:
            total_size = sum((_decimal(_read(trade, "size")) for trade in confirmed), Decimal("0"))
            if total_size <= 0:
                raise TinyLiveRoundTripError("confirmed entry trade has no size")
            notional = sum(
                _decimal(_read(trade, "size")) * _decimal(_read(trade, "price"))
                for trade in confirmed
            )
            average = notional / total_size
            fee = Btc15mFavoriteTakeProfitStrategy.expected_fee(
                market_fee,
                price=average,
                size=total_size,
            )
            return FilledEntry(
                order_id=order_id,
                size=total_size,
                weighted_average_price=average,
                fee=fee,
                trade_count=len(confirmed),
                confirmed_at=clock(),
                fee_rate_bps=tuple(
                    str(value)
                    for trade in confirmed
                    if (value := _read(trade, "fee_rate_bps")) is not None
                ),
            )
        if attempt + 1 < attempts:
            await sleeper(interval_seconds)
    return None


async def _reconciled_position_size(
    adapter: RoundTripExecutionPort,
    *,
    market: MarketDetails,
    token_id: str,
    expected_size: Decimal,
) -> tuple[Decimal, list[Any]]:
    positions = await adapter.list_positions(
        market=(market.condition_id,) if market.condition_id else None,
        size_threshold=0,
    )
    matching = [position for position in positions if str(_read(position, "token_id")) == token_id]
    if len(matching) != 1:
        raise TinyLiveRoundTripError("filled position cannot be identified uniquely")
    available = _position_size(matching[0])
    conditional = _mapping(
        await adapter.get_balance_allowance(asset_type="CONDITIONAL", token_id=token_id)
    )
    conditional_balance = _base_units_to_decimal(conditional.get("balance"))
    allowances = conditional.get("allowances")
    if not isinstance(allowances, dict) or not allowances:
        raise TinyLiveRoundTripError("conditional-token allowance is unreadable")
    conditional_allowance = min(_base_units_to_decimal(value) for value in allowances.values())
    if available <= 0 or conditional_balance < available or conditional_allowance < available:
        raise TinyLiveRoundTripError("conditional balance/allowance cannot support the exit")
    tolerance = Decimal("0.000001")
    if abs(available - expected_size) > tolerance:
        raise TinyLiveRoundTripError("confirmed fill and external position do not reconcile")
    return available, positions


async def _classify_and_reconcile_exit(
    adapter: RoundTripExecutionPort,
    *,
    market: MarketDetails,
    token_id: str,
    exit_order_id: str,
    expected_position: Decimal,
    clock: Clock,
    kill_switch: KillSwitch,
) -> tuple[RoundTripResult, ReconciliationResult, FilledExit | None, Decimal]:
    open_orders = await adapter.get_open_orders(token_id=token_id)
    positions = await adapter.list_positions(
        market=(market.condition_id,) if market.condition_id else None,
        size_threshold=0,
    )
    trades = await adapter.list_account_trades(token_id=token_id, market=market.condition_id)
    confirmed_exit_trades = [
        trade
        for trade in trades
        if _trade_matches_order(trade, exit_order_id)
        and str(_read(trade, "status") or "").upper() == "CONFIRMED"
    ]
    checked_at = clock()
    exit_fill = _summarize_exit_fill(
        confirmed_exit_trades,
        order_id=exit_order_id,
        market=market,
        confirmed_at=checked_at,
    )
    exit_open = any(str(_read(order, "id")) == exit_order_id for order in open_orders)
    actual_position = _position_for_token(positions, token_id)
    confirmed_size = exit_fill.size if exit_fill is not None else Decimal("0")
    expected_remaining = expected_position - confirmed_size
    tolerance = Decimal("0.000001")
    overfilled = expected_remaining < -tolerance
    normalized_remaining = max(Decimal("0"), expected_remaining)
    position_matches = abs(actual_position - normalized_remaining) <= tolerance
    fully_closed = (
        exit_fill is not None
        and not overfilled
        and normalized_remaining == 0
        and abs(actual_position) <= tolerance
    )
    if fully_closed:
        internal = InternalExpectedState(
            last_successful_account_read_at=checked_at,
            updated_at=checked_at,
        )
        result: RoundTripResult = "COMPLETED_ROUND_TRIP"
    elif exit_open and not overfilled and position_matches:
        internal = InternalExpectedState(
            last_successful_account_read_at=checked_at,
            open_orders=(
                OrderSnapshot(
                    order_id=exit_order_id,
                    status="OPEN",
                    token_id=token_id,
                    updated_at=checked_at,
                ),
            ),
            positions=(
                PositionSnapshot(
                    token_id=token_id,
                    size=normalized_remaining,
                    updated_at=checked_at,
                ),
            )
            if normalized_remaining > 0
            else (),
            updated_at=checked_at,
        )
        result = "ENTRY_FILLED_EXIT_OPEN"
    else:
        expected_internal_size = (
            expected_position if overfilled else normalized_remaining
        )
        internal = InternalExpectedState(
            last_successful_account_read_at=checked_at,
            open_orders=(
                OrderSnapshot(
                    order_id=exit_order_id,
                    status="OPEN",
                    token_id=token_id,
                    updated_at=checked_at,
                ),
            )
            if expected_internal_size > 0
            else (),
            positions=(
                PositionSnapshot(
                    token_id=token_id,
                    size=expected_internal_size,
                    updated_at=checked_at,
                ),
            )
            if expected_internal_size > 0
            else (),
            updated_at=checked_at,
        )
        result = "SAFETY_STOP"
    actual = ActualAccountState(
        account_readable=True,
        open_orders=tuple(_order_snapshot(order, checked_at) for order in open_orders),
        open_orders_readable=True,
        positions=tuple(_position_snapshot(position, checked_at) for position in positions),
        positions_readable=True,
        read_at=checked_at,
    )
    reconciliation = ReconciliationManager(
        safety_pause=KillSwitchSafetyPause(kill_switch)
    ).reconcile(
        ReconciliationInput(
            actual=actual,
            checked_at=checked_at,
            internal=internal,
            live_mode=True,
        )
    )
    return result, reconciliation, exit_fill, actual_position


async def _reconcile_without_entry(
    adapter: RoundTripExecutionPort,
    *,
    market: MarketDetails,
    token_ids: tuple[str, ...],
    clock: Clock,
    kill_switch: KillSwitch,
) -> ReconciliationResult:
    open_orders: list[Any] = []
    for token_id in token_ids:
        open_orders.extend(await adapter.get_open_orders(token_id=token_id))
    positions = await adapter.list_positions(
        market=(market.condition_id,) if market.condition_id else None,
        size_threshold=0,
    )
    selected_positions = [
        position
        for position in positions
        if str(_read(position, "token_id") or "") in set(token_ids)
        and _position_size(position) != 0
    ]
    return _reconcile_snapshots(
        open_orders=open_orders,
        positions=selected_positions,
        internal_orders=(),
        internal_positions=(),
        clock=clock,
        kill_switch=kill_switch,
    )


async def _reconcile_position_without_exit(
    adapter: RoundTripExecutionPort,
    *,
    market: MarketDetails,
    token_id: str,
    expected_position: Decimal,
    clock: Clock,
    kill_switch: KillSwitch,
) -> ReconciliationResult:
    open_orders = await adapter.get_open_orders(token_id=token_id)
    positions = await adapter.list_positions(
        market=(market.condition_id,) if market.condition_id else None,
        size_threshold=0,
    )
    selected_positions = [
        position
        for position in positions
        if str(_read(position, "token_id") or "") == token_id
        and _position_size(position) != 0
    ]
    checked_at = clock()
    return _reconcile_snapshots(
        open_orders=open_orders,
        positions=selected_positions,
        internal_orders=(),
        internal_positions=(
            PositionSnapshot(
                token_id=token_id,
                size=expected_position,
                updated_at=checked_at,
            ),
        ),
        clock=lambda: checked_at,
        kill_switch=kill_switch,
    )


def _reconcile_snapshots(
    *,
    open_orders: list[Any],
    positions: list[Any],
    internal_orders: tuple[OrderSnapshot, ...],
    internal_positions: tuple[PositionSnapshot, ...],
    clock: Clock,
    kill_switch: KillSwitch,
) -> ReconciliationResult:
    checked_at = clock()
    return ReconciliationManager(
        safety_pause=KillSwitchSafetyPause(kill_switch)
    ).reconcile(
        ReconciliationInput(
            actual=ActualAccountState(
                account_readable=True,
                open_orders=tuple(
                    _order_snapshot(order, checked_at) for order in open_orders
                ),
                open_orders_readable=True,
                positions=tuple(
                    _position_snapshot(position, checked_at) for position in positions
                ),
                positions_readable=True,
                read_at=checked_at,
            ),
            checked_at=checked_at,
            internal=InternalExpectedState(
                last_successful_account_read_at=checked_at,
                open_orders=internal_orders,
                positions=internal_positions,
                updated_at=checked_at,
            ),
            live_mode=True,
        )
    )


def _persist_execution_evidence(connection: Any, report: TinyLiveRoundTripReport) -> None:
    token_id = str(report.strategy_decision.get("selected_token_id") or "unknown")
    _persist_entry_order_state(
        connection,
        entry_order=report.entry_order,
        token_id=token_id,
        timestamp=report.generated_at,
    )
    entry_fill = report.entry_order.get("actual_fill")
    if isinstance(entry_fill, dict) and report.entry_order.get("order_id"):
        _persist_fill_state(
            connection,
            run_id=report.run_id,
            side="BUY",
            token_id=token_id,
            fill=entry_fill,
            order_id=str(report.entry_order["order_id"]),
            timestamp=report.generated_at,
        )
    _persist_exit_order_state(
        connection,
        exit_order=report.exit_order,
        token_id=token_id,
        timestamp=report.generated_at,
    )
    exit_fill = report.exit_order.get("actual_fill")
    if isinstance(exit_fill, dict) and report.exit_order.get("order_id"):
        _persist_fill_state(
            connection,
            run_id=report.run_id,
            side="SELL",
            token_id=token_id,
            fill=exit_fill,
            order_id=str(report.exit_order["order_id"]),
            timestamp=report.generated_at,
        )
    average_entry_price = _decimal_or_zero(
        cast(dict[str, object], report.entry_order.get("actual_fill") or {}).get(
            "weighted_average_price"
        )
    )
    _persist_position_state(
        connection,
        market_id=str(report.market_snapshot.get("market_id") or "") or None,
        position_state=report.position_state,
        average_entry_price=average_entry_price,
        timestamp=report.generated_at,
    )
    _persist_ledger_entries(
        connection,
        run_id=report.run_id,
        entries=report.ledger_entries,
    )


def _persist_entry_order_state(
    connection: Any,
    *,
    entry_order: dict[str, object],
    token_id: str,
    timestamp: datetime,
) -> None:
    if entry_order.get("attempted") is not True or not entry_order.get("order_id"):
        return
    OrderRepository(connection).upsert(
        order_id=str(entry_order["order_id"]),
        broker="polymarket-live",
        strategy_id=STRATEGY_ID,
        token_id=token_id,
        side="BUY",
        price=_decimal_or_zero(entry_order.get("requested_price")),
        size=_decimal_or_zero(entry_order.get("requested_size")),
        status=str(entry_order.get("status") or "UNKNOWN"),
        payload=entry_order,
        timestamp=timestamp,
    )


def _persist_exit_order_state(
    connection: Any,
    *,
    exit_order: dict[str, object],
    token_id: str,
    timestamp: datetime,
) -> None:
    if exit_order.get("attempted") is not True or not exit_order.get("order_id"):
        return
    OrderRepository(connection).upsert(
        order_id=str(exit_order["order_id"]),
        broker="polymarket-live",
        strategy_id=STRATEGY_ID,
        token_id=token_id,
        side="SELL",
        price=_decimal_or_zero(exit_order.get("normalized_target")),
        size=_decimal_or_zero(exit_order.get("sell_quantity")),
        status=str(exit_order.get("status") or "UNKNOWN"),
        payload=exit_order,
        timestamp=timestamp,
    )


def _persist_fill_state(
    connection: Any,
    *,
    run_id: str,
    side: OrderSide,
    token_id: str,
    fill: dict[str, object],
    order_id: str,
    timestamp: datetime,
) -> None:
    phase = "entry" if side == "BUY" else "exit"
    fill_id = f"{run_id}:{phase}"
    repository = FillRepository(connection)
    if repository.get(fill_id) is not None:
        return
    repository.add(
        fill_id=fill_id,
        order_id=order_id,
        token_id=token_id,
        side=side,
        price=_decimal_or_zero(fill.get("weighted_average_price")),
        size=_decimal_or_zero(fill.get("size")),
        fee=_decimal_or_zero(fill.get("fee")),
        liquidity_role="TAKER" if side == "BUY" else None,
        payload=fill,
        created_at=timestamp,
    )


def _persist_position_state(
    connection: Any,
    *,
    market_id: str | None,
    position_state: dict[str, object],
    average_entry_price: Decimal,
    timestamp: datetime,
) -> None:
    if not position_state.get("token_id"):
        return
    PositionRepository(connection).upsert(
        token_id=str(position_state["token_id"]),
        market_id=market_id,
        size=_decimal_or_zero(position_state.get("available_size")),
        avg_price=average_entry_price,
        realized_pnl=_decimal_or_zero(position_state.get("realized_pnl")),
        payload=position_state,
        updated_at=timestamp,
    )


def _persist_ledger_entries(
    connection: Any,
    *,
    run_id: str,
    entries: tuple[dict[str, object], ...] | list[dict[str, object]],
) -> None:
    repository = LedgerEventRepository(connection)
    existing = {event.event_id for event in repository.list_for_run(run_id)}
    for item in entries:
        event_id = str(item["event_id"])
        if event_id in existing:
            continue
        repository.add(
            run_id=run_id,
            event=LedgerEvent(
                event_id=event_id,
                event_type=str(item["event_type"]),
                instrument_id=_safe(item.get("instrument_id")),
                amount=_decimal(item["amount"]),
                currency=str(item["currency"]),
                occurred_at=datetime.fromisoformat(str(item["occurred_at"])),
                order_id=_safe(item.get("order_id")),
                fill_id=_safe(item.get("fill_id")),
            ),
            payload=item,
        )
        existing.add(event_id)


def _entry_ledger_entries(
    *,
    run_id: str,
    token_id: str,
    fill: FilledEntry,
) -> tuple[dict[str, object], ...]:
    fill_id = f"{run_id}:entry"
    common = {
        "fill_id": fill_id,
        "instrument_id": token_id,
        "occurred_at": fill.confirmed_at.isoformat(),
        "order_id": fill.order_id,
    }
    return (
        {
            **common,
            "amount": str(fill.size),
            "currency": "shares",
            "event_id": f"{run_id}:entry:position",
            "event_type": "LIVE_ENTRY_POSITION_INCREASE",
        },
        {
            **common,
            "amount": str(
                -((fill.weighted_average_price * fill.size) + fill.fee)
            ),
            "currency": "collateral",
            "event_id": f"{run_id}:entry:collateral",
            "event_type": "LIVE_ENTRY_COLLATERAL_DECREASE",
        },
    )


def _exit_ledger_entries(
    *,
    run_id: str,
    token_id: str,
    fill: FilledExit,
) -> tuple[dict[str, object], ...]:
    fill_id = f"{run_id}:exit"
    common = {
        "fill_id": fill_id,
        "instrument_id": token_id,
        "occurred_at": fill.confirmed_at.isoformat(),
        "order_id": fill.order_id,
    }
    return (
        {
            **common,
            "amount": str(-fill.size),
            "currency": "shares",
            "event_id": f"{run_id}:exit:position",
            "event_type": "LIVE_EXIT_POSITION_DECREASE",
        },
        {
            **common,
            "amount": str(
                (fill.weighted_average_price * fill.size) - fill.fee
            ),
            "currency": "collateral",
            "event_id": f"{run_id}:exit:collateral",
            "event_type": "LIVE_EXIT_COLLATERAL_INCREASE",
        },
    )


def _summarize_exit_fill(
    trades: list[Any],
    *,
    order_id: str,
    market: MarketDetails,
    confirmed_at: datetime,
) -> FilledExit | None:
    if not trades:
        return None
    total_size = sum((_decimal(_read(trade, "size")) for trade in trades), Decimal("0"))
    if total_size <= 0:
        raise TinyLiveRoundTripError("confirmed exit trade has no size")
    notional = sum(
        _decimal(_read(trade, "size")) * _decimal(_read(trade, "price"))
        for trade in trades
    )
    average = notional / total_size
    fee = Btc15mFavoriteTakeProfitStrategy.expected_fee(
        market,
        price=average,
        size=total_size,
    )
    return FilledExit(
        order_id=order_id,
        size=total_size,
        weighted_average_price=average,
        fee=fee,
        trade_count=len(trades),
        confirmed_at=confirmed_at,
        fee_rate_bps=tuple(
            str(value)
            for trade in trades
            if (value := _read(trade, "fee_rate_bps")) is not None
        ),
    )


def _market_snapshot(
    market: MarketDetails | None,
    books: tuple[MarketOrderBookSnapshot, ...],
    geoblock: dict[str, object],
    *,
    as_of: datetime,
) -> dict[str, object]:
    if market is None:
        return {"geoblock": geoblock}
    return {
        "accepting_orders": market.accepting_orders,
        "active": market.active,
        "closed": market.closed,
        "end_date": market.end_date.isoformat() if market.end_date else None,
        "start_date": market.start_date.isoformat() if market.start_date else None,
        "remaining_seconds": _remaining_seconds(market.end_date, as_of),
        "fee_schedule": (
            market.fee_schedule.model_dump(mode="json") if market.fee_schedule else None
        ),
        "geoblock": geoblock,
        "market_id": market.id,
        "liquidity": str(market.liquidity) if market.liquidity is not None else None,
        "order_book_enabled": market.enable_order_book,
        "order_books": [
            {
                "best_ask": str(book.best_ask.price) if book.best_ask else None,
                "best_ask_size": str(book.best_ask.size) if book.best_ask else None,
                "best_bid": str(book.best_bid.price) if book.best_bid else None,
                "minimum_order_size": str(book.minimum_order_size),
                "spread": str(book.spread) if book.spread is not None else None,
                "tick_size": str(book.tick_size),
                "timestamp": book.timestamp.isoformat(),
                "token_id": book.token_id,
            }
            for book in books
        ],
        "question": market.question,
        "slug": market.slug,
    }


def _fee_evidence(market: MarketDetails, *, expected_fee: Decimal) -> dict[str, object]:
    schedule = market.fee_schedule
    return {
        "enabled": schedule.enabled if schedule else None,
        "expected_entry_fee": str(expected_fee),
        "exponent": str(schedule.exponent) if schedule and schedule.exponent is not None else None,
        "rate": str(schedule.rate) if schedule and schedule.rate is not None else None,
        "source": "market feeSchedule",
        "taker_only": schedule.taker_only if schedule else None,
    }


def _remaining_seconds(end_date: datetime | None, as_of: datetime) -> int | None:
    if end_date is None:
        return None
    normalized_end = (
        end_date if end_date.tzinfo is not None else end_date.replace(tzinfo=UTC)
    )
    normalized_as_of = as_of if as_of.tzinfo is not None else as_of.replace(tzinfo=UTC)
    return max(0, int((normalized_end - normalized_as_of).total_seconds()))


def _aware_datetime(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _data_age_ms(timestamp: datetime, now: datetime) -> int:
    normalized_timestamp = _aware_datetime(timestamp)
    return max(0, int((now - normalized_timestamp).total_seconds() * 1000))


def _safe_order_response(response: Any, *, attempted: bool) -> dict[str, object]:
    payload = _mapping(response)
    accepted = payload.get("ok", True) is True
    return {
        "accepted": accepted,
        "attempted": attempted,
        "making_amount": _safe(payload.get("making_amount")),
        "order_id": _safe(payload.get("order_id")),
        "rejection_code": _safe(payload.get("code")),
        "rejection_reason": _safe(payload.get("message")),
        "status": _safe(payload.get("status")) or ("ACCEPTED" if accepted else "REJECTED"),
        "taking_amount": _safe(payload.get("taking_amount")),
        "trade_count": len(payload.get("trade_ids", ()))
        if isinstance(payload.get("trade_ids"), (list, tuple))
        else 0,
    }


def _required_order_id(response: Any) -> str:
    value = _mapping(response).get("order_id")
    if value is None or not str(value):
        raise TinyLiveRoundTripError("accepted order response has no order id")
    return str(value)


def _trade_matches_order(trade: Any, order_id: str) -> bool:
    if str(_read(trade, "taker_order_id") or "") == order_id:
        return True
    for maker in _read(trade, "maker_orders") or ():
        if str(_read(maker, "order_id") or "") == order_id:
            return True
    return False


def _conflicting_orders(
    orders: list[Any],
    market: MarketDetails,
    books: tuple[MarketOrderBookSnapshot, ...],
) -> list[Any]:
    token_ids = {book.token_id for book in books}
    return [
        order
        for order in orders
        if str(_read(order, "market") or "") == str(market.condition_id or "")
        or str(_read(order, "token_id") or "") in token_ids
    ]


def _conflicting_positions(
    positions: list[Any],
    market: MarketDetails,
    books: tuple[MarketOrderBookSnapshot, ...],
) -> list[Any]:
    token_ids = {book.token_id for book in books}
    return [
        position
        for position in positions
        if _position_size(position) > 0
        and (
            str(_read(position, "condition_id") or "") == str(market.condition_id or "")
            or str(_read(position, "token_id") or "") in token_ids
        )
    ]


def _position_total(positions: list[Any]) -> Decimal:
    return sum((_position_size(position) for position in positions), Decimal("0"))


def _position_for_token(positions: list[Any], token_id: str) -> Decimal:
    return sum(
        (
            _position_size(position)
            for position in positions
            if str(_read(position, "token_id")) == token_id
        ),
        Decimal("0"),
    )


def _position_size(position: Any) -> Decimal:
    return _decimal(_read(position, "size"))


def _reserved_notional(order: Any) -> Decimal:
    side = str(_read(order, "side") or "").upper()
    if side == "SELL":
        return Decimal("0")
    if side != "BUY":
        raise TinyLiveRoundTripError("open-order side is unreadable")
    original = _decimal(_read(order, "original_size"))
    matched = _decimal(_read(order, "size_matched"))
    price = _decimal(_read(order, "price"))
    return max(Decimal("0"), original - matched) * price


def _safe_identity(identity: Any) -> dict[str, object]:
    payload = _mapping(identity)
    allowed = {
        "active_wallet_source",
        "configured_signature_type",
        "funder_configured",
        "legacy_wallet_configured",
        "sdk_signature_type",
        "signature_type_matches_sdk",
        "signer_configured",
        "wallet_type",
    }
    return {key: payload.get(key) for key in sorted(allowed)}


def _base_units_to_decimal(value: object) -> Decimal:
    parsed = _decimal(value)
    if parsed < 0:
        raise TinyLiveRoundTripError("balance or allowance cannot be negative")
    return parsed / BASE_UNITS


def _price_is_tick_aligned(price: Decimal, tick_size: Decimal) -> bool:
    return tick_size > 0 and price > 0 and price < 1 and price % tick_size == 0


def _order_snapshot(order: Any, checked_at: datetime) -> OrderSnapshot:
    return OrderSnapshot(
        order_id=str(_read(order, "id") or "unknown-order"),
        status=_safe(_read(order, "status")),
        token_id=_safe(_read(order, "token_id")),
        updated_at=checked_at,
    )


def _position_snapshot(position: Any, checked_at: datetime) -> PositionSnapshot:
    return PositionSnapshot(
        token_id=str(_read(position, "token_id") or "unknown-position"),
        size=_position_size(position),
        updated_at=checked_at,
    )


def _reconciliation_to_dict(result: ReconciliationResult) -> dict[str, object]:
    payload = result.to_dict()
    payload["resolution"] = (
        "states_match" if not result.detected_events else "mismatch_detected"
    )
    return payload


def _risk_to_dict(decision: RiskDecision) -> dict[str, object]:
    return {
        "adjusted_size": str(decision.adjusted_size) if decision.adjusted_size else None,
        "approved": decision.approved,
        "reason": decision.reason,
    }


def _mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return dict(value.model_dump(mode="python"))
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if isinstance(value, dict):
        return dict(value)
    return {
        name: getattr(value, name)
        for name in dir(value)
        if not name.startswith("_") and not callable(getattr(value, name))
    }


def _read(value: Any, name: str) -> Any:
    return _mapping(value).get(name)


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise TinyLiveRoundTripError("external numeric value is unreadable") from error


def _decimal_or_zero(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _safe(value: object) -> str | None:
    return None if value is None else str(value)


def _git_value(
    root: Path,
    command: tuple[str, ...],
    reader: GitReader | None,
) -> str | None:
    try:
        if reader is not None:
            return reader(root.resolve(), command).strip()
        result = subprocess.run(
            list(command),
            check=True,
            capture_output=True,
            cwd=root.resolve(),
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


__all__ = [
    "AUTHORIZATION_ID",
    "AccountPreflight",
    "FilledEntry",
    "RoundTripOrderManager",
    "TinyLiveRoundTripConfig",
    "TinyLiveRoundTripError",
    "TinyLiveRoundTripReport",
    "normalize_exit_target",
    "run_tiny_live_round_trip",
]
