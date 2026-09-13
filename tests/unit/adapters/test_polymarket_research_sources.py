from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from polysia.adapters.polymarket.request_scheduling import TradesSourceUnavailableError
from polysia.adapters.polymarket.research_sources import (
    ACTIVITY_SOURCE_ID,
    REST_ACTIVITY_CANDIDATE,
    USER_CHANNEL_CANDIDATE,
    DataApiWalletPollSource,
    FollowedMarketDiscovery,
    MarketDiscoverySnapshot,
    OfficialMarketStreamSource,
    TerminalMarketSnapshot,
    _normalize_wallet_row,
    discover_clob_market_fee_schedules,
    discover_followed_markets,
    discover_public_follow_set,
    public_wallet_alias,
)
from polysia.application.ports.copytrading import LeaderReadPurpose
from polysia.domain.events import MarketDataEvent
from polysia.domain.market import MarketFeeSchedule, MarketOrderBookSnapshot, OrderBookLevel
from polysia.domain.research_evidence.models import (
    AttributionStatus,
    ObservationKind,
    SourceCandidateStatus,
)

WALLET = "0x1111111111111111111111111111111111111111"
OBSERVED = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


class _BoundedClock:
    def __init__(self) -> None:
        self.n = 0

    def __call__(self) -> datetime:
        self.n += 1
        if self.n < 8:
            return OBSERVED
        return OBSERVED + timedelta(seconds=10)


class FakeTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    async def get_json(
        self,
        base_url: str,
        path: str,
        params: dict[str, str | int | bool],
        *,
        purpose: LeaderReadPurpose = LeaderReadPurpose.BASELINE,
    ) -> object:
        del purpose
        self.calls.append((base_url, path))
        return self.payload


class RoutingTransport:
    def __init__(self, payloads: dict[str, object]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, str, dict[str, str | int | bool]]] = []

    async def get_json(
        self,
        base_url: str,
        path: str,
        params: dict[str, str | int | bool],
        *,
        purpose: LeaderReadPurpose = LeaderReadPurpose.BASELINE,
    ) -> object:
        del purpose
        self.calls.append((base_url, path, params))
        return self.payloads[path]


class WalletRoutingTransport:
    def __init__(self, payloads: dict[str, object]) -> None:
        self.payloads = payloads
        self.calls: list[str] = []

    async def get_json(
        self,
        base_url: str,
        path: str,
        params: dict[str, str | int | bool],
        *,
        purpose: LeaderReadPurpose = LeaderReadPurpose.BASELINE,
    ) -> object:
        del base_url, path, purpose
        wallet = str(params["user"])
        self.calls.append(wallet)
        return self.payloads[wallet]


class SequencedTransport:
    def __init__(self, trades: list[object], markets: dict[str, object]) -> None:
        self._trades = iter(trades)
        self._markets = markets
        self.calls: list[str] = []

    async def get_json(
        self,
        base_url: str,
        path: str,
        params: dict[str, str | int | bool],
        *,
        purpose: LeaderReadPurpose = LeaderReadPurpose.BASELINE,
    ) -> object:
        del base_url, params, purpose
        self.calls.append(path)
        if path == "/trades":
            return next(self._trades)
        return self._markets[path]


class RecordingMarketStream:
    def __init__(self, token_ids: tuple[str, ...]) -> None:
        self.token_ids = token_ids

    async def run(self, *, max_events: int | None = None) -> None:
        del max_events
        await asyncio.Event().wait()


class RecoveryTransport:
    def __init__(self, clock: AdvancingClock) -> None:
        self._clock = clock
        self.purposes: list[LeaderReadPurpose] = []

    async def get_json(
        self,
        base_url: str,
        path: str,
        params: dict[str, str | int | bool],
        *,
        purpose: LeaderReadPurpose = LeaderReadPurpose.BASELINE,
    ) -> object:
        del base_url, path, params
        self.purposes.append(purpose)
        if len(self.purposes) == 1:
            raise TradesSourceUnavailableError(
                outage_started_at=self._clock(),
                retry_at=self._clock() + timedelta(seconds=1),
                reason="cooldown",
            )
        return []


