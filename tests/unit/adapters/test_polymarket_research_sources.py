from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from polysia.adapters.polymarket.request_scheduling import TradesSourceUnavailableError
from polysia.adapters.polymarket.research_sources import (
    ACTIVITY_SOURCE_ID,
    DATA_API_V2_ACTIVITY_PATH,
    DATA_API_V2_TRADES_PATH,
    REST_ACTIVITY_CANDIDATE,
    REST_TRADES_CANDIDATE,
    TRADES_SOURCE_ID,
    USER_CHANNEL_CANDIDATE,
    DataApiGlobalTradePollSource,
    DataApiWalletPollSource,
    FollowedMarketDiscovery,
    IncompleteWalletWindowError,
    MarketDiscoverySnapshot,
    OfficialMarketStreamSource,
    TerminalMarketSnapshot,
    _normalize_wallet_row,
    data_api_v2_rows,
    discover_clob_market_fee_schedules,
    discover_followed_markets,
    discover_public_follow_set,
    fetch_data_api_v2_window,
    public_wallet_alias,
)
from polysia.application.ports.copytrading import LeaderReadPurpose
from polysia.domain.events import MarketDataEvent
from polysia.domain.market import MarketFeeSchedule, MarketOrderBookSnapshot, OrderBookLevel
from polysia.domain.research_evidence.models import (
    AttributionStatus,
    IntervalValidity,
    ObservationKind,
    ResearchInterval,
    SourceCandidateStatus,
)
from polysia.storage.research_evidence import ResearchEvidenceStore

WALLET = "0x1111111111111111111111111111111111111111"
OBSERVED = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def _v2(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "data": rows,
        "pagination": {
            "has_more": False,
            "limit": len(rows),
            "next_cursor": None,
            "offset": 0,
        },
    }


def test_v2_feed_requires_explicit_array_data() -> None:
    for payload in ({}, {"data": None}):
        with pytest.raises(TypeError, match="missing"):
            data_api_v2_rows(payload)
    assert data_api_v2_rows(_v2([])) == []
    with pytest.raises(TypeError, match="list of objects"):
        data_api_v2_rows({"data": {"proxy_wallet": WALLET}})


class _BoundedClock:
    def __init__(self, *, limit: int = 8) -> None:
        self.n = 0
        self.limit = limit

    def __call__(self) -> datetime:
        self.n += 1
        if self.n < self.limit:
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


class CursorTransport:
    def __init__(self, pages: list[object]) -> None:
        self.pages = iter(pages)
        self.calls: list[dict[str, str | int | bool]] = []

    async def get_json(
        self,
        base_url: str,
        path: str,
        params: dict[str, str | int | bool],
        *,
        purpose: LeaderReadPurpose = LeaderReadPurpose.BASELINE,
    ) -> object:
        del base_url, path, purpose
        self.calls.append(dict(params))
        result = next(self.pages)
        if isinstance(result, Exception):
            raise result
        return result


def _page(rows: list[dict[str, object]], cursor: str | None) -> dict[str, object]:
    return {
        "data": rows,
        "pagination": {"has_more": cursor is not None, "next_cursor": cursor},
    }


def _trade(trade_id: str, timestamp: int = int(OBSERVED.timestamp())) -> dict[str, object]:
    return {
        "id": trade_id,
        "proxy_wallet": WALLET,
        "timestamp": timestamp,
        "side": "BUY",
        "price": "0.5",
        "size": "1",
        "condition_id": "0x" + "a" * 64,
        "token_id": "token-1",
        "transaction_hash": "0x" + trade_id * 64,
    }


