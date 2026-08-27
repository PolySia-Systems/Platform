from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from polysia.application.ports.candidate_intelligence import (
    CandidatePipelineBusyError,
    CandidatePipelineLeaseLostError,
)
from polysia.application.ports.continuous_shadow import (
    ContinuousCandidatePort,
    ContinuousEvaluationRecord,
    ContinuousLedgerRecord,
    ContinuousMarketReadPort,
    ContinuousPollCompletion,
    ContinuousPollOutcome,
    ContinuousPositionMark,
    ContinuousShadowExperiment,
    ContinuousShadowStorePort,
    FollowerAttribution,
)
from polysia.application.ports.copytrading import (
    LeaderReadPurpose,
    LeaderTradeCheckpoint,
    LeaderTradeSourcePort,
)
from polysia.application.ports.dynamic_shadow import (
    DynamicShadowLeasePort,
    LeaderSourceFactory,
    ProtectedShadowCandidate,
)
from polysia.application.services.continuous_shadow_failures import (
    FAILURE_CATEGORY_MARKET_READ_FAILED,
    FAILURE_CATEGORY_SOURCE_UNAVAILABLE,
    FAILURE_CATEGORY_UNEXPECTED,
    FAILURE_STAGE_ACQUIRE_LEASE,
    FAILURE_STAGE_APPLY_EVENTS,
    FAILURE_STAGE_COLLECT_EVENTS,
    FAILURE_STAGE_FAIL_POLL,
    FAILURE_STAGE_INITIALIZE,
    FAILURE_STAGE_LOAD_STATE,
    FAILURE_STAGE_MARKET_READ,
    FAILURE_STAGE_PERSIST,
    FAILURE_STAGE_RELEASE_LEASE,
    FAILURE_STAGE_RENEW_LEASE,
    FAILURE_STAGE_UNEXPECTED,
    classify_continuous_shadow_failure,
)
from polysia.config.structured_logging import get_logger
from polysia.domain.copytrading import LeaderTradeAction, LeaderTradeEvent
from polysia.domain.copytrading.continuous_shadow import (
    FOLLOWER_KIND_SPECS,
    FOLLOWER_KINDS,
    ContinuousEvaluationStatus,
    ContinuousPortfolio,
    ContinuousPortfolioKind,
    ContinuousPosition,
    ContinuousShadowConfig,
    ContinuousShadowLifecycle,
    adverse_price_drift_exceeded,
    calculate_verified_taker_fee,
    follower_accepts_pool,
    mark_freshness,
    quote_is_fresh,
    verified_settlement_prices,
    walk_order_book,
)
from polysia.domain.market import MarketDetails, MarketOrderBookSnapshot
from polysia.domain.wallet_intelligence import CandidatePipelineLease

Clock = Callable[[], datetime]
CONTINUOUS_SHADOW_LEASE_RESOURCE = "continuous-shadow-portfolio-pipeline"
ZERO = Decimal("0")


class ContinuousShadowError(RuntimeError):
    error_code = FAILURE_CATEGORY_UNEXPECTED
    processing_stage = FAILURE_STAGE_UNEXPECTED

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        processing_stage: str | None = None,
    ) -> None:
        super().__init__(message)
        if error_code is not None:
            self.error_code = error_code
        if processing_stage is not None:
            self.processing_stage = processing_stage


def _classified_poll_boundary_error(
    error: BaseException,
    *,
    stage: str,
) -> ContinuousShadowError:
    classified = classify_continuous_shadow_failure(error, stage=stage)
    return ContinuousShadowError(
        "Continuous Shadow poll boundary failed safely; durable state was preserved.",
        error_code=classified.category,
        processing_stage=classified.stage,
    )


@dataclass(slots=True)
class _MutablePosition:
    market_reference: str
    outcome_reference: str
    quantity: Decimal
    cost_basis: Decimal
    entry_fees: Decimal
    mark_price: Decimal | None
    marked_at: datetime | None


@dataclass(slots=True)
class _MutablePortfolio:
    portfolio_id: str
    kind: ContinuousPortfolioKind
    wallet_id: str | None
    initial_cash: Decimal
    cash: Decimal
    realized_pnl: Decimal
    fees: Decimal
    high_water_nav: Decimal
    drawdown: Decimal
    positions: dict[tuple[str, str], _MutablePosition]

    @property
    def exposure(self) -> Decimal:
        return sum((item.cost_basis for item in self.positions.values()), ZERO)


@dataclass(slots=True)
class _MutableAttribution:
    quantity: Decimal
    cost_basis: Decimal
    pool_class: str
    last_event_id: str | None