class AdvancingClock:
    def __init__(self) -> None:
        self.now = OBSERVED

    def __call__(self) -> datetime:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.mark.asyncio
async def test_wallet_poll_source_aliases_and_does_not_emit_addresses() -> None:
    transport = FakeTransport(
        [
            {
                "proxyWallet": WALLET,
                "side": "BUY",
                "price": "0.51",
                "size": "2",
                "timestamp": int(OBSERVED.timestamp()),
                "conditionId": "0x" + "a" * 64,
                "asset": "token-1",
                "transactionHash": "0x" + "b" * 64,
            }
        ]
    )
    source = DataApiWalletPollSource(
        REST_ACTIVITY_CANDIDATE,
        path="/activity",
        source_id=ACTIVITY_SOURCE_ID,
        aliases={public_wallet_alias(WALLET): WALLET},
        transport=transport,
        clock=_BoundedClock(),
        monotonic_ns=lambda: 10,
        sleep=_noop_sleep,
        poll_interval_seconds=1,
    )
    events = []
    async for event in source.run(run_id="r1", deadline=OBSERVED + timedelta(seconds=5)):
        events.append(event)
    assert events
    assert events[0].leader_alias == public_wallet_alias(WALLET)
    assert WALLET not in events[0].leader_alias
    assert events[0].attribution_status is AttributionStatus.WALLET_ALIASED
    assert "user" not in events[0].provenance


@pytest.mark.asyncio
async def test_wallet_poll_source_does_not_emit_pre_run_backlog() -> None:
    transport = FakeTransport(
        [
            {
                "proxyWallet": WALLET,
                "side": "BUY",
                "price": "0.51",
                "size": "2",
                "timestamp": int(OBSERVED.timestamp()) - 3,
                "conditionId": "0x" + "a" * 64,
                "asset": "token-1",
                "transactionHash": "0x" + "b" * 64,
            }
        ]
    )
    source = DataApiWalletPollSource(
        REST_ACTIVITY_CANDIDATE,
        path="/activity",
        source_id=ACTIVITY_SOURCE_ID,
        aliases={public_wallet_alias(WALLET): WALLET},
        transport=transport,
        clock=_BoundedClock(),
        monotonic_ns=lambda: 10,
        sleep=_noop_sleep,
        poll_interval_seconds=1,
    )

    events = [
        event
        async for event in source.run(
            run_id="r1",
            deadline=OBSERVED + timedelta(seconds=5),
        )
    ]

    assert events == []
    assert source.health_snapshot()["bootstrap_rows_skipped"] >= 1


@pytest.mark.asyncio
async def test_wallet_poll_source_honors_initial_market_warmup() -> None:
    clock = AdvancingClock()
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        await clock.sleep(seconds)

    source = DataApiWalletPollSource(
        REST_ACTIVITY_CANDIDATE,
        path="/trades",
        source_id=ACTIVITY_SOURCE_ID,
        aliases={public_wallet_alias(WALLET): WALLET},
        transport=FakeTransport([]),
        clock=clock,
        monotonic_ns=lambda: 10,
        sleep=sleep,
        poll_interval_seconds=1,
        initial_delay_seconds=2,
    )

    events = [
        event
        async for event in source.run(
            run_id="r1",
            deadline=OBSERVED + timedelta(seconds=3),
        )
    ]

    assert events == []
    assert waits[0] == 2


@pytest.mark.asyncio
async def test_market_stream_is_not_wallet_attributable() -> None:
    async def factory():
        yield MarketDataEvent(
            source="polymarket",
            event_type="price_change",
            token_id="token-1",
            received_at=OBSERVED,
            exchange_ts=OBSERVED - timedelta(milliseconds=20),
            payload={"price": "0.42"},
            raw_payload={},
        )

    source = OfficialMarketStreamSource(
        token_ids=("token-1",),
        event_factory=factory,
        clock=lambda: OBSERVED,
        monotonic_ns=lambda: 5,
    )
    events = [
        event
        async for event in source.run(run_id="r1", deadline=OBSERVED + timedelta(seconds=1))
    ]
    assert events[0].event_kind is ObservationKind.MARKET_STATE
    assert events[0].attribution_status is AttributionStatus.NOT_APPLICABLE
    assert events[0].leader_alias is None
    assert source.candidate.wallet_attributable is False


