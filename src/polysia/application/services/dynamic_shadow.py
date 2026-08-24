from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from polysia.application.ports.copytrading import (
    LeaderReadPurpose,
    LeaderTradeCheckpoint,
    LeaderTradeSourcePort,
)
from polysia.application.ports.dynamic_shadow import (
    DynamicShadowLeasePort,
    DynamicShadowOutcome,
    DynamicShadowRunRecord,
    DynamicShadowStorePort,
    LeaderSourceFactory,
    ProtectedShadowCandidate,
    ShadowQuotePort,
)
from polysia.domain.copytrading import LeaderTradeEvent
from polysia.domain.copytrading.dynamic_shadow import (
    DynamicShadowConfig,
    DynamicShadowMode,
    ShadowEventEvaluation,
    ShadowQuoteEvidence,
    ShadowWalletSummary,
    evaluate_shadow_events,
    quote_from_order_book,
)
from polysia.domain.wallet_intelligence import CandidatePipelineLease

Clock = Callable[[], datetime]
PIPELINE_LEASE_RESOURCE = "wallet-intelligence-pipeline"


class DynamicShadowError(RuntimeError):
    error_code = "dynamic_shadow_failed"


class DynamicShadowService:
    """Read-only Stage 4 orchestration; it has no execution or order port."""

    def __init__(
        self,
        store: DynamicShadowStorePort,
        lease_store: DynamicShadowLeasePort,
        source_factory: LeaderSourceFactory,
        *,
        quote_port: ShadowQuotePort | None = None,
        config: DynamicShadowConfig | None = None,
        clock: Clock | None = None,
        maximum_pages_per_wallet: int = 100,
        concurrency: int = 4,
    ) -> None:
        if not 20 <= maximum_pages_per_wallet <= 200:
            raise ValueError("maximum_pages_per_wallet must be within [20, 200]")
        if not 1 <= concurrency <= 8:
            raise ValueError("concurrency must be within [1, 8]")
        self._store = store
        self._lease_store = lease_store
        self._source_factory = source_factory
        self._quote_port = quote_port
        self._config = config or DynamicShadowConfig()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._maximum_pages = maximum_pages_per_wallet
        self._concurrency = concurrency

    async def run(
        self,
        source_id: str,
        *,
        mode: DynamicShadowMode,
        lookback: timedelta,
        as_of: datetime | None = None,
    ) -> DynamicShadowOutcome:
        if lookback <= timedelta(0) or lookback > timedelta(days=30):
            raise ValueError("lookback must be within (0, 30 days]")
        self._store.initialize()
        self._lease_store.initialize()
        lease = self._lease_store.acquire_lease(
            PIPELINE_LEASE_RESOURCE,
            owner_id=f"dynamic-shadow-{uuid.uuid4().hex}",
            acquired_at=_utc(self._clock()),
            lease_duration=timedelta(minutes=30),
        )
        try:
            return await self._run_locked(
                source_id,
                mode=mode,
                lookback=lookback,
                as_of=as_of,
                lease=lease,
            )
        finally:
            self._lease_store.release_lease(lease)

    async def _run_locked(
        self,
        source_id: str,
        *,
        mode: DynamicShadowMode,
        lookback: timedelta,
        as_of: datetime | None,
        lease: CandidatePipelineLease,
    ) -> DynamicShadowOutcome:
        selection_run_id, candidates = self._store.current_candidates(source_id)
        window_end = _utc(as_of or self._clock())
        window_start = window_end - lookback
        existing = self._store.successful_run(
            selection_run_id=selection_run_id,
            mode=mode,
            policy_version=self._config.policy_version,
            cost_model_version=self._config.effective_cost_model_version,
            window_start=window_start,
            window_end=window_end,
        )
        if existing is not None:
            return _outcome(
                existing,
                candidates=candidates,
                summaries=(),
                telemetry={},
                circuit={},
                idempotent=True,
            )
        run_id = self._store.start_run(
            source_id=source_id,
            selection_run_id=selection_run_id,
            mode=mode,
            policy_version=self._config.policy_version,
            cost_model_version=self._config.effective_cost_model_version,
            window_start=window_start,
            window_end=window_end,
            started_at=_utc(self._clock()),
            candidate_count=len(candidates),
        )
        source: LeaderTradeSourcePort | None = None
        try:
            source = self._source_factory({item.wallet_id: item.address for item in candidates})
            events_by_wallet = await self._collect_events(
                source,
                candidates,
                window_start=window_start,
                window_end=window_end,
                mode=mode,
            )
            quote_requested_at = _utc(self._clock())
            quotes = await self._quotes(
                events_by_wallet,
                mode=mode,
                evaluated_at=quote_requested_at,
            )
            evaluated_at = (
                window_end if mode is DynamicShadowMode.HISTORICAL else _utc(self._clock())
            )
            evaluations: list[ShadowEventEvaluation] = []
            summaries: list[ShadowWalletSummary] = []
            for candidate in candidates:
                wallet_evaluations, summary = evaluate_shadow_events(
                    candidate.wallet_id,
                    events_by_wallet[candidate.wallet_id],
                    mode=mode,
                    config=self._config,
                    quotes=quotes,
                    evaluated_at=evaluated_at,
                )
                evaluations.extend(wallet_evaluations)
                summaries.append(summary)
            self._lease_store.renew_lease(
                lease,
                renewed_at=_utc(self._clock()),
                lease_duration=timedelta(minutes=30),
            )
            completed = self._store.complete_run(
                run_id,
                candidates=candidates,
                evaluations=tuple(evaluations),
                summaries=tuple(summaries),
                completed_at=_utc(self._clock()),
            )
        except Exception as error:
            self._store.fail_run(
                run_id,
                failed_at=_utc(self._clock()),
                error_code=getattr(error, "error_code", "dynamic_shadow_failed"),
            )
            raise DynamicShadowError(
                "Dynamic Shadow failed safely; prior evidence was kept."
            ) from error
        assert source is not None
        telemetry = _safe_mapping(source, "request_telemetry")
        circuit = _safe_mapping(source, "trades_circuit")
        return _outcome(
            completed,
            candidates=candidates,
            summaries=tuple(summaries),
            telemetry=telemetry,
            circuit=circuit,
            idempotent=False,
        )

    async def _collect_events(
        self,
        source: LeaderTradeSourcePort,
        candidates: tuple[ProtectedShadowCandidate, ...],
        *,
        window_start: datetime,
        window_end: datetime,
        mode: DynamicShadowMode,
    ) -> dict[str, tuple[LeaderTradeEvent, ...]]:
        semaphore = asyncio.Semaphore(self._concurrency)
        purpose = (
            LeaderReadPurpose.BASELINE
            if mode is DynamicShadowMode.HISTORICAL
            else LeaderReadPurpose.DISCOVERY
        )

        async def collect(
            candidate: ProtectedShadowCandidate,
        ) -> tuple[str, tuple[LeaderTradeEvent, ...]]:
            page_count = 0

            async def collect_window(
                start_at: datetime,
                end_at: datetime,
                *,
                split_depth: int,
            ) -> list[LeaderTradeEvent]:
                nonlocal page_count
                events: list[LeaderTradeEvent] = []
                checkpoint: LeaderTradeCheckpoint | None = None
                for _ in range(20):
                    if page_count >= self._maximum_pages:
                        raise DynamicShadowError(
                            "Leader history exceeded the bounded total page limit."
                        )
                    page = await source.read_page(
                        candidate.wallet_id,
                        start_at=start_at,
                        end_at=end_at,
                        page_size=500,
                        checkpoint=checkpoint,
                        purpose=purpose,
                    )
                    page_count += 1
                    if any(
                        event.leader_id != candidate.wallet_id
                        or event.executed_at < start_at
                        or event.executed_at > end_at
                        for event in page.events
                    ):
                        raise DynamicShadowError(
                            "Leader source returned event evidence outside its requested scope."
                        )
                    events.extend(page.events)
                    checkpoint = page.next_checkpoint
                    if checkpoint is None:
                        return events
                if split_depth >= 8 or end_at - start_at <= timedelta(seconds=2):
                    raise DynamicShadowError(
                        "Leader history remained dense after bounded window splitting."
                    )
                midpoint = start_at + (end_at - start_at) / 2
                left = await collect_window(start_at, midpoint, split_depth=split_depth + 1)
                right = await collect_window(midpoint, end_at, split_depth=split_depth + 1)
                return [*left, *right]

            async with semaphore:
                events = await collect_window(window_start, window_end, split_depth=0)
            unique = {item.event_id: item for item in events}
            return candidate.wallet_id, tuple(
                sorted(unique.values(), key=lambda item: (item.executed_at, item.event_id))
            )

        rows = await asyncio.gather(*(collect(candidate) for candidate in candidates))
        return dict(rows)

    async def _quotes(
        self,
        events_by_wallet: dict[str, tuple[LeaderTradeEvent, ...]],
        *,
        mode: DynamicShadowMode,
        evaluated_at: datetime,
    ) -> dict[str, ShadowQuoteEvidence | None]:
        if mode is DynamicShadowMode.HISTORICAL:
            return {}
        if self._quote_port is None:
            raise DynamicShadowError("Forward Shadow requires a public order-book adapter.")
        quote_port = self._quote_port
        events = tuple(event for values in events_by_wallet.values() for event in values)
        semaphore = asyncio.Semaphore(self._concurrency)

        async def quote(
            event: LeaderTradeEvent,
        ) -> tuple[str, ShadowQuoteEvidence | None]:
            actual_delay = evaluated_at - event.executed_at
            if actual_delay > timedelta(milliseconds=self._config.maximum_forward_delay_ms):
                return event.event_id, None
            try:
                async with semaphore:
                    book = await quote_port.get_order_book(event.outcome_reference)
                return event.event_id, quote_from_order_book(book)
            except Exception:
                return event.event_id, None

        return dict(await asyncio.gather(*(quote(event) for event in events)))