class ContinuousShadowService:
    """Persistent read-only Stage 4B simulation with no order or account-mutation port."""

    def __init__(
        self,
        store: ContinuousShadowStorePort,
        candidate_port: ContinuousCandidatePort,
        lease_port: DynamicShadowLeasePort,
        source_factory: LeaderSourceFactory,
        market_port: ContinuousMarketReadPort,
        *,
        config: ContinuousShadowConfig | None = None,
        clock: Clock | None = None,
        concurrency: int = 6,
        maximum_pages_per_wallet: int = 40,
    ) -> None:
        if not 1 <= concurrency <= 12:
            raise ValueError("concurrency must be within [1, 12]")
        if not 1 <= maximum_pages_per_wallet <= 100:
            raise ValueError("maximum_pages_per_wallet must be within [1, 100]")
        self._store = store
        self._candidate_port = candidate_port
        self._lease_port = lease_port
        self._source_factory = source_factory
        self._market_port = market_port
        self._config = config or ContinuousShadowConfig()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._concurrency = concurrency
        self._maximum_pages = maximum_pages_per_wallet
        self._store_initialized = False
        self._lease_port_initialized = False

    def start(self, source_id: str) -> ContinuousShadowExperiment:
        self._initialize_store()
        selection_run_id, candidates = self._candidate_port.current_candidates(source_id)
        return self._store.start_experiment(
            source_id=source_id,
            selection_run_id=selection_run_id,
            candidates=candidates,
            config=self._config,
            started_at=self._now(),
        )

    def drain(self, source_id: str) -> ContinuousShadowExperiment:
        self._initialize_store()
        experiment = self._required_experiment(source_id)
        return self._store.transition(
            experiment.experiment_id,
            lifecycle=ContinuousShadowLifecycle.DRAINING,
            transitioned_at=self._now(),
        )

    def finalize(self, source_id: str) -> ContinuousShadowExperiment:
        self._initialize_store()
        experiment = self._required_experiment(source_id)
        return self._store.transition(
            experiment.experiment_id,
            lifecycle=ContinuousShadowLifecycle.FINALIZED,
            transitioned_at=self._now(),
        )

    async def poll(self, source_id: str) -> ContinuousPollOutcome:
        try:
            self._initialize_store()
            self._initialize_lease_port()
        except (CandidatePipelineBusyError, CandidatePipelineLeaseLostError):
            raise
        except Exception as error:
            raise _classified_poll_boundary_error(
                error,
                stage=FAILURE_STAGE_INITIALIZE,
            ) from error
        try:
            lease = self._lease_port.acquire_lease(
                CONTINUOUS_SHADOW_LEASE_RESOURCE,
                owner_id=f"continuous-shadow-{uuid.uuid4().hex}",
                acquired_at=self._now(),
                lease_duration=timedelta(minutes=30),
            )
        except (CandidatePipelineBusyError, CandidatePipelineLeaseLostError):
            raise
        except Exception as error:
            raise _classified_poll_boundary_error(
                error,
                stage=FAILURE_STAGE_ACQUIRE_LEASE,
            ) from error
        try:
            try:
                return await self._poll_locked(source_id, lease=lease)
            except ContinuousShadowError:
                raise
            except Exception as error:
                raise _classified_poll_boundary_error(
                    error,
                    stage=FAILURE_STAGE_LOAD_STATE,
                ) from error
        finally:
            try:
                self._lease_port.release_lease(lease)
            except (CandidatePipelineBusyError, CandidatePipelineLeaseLostError):
                raise
            except Exception as error:
                raise _classified_poll_boundary_error(
                    error,
                    stage=FAILURE_STAGE_RELEASE_LEASE,
                ) from error

    def _initialize_store(self) -> None:
        if self._store_initialized:
            return
        self._store.initialize()
        self._store_initialized = True

    def _initialize_lease_port(self) -> None:
        if self._lease_port_initialized:
            return
        self._lease_port.initialize()
        self._lease_port_initialized = True

    async def _poll_locked(
        self,
        source_id: str,
        *,
        lease: CandidatePipelineLease,
    ) -> ContinuousPollOutcome:
        experiment = self._required_experiment(source_id)
        if experiment.lifecycle is ContinuousShadowLifecycle.FINALIZED:
            raise ContinuousShadowError("Finalized Continuous Shadow cannot accept polls.")
        if experiment.config.to_dict() != self._config.to_dict():
            raise ContinuousShadowError(
                "Continuous Shadow runtime config differs from the versioned experiment."
            )
        selection_run_id, current_candidates = self._candidate_port.current_candidates(source_id)
        retained = self._store.retained_candidates(experiment.experiment_id)
        candidates = _merge_candidates(current_candidates, retained)
        if not candidates:
            raise ContinuousShadowError("Continuous Shadow has no candidates to poll.")
        window_end = self._now().replace(microsecond=0)
        watermark = self._store.watermark(experiment.experiment_id)
        if watermark is None:
            window_start = max(
                experiment.started_at.replace(microsecond=0),
                window_end - timedelta(minutes=self._config.initial_lookback_minutes),
            )
        else:
            window_start = watermark - timedelta(seconds=self._config.overlap_seconds)
        if window_start >= window_end:
            window_start = window_end - timedelta(seconds=1)
        poll_run_id = self._store.start_poll(
            experiment_id=experiment.experiment_id,
            selection_run_id=selection_run_id,
            window_start=window_start,
            window_end=window_end,
            started_at=self._now(),
            candidate_count=len(candidates),
        )
        source: LeaderTradeSourcePort | None = None
        stage = FAILURE_STAGE_COLLECT_EVENTS
        try:
            source = self._source_factory(
                {candidate.wallet_id: candidate.address for candidate in candidates}
            )
            raw_events, source_duplicates = await self._collect_events(
                source,
                candidates,
                window_start=window_start,
                window_end=window_end,
            )
            eligible = tuple(
                event for event in raw_events if event.executed_at >= experiment.started_at
            )
            seen = self._store.seen_event_ids(tuple(event.event_id for event in eligible))
            new_events = tuple(event for event in eligible if event.event_id not in seen)
            duplicate_count = source_duplicates + len(eligible) - len(new_events)
            portfolios = _mutable_portfolios(
                self._store.portfolios(experiment.experiment_id),
                current_candidates=current_candidates,
                wallet_bankroll=self._config.wallet_bankroll,
                follower_bankroll=self._config.follower_bankroll,
            )
            attributions = _mutable_attributions(
                self._store.attributions(experiment.experiment_id)
            )
            market_ids = {
                position.market_reference
                for portfolio in portfolios.values()
                for position in portfolio.positions.values()
            } | {event.market_reference for event in new_events}
            token_ids = {
                position.outcome_reference
                for portfolio in portfolios.values()
                for position in portfolio.positions.values()
            } | {event.outcome_reference for event in new_events}
            stage = FAILURE_STAGE_MARKET_READ
            markets = await self._markets(market_ids)
            books = await self._books(token_ids, markets_by_id=markets)
            evaluated_at = self._now()
            stage = FAILURE_STAGE_APPLY_EVENTS
            ledger, marks, settlement_count, settlement_backlog_count = _apply_settlements(
                portfolios,
                attributions,
                markets,
                evaluated_at=evaluated_at,
            )
            evaluations: list[ContinuousEvaluationRecord] = []
            consumed_by_scope: dict[tuple[str, str], dict[Decimal, Decimal]] = {}
            current_by_wallet = {item.wallet_id: item for item in current_candidates}
            retained_by_wallet = {item.wallet_id: item for item in retained}
            all_by_wallet = {**retained_by_wallet, **current_by_wallet}
            for event in sorted(new_events, key=lambda item: (item.executed_at, item.event_id)):
                candidate = all_by_wallet[event.leader_id]
                pool_class = _pool_class(candidate.pools)
                wallet_portfolio = portfolios[f"wallet:{event.leader_id}"]
                targets = [wallet_portfolio]
                for portfolio in portfolios.values():
                    if portfolio.kind not in FOLLOWER_KINDS or portfolio in targets:
                        continue
                    if event.trade_action is LeaderTradeAction.BUY:
                        if follower_accepts_pool(portfolio.kind, pool_class):
                            targets.append(portfolio)
                    elif any(
                        key[0] == portfolio.portfolio_id
                        and key[1] == event.leader_id
                        and key[2] == event.market_reference
                        and key[3] == event.outcome_reference
                        for key in attributions
                    ) or follower_accepts_pool(portfolio.kind, pool_class):
                        targets.append(portfolio)
                for portfolio in targets:
                    evaluation, entry = self._apply_event(
                        portfolio,
                        event,
                        pool_class=pool_class,
                        lifecycle=experiment.lifecycle,
                        market=markets.get(event.market_reference),
                        book=books.get(event.outcome_reference),
                        attributions=attributions,
                        consumed_by_scope=consumed_by_scope,
                        evaluated_at=evaluated_at,
                    )
                    evaluations.append(evaluation)
                    if entry is not None:
                        ledger.append(entry)
            new_marks = _mark_positions(
                portfolios,
                books,
                evaluated_at=evaluated_at,
                maximum_age_ms=self._config.maximum_quote_age_ms,
            )
            marks.extend(new_marks)
            stage = FAILURE_STAGE_RENEW_LEASE
            self._lease_port.renew_lease(
                lease,
                renewed_at=self._now(),
                lease_duration=timedelta(minutes=30),
            )
            pools_by_wallet = {
                item.wallet_id: item.pools
                for item in _merge_candidates(current_candidates, retained)
            }
            completion = ContinuousPollCompletion(
                events=tuple(
                    (event, pools_by_wallet[event.leader_id]) for event in new_events
                ),
                evaluations=tuple(evaluations),
                portfolios=tuple(_freeze_portfolio(item) for item in portfolios.values()),
                attributions=tuple(
                    FollowerAttribution(
                        wallet_id=key[1],
                        market_reference=key[2],
                        outcome_reference=key[3],
                        quantity=value.quantity,
                        cost_basis=value.cost_basis,
                        portfolio_id=key[0],
                        pool_class=value.pool_class,
                        last_event_id=value.last_event_id,
                    )
                    for key, value in sorted(attributions.items())
                    if value.quantity > ZERO
                ),
                ledger=tuple(ledger),
                marks=tuple(marks),
                raw_event_count=len(raw_events),
                duplicate_count=duplicate_count,
                settlement_count=settlement_count,
                settlement_backlog_count=settlement_backlog_count,
                request_telemetry=_safe_mapping(source, "request_telemetry"),
            )
            stage = FAILURE_STAGE_PERSIST
            return self._store.complete_poll(
                poll_run_id,
                experiment=experiment,
                selection_run_id=selection_run_id,
                current_candidates=current_candidates,
                completion=completion,
                completed_at=self._now(),
            )
        except Exception as error:
            classified = classify_continuous_shadow_failure(error, stage=stage)
            try:
                self._store.fail_poll(
                    poll_run_id,
                    failed_at=self._now(),
                    error_code=classified.persistence_code,
                )
            except Exception as persist_error:
                persist_classified = classify_continuous_shadow_failure(
                    persist_error,
                    stage=FAILURE_STAGE_FAIL_POLL,
                )
                get_logger(__name__).warning(
                    "continuous_shadow_fail_poll_recording_failed",
                    original_failure_category=classified.category,
                    original_failure_stage=classified.stage,
                    persist_failure_category=persist_classified.category,
                    persist_failure_stage=persist_classified.stage,
                )
            raise ContinuousShadowError(
                "Continuous Shadow poll failed safely; durable prior state was kept.",
                error_code=classified.category,
                processing_stage=classified.stage,
            ) from error

    async def _collect_events(
        self,
        source: LeaderTradeSourcePort,
        candidates: tuple[ProtectedShadowCandidate, ...],
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> tuple[tuple[LeaderTradeEvent, ...], int]:
        semaphore = asyncio.Semaphore(self._concurrency)

        async def collect(
            candidate: ProtectedShadowCandidate,
        ) -> tuple[tuple[LeaderTradeEvent, ...], int]:
            events: list[LeaderTradeEvent] = []
            checkpoint: LeaderTradeCheckpoint | None = None
            duplicate_count = 0
            async with semaphore:
                for _ in range(self._maximum_pages):
                    try:
                        page = await source.read_page(
                            candidate.wallet_id,
                            start_at=window_start,
                            end_at=window_end,
                            page_size=500,
                            checkpoint=checkpoint,
                            purpose=LeaderReadPurpose.DISCOVERY,
                        )
                    except ContinuousShadowError:
                        raise
                    except Exception as error:
                        raise ContinuousShadowError(
                            "Leader source was unavailable.",
                            error_code=FAILURE_CATEGORY_SOURCE_UNAVAILABLE,
                            processing_stage=FAILURE_STAGE_COLLECT_EVENTS,
                        ) from error
                    if any(
                        event.leader_id != candidate.wallet_id
                        or event.executed_at < window_start
                        or event.executed_at > window_end
                        for event in page.events
                    ):
                        raise ContinuousShadowError(
                            "Leader source returned evidence outside its requested scope."
                        )
                    events.extend(page.events)
                    duplicate_count += page.duplicate_count
                    checkpoint = page.next_checkpoint
                    if checkpoint is None:
                        unique = {item.event_id: item for item in events}
                        duplicate_count += len(events) - len(unique)
                        return (
                            tuple(
                                sorted(
                                    unique.values(),
                                    key=lambda item: (item.executed_at, item.event_id),
                                )
                            ),
                            duplicate_count,
                        )
            raise ContinuousShadowError("Leader history exceeded the bounded page limit.")

        rows = await asyncio.gather(*(collect(candidate) for candidate in candidates))
        all_events = [event for events, _ in rows for event in events]
        unique = {item.event_id: item for item in all_events}
        duplicates = sum(count for _, count in rows) + len(all_events) - len(unique)
        return (
            tuple(sorted(unique.values(), key=lambda item: (item.executed_at, item.event_id))),
            duplicates,
        )

    async def _markets(self, market_ids: set[str]) -> dict[str, MarketDetails | None]:
        semaphore = asyncio.Semaphore(self._concurrency)

        async def read(market_id: str) -> tuple[str, MarketDetails | None]:
            try:
                async with semaphore:
                    market = await self._market_port.get_market_by_condition_id(market_id)
                if market.condition_id not in {None, market_id}:
                    return market_id, None
                return market_id, market
            except Exception:
                return market_id, None

        try:
            return dict(await asyncio.gather(*(read(value) for value in sorted(market_ids))))
        except ContinuousShadowError:
            raise
        except Exception as error:
            raise ContinuousShadowError(
                "Market metadata was unavailable.",
                error_code=FAILURE_CATEGORY_MARKET_READ_FAILED,
                processing_stage=FAILURE_STAGE_MARKET_READ,
            ) from error

    async def _books(
        self,
        token_ids: set[str],
        *,
        markets_by_id: Mapping[str, MarketDetails | None],
    ) -> dict[str, MarketOrderBookSnapshot | None]:
        closed_tokens: set[str] = set()
        closed_entries: list[tuple[str, str]] = []
        for market in markets_by_id.values():
            if market is None or market.closed is not True:
                continue
            for outcome in market.outcomes:
                if outcome.token_id is None:
                    continue
                closed_tokens.add(outcome.token_id)
                closed_entries.append((outcome.token_id, "MARKET_CLOSED"))
        if closed_entries:
            self._store.remember_terminal_books(
                tuple(closed_entries),
                now=self._now(),
                ttl_seconds=self._config.negative_cache_ttl_seconds,
            )
        cached = self._store.terminal_book_cache(
            tuple(sorted(token_ids)),
            now=self._now(),
        )
        skip = closed_tokens | set(cached)
        pending = {token_id for token_id in token_ids if token_id not in skip}
        semaphore = asyncio.Semaphore(self._concurrency)
        discovered: list[tuple[str, str]] = []

        async def read(token_id: str) -> tuple[str, MarketOrderBookSnapshot | None]:
            try:
                async with semaphore:
                    book = await self._market_port.get_order_book(token_id)
                return (token_id, book) if book.token_id == token_id else (token_id, None)
            except Exception as error:
                diagnostic = getattr(error, "diagnostic", None)
                status = getattr(diagnostic, "status_code", None)
                if status == 404:
                    discovered.append((token_id, "TERMINAL_404"))
                return token_id, None

        try:
            fetched = dict(await asyncio.gather(*(read(value) for value in sorted(pending))))
        except ContinuousShadowError:
            raise
        except Exception as error:
            raise ContinuousShadowError(
                "Market order books were unavailable.",
                error_code=FAILURE_CATEGORY_MARKET_READ_FAILED,
                processing_stage=FAILURE_STAGE_MARKET_READ,
            ) from error
        if discovered:
            self._store.remember_terminal_books(
                tuple(discovered),
                now=self._now(),
                ttl_seconds=self._config.negative_cache_ttl_seconds,
            )
        return {token_id: fetched.get(token_id) for token_id in token_ids}

    def _apply_event(
        self,
        portfolio: _MutablePortfolio,
        event: LeaderTradeEvent,
        *,
        pool_class: str,
        lifecycle: ContinuousShadowLifecycle,
        market: MarketDetails | None,
        book: MarketOrderBookSnapshot | None,
        attributions: dict[tuple[str, str, str, str], _MutableAttribution],
        consumed_by_scope: dict[tuple[str, str], dict[Decimal, Decimal]],
        evaluated_at: datetime,
    ) -> tuple[ContinuousEvaluationRecord, ContinuousLedgerRecord | None]:
        api_lag = _milliseconds(event.observed_at - event.executed_at)
        signal_delay = _milliseconds(evaluated_at - event.observed_at)
        total_delay = _milliseconds(evaluated_at - event.executed_at)

        def evidence(
            status: ContinuousEvaluationStatus,
            reason: str,
            *,
            requested_size: Decimal = ZERO,
            fee_status: str = "NOT_EVALUATED",
            fee_source: str = "not_evaluated",
        ) -> tuple[ContinuousEvaluationRecord, None]:
            return (
                ContinuousEvaluationRecord(
                    event_id=event.event_id,
                    portfolio_id=portfolio.portfolio_id,
                    wallet_id=event.leader_id,
                    pool_class=pool_class,
                    status=status,
                    reason=reason,
                    requested_size=requested_size,
                    filled_size=ZERO,
                    follower_price=None,
                    gross_notional=None,
                    fee=None,
                    fee_status=fee_status,
                    fee_source=fee_source,
                    fee_rate=None,
                    fee_exponent=None,
                    realized_pnl=None,
                    source_api_lag_ms=api_lag,
                    signal_delay_ms=signal_delay,
                    price_movement=None,
                    spread_cost=None,
                    depth_impact=None,
                    liquidity_loss=None,
                    available_liquidity=None,
                    quote_timestamp=None,
                    evaluated_at=evaluated_at,
                ),
                None,
            )

        if total_delay > self._config.maximum_forward_delay_ms:
            return evidence(ContinuousEvaluationStatus.UNKNOWN, "source_and_signal_delay_exceeded")
        if book is None:
            return evidence(ContinuousEvaluationStatus.UNKNOWN, "current_order_book_unavailable")
        if not quote_is_fresh(
            book,
            evaluated_at=evaluated_at,
            maximum_age_ms=self._config.maximum_quote_age_ms,
        ):
            return evidence(ContinuousEvaluationStatus.UNKNOWN, "current_order_book_stale")
        levels = book.asks if event.trade_action is LeaderTradeAction.BUY else book.bids
        if not levels:
            return evidence(ContinuousEvaluationStatus.UNKNOWN, "executable_book_side_empty")
        if (
            event.trade_action is LeaderTradeAction.BUY
            and lifecycle is ContinuousShadowLifecycle.DRAINING
        ):
            return evidence(
                ContinuousEvaluationStatus.REJECTED,
                "draining_blocks_new_exposure",
            )
        key = (event.market_reference, event.outcome_reference)
        position = portfolio.positions.get(key)
        attribution_key = (
            portfolio.portfolio_id,
            event.leader_id,
            event.market_reference,
            event.outcome_reference,
        )
        attribution = attributions.get(attribution_key)
        if event.trade_action is LeaderTradeAction.SELL:
            available_position = ZERO if position is None else position.quantity
            if portfolio.kind in FOLLOWER_KINDS:
                available_position = min(
                    available_position,
                    ZERO if attribution is None else attribution.quantity,
                )
            requested_size = min(event.executed_size, available_position)
            if requested_size <= ZERO:
                return evidence(
                    ContinuousEvaluationStatus.UNKNOWN,
                    "persistent_portfolio_has_no_copyable_position",
                )
        else:
            opposing = any(
                item.market_reference == event.market_reference
                and item.outcome_reference != event.outcome_reference
                and item.quantity > ZERO
                for item in portfolio.positions.values()
            )
            if opposing:
                return evidence(
                    ContinuousEvaluationStatus.REJECTED,
                    "conflicting_market_outcome_exposure",
                )
            maximum_notional = min(
                self._config.maximum_event_notional,
                event.executed_price * event.executed_size,
            )
            exposure_room = (
                self._config.wallet_maximum_exposure - portfolio.exposure
                if portfolio.kind is ContinuousPortfolioKind.WALLET
                else self._config.follower_maximum_exposure - portfolio.exposure
            )
            if portfolio.kind in FOLLOWER_KINDS:
                wallet_exposure = sum(
                    value.cost_basis
                    for attr_key, value in attributions.items()
                    if attr_key[0] == portfolio.portfolio_id
                    and attr_key[1] == event.leader_id
                )
                market_exposure = sum(
                    item.cost_basis
                    for item in portfolio.positions.values()
                    if item.market_reference == event.market_reference
                )
                exposure_room = min(
                    exposure_room,
                    self._config.follower_maximum_wallet_exposure - wallet_exposure,
                    self._config.follower_maximum_market_exposure - market_exposure,
                )
                if (
                    position is None
                    and len(portfolio.positions)
                    >= self._config.follower_maximum_positions
                ):
                    return evidence(
                        ContinuousEvaluationStatus.REJECTED,
                        "follower_position_limit_reached",
                    )
            maximum_notional = min(maximum_notional, exposure_room, portfolio.cash)
            top = min(level.price for level in book.asks)
            if maximum_notional <= ZERO or top <= ZERO:
                return evidence(
                    ContinuousEvaluationStatus.REJECTED,
                    "synthetic_capital_limit_reached",
                )
            requested_size = min(event.executed_size, maximum_notional / top)
        scope = (portfolio.portfolio_id, event.outcome_reference)
        consumed = consumed_by_scope.setdefault(scope, {})
        walk = walk_order_book(
            book,
            action=event.trade_action,
            requested_size=requested_size,
            already_consumed=consumed,
        )
        if walk.filled_size <= ZERO or walk.follower_price is None:
            return evidence(
                ContinuousEvaluationStatus.UNKNOWN,
                "shared_liquidity_unavailable",
                requested_size=requested_size,
            )
        if walk.filled_size < book.minimum_order_size:
            return evidence(
                ContinuousEvaluationStatus.REJECTED,
                "fill_below_market_minimum_order_size",
                requested_size=requested_size,
            )
        fee = calculate_verified_taker_fee(
            market,
            price=walk.follower_price,
            size=walk.filled_size,
        )
        if fee.amount is None:
            evaluation, _ = evidence(
                ContinuousEvaluationStatus.UNKNOWN,
                "market_specific_fee_provenance_unknown",
                requested_size=requested_size,
                fee_status=fee.status,
                fee_source=fee.source,
            )
            return (
                replace(
                    evaluation,
                    available_liquidity=walk.available_liquidity,
                    quote_timestamp=book.timestamp,
                ),
                None,
            )
        movement = (
            (walk.follower_price - event.executed_price) * walk.filled_size
            if event.trade_action is LeaderTradeAction.BUY
            else (event.executed_price - walk.follower_price) * walk.filled_size
        )
        if adverse_price_drift_exceeded(
            action=event.trade_action,
            price_movement=movement,
            gross_notional=walk.gross_notional,
            maximum_ratio=self._config.price_drift_max_ratio,
        ):
            return evidence(
                ContinuousEvaluationStatus.REJECTED,
                "price_drift_exceeded",
                requested_size=requested_size,
                fee_status=fee.status,
                fee_source=fee.source,
            )
        total_buy_cost = walk.gross_notional + fee.amount
        if event.trade_action is LeaderTradeAction.BUY and total_buy_cost > portfolio.cash:
            return evidence(
                ContinuousEvaluationStatus.REJECTED,
                "synthetic_cash_limit_reached_after_verified_fee",
                requested_size=requested_size,
                fee_status=fee.status,
                fee_source=fee.source,
            )
        for price, size in walk.consumed:
            consumed[price] = consumed.get(price, ZERO) + size
        realized: Decimal | None = None
        entry_type: str
        quantity_delta: Decimal
        cash_delta: Decimal
        cost_delta: Decimal
        if event.trade_action is LeaderTradeAction.BUY:
            entry_type = "OPEN" if position is None else "INCREASE"
            portfolio.cash -= total_buy_cost
            portfolio.fees += fee.amount
            if position is None:
                position = _MutablePosition(
                    market_reference=event.market_reference,
                    outcome_reference=event.outcome_reference,
                    quantity=ZERO,
                    cost_basis=ZERO,
                    entry_fees=ZERO,
                    mark_price=None,
                    marked_at=None,
                )
                portfolio.positions[key] = position
            position.quantity += walk.filled_size
            position.cost_basis += walk.gross_notional
            position.entry_fees += fee.amount
            quantity_delta = walk.filled_size
            cash_delta = -total_buy_cost
            cost_delta = walk.gross_notional
            if portfolio.kind in FOLLOWER_KINDS:
                if attribution is None:
                    attribution = _MutableAttribution(ZERO, ZERO, pool_class, event.event_id)
                    attributions[attribution_key] = attribution
                attribution.quantity += walk.filled_size
                attribution.cost_basis += walk.gross_notional
                attribution.pool_class = pool_class
                attribution.last_event_id = event.event_id
        else:
            assert position is not None
            entry_type = "CLOSE" if walk.filled_size == position.quantity else "REDUCE"
            ratio = walk.filled_size / position.quantity
            allocated_cost = position.cost_basis * ratio
            allocated_entry_fees = position.entry_fees * ratio
            realized = walk.gross_notional - allocated_cost
            cash_delta = walk.gross_notional - fee.amount
            portfolio.cash += cash_delta
            portfolio.realized_pnl += realized
            portfolio.fees += fee.amount
            position.quantity -= walk.filled_size
            position.cost_basis -= allocated_cost
            position.entry_fees -= allocated_entry_fees
            quantity_delta = -walk.filled_size
            cost_delta = -allocated_cost
            if position.quantity <= ZERO:
                del portfolio.positions[key]
            if portfolio.kind in FOLLOWER_KINDS:
                assert attribution is not None
                attr_ratio = walk.filled_size / attribution.quantity
                attribution.quantity -= walk.filled_size
                attribution.cost_basis -= attribution.cost_basis * attr_ratio
                attribution.last_event_id = event.event_id
                if attribution.quantity <= ZERO:
                    del attributions[attribution_key]
        evaluation = ContinuousEvaluationRecord(
            event_id=event.event_id,
            portfolio_id=portfolio.portfolio_id,
            wallet_id=event.leader_id,
            pool_class=pool_class,
            status=ContinuousEvaluationStatus.SIMULATED,
            reason=(
                "partial_fill_after_shared_liquidity"
                if walk.filled_size < requested_size
                else "verified_forward_fill"
            ),
            requested_size=requested_size,
            filled_size=walk.filled_size,
            follower_price=walk.follower_price,
            gross_notional=walk.gross_notional,
            fee=fee.amount,
            fee_status=fee.status,
            fee_source=fee.source,
            fee_rate=fee.rate,
            fee_exponent=fee.exponent,
            realized_pnl=realized,
            source_api_lag_ms=api_lag,
            signal_delay_ms=signal_delay,
            price_movement=movement,
            spread_cost=walk.spread_cost,
            depth_impact=walk.depth_impact,
            liquidity_loss=(requested_size - walk.filled_size) * event.executed_price,
            available_liquidity=walk.available_liquidity,
            quote_timestamp=book.timestamp,
            evaluated_at=evaluated_at,
            consumed=walk.consumed,
        )
        ledger = ContinuousLedgerRecord(
            entry_id=uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"polysia:continuous-shadow:{event.event_id}:{portfolio.portfolio_id}",
            ).hex,
            portfolio_id=portfolio.portfolio_id,
            event_id=event.event_id,
            entry_type=entry_type,
            market_reference=event.market_reference,
            outcome_reference=event.outcome_reference,
            quantity_delta=quantity_delta,
            cash_delta=cash_delta,
            cost_basis_delta=cost_delta,
            realized_pnl_delta=realized or ZERO,
            fee_delta=fee.amount,
            created_at=evaluated_at,
            wallet_id=event.leader_id,
            pool_class=pool_class,
        )
        return evaluation, ledger

    def _required_experiment(self, source_id: str) -> ContinuousShadowExperiment:
        experiment = self._store.active_experiment(source_id)
        if experiment is None:
            raise ContinuousShadowError("Continuous Shadow experiment is not running.")
        return experiment

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("clock must return timezone-aware UTC")
        return value