@pytest.mark.asyncio
async def test_market_book_emits_side_aware_depth_and_fee_evidence() -> None:
    async def factory():
        yield MarketDataEvent(
            source="polymarket",
            event_type="book",
            token_id="token-1",
            received_at=OBSERVED,
            exchange_ts=OBSERVED - timedelta(milliseconds=20),
            payload={
                "market": "market-a",
                "bids": [
                    {"price": "0.48", "size": "4"},
                    {"price": "0.47", "size": "10"},
                ],
                "asks": [
                    {"price": "0.52", "size": "3"},
                    {"price": "0.53", "size": "10"},
                ],
            },
            raw_payload={},
        )

    source = OfficialMarketStreamSource(
        token_ids=("token-1",),
        event_factory=factory,
        clock=lambda: OBSERVED,
        monotonic_ns=lambda: 5,
        fee_schedules={
            "token-1": MarketFeeSchedule(
                enabled=True,
                rate=Decimal("0.25"),
                exponent=Decimal("2"),
                taker_only=True,
            )
        },
    )
    events = [
        event
        async for event in source.run(run_id="r1", deadline=OBSERVED + timedelta(seconds=1))
    ]

    assert len(events) == 3
    base, buy, sell = events
    assert base.market_reference == "market-a"
    assert base.price == Decimal("0.48")
    assert buy.side == "BUY" and buy.price == Decimal("0.52")
    assert sell.side == "SELL" and sell.price == Decimal("0.48")
    assert buy.provenance["book_levels"][1] == {"price": "0.53", "size": "10"}
    assert sell.provenance["fee_exponent"] == "2"
    assert buy.related_evidence_id == base.evidence_id
    assert buy.provenance["execution_evidence"] is True


def test_invalid_book_update_discards_stale_state_until_fresh_snapshot() -> None:
    source = OfficialMarketStreamSource(
        token_ids=("token-1",),
        clock=lambda: OBSERVED,
        monotonic_ns=lambda: 5,
    )

    fresh = MarketDataEvent(
        source="polymarket",
        event_type="book",
        token_id="token-1",
        received_at=OBSERVED,
        exchange_ts=OBSERVED,
        payload={
            "market": "market-a",
            "bids": [{"price": "0.48", "size": "4"}],
            "asks": [{"price": "0.52", "size": "4"}],
        },
        raw_payload={},
    )
    assert len(source._from_market_event(fresh, run_id="r1")) == 3

    invalid = MarketDataEvent(
        source="polymarket",
        event_type="price_change",
        token_id="token-1",
        received_at=OBSERVED + timedelta(seconds=1),
        exchange_ts=OBSERVED + timedelta(seconds=1),
        payload={"market": "market-a", "price_change": {"side": "BROKEN"}},
        raw_payload={},
    )
    invalid_events = source._from_market_event(invalid, run_id="r1")
    assert len(invalid_events) == 1
    assert invalid_events[0].price is None
    assert invalid_events[0].provenance["book_state"] == "invalid"
    assert source._books.get_book("token-1") is None

    incremental = MarketDataEvent(
        source="polymarket",
        event_type="price_change",
        token_id="token-1",
        received_at=OBSERVED + timedelta(seconds=2),
        exchange_ts=OBSERVED + timedelta(seconds=2),
        payload={
            "market": "market-a",
            "price_change": {"side": "BUY", "price": "0.49", "size": "5"},
        },
        raw_payload={},
    )
    waiting = source._from_market_event(incremental, run_id="r1")
    assert len(waiting) == 1
    assert waiting[0].provenance["book_validation_failure"] == "awaiting_fresh_snapshot"
    assert source._books.get_book("token-1") is None

    recovered = source._from_market_event(fresh, run_id="r1")
    assert len(recovered) == 3
    health = source.health_snapshot()
    assert health["book_validation_failure_count"] == 1
    assert health["invalid_book_token_count"] == 0
    assert health["usable_book_token_count"] == 1