def _outcome(
    run: DynamicShadowRunRecord,
    *,
    candidates: tuple[ProtectedShadowCandidate, ...],
    summaries: tuple[ShadowWalletSummary, ...],
    telemetry: dict[str, object],
    circuit: dict[str, object],
    idempotent: bool,
) -> DynamicShadowOutcome:
    alpha = {item.wallet_id for item in candidates if "SHADOW_ALPHA" in item.pools}
    stress = {item.wallet_id for item in candidates if "SHADOW_STRESS" in item.pools}
    return DynamicShadowOutcome(
        run=run,
        idempotent_replay=idempotent,
        candidate_count=len(candidates),
        alpha_count=len(alpha),
        stress_count=len(stress),
        overlap_count=len(alpha & stress),
        event_count=sum(item.event_count for item in summaries) if summaries else run.event_count,
        simulated_count=(
            sum(item.simulated_count for item in summaries) if summaries else run.simulated_count
        ),
        unknown_count=(
            sum(item.unknown_count for item in summaries) if summaries else run.unknown_count
        ),
        rejected_count=(
            sum(item.rejected_count for item in summaries) if summaries else run.rejected_count
        ),
        realized_pnl=(
            sum((item.realized_pnl for item in summaries), Decimal("0"))
            if summaries
            else run.realized_pnl
        ),
        fees=(sum((item.fees for item in summaries), Decimal("0")) if summaries else run.fees),
        slippage=(
            sum((item.slippage for item in summaries), Decimal("0")) if summaries else run.slippage
        ),
        request_telemetry=telemetry,
        trades_circuit=circuit,
    )


def _safe_mapping(source: object, name: str) -> dict[str, object]:
    method = getattr(source, name, None)
    if method is None:
        return {}
    value = method()
    return value if isinstance(value, dict) else {}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("clock must return timezone-aware UTC")
    return value