def _mutable_portfolios(
    stored: tuple[ContinuousPortfolio, ...],
    *,
    current_candidates: tuple[ProtectedShadowCandidate, ...],
    wallet_bankroll: Decimal,
    follower_bankroll: Decimal,
) -> dict[str, _MutablePortfolio]:
    portfolios = {
        item.portfolio_id: _MutablePortfolio(
            portfolio_id=item.portfolio_id,
            kind=item.kind,
            wallet_id=item.wallet_id,
            initial_cash=item.initial_cash,
            cash=item.cash,
            realized_pnl=item.realized_pnl,
            fees=item.fees,
            high_water_nav=item.high_water_nav,
            drawdown=item.drawdown,
            positions={
                (position.market_reference, position.outcome_reference): _MutablePosition(
                    market_reference=position.market_reference,
                    outcome_reference=position.outcome_reference,
                    quantity=position.quantity,
                    cost_basis=position.cost_basis,
                    entry_fees=position.entry_fees,
                    mark_price=position.mark_price,
                    marked_at=position.marked_at,
                )
                for position in item.positions
            },
        )
        for item in stored
    }
    for candidate in current_candidates:
        portfolio_id = f"wallet:{candidate.wallet_id}"
        portfolios.setdefault(
            portfolio_id,
            _MutablePortfolio(
                portfolio_id=portfolio_id,
                kind=ContinuousPortfolioKind.WALLET,
                wallet_id=candidate.wallet_id,
                initial_cash=wallet_bankroll,
                cash=wallet_bankroll,
                realized_pnl=ZERO,
                fees=ZERO,
                high_water_nav=wallet_bankroll,
                drawdown=ZERO,
                positions={},
            ),
        )
    for portfolio_id, kind, _accepted in FOLLOWER_KIND_SPECS:
        portfolios.setdefault(
            portfolio_id,
            _MutablePortfolio(
                portfolio_id=portfolio_id,
                kind=kind,
                wallet_id=None,
                initial_cash=follower_bankroll,
                cash=follower_bankroll,
                realized_pnl=ZERO,
                fees=ZERO,
                high_water_nav=follower_bankroll,
                drawdown=ZERO,
                positions={},
            ),
        )
    if "follower" not in portfolios:
        raise ContinuousShadowError("Continuous Shadow follower portfolio is unavailable.")
    return portfolios