@pytest.mark.asyncio
async def test_terminal_snapshot_emits_fresh_side_aware_evidence() -> None:
    requests: list[dict[str, str]] = []

    async def fetch(token_markets: dict[str, str]) -> TerminalMarketSnapshot:
        requests.append(dict(token_markets))
        return TerminalMarketSnapshot(
            books={
                "token-1": MarketOrderBookSnapshot(
                    token_id="token-1",
                    market_id="market-a",
                    timestamp=OBSERVED,
                    bids=(OrderBookLevel(price=Decimal("0.48"), size=Decimal("4")),),
                    asks=(OrderBookLevel(price=Decimal("0.52"), size=Decimal("5")),),
                    minimum_order_size=Decimal("1"),
                    tick_size=Decimal("0.01"),
                    book_hash="terminal-hash",
                )
            },
            fee_schedules={
                "token-1": MarketFeeSchedule(
                    enabled=True,
                    rate=Decimal("0.25"),
                    exponent=Decimal("2"),
                    taker_only=True,
                )
            },
        )

    source = OfficialMarketStreamSource(
        token_ids=("token-1",),
        clock=lambda: OBSERVED,
        monotonic_ns=lambda: 5,
        terminal_snapshot_fetcher=fetch,
    )
    events = await source.capture_terminal_evidence(
        run_id="r1",
        token_markets={"token-1": "market-a"},
    )

    assert requests == [{"token-1": "market-a"}]
    assert len(events) == 3
    assert [event.side for event in events] == [None, "BUY", "SELL"]
    assert events[2].price == Decimal("0.48")
    assert events[2].provenance["execution_evidence"] is True
    health = source.health_snapshot()
    assert health["terminal_snapshot_requested"] == 1
    assert health["terminal_snapshot_captured"] == 1
    assert health["terminal_snapshot_missing"] == 0


@pytest.mark.asyncio
async def test_terminal_snapshot_uses_resolved_settlement_when_book_is_closed() -> None:
    async def fetch(token_markets: dict[str, str]) -> TerminalMarketSnapshot:
        del token_markets
        return TerminalMarketSnapshot(books={}, fee_schedules={})

    async def settlements(token_markets: dict[str, str]) -> dict[str, Decimal]:
        assert token_markets == {"token-1": "market-a"}
        return {"token-1": Decimal("0")}

    source = OfficialMarketStreamSource(
        token_ids=("token-1",),
        clock=lambda: OBSERVED,
        monotonic_ns=lambda: 5,
        terminal_snapshot_fetcher=fetch,
        terminal_settlement_fetcher=settlements,
    )
    source._invalid_book_tokens.add("token-1")
    events = await source.capture_terminal_evidence(
        run_id="r1",
        token_markets={"token-1": "market-a"},
    )

    assert len(events) == 1
    assert events[0].price is None
    assert events[0].provenance["settlement_price"] == "0"
    assert (
        events[0].provenance["settlement_evidence_version"]
        == "official-terminal-settlement-v1"
    )
    health = source.health_snapshot()
    assert health["terminal_snapshot_requested"] == 1
    assert health["terminal_snapshot_captured"] == 1
    assert health["terminal_snapshot_missing"] == 0
    assert health["invalid_book_token_count"] == 0