def test_trade_match_identity_survives_endpoint_specific_row_id() -> None:
    row = _trade("a")
    common = dict(
        source_id=ACTIVITY_SOURCE_ID, alias=public_wallet_alias(WALLET),
        expected_wallet=WALLET, run_id="run", observed_time=OBSERVED,
        receive_ns=1, normalize_ns=2,
    )
    activity = _normalize_wallet_row(row, **common)
    trades_row = {key: value for key, value in row.items() if key != "id"}
    trades = _normalize_wallet_row(trades_row, **common)
    assert activity.source_event_id != trades.source_event_id
    assert activity.provenance["source_match_id"] == trades.provenance["source_match_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [DATA_API_V2_TRADES_PATH, DATA_API_V2_ACTIVITY_PATH])
async def test_v2_window_walk_keeps_filters_and_page_two_timestamp_ties(
    path: str,
) -> None:
    transport = CursorTransport(
        [_page([_trade("a")], "next"), _page([_trade("b"), _trade("a")], None)]
    )
    params: dict[str, str | int | bool] = {
        "user": WALLET,
        "start": 1,
        "end": int(OBSERVED.timestamp()),
        "limit": 1,
    }
    if path == DATA_API_V2_ACTIVITY_PATH:
        params.update({"type": "TRADE", "sort_by": "TIMESTAMP", "sort_direction": "ASC"})
    rows = await fetch_data_api_v2_window(transport, path, params)
    assert [row["id"] for row in rows] == ["a", "b", "a"]
    assert transport.calls == [params, {**params, "cursor": "next"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pages", "expected"),
    [
        ([_page([_trade("a")], "next"), OSError("later page")], OSError),
        ([_page([_trade("a")], "next"), {"data": None}], TypeError),
        ([_page([_trade("a")], "next"), {"data": []}], TypeError),
        (
            [
                _page([_trade("a")], "next"),
                {"data": [], "pagination": {"has_more": False, "next_cursor": "wrong"}},
            ],
            TypeError,
        ),
        ([_page([_trade("a")], "next"), _page([], "next")], IncompleteWalletWindowError),
        ([_page([_trade("a")], "next")], IncompleteWalletWindowError),
    ],
)
async def test_v2_window_never_returns_partial_pages(
    pages: list[object], expected: type[Exception]
) -> None:
    transport = CursorTransport(pages)
    with pytest.raises(expected):
        await fetch_data_api_v2_window(
            transport,
            DATA_API_V2_TRADES_PATH,
            {"user": WALLET},
            max_pages=1 if len(pages) == 1 else 20,
        )


@pytest.mark.asyncio
async def test_v2_window_budget_and_confirmed_empty() -> None:
    assert (
        await fetch_data_api_v2_window(
            CursorTransport([_page([], None)]), DATA_API_V2_TRADES_PATH, {"user": WALLET}
        )
        == []
    )
    with pytest.raises(IncompleteWalletWindowError, match="budget_exhausted"):
        await fetch_data_api_v2_window(
            CursorTransport([_page([], "more")]),
            DATA_API_V2_TRADES_PATH,
            {"user": WALLET},
            max_requests=1,
        )
    ticks = iter((0.0, 0.0, 2.0))
    with pytest.raises(IncompleteWalletWindowError, match="time_budget"):
        await fetch_data_api_v2_window(
            CursorTransport([_page([_trade("a")], None)]),
            DATA_API_V2_TRADES_PATH,
            {"user": WALLET},
            max_elapsed_seconds=1.0,
            monotonic=lambda: next(ticks),
        )


@pytest.mark.asyncio
async def test_v2_window_cancels_awaited_later_page_at_absolute_deadline() -> None:
    class HangingSecondPage(CursorTransport):
        async def get_json(self, *args: object, **kwargs: object) -> object:
            if self.calls:
                await asyncio.Event().wait()
            return await super().get_json(*args, **kwargs)

    captured: list[str] = []
    transport = HangingSecondPage([_page([_trade("a")], "more")])
    with pytest.raises(IncompleteWalletWindowError, match="time_budget_exhausted"):
        await fetch_data_api_v2_window(
            transport,
            DATA_API_V2_TRADES_PATH,
            {"user": WALLET},
            max_elapsed_seconds=0.02,
            on_page=lambda rows: captured.extend(str(row["id"]) for row in rows),
        )
    assert captured == ["a"]
    assert transport.calls == [{"user": WALLET}]


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
        del base_url, purpose
        assert path == "/v2/trades"
        wallet = str(params["user"])
        self.calls.append(wallet)
        return _v2(self.payloads[wallet])  # type: ignore[arg-type]


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
        if path == "/v2/trades":
            return _v2(next(self._trades))  # type: ignore[arg-type]
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
async def test_wallet_poll_source_accepts_v2_envelope_and_uses_v2_parameters() -> None:
    transport = RoutingTransport(
        {
            DATA_API_V2_TRADES_PATH: _v2(
                [
                    {
                        "proxy_wallet": WALLET,
                        "side": "BUY",
                        "price": "0.51",
                        "size": "2",
                        "timestamp": int(OBSERVED.timestamp()),
                        "condition_id": "0x" + "a" * 64,
                        "token_id": "token-1",
                        "transaction_hash": "0x" + "b" * 64,
                    }
                ]
            )
        }
    )
    source = DataApiWalletPollSource(
        REST_ACTIVITY_CANDIDATE,
        path=DATA_API_V2_TRADES_PATH,
        source_id=ACTIVITY_SOURCE_ID,
        aliases={public_wallet_alias(WALLET): WALLET},
        transport=transport,
        clock=_BoundedClock(limit=20),
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

    assert events
    assert events[0].outcome_reference == "token-1"
    _, path, params = transport.calls[0]
    assert path == DATA_API_V2_TRADES_PATH
    assert params["taker_only"] is False
    assert "takerOnly" not in params
    assert "offset" not in params


@pytest.mark.asyncio
async def test_wallet_poll_emits_page_two_ties_once_in_timestamp_order() -> None:
    clock = AdvancingClock()
    transport = CursorTransport(
        [
            _page([_trade("late", int(OBSERVED.timestamp()) + 1)], "next"),
            _page(
                [
                    _trade("early"),
                    _trade("tie", int(OBSERVED.timestamp()) + 1),
                    _trade("late", int(OBSERVED.timestamp()) + 1),
                ],
                None,
            ),
        ]
    )
    source = DataApiWalletPollSource(
        REST_ACTIVITY_CANDIDATE,
        path=DATA_API_V2_TRADES_PATH,
        source_id=ACTIVITY_SOURCE_ID,
        aliases={public_wallet_alias(WALLET): WALLET},
        transport=transport,
        clock=clock,
        sleep=clock.sleep,
        poll_interval_seconds=1,
    )
    events = [
        event async for event in source.run(run_id="r1", deadline=OBSERVED + timedelta(seconds=1))
    ]
    assert [event.source_time for event in events] == [
        OBSERVED,
        OBSERVED + timedelta(seconds=1),
        OBSERVED + timedelta(seconds=1),
    ]
    assert len({event.evidence_id for event in events}) == 3
    assert all(event.admission_time is not None for event in events)
    assert all(event.admission_time >= event.observed_time for event in events)
    assert source.health_snapshot()["last_request_outcome"] == "success_events"
    stages = source.health_snapshot()["wallet_diagnostics"][public_wallet_alias(WALLET)]
    assert stages["response_pages"] == 2
    assert stages["parsed_rows"] == 4
    assert stages["admitted_occurrences"] == 3


@pytest.mark.asyncio
async def test_wallet_source_counts_malformed_trade_as_incomplete() -> None:
    alias = public_wallet_alias(WALLET)
    row = {**_trade("wrong"), "side": "HOLD"}
    clock = AdvancingClock()
    source = DataApiWalletPollSource(
        REST_TRADES_CANDIDATE,
        path=DATA_API_V2_TRADES_PATH,
        source_id=TRADES_SOURCE_ID,
        aliases={alias: WALLET},
        transport=CursorTransport([_page([row], None)]),
        clock=clock,
        sleep=clock.sleep,
        poll_interval_seconds=1,
    )
    events = [
        event async for event in source.run(
            run_id="identity-rejection", deadline=OBSERVED + timedelta(seconds=1)
        )
    ]
    assert len(events) == 1
    assert events[0].event_kind is ObservationKind.CONTROL
    stages = source.health_snapshot()["wallet_diagnostics"][alias]
    assert stages["parsed_rows"] == 1
    assert stages["eligible_occurrences"] == 0
    assert stages["incomplete_windows"] == 1
    assert stages["admitted_occurrences"] == 0


@pytest.mark.asyncio
async def test_wallet_source_counts_bootstrap_filter_separately_from_empty() -> None:
    alias = public_wallet_alias(WALLET)
    clock = AdvancingClock()
    source = DataApiWalletPollSource(
        REST_TRADES_CANDIDATE,
        path=DATA_API_V2_TRADES_PATH,
        source_id=TRADES_SOURCE_ID,
        aliases={alias: WALLET},
        transport=CursorTransport([_page([_trade("old", int(OBSERVED.timestamp()) - 1)], None)]),
        clock=clock, sleep=clock.sleep, poll_interval_seconds=1,
    )
    events = [
        event async for event in source.run(
            run_id="filtered", deadline=OBSERVED + timedelta(seconds=1)
        )
    ]
    assert events == []
    stages = source.health_snapshot()["wallet_diagnostics"][alias]
    assert stages["parsed_rows"] == 1
    assert stages["complete_windows"] == 1
    assert stages["empty_windows"] == 0
    assert stages["last_outcome"] == "success_filtered"


@pytest.mark.asyncio
async def test_wallet_poll_later_page_failure_keeps_window_incomplete(
    tmp_path: Path,
) -> None:
    clock = AdvancingClock()
    transport = CursorTransport([_page([_trade("first")], "next"), OSError("lost")])
    source = DataApiWalletPollSource(
        REST_ACTIVITY_CANDIDATE,
        path=DATA_API_V2_TRADES_PATH,
        source_id=ACTIVITY_SOURCE_ID,
        aliases={public_wallet_alias(WALLET): WALLET},
        transport=transport,
        clock=clock,
        sleep=clock.sleep,
        poll_interval_seconds=1,
    )
    store = ResearchEvidenceStore(tmp_path / "evidence.sqlite3")
    store.initialize()
    source.set_pending_observer(store.capture_pending_observations)
    source.set_progress_store(
        store.completed_source_windows, store.record_completed_source_windows
    )
    events = [
        event async for event in source.run(run_id="r1", deadline=OBSERVED + timedelta(seconds=1))
    ]
    assert len(events) == 1
    assert events[0].event_kind is ObservationKind.CONTROL
    assert source.health_snapshot()["last_successful_request_at"] is None
    assert source.health_snapshot()["last_request_outcome"] == "transient_error"
    stages = source.health_snapshot()["wallet_diagnostics"][public_wallet_alias(WALLET)]
    assert stages["parsed_rows"] == 1
    assert stages["incomplete_windows"] == 1
    assert stages["admitted_occurrences"] == 0
    assert store.completed_source_windows("r1", ACTIVITY_SOURCE_ID) == {}
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM research_pending_observations"
        ).fetchone() == (1,)

    recovered_clock = AdvancingClock()
    recovered_clock.now = OBSERVED + timedelta(seconds=2)
    recovered = DataApiWalletPollSource(
        REST_ACTIVITY_CANDIDATE,
        path=DATA_API_V2_TRADES_PATH,
        source_id=ACTIVITY_SOURCE_ID,
        aliases={public_wallet_alias(WALLET): WALLET},
        transport=CursorTransport([_page([_trade("first")], None)]),
        clock=recovered_clock,
        sleep=recovered_clock.sleep,
        poll_interval_seconds=1,
    )
    recovered.set_collection_start(OBSERVED)
    recovered.set_pending_observer(store.capture_pending_observations)
    recovered.set_progress_store(
        store.completed_source_windows, store.record_completed_source_windows
    )
    admitted = [
        event async for event in recovered.run(
            run_id="r1", deadline=OBSERVED + timedelta(seconds=3)
        )
    ]
    assert len(admitted) == 1
    assert admitted[0].observed_time == OBSERVED
    assert admitted[0].admission_time == OBSERVED + timedelta(seconds=2)

    store.persist_interval(
        ResearchInterval(
            interval_id="window-1",
            started_at=OBSERVED,
            ended_at=None,
            validity=IntervalValidity.OPEN,
            reason="open",
            code_sha=None,
            configuration_digest=None,
            policy_version="test-v1",
        )
    )
    store.persist_event(events[0], interval_id="window-1")
    assert store.watermark(ACTIVITY_SOURCE_ID)[0] is None


@pytest.mark.asyncio
async def test_wallet_completed_boundary_waits_for_consumed_batch(tmp_path: Path) -> None:
    clock = AdvancingClock()
    source = DataApiWalletPollSource(
        REST_TRADES_CANDIDATE,
        path=DATA_API_V2_TRADES_PATH,
        source_id=TRADES_SOURCE_ID,
        aliases={public_wallet_alias(WALLET): WALLET},
        transport=CursorTransport([_page([_trade("one"), _trade("two")], None)]),
        clock=clock, sleep=clock.sleep, poll_interval_seconds=1,
    )
    store = ResearchEvidenceStore(tmp_path / "evidence.sqlite3")
    store.initialize()
    source.set_progress_store(
        store.completed_source_windows, store.record_completed_source_windows
    )
    iterator = source.run(run_id="batch", deadline=OBSERVED + timedelta(seconds=1))
    first = await anext(iterator)
    assert first.admission_time == OBSERVED
    assert store.completed_source_windows("batch", TRADES_SOURCE_ID) == {}
    await iterator.aclose()
    assert store.completed_source_windows("batch", TRADES_SOURCE_ID) == {}


@pytest.mark.asyncio
async def test_wallet_poll_malformed_trade_row_cannot_advance_completed_end() -> None:
    clock = AdvancingClock()
    malformed = {key: value for key, value in _trade("a").items() if key != "price"}
    transport = CursorTransport([_page([malformed], None)])
    source = DataApiWalletPollSource(
        REST_ACTIVITY_CANDIDATE, path=DATA_API_V2_TRADES_PATH,
        source_id=ACTIVITY_SOURCE_ID,
        aliases={public_wallet_alias(WALLET): WALLET}, transport=transport,
        clock=clock, sleep=clock.sleep, poll_interval_seconds=1,
    )
    events = [
        event async for event in source.run(
            run_id="malformed", deadline=OBSERVED + timedelta(seconds=1)
        )
    ]
    assert len(events) == 1 and events[0].event_kind is ObservationKind.CONTROL
    assert source.health_snapshot()["last_successful_request_at"] is None
    assert source.health_snapshot()["last_request_outcome"] == "incomplete_window"


def test_pending_first_observation_survives_store_restart_without_admission(
    tmp_path: Path,
) -> None:
    path = tmp_path / "evidence.sqlite3"
    first = ResearchEvidenceStore(path)
    first.initialize()
    first_time = first.capture_pending_observations(
        "run-1", ACTIVITY_SOURCE_ID, "pub-wallet", ("event-1",), OBSERVED
    )
    assert first_time == {"event-1": OBSERVED}
    restarted = ResearchEvidenceStore(path)
    restarted.initialize()
    again = restarted.capture_pending_observations(
        "run-1", ACTIVITY_SOURCE_ID, "pub-wallet", ("event-1",),
        OBSERVED + timedelta(seconds=10),
    )
    assert again == first_time
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM research_events").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM research_pending_observations"
        ).fetchone()[0] == 1


@pytest.mark.asyncio
async def test_v2_completed_window_resumes_with_overlap_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "evidence.sqlite3"
    store = ResearchEvidenceStore(path)
    store.initialize()
    alias = public_wallet_alias(WALLET)
    clock = AdvancingClock()
    first_transport = CursorTransport([_page([_trade("a")], None)])
    first = DataApiWalletPollSource(
        REST_ACTIVITY_CANDIDATE, path=DATA_API_V2_TRADES_PATH,
        source_id=ACTIVITY_SOURCE_ID, aliases={alias: WALLET},
        transport=first_transport, clock=clock, sleep=clock.sleep,
        poll_interval_seconds=1,
    )
    first.set_pending_observer(store.capture_pending_observations)
    first.set_progress_store(
        store.completed_source_windows, store.record_completed_source_windows
    )
    assert len([
        event async for event in first.run(
            run_id="run-1", deadline=OBSERVED + timedelta(seconds=1)
        )
    ]) == 1
    assert store.completed_source_windows("run-1", ACTIVITY_SOURCE_ID) == {alias: OBSERVED}

    restarted_store = ResearchEvidenceStore(path)
    restarted_store.initialize()
    restarted_clock = AdvancingClock()
    restarted_clock.now = OBSERVED + timedelta(seconds=2)
    second_transport = CursorTransport([_page([_trade("a")], None)])
    restarted = DataApiWalletPollSource(
        REST_ACTIVITY_CANDIDATE, path=DATA_API_V2_TRADES_PATH,
        source_id=ACTIVITY_SOURCE_ID, aliases={alias: WALLET},
        transport=second_transport, clock=restarted_clock, sleep=restarted_clock.sleep,
        poll_interval_seconds=1,
    )
    restarted.set_collection_start(OBSERVED)
    restarted.set_pending_observer(restarted_store.capture_pending_observations)
    restarted.set_progress_store(
        restarted_store.completed_source_windows,
        restarted_store.record_completed_source_windows,
    )
    repeated = [
        event async for event in restarted.run(
            run_id="run-1", deadline=OBSERVED + timedelta(seconds=3)
        )
    ]
    assert len(repeated) == 1
    assert repeated[0].observed_time == OBSERVED
    assert repeated[0].admission_time == OBSERVED + timedelta(seconds=2)
    assert second_transport.calls[0]["start"] == int((OBSERVED - timedelta(seconds=30)).timestamp())


@pytest.mark.asyncio
async def test_global_candidate_filters_attributed_rows_client_side_without_time_params() -> None:
    clock = AdvancingClock()
    other = {**_trade("b"), "proxy_wallet": "0x" + "2" * 40}
    transport = CursorTransport([_page([_trade("a"), other], None)])
    source = DataApiGlobalTradePollSource(
        aliases={public_wallet_alias(WALLET): WALLET}, transport=transport,
        clock=clock, sleep=clock.sleep,
    )
    events = [
        event async for event in source.run(
            run_id="global", deadline=OBSERVED + timedelta(seconds=1)
        )
    ]
    assert len(events) == 1
    assert events[0].leader_alias == public_wallet_alias(WALLET)
    assert transport.calls[0] == {"limit": 500, "taker_only": False}
    assert source.health_snapshot()["coverage_scope"] == (
        "bounded_global_snapshot_not_interval_coverage"
    )


@pytest.mark.asyncio
async def test_global_candidate_budget_exhaustion_never_publishes_partial_rows() -> None:
    clock = AdvancingClock()
    transport = CursorTransport(
        [_page([_trade("a")], str(index)) for index in range(1, 5)]
    )
    source = DataApiGlobalTradePollSource(
        aliases={public_wallet_alias(WALLET): WALLET}, transport=transport,
        clock=clock, sleep=clock.sleep,
    )
    events = [
        event async for event in source.run(
            run_id="global", deadline=OBSERVED + timedelta(seconds=1)
        )
    ]
    assert len(events) == 1
    assert events[0].event_kind is ObservationKind.CONTROL
    assert source.health_snapshot()["last_request_outcome"] == "incomplete_global_snapshot"


@pytest.mark.asyncio
async def test_wallet_poll_does_not_publish_earlier_alias_on_later_alias_failure() -> None:
    clock = AdvancingClock()
    transport = CursorTransport([_page([_trade("first")], None), OSError("second wallet")])
    second_wallet = "0x" + "2" * 40
    source = DataApiWalletPollSource(
        REST_ACTIVITY_CANDIDATE,
        path=DATA_API_V2_TRADES_PATH,
        source_id=ACTIVITY_SOURCE_ID,
        aliases={public_wallet_alias(WALLET): WALLET,
                 public_wallet_alias(second_wallet): second_wallet},
        transport=transport,
        clock=clock,
        sleep=clock.sleep,
        poll_interval_seconds=1,
    )
    events = [event async for event in source.run(
        run_id="r1", deadline=OBSERVED + timedelta(seconds=1)
    )]
    assert len(events) == 1
    assert events[0].event_kind is ObservationKind.CONTROL
    assert source.health_snapshot()["last_successful_request_at"] is None


@pytest.mark.asyncio
async def test_wallet_poll_retries_failed_window_before_advancing() -> None:
    clock = AdvancingClock()
    transport = CursorTransport(
        [
            _page([_trade("first")], "lost"),
            OSError("later page failed"),
            _page([_trade("first"), _trade("second", int(OBSERVED.timestamp()) + 1)], None),
        ]
    )
    source = DataApiWalletPollSource(
        REST_ACTIVITY_CANDIDATE,
        path=DATA_API_V2_TRADES_PATH,
        source_id=ACTIVITY_SOURCE_ID,
        aliases={public_wallet_alias(WALLET): WALLET},
        transport=transport,
        clock=clock,
        sleep=clock.sleep,
        poll_interval_seconds=1,
    )
    events = [
        event async for event in source.run(run_id="r1", deadline=OBSERVED + timedelta(seconds=2))
    ]
    assert [event.event_kind for event in events] == [
        ObservationKind.CONTROL,
        ObservationKind.WALLET_TRADE,
        ObservationKind.WALLET_TRADE,
    ]
    assert transport.calls[0]["start"] == transport.calls[2]["start"]
    assert source.health_snapshot()["last_request_outcome"] == "recovered"


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
        event async for event in source.run(run_id="r1", deadline=OBSERVED + timedelta(seconds=1))
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
        event async for event in source.run(run_id="r1", deadline=OBSERVED + timedelta(seconds=1))
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
    assert events[0].provenance["settlement_evidence_version"] == "official-terminal-settlement-v1"
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
        _v2(
            [
                {
                    "proxy_wallet": WALLET,
                    "token_id": "token-1",
                }
            ]
        )
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
            "/v2/trades": _v2(
                [
                    {
                        "token_id": "token-1",
                        "condition_id": condition,
                    }
                ]
            )
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
async def test_market_stream_waits_for_discovered_tokens_and_stops_when_empty() -> None:
    clock = AdvancingClock()
    streams: list[RecordingMarketStream] = []
    discovered = iter(({}, {"token-1": "market-1"}, {}))

    def stream_factory(
        bus: object,
        token_ids: tuple[str, ...],
        stale_after: timedelta,
    ) -> RecordingMarketStream:
        del bus, stale_after
        assert token_ids
        stream = RecordingMarketStream(token_ids)
        streams.append(stream)
        return stream

    async def discover() -> MarketDiscoverySnapshot:
        return MarketDiscoverySnapshot(token_markets=next(discovered), fee_schedules={})

    source = OfficialMarketStreamSource(
        token_ids=(),
        clock=clock,
        sleep=clock.sleep,
        market_discovery=discover,
        discovery_interval_seconds=2,
        market_stream_factory=stream_factory,
    )

    events = [
        event
        async for event in source.run(
            run_id="r1",
            deadline=OBSERVED + timedelta(seconds=6),
        )
    ]

    assert events == []
    assert [stream.token_ids for stream in streams] == [("token-1",)]
    assert source.subscription_update_count == 2
    assert source.reconnect_count == 0
    assert source.health_snapshot()["availability"] == "not_started"


@pytest.mark.asyncio
async def test_market_stream_with_no_discovered_tokens_remains_unstarted() -> None:
    clock = AdvancingClock()

    async def discover() -> MarketDiscoverySnapshot:
        return MarketDiscoverySnapshot(token_markets={}, fee_schedules={})

    source = OfficialMarketStreamSource(
        token_ids=(),
        clock=clock,
        sleep=clock.sleep,
        market_discovery=discover,
        discovery_interval_seconds=1,
    )

    assert [
        event
        async for event in source.run(
            run_id="r1",
            deadline=OBSERVED + timedelta(seconds=3),
        )
    ] == []
    assert source.subscription_update_count == 0
    assert source.reconnect_count == 0
    assert source.health_snapshot()["availability"] == "not_started"


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