def _mutable_attributions(
    stored: tuple[FollowerAttribution, ...],
) -> dict[tuple[str, str, str, str], _MutableAttribution]:
    return {
        (
            item.portfolio_id,
            item.wallet_id,
            item.market_reference,
            item.outcome_reference,
        ): _MutableAttribution(
            item.quantity,
            item.cost_basis,
            item.pool_class,
            item.last_event_id,
        )
        for item in stored
    }


def _apply_settlements(
    portfolios: dict[str, _MutablePortfolio],
    attributions: dict[tuple[str, str, str, str], _MutableAttribution],
    markets: Mapping[str, MarketDetails | None],
    *,
    evaluated_at: datetime,
) -> tuple[list[ContinuousLedgerRecord], list[ContinuousPositionMark], int, int]:
    ledger: list[ContinuousLedgerRecord] = []
    marks: list[ContinuousPositionMark] = []
    count = 0
    backlog_count = 0
    for portfolio in portfolios.values():
        for key, position in tuple(portfolio.positions.items()):
            market = markets.get(position.market_reference)
            settlement = verified_settlement_prices(market)
            if settlement is None or position.outcome_reference not in settlement:
                if market is not None and market.closed:
                    backlog_count += 1
                continue
            price = settlement[position.outcome_reference]
            proceeds = position.quantity * price
            realized = proceeds - position.cost_basis
            portfolio.cash += proceeds
            portfolio.realized_pnl += realized
            matching = [
                (attr_key, attr)
                for attr_key, attr in tuple(attributions.items())
                if attr_key[0] == portfolio.portfolio_id and attr_key[2:] == key
            ]
            if matching and portfolio.kind in FOLLOWER_KINDS:
                remaining_qty = position.quantity
                remaining_cost = position.cost_basis
                remaining_proceeds = proceeds
                remaining_realized = realized
                for index, (attr_key, attr) in enumerate(matching):
                    last = index == len(matching) - 1
                    share_qty = remaining_qty if last else attr.quantity
                    share_cost = remaining_cost if last else attr.cost_basis
                    share_proceeds = remaining_proceeds if last else share_qty * price
                    share_realized = remaining_realized if last else share_proceeds - share_cost
                    remaining_qty -= share_qty
                    remaining_cost -= share_cost
                    remaining_proceeds -= share_proceeds
                    remaining_realized -= share_realized
                    ledger.append(
                        _settlement_entry(
                            portfolio_id=portfolio.portfolio_id,
                            position=position,
                            evaluated_at=evaluated_at,
                            quantity=share_qty,
                            proceeds=share_proceeds,
                            cost=share_cost,
                            realized=share_realized,
                            wallet_id=attr_key[1],
                            pool_class=attr.pool_class,
                            suffix=attr_key[1],
                        )
                    )
                    del attributions[attr_key]
            else:
                ledger.append(
                    _settlement_entry(
                        portfolio_id=portfolio.portfolio_id,
                        position=position,
                        evaluated_at=evaluated_at,
                        quantity=position.quantity,
                        proceeds=proceeds,
                        cost=position.cost_basis,
                        realized=realized,
                        wallet_id=portfolio.wallet_id,
                        pool_class=None,
                        suffix="portfolio",
                    )
                )
            age_ms, freshness = mark_freshness(
                mark_status="VERIFIED_SETTLEMENT",
                source_timestamp=evaluated_at,
                evaluated_at=evaluated_at,
                maximum_age_ms=0,
            )
            marks.append(
                ContinuousPositionMark(
                    portfolio_id=portfolio.portfolio_id,
                    market_reference=position.market_reference,
                    outcome_reference=position.outcome_reference,
                    quantity=position.quantity,
                    mark_price=price,
                    market_value=proceeds,
                    unrealized_pnl=realized,
                    mark_status="VERIFIED_SETTLEMENT",
                    marked_at=evaluated_at,
                    source_timestamp=evaluated_at,
                    source_age_ms=age_ms,
                    freshness=freshness,
                )
            )
            del portfolio.positions[key]
            count += 1
    return ledger, marks, count, backlog_count