@pytest.mark.asyncio
async def test_official_stream_refreshes_quiet_book_before_freshness_expires() -> None:
    clock = AdvancingClock()
    requests: list[dict[str, str]] = []

    async def fetch(token_markets: dict[str, str]) -> TerminalMarketSnapshot:
        requests.append(dict(token_markets))
        return TerminalMarketSnapshot(
            books={
                "token-1": MarketOrderBookSnapshot(
                    token_id="token-1",
                    market_id="market-a",
                    timestamp=clock(),
                    bids=(OrderBookLevel(price=Decimal("0.48"), size=Decimal("4")),),
                    asks=(OrderBookLevel(price=Decimal("0.52"), size=Decimal("5")),),
                    minimum_order_size=Decimal("1"),
                    tick_size=Decimal("0.01"),
                )
            },
            fee_schedules={
                "token-1": MarketFeeSchedule(
                    enabled=False,
                    rate=None,
                    exponent=None,
                    taker_only=None,
                )
            },
        )

    source = OfficialMarketStreamSource(
        token_ids=("token-1",),
        token_markets={"token-1": "market-a"},
        clock=clock,
        sleep=clock.sleep,
        market_stream_factory=lambda bus, tokens, stale: RecordingMarketStream(tokens),
        terminal_snapshot_fetcher=fetch,
        snapshot_refresh_interval_seconds=20,
    )
    events = [
        event
        async for event in source.run(
            run_id="r1",
            deadline=OBSERVED + timedelta(seconds=2),
        )
    ]

    assert requests == [{"token-1": "market-a"}]
    assert len(events) == 3
    assert events[1].provenance["execution_evidence"] is True
    assert events[1].provenance["source_event_type"] == "book"
    health = source.health_snapshot()
    assert health["snapshot_refresh_count"] == 1
    assert health["snapshot_refresh_failure_count"] == 0
    assert health["snapshot_refresh_missing"] == 0


def test_wallet_observation_identity_preserves_distinct_wallet_attribution() -> None:
    second_wallet = "0x2222222222222222222222222222222222222222"
    shared = {
        "side": "BUY",
        "price": "0.51",
        "size": "2",
        "timestamp": int(OBSERVED.timestamp()) - 3,
        "conditionId": "0x" + "a" * 64,
        "asset": "token-1",
        "transactionHash": "0x" + "b" * 64,
    }
    first = _normalize_wallet_row(
        {**shared, "proxyWallet": WALLET},
        source_id=ACTIVITY_SOURCE_ID,
        alias=public_wallet_alias(WALLET),
        expected_wallet=WALLET,
        run_id="r1",
        observed_time=OBSERVED,
        receive_ns=1,
        normalize_ns=2,
    )
    second = _normalize_wallet_row(
        {**shared, "proxyWallet": second_wallet},
        source_id=ACTIVITY_SOURCE_ID,
        alias=public_wallet_alias(second_wallet),
        expected_wallet=second_wallet,
        run_id="r1",
        observed_time=OBSERVED,
        receive_ns=1,
        normalize_ns=2,
    )
    assert first.source_event_id == second.source_event_id
    assert first.evidence_id != second.evidence_id
    assert first.leader_alias != second.leader_alias


@pytest.mark.asyncio
async def test_public_discovery_and_unavailable_user_channel() -> None:
    transport = FakeTransport(
        [
            {
                "proxyWallet": WALLET,
                "asset": "token-1",
            }
        ]
    )
    aliases, tokens = await discover_public_follow_set(transport, wallet_limit=2)
    assert public_wallet_alias(WALLET) in aliases
    assert aliases[public_wallet_alias(WALLET)] == WALLET
    assert tokens == ("token-1",)
    assert USER_CHANNEL_CANDIDATE.status is SourceCandidateStatus.UNAVAILABLE
    assert USER_CHANNEL_CANDIDATE.unavailable_reason is not None


@pytest.mark.asyncio
async def test_followed_market_discovery_matches_wallet_source_lookback() -> None:
    condition = "0x" + "a" * 64
    transport = RoutingTransport(
        {
            "/trades": [
                {
                    "asset": "token-1",
                    "conditionId": condition,
                }
            ]
        }
    )

    markets = await discover_followed_markets(
        transport,
        {public_wallet_alias(WALLET): WALLET},
        clock=lambda: OBSERVED,
    )

    assert markets == {"token-1": condition}
    _, _, params = transport.calls[0]
    assert params["start"] == int((OBSERVED - timedelta(minutes=30)).timestamp())
    assert params["end"] == int(OBSERVED.timestamp())
    assert params["limit"] == 500


