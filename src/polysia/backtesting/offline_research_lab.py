"""Deterministic production-path laboratory for prospective research.

Fakes only network transport, coordinated time, and controlled interruption.
Adapter parsing, collection, persistence, replay, economics, finalization, and
restore remain the real production components.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from polysia.adapters.polymarket.request_scheduling import TradesSourceUnavailableError
from polysia.adapters.polymarket.research_sources import (
    REST_TRADES_CANDIDATE,
    TRADES_SOURCE_ID,
    DataApiWalletPollSource,
    OfficialMarketStreamSource,
    TerminalMarketSnapshot,
    public_wallet_alias,
)
from polysia.application.services.persistent_prospective_collector import (
    PersistentCollectorConfig,
    PersistentProspectiveCollector,
)
from polysia.backtesting.prospective_analysis import open_recorded_experiment_store
from polysia.backtesting.prospective_replay import replay_recorded_experiment
from polysia.backtesting.replay_report import detailed_replay_payload, result_hash
from polysia.deployment.research_experiment_bundle import finalize_research_experiment
from polysia.domain.events import MarketDataEvent
from polysia.domain.market import MarketFeeSchedule
from polysia.domain.research_evidence.models import (
    AttributionStatus,
    EvidenceClassification,
    ObservationKind,
)
from polysia.storage.immutable_sqlite import sha256_file
from polysia.storage.research_evidence import ResearchEvidenceStore

LAB_START = datetime(2026, 1, 1, tzinfo=UTC)
WALLET_A = "0x1111111111111111111111111111111111111111"
WALLET_B = "0x2222222222222222222222222222222222222222"
MARKET = "0x" + "ab" * 32
TOKEN = "123456789"
ASK = Decimal("0.40")
BID = Decimal("0.39")
LEADER_PRICE = Decimal("0.50")
LEADER_SIZE = Decimal("20")
DEPTH = Decimal("100")
FEE_RATE = Decimal("0.01")
FEE_EXPONENT = Decimal("1")
ENTRY_BUDGET = Decimal("5")
INITIAL_CAPITAL = Decimal("1000")
FEE_QUANTUM = Decimal("0.00001")
TRADE_COUNT = 20
CODE_SHA = "a" * 40


class CoordinatedClock:
    """One injected clock. Only ``sleep`` mutates simulated time."""

    def __init__(self, start: datetime = LAB_START) -> None:
        self._now = start
        self._start = start

    def __call__(self) -> datetime:
        return self._now

    def monotonic_ns(self) -> int:
        return max(0, int((self._now - self._start).total_seconds() * 1_000_000_000))

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(0)
        seconds = max(0.0, float(seconds))
        if seconds:
            self._now += timedelta(microseconds=int(seconds * 1_000_000))
        await asyncio.sleep(0)

    async def park(self, seconds: float) -> None:
        target = self._now + timedelta(microseconds=int(max(0.0, float(seconds)) * 1_000_000))
        while self._now < target:
            await asyncio.sleep(0)


@dataclass
class ScriptedJsonTransport:
    rows_by_call: list[list[dict[str, Any]]] | None = None
    v2_pages: bool = False
    failures_remaining: int = 0
    calls: int = 0
    purposes: list[str] = field(default_factory=list)

    async def get_json(
        self,
        base_url: str,
        path: str,
        params: Mapping[str, str | int | bool],
        *,
        purpose: object = None,
    ) -> Any:
        del base_url
        self.calls += 1
        self.purposes.append(getattr(purpose, "value", str(purpose)))
        if self.failures_remaining > 0:
            self.failures_remaining -= 1
            now = LAB_START
            raise TradesSourceUnavailableError(
                outage_started_at=now,
                retry_at=now + timedelta(seconds=1),
                reason="lab-injected-outage",
            )
        if self.rows_by_call is None:
            return []
        index = min(self.calls - 1, len(self.rows_by_call) - 1)
        rows = list(self.rows_by_call[index])
        if self.v2_pages and path == "/v2/trades":
            midpoint = len(rows) // 2
            cursor = params.get("cursor")
            page = rows[midpoint:] if cursor == "lab-page-2" else rows[:midpoint]
            return {
                "data": page,
                "pagination": {
                    "has_more": cursor is None,
                    "next_cursor": "lab-page-2" if cursor is None else None,
                },
            }
        return rows


class ScriptedMarketStream:
    generation = 0

    def __init__(
        self,
        bus: Any,
        events: tuple[MarketDataEvent, ...],
        *,
        fail_first: bool = False,
        park: CoordinatedClock,
    ) -> None:
        self._bus = bus
        self._events = events
        self._fail_first = fail_first
        self._park = park
        type(self).generation += 1
        self._generation = type(self).generation

    async def run(self, *, max_events: int | None = None) -> None:
        del max_events
        event = self._events[0] if self._generation == 1 else self._events[-1]
        await self._bus.publish(event)
        if self._fail_first and self._generation == 1:
            raise RuntimeError("lab-injected-disconnect")
        while True:
            await self._park.park(1.0)


def fee_schedule() -> MarketFeeSchedule:
    return MarketFeeSchedule(
        enabled=True,
        rate=FEE_RATE,
        exponent=FEE_EXPONENT,
        taker_only=True,
    )


def independent_fill() -> dict[str, Decimal]:
    """Hand calculation of one BUY. Does not call production economics."""

    requested_notional = min(ENTRY_BUDGET, LEADER_PRICE * LEADER_SIZE)
    quantity = min(DEPTH, LEADER_SIZE, requested_notional / ASK)
    notional = ASK * quantity
    per_share = FEE_RATE * ((ASK * (Decimal("1") - ASK)) ** FEE_EXPONENT)
    fee = (quantity * per_share).quantize(FEE_QUANTUM)
    slippage = max(Decimal("0"), ASK - LEADER_PRICE) * quantity
    liquidation = Decimal("1") * quantity
    cash = INITIAL_CAPITAL - notional - fee
    net_pnl = cash + liquidation - INITIAL_CAPITAL
    return {
        "available_quantity": quantity,
        "cash": cash,
        "fees": fee,
        "net_pnl": net_pnl,
        "notional": notional,
        "slippage": slippage,
    }


def independent_control_economics() -> dict[str, Decimal]:
    one = independent_fill()
    fills = Decimal(TRADE_COUNT)
    fees = one["fees"] * fills
    notional = one["notional"] * fills
    quantity = one["available_quantity"] * fills
    cash = INITIAL_CAPITAL - notional - fees
    return {
        "available_quantity": quantity,
        "cash": cash,
        "fees": fees,
        "net_pnl": cash + quantity - INITIAL_CAPITAL,
        "notional": notional,
        "slippage": one["slippage"] * fills,
    }


def trade_row(
    *,
    wallet: str,
    trade_id: str,
    timestamp: datetime,
    duplicate_id: str | None = None,
) -> dict[str, Any]:
    return {
        "asset": TOKEN,
        "conditionId": MARKET,
        "id": duplicate_id or trade_id,
        "price": format(LEADER_PRICE, "f"),
        "proxyWallet": wallet,
        "side": "buy",
        "size": format(LEADER_SIZE, "f"),
        "timestamp": int(timestamp.timestamp()),
        "transactionHash": f"0x{trade_id.encode().hex()[:64].ljust(64, '0')}",
    }


def book_event(clock: CoordinatedClock, *, crossed: bool = False) -> MarketDataEvent:
    observed = clock()
    asks = [{"price": "0.10", "size": "1"}] if crossed else [
        {"price": format(ASK, "f"), "size": format(DEPTH, "f")}
    ]
    bids = [{"price": "0.90", "size": "1"}] if crossed else [
        {"price": format(BID, "f"), "size": format(DEPTH, "f")}
    ]
    return MarketDataEvent(
        source="polymarket",
        event_type="book",
        token_id=TOKEN,
        received_at=observed,
        exchange_ts=observed,
        payload={"asks": asks, "bids": bids, "hash": "lab-book", "market": MARKET},
        raw_payload={"asks": asks, "bids": bids},
    )


def _aliases() -> dict[str, str]:
    return {
        public_wallet_alias(WALLET_A): WALLET_A,
        public_wallet_alias(WALLET_B): WALLET_B,
    }


def _complete_rows(clock: CoordinatedClock) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    bootstrap = clock() - timedelta(hours=1)
    rows.append(trade_row(wallet=WALLET_A, trade_id="bootstrap", timestamp=bootstrap))
    for index in range(TRADE_COUNT):
        wallet = WALLET_A if index < TRADE_COUNT // 2 else WALLET_B
        rows.append(
            trade_row(
                wallet=wallet,
                trade_id=f"trade-{index}",
                timestamp=clock(),
            )
        )
    rows.append(
        trade_row(
            wallet=WALLET_A,
            trade_id="trade-0",
            timestamp=clock(),
            duplicate_id="trade-0",
        )
    )
    return rows


async def _event_factory(
    clock: CoordinatedClock,
    event: MarketDataEvent,
) -> AsyncIterator[MarketDataEvent]:
    yield event
    while True:
        await clock.park(1.0)


def _collector(
    work: Path,
    *,
    clock: CoordinatedClock,
    transport: ScriptedJsonTransport,
    market: OfficialMarketStreamSource,
    window: timedelta,
    run_id: str,
    aliases: Mapping[str, str] | None = None,
) -> tuple[ResearchEvidenceStore, PersistentProspectiveCollector]:
    store = ResearchEvidenceStore(work / "research-evidence.sqlite3", clock=clock)
    aliases = dict(aliases) if aliases is not None else _aliases()
    wallet = DataApiWalletPollSource(
        REST_TRADES_CANDIDATE,
        path="/trades",
        source_id=TRADES_SOURCE_ID,
        aliases=aliases,
        transport=transport,
        poll_interval_seconds=(
            max(window.total_seconds() - 5.0, 1.0)
            if window.total_seconds() > 10
            else max(window.total_seconds(), 1.0)
        ),
        initial_delay_seconds=0.5,
        clock=clock,
        monotonic_ns=clock.monotonic_ns,
        sleep=clock.park,
    )
    collector = PersistentProspectiveCollector(
        store,
        (market, wallet),
        config=PersistentCollectorConfig(
            window=window,
            required_source_ids=("rest_trades",),
            optional_source_ids=("clob_market_ws",),
            tracked_wallet_aliases=tuple(aliases),
            tracked_market_tokens=(TOKEN,),
            code_sha=CODE_SHA,
            experiment_duration=timedelta(seconds=max(window.total_seconds() * 4, 8)),
            experiment_max_events=10_000,
            experiment_max_bytes=10_000_000,
        ),
        clock=clock,
        sleep=clock.sleep,
        run_id=run_id,
    )
    return store, collector


def _market_source(
    clock: CoordinatedClock,
    *,
    event: MarketDataEvent | None = None,
    stream_factory: Any = None,
    snapshot_calls: dict[str, int] | None = None,
) -> OfficialMarketStreamSource:
    calls = snapshot_calls if snapshot_calls is not None else {"n": 0}

    async def snapshots(token_markets: Mapping[str, str]) -> TerminalMarketSnapshot:
        del token_markets
        calls["n"] += 1
        return TerminalMarketSnapshot(books={}, fee_schedules={TOKEN: fee_schedule()})

    async def settlements(token_markets: Mapping[str, str]) -> Mapping[str, Decimal]:
        return {token: Decimal("1") for token in token_markets}

    factory = None
    if event is not None and stream_factory is None:
        async def events() -> AsyncIterator[MarketDataEvent]:
            async for item in _event_factory(clock, event):
                yield item

        factory = events
    return OfficialMarketStreamSource(
        token_ids=(TOKEN,),
        event_factory=factory,
        clock=clock,
        monotonic_ns=clock.monotonic_ns,
        sleep=clock.park,
        fee_schedules={TOKEN: fee_schedule()},
        market_stream_factory=stream_factory,
        token_markets={TOKEN: MARKET},
        terminal_snapshot_fetcher=snapshots,
        terminal_settlement_fetcher=settlements,
        snapshot_refresh_interval_seconds=20.0,
        discovery_interval_seconds=30.0,
    )


@dataclass(frozen=True, slots=True)
class LabScenarioResult:
    name: str
    run_id: str
    report: dict[str, object]
    replay_hashes: tuple[str, str]
    bundle_outcome: str
    bundle_verified: bool
    source_hash_before: str
    source_hash_after: str
    extras: dict[str, object]


async def run_scenario_a(work: Path) -> LabScenarioResult:
    clock = CoordinatedClock()
    transport = ScriptedJsonTransport(rows_by_call=[_complete_rows(clock)])
    market = _market_source(clock, event=book_event(clock))
    store, collector = _collector(
        work,
        clock=clock,
        transport=transport,
        market=market,
        window=timedelta(seconds=2),
        run_id="lab-complete-economic",
    )
    await collector.run(cycles=1)
    return await _finalize_and_analyze(
        "A",
        store=store,
        work=work,
        run_id=collector.run_id,
        extras={"bootstrap_skipped": True, "duplicate_trade": "trade-0"},
    )


async def run_scenario_b(work: Path) -> LabScenarioResult:
    clock = CoordinatedClock()
    recovered_at = clock() + timedelta(seconds=1)
    first_rows = [
        trade_row(wallet=WALLET_A, trade_id="recover-1", timestamp=recovered_at),
    ]
    transport = ScriptedJsonTransport(
        rows_by_call=[first_rows],
        failures_remaining=1,
    )
    ScriptedMarketStream.generation = 0

    def stream_factory(
        bus: Any,
        token_ids: tuple[str, ...],
        stale_after: timedelta,
    ) -> ScriptedMarketStream:
        del token_ids, stale_after
        return ScriptedMarketStream(
            bus,
            (book_event(clock, crossed=True), book_event(clock)),
            fail_first=True,
            park=clock,
        )

    market = _market_source(clock, stream_factory=stream_factory)
    store, collector = _collector(
        work,
        clock=clock,
        transport=transport,
        market=market,
        window=timedelta(seconds=12),
        run_id="lab-interrupt-recovery",
    )
    await collector.run(cycles=1)
    first_events = store.load_events(run_id=collector.run_id)
    first_ids = {event.evidence_id for event in first_events}
    first_wallet_ids = {
        event.evidence_id
        for event in first_events
        if event.event_kind is ObservationKind.WALLET_TRADE and event.source_event_id
    }
    later_rows = first_rows + [
        trade_row(wallet=WALLET_B, trade_id="recover-2", timestamp=clock()),
    ]
    clock_two = CoordinatedClock(clock())
    transport_two = ScriptedJsonTransport(rows_by_call=[later_rows])
    market_two = _market_source(clock_two, event=book_event(clock_two))
    store_two, collector_two = _collector(
        work,
        clock=clock_two,
        transport=transport_two,
        market=market_two,
        window=timedelta(seconds=12),
        run_id="lab-interrupt-recovery",
    )
    await collector_two.run(cycles=1)
    events = store_two.load_events(run_id=collector_two.run_id)
    wallet_events = [
        event
        for event in events
        if event.event_kind is ObservationKind.WALLET_TRADE and event.source_event_id
    ]
    aliased = [
        event
        for event in wallet_events
        if event.classification is EvidenceClassification.ACCEPTED
        and event.attribution_status is AttributionStatus.WALLET_ALIASED
    ]
    source_event_ids = [event.source_event_id for event in wallet_events]
    aliased_source_ids = [event.source_event_id for event in aliased]
    result = await _finalize_and_analyze(
        "B",
        store=store_two,
        work=work,
        run_id=collector_two.run_id,
        extras={
            "first_process_evidence_ids": sorted(first_ids),
            "first_process_wallet_ids": sorted(first_wallet_ids),
            "restart_event_count": len(events),
            "restart_wallet_count": len(wallet_events),
            "restart_wallet_ids": sorted(event.evidence_id for event in wallet_events),
            "unique_source_event_ids": len(set(source_event_ids)),
            "aliased_wallet_count": len(aliased),
            "unique_aliased_source_event_ids": len(set(aliased_source_ids)),
            "wallet_recovery_count": market.book_recovery_count + transport.calls,
            "book_recovery_count": market.book_recovery_count,
            "reconnect_count": market.reconnect_count,
            "transport_purposes": list(transport.purposes) + list(transport_two.purposes),
        },
    )
    return result


async def run_scenario_c(work: Path) -> LabScenarioResult:
    clock = CoordinatedClock()
    stale_rows = [
        trade_row(
            wallet=WALLET_A,
            trade_id=f"stale-{index}",
            timestamp=clock() + timedelta(seconds=40),
        )
        for index in range(3)
    ]
    transport = ScriptedJsonTransport(rows_by_call=[[], stale_rows])
    market = _market_source(clock, event=book_event(clock))
    store, collector = _collector(
        work,
        clock=clock,
        transport=transport,
        market=market,
        window=timedelta(seconds=45),
        run_id="lab-honest-failure",
    )
    await collector.run(cycles=1)
    return await _finalize_and_analyze(
        "C",
        store=store,
        work=work,
        run_id=collector.run_id,
        extras={"stale_quote_injected": True},
    )


async def _finalize_and_analyze(
    name: str,
    *,
    store: ResearchEvidenceStore,
    work: Path,
    run_id: str,
    extras: dict[str, object],
) -> LabScenarioResult:
    bundle_root = work / "bundles"
    bundle = finalize_research_experiment(store.path, bundle_root, run_id=run_id)
    before = sha256_file(bundle.database_path)
    with open_recorded_experiment_store(
        bundle.database_path,
        bundle_root=bundle.path,
        expected_database_sha256=bundle.sha256,
    ) as replica:
        first = replay_recorded_experiment(replica, run_id=run_id)
        second = replay_recorded_experiment(replica, run_id=run_id)
    after = sha256_file(bundle.database_path)
    experiment = ResearchEvidenceStore(
        bundle.database_path,
        read_only=True,
        immutable=True,
    ).load_experiment(run_id)
    if experiment is None:
        raise RuntimeError("lab experiment disappeared after finalization")
    report = detailed_replay_payload(
        first,
        experiment=experiment,
        run_id=run_id,
        source_database_sha256=bundle.sha256,
    )
    second_report = detailed_replay_payload(
        second,
        experiment=experiment,
        run_id=run_id,
        source_database_sha256=bundle.sha256,
    )
    return LabScenarioResult(
        name=name,
        run_id=run_id,
        report=report,
        replay_hashes=(result_hash(report), result_hash(second_report)),
        bundle_outcome=bundle.outcome,
        bundle_verified=bundle.verified,
        source_hash_before=before,
        source_hash_after=after,
        extras=extras,
    )


async def run_offline_proof(work: Path) -> dict[str, LabScenarioResult]:
    work.mkdir(parents=True, exist_ok=True)
    return {
        "A": await run_scenario_a(work / "scenario-a"),
        "B": await run_scenario_b(work / "scenario-b"),
        "C": await run_scenario_c(work / "scenario-c"),
    }


def lab_source_factory(
    clock: CoordinatedClock,
    *,
    rows: list[dict[str, Any]] | None = None,
    v2_pages: bool = False,
) -> tuple[
    Callable[..., Awaitable[tuple[tuple[Any, ...], dict[str, object]]]],
    ScriptedJsonTransport,
]:
    transport = ScriptedJsonTransport(
        rows_by_call=[rows or _complete_rows(clock)], v2_pages=v2_pages
    )
    market = _market_source(clock, event=book_event(clock))
    aliases = _aliases()

    async def factory(**_kwargs: object) -> tuple[tuple[Any, ...], dict[str, object]]:
        wallet = DataApiWalletPollSource(
            REST_TRADES_CANDIDATE,
            path="/v2/trades" if v2_pages else "/trades",
            source_id=TRADES_SOURCE_ID,
            aliases=aliases,
            transport=transport,
            poll_interval_seconds=1.0,
            initial_delay_seconds=0.5,
            clock=clock,
            monotonic_ns=clock.monotonic_ns,
            sleep=clock.park,
        )
        return (market, wallet), {
            "followed_aliases": sorted(aliases),
            "market_tokens": [TOKEN],
            "required_source_ids": ["rest_trades"],
            "optional_source_ids": ["clob_market_ws"],
            "unavailable": [],
        }

    return factory, transport