def _settlement_entry(
    *,
    portfolio_id: str,
    position: _MutablePosition,
    evaluated_at: datetime,
    quantity: Decimal,
    proceeds: Decimal,
    cost: Decimal,
    realized: Decimal,
    wallet_id: str | None,
    pool_class: str | None,
    suffix: str,
) -> ContinuousLedgerRecord:
    return ContinuousLedgerRecord(
        entry_id=uuid.uuid5(
            uuid.NAMESPACE_URL,
            "polysia:continuous-shadow:settlement:"
            f"{portfolio_id}:{position.market_reference}:"
            f"{position.outcome_reference}:{suffix}:{evaluated_at.isoformat()}",
        ).hex,
        portfolio_id=portfolio_id,
        event_id=None,
        entry_type="SETTLEMENT",
        market_reference=position.market_reference,
        outcome_reference=position.outcome_reference,
        quantity_delta=-quantity,
        cash_delta=proceeds,
        cost_basis_delta=-cost,
        realized_pnl_delta=realized,
        fee_delta=ZERO,
        created_at=evaluated_at,
        wallet_id=wallet_id,
        pool_class=pool_class,
    )


def _mark_positions(
    portfolios: dict[str, _MutablePortfolio],
    books: Mapping[str, MarketOrderBookSnapshot | None],
    *,
    evaluated_at: datetime,
    maximum_age_ms: int,
) -> list[ContinuousPositionMark]:
    marks: list[ContinuousPositionMark] = []
    for portfolio in portfolios.values():
        for position in portfolio.positions.values():
            book = books.get(position.outcome_reference)
            mark_status = "MISSING"
            source_timestamp = position.marked_at
            if (
                book is not None
                and quote_is_fresh(book, evaluated_at=evaluated_at, maximum_age_ms=maximum_age_ms)
                and book.best_bid is not None
            ):
                position.mark_price = book.best_bid.price
                position.marked_at = book.timestamp
                source_timestamp = book.timestamp
                mark_status = "VERIFIED_EXECUTABLE_BID"
            elif position.mark_price is not None:
                mark_status = "LAST_KNOWN_GOOD"
            age_ms, freshness = mark_freshness(
                mark_status=mark_status,
                source_timestamp=source_timestamp,
                evaluated_at=evaluated_at,
                maximum_age_ms=maximum_age_ms,
            )
            market_value = (
                None
                if position.mark_price is None
                else position.quantity * position.mark_price
            )
            marks.append(
                ContinuousPositionMark(
                    portfolio_id=portfolio.portfolio_id,
                    market_reference=position.market_reference,
                    outcome_reference=position.outcome_reference,
                    quantity=position.quantity,
                    mark_price=position.mark_price,
                    market_value=market_value,
                    unrealized_pnl=(
                        None if market_value is None else market_value - position.cost_basis
                    ),
                    mark_status=mark_status,
                    marked_at=evaluated_at,
                    source_timestamp=source_timestamp,
                    source_age_ms=age_ms,
                    freshness=freshness,
                )
            )
    return marks