@pytest.mark.asyncio
async def test_followed_market_discovery_ranks_recent_tokens_across_wallets() -> None:
    second_wallet = "0x2222222222222222222222222222222222222222"
    conditions = {
        token: "0x" + digit * 64
        for token, digit in (
            ("token-1", "1"),
            ("token-2", "2"),
            ("token-3", "3"),
            ("token-4", "4"),
        )
    }
    transport = WalletRoutingTransport(
        {
            WALLET: [
                {
                    "asset": "token-1",
                    "conditionId": conditions["token-1"],
                    "timestamp": 100,
                },
                {
                    "asset": "token-2",
                    "conditionId": conditions["token-2"],
                    "timestamp": 99,
                },
                {
                    "asset": "token-3",
                    "conditionId": conditions["token-3"],
                    "timestamp": 98,
                },
            ],
            second_wallet: [
                {
                    "asset": "token-4",
                    "conditionId": conditions["token-4"],
                    "timestamp": 101,
                }
            ],
        }
    )

    markets = await discover_followed_markets(
        transport,
        {
            public_wallet_alias(WALLET): WALLET,
            public_wallet_alias(second_wallet): second_wallet,
        },
        token_limit=3,
        clock=lambda: OBSERVED,
    )

    assert tuple(markets) == ("token-4", "token-1", "token-2")
    assert transport.calls == [WALLET, second_wallet]


@pytest.mark.asyncio
async def test_clob_market_info_resolves_fee_curve_for_requested_tokens() -> None:
    condition = "0x" + "a" * 64
    transport = RoutingTransport(
        {
            f"/clob-markets/{condition}": {
                "t": [{"t": "token-1"}, {"t": "token-2"}],
                "fd": {"r": "0.04", "e": 1, "to": True},
            }
        }
    )

    schedules = await discover_clob_market_fee_schedules(
        transport,
        {"token-1": condition},
    )

    assert set(schedules) == {"token-1"}
    assert schedules["token-1"] == MarketFeeSchedule(
        enabled=True,
        rate=Decimal("0.04"),
        exponent=Decimal("1"),
        taker_only=True,
    )


@pytest.mark.asyncio
async def test_followed_market_discovery_adds_tokens_and_resolves_fee_once() -> None:
    first_condition = "0x" + "a" * 64
    second_condition = "0x" + "b" * 64
    fee = {"fd": {"r": "0.04", "e": 1, "to": True}}
    transport = SequencedTransport(
        [
            [{"asset": "token-1", "conditionId": first_condition}],
            [
                {"asset": "token-1", "conditionId": first_condition},
                {"asset": "token-2", "conditionId": second_condition},
            ],
        ],
        {
            f"/clob-markets/{first_condition}": {
                **fee,
                "t": [{"t": "token-1"}],
            },
            f"/clob-markets/{second_condition}": {
                **fee,
                "t": [{"t": "token-2"}],
            },
        },
    )
    discovery = FollowedMarketDiscovery(
        transport,
        {public_wallet_alias(WALLET): WALLET},
        clock=lambda: OBSERVED,
    )

    first = await discovery.refresh()
    second = await discovery.refresh()

    assert tuple(first.token_markets) == ("token-1",)
    assert tuple(second.token_markets) == ("token-1", "token-2")
    assert set(second.fee_schedules) == {"token-1", "token-2"}
    assert transport.calls.count(f"/clob-markets/{first_condition}") == 1
    assert transport.calls.count(f"/clob-markets/{second_condition}") == 1


@pytest.mark.asyncio
async def test_followed_market_discovery_rotates_out_expired_tokens() -> None:
    first_condition = "0x" + "a" * 64
    second_condition = "0x" + "b" * 64
    fee = {"fd": {"r": "0.04", "e": 1, "to": True}}
    transport = SequencedTransport(
        [
            [{"asset": "token-1", "conditionId": first_condition, "timestamp": 1}],
            [{"asset": "token-2", "conditionId": second_condition, "timestamp": 2}],
        ],
        {
            f"/clob-markets/{first_condition}": {**fee, "t": [{"t": "token-1"}]},
            f"/clob-markets/{second_condition}": {**fee, "t": [{"t": "token-2"}]},
        },
    )
    discovery = FollowedMarketDiscovery(
        transport,
        {public_wallet_alias(WALLET): WALLET},
        token_limit=1,
        clock=lambda: OBSERVED,
    )

    first = await discovery.refresh()
    second = await discovery.refresh()

    assert tuple(first.token_markets) == ("token-1",)
    assert tuple(second.token_markets) == ("token-2",)
    assert set(second.fee_schedules) == {"token-2"}


@pytest.mark.asyncio
async def test_market_stream_rotates_subscription_to_current_wallet_tokens() -> None:
    clock = AdvancingClock()
    streams: list[RecordingMarketStream] = []

    def stream_factory(
        bus: object,
        token_ids: tuple[str, ...],
        stale_after: timedelta,
    ) -> RecordingMarketStream:
        del bus, stale_after
        stream = RecordingMarketStream(token_ids)
        streams.append(stream)
        return stream

    async def discover() -> MarketDiscoverySnapshot:
        return MarketDiscoverySnapshot(
            token_markets={"token-2": "market-2"},
            fee_schedules={},
        )

    requests: list[dict[str, str]] = []

    async def fetch(token_markets: dict[str, str]) -> TerminalMarketSnapshot:
        requests.append(dict(token_markets))
        token = next(iter(token_markets))
        market = token_markets[token]
        return TerminalMarketSnapshot(
            books={
                token: MarketOrderBookSnapshot(
                    token_id=token,
                    market_id=market,
                    timestamp=clock(),
                    bids=(OrderBookLevel(price=Decimal("0.48"), size=Decimal("4")),),
                    asks=(OrderBookLevel(price=Decimal("0.52"), size=Decimal("5")),),
                    minimum_order_size=Decimal("1"),
                    tick_size=Decimal("0.01"),
                )
            },
            fee_schedules={token: MarketFeeSchedule(enabled=False)},
        )

    source = OfficialMarketStreamSource(
        token_ids=("token-1",),
        clock=clock,
        sleep=clock.sleep,
        market_discovery=discover,
        discovery_interval_seconds=2,
        market_stream_factory=stream_factory,
        token_markets={"token-1": "market-1"},
        terminal_snapshot_fetcher=fetch,
        snapshot_refresh_interval_seconds=20,
    )

    events = [
        event
        async for event in source.run(
            run_id="r1",
            deadline=OBSERVED + timedelta(seconds=3),
        )
    ]

    assert len(events) == 6
    assert requests == [
        {"token-1": "market-1"},
        {"token-2": "market-2"},
    ]
    assert [stream.token_ids for stream in streams] == [
        ("token-1",),
        ("token-2",),
    ]
    assert source.subscription_update_count == 1


@pytest.mark.asyncio
async def test_wallet_source_uses_recovery_probe_then_resumes_discovery() -> None:
    clock = AdvancingClock()
    transport = RecoveryTransport(clock)
    source = DataApiWalletPollSource(
        REST_ACTIVITY_CANDIDATE,
        path="/trades",
        source_id=ACTIVITY_SOURCE_ID,
        aliases={public_wallet_alias(WALLET): WALLET},
        transport=transport,
        clock=clock,
        monotonic_ns=lambda: 10,
        sleep=clock.sleep,
        poll_interval_seconds=1,
    )

    events = [
        event
        async for event in source.run(
            run_id="r1",
            deadline=OBSERVED + timedelta(seconds=4),
        )
    ]

    assert transport.purposes[:3] == [
        LeaderReadPurpose.DISCOVERY,
        LeaderReadPurpose.RECOVERY,
        LeaderReadPurpose.DISCOVERY,
    ]
    assert events[0].provenance["failure_class"] == "trades_circuit_open"
    health = source.health_snapshot()
    assert health["availability"] == "available"
    assert health["recovery_count"] == 1


async def _noop_sleep(delay: float) -> None:
    del delay