def _freeze_portfolio(portfolio: _MutablePortfolio) -> ContinuousPortfolio:
    return ContinuousPortfolio(
        portfolio_id=portfolio.portfolio_id,
        kind=portfolio.kind,
        wallet_id=portfolio.wallet_id,
        initial_cash=portfolio.initial_cash,
        cash=portfolio.cash,
        realized_pnl=portfolio.realized_pnl,
        fees=portfolio.fees,
        high_water_nav=portfolio.high_water_nav,
        drawdown=portfolio.drawdown,
        positions=tuple(
            ContinuousPosition(
                portfolio_id=portfolio.portfolio_id,
                market_reference=item.market_reference,
                outcome_reference=item.outcome_reference,
                quantity=item.quantity,
                cost_basis=item.cost_basis,
                entry_fees=item.entry_fees,
                mark_price=item.mark_price,
                marked_at=item.marked_at,
            )
            for item in sorted(
                portfolio.positions.values(),
                key=lambda value: (value.market_reference, value.outcome_reference),
            )
        ),
    )


def _merge_candidates(
    current: tuple[ProtectedShadowCandidate, ...],
    retained: tuple[ProtectedShadowCandidate, ...],
) -> tuple[ProtectedShadowCandidate, ...]:
    values = {item.wallet_id: item for item in retained}
    values.update({item.wallet_id: item for item in current})
    return tuple(values[key] for key in sorted(values))


def _pool_class(pools: tuple[str, ...]) -> str:
    alpha = "SHADOW_ALPHA" in pools
    stress = "SHADOW_STRESS" in pools
    if alpha and stress:
        return "ALPHA_STRESS"
    if alpha:
        return "ALPHA"
    if stress:
        return "STRESS"
    return "RETAINED_EXIT_ONLY"


def _milliseconds(value: timedelta) -> int:
    return max(0, int(value.total_seconds() * 1000))


def _safe_mapping(source: object, name: str) -> dict[str, object]:
    method = getattr(source, name, None)
    if method is None:
        return {}
    value = method()
    return value if isinstance(value, dict) else {}


__all__ = [
    "CONTINUOUS_SHADOW_LEASE_RESOURCE",
    "ContinuousShadowError",
    "ContinuousShadowService",
]
