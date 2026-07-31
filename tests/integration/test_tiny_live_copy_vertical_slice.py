from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from polysia.adapters.polymarket.geoblock import GeoblockStatus
from polysia.adapters.polymarket.request_scheduling import (
    TradesSourceUnavailableError,
)
from polysia.application.ports.copytrading import (
    LeaderInventorySnapshot,
    LeaderMarketMetadata,
    LeaderReadPurpose,
    LeaderTradeReadPage,
)
from polysia.config.settings import AppSettings, TradingMode
from polysia.domain.copytrading import (
    LeaderPositionEffect,
    LeaderTradeAction,
    LeaderTradeEvent,
)
from polysia.domain.market import (
    MarketDetails,
    MarketFeeSchedule,
    MarketOrderBookSnapshot,
    MarketOutcomeSummary,
    OrderBookLevel,
)
from polysia.execution.tiny_live_copy import TinyLiveCopyConfig, run_tiny_live_copy

NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)
CONDITION = "0x" + ("a" * 64)
TOKEN = "111111"
SLUG = f"btc-updown-15m-{int(NOW.timestamp())}"


class MutableClock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class Source:
    def __init__(self, clock: MutableClock) -> None:
        self.clock = clock
        self.baseline_trade_reads = 102

    async def read_inventory(self, leader_id: str) -> LeaderInventorySnapshot:
        return LeaderInventorySnapshot(
            leader_id=leader_id,
            positions={},
            observed_at=self.clock(),
            evidence_digest=f"sha256:{leader_id}",
        )

    async def read_page(
        self,
        leader_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        page_size: int = 100,
        checkpoint: object | None = None,
        purpose: LeaderReadPurpose = LeaderReadPurpose.DISCOVERY,
    ) -> LeaderTradeReadPage:
        del start_at, end_at, page_size, checkpoint, purpose
        if leader_id == "candidate-001":
            events = (
                LeaderTradeEvent(
                    event_id="event-1",
                    source_id="fixture",
                    leader_id=leader_id,
                    market_reference=CONDITION,
                    outcome_reference=TOKEN,
                    trade_action=LeaderTradeAction.BUY,
                    position_effect=LeaderPositionEffect.UNKNOWN,
                    executed_price=Decimal("0.50"),
                    executed_size=Decimal("5"),
                    executed_at=self.clock() - timedelta(seconds=1),
                    observed_at=self.clock(),
                    external_evidence_reference="sha256:evidence",
                ),
            )
        else:
            events = ()
        return LeaderTradeReadPage(
            events=events,
            next_checkpoint=None,
            raw_count=len(events),
            filtered_count=0,
            rejected_count=0,
            duplicate_count=0,
        )

    def market_metadata(
        self,
        market_reference: str,
        outcome_reference: str,
    ) -> LeaderMarketMetadata:
        return LeaderMarketMetadata(
            market_reference=market_reference,
            outcome_reference=outcome_reference,
            external_slug=SLUG,
            outcome_label="Up",
            starts_at=NOW,
            ends_at=NOW + timedelta(minutes=10),
        )


class MarketPort:
    def __init__(self, clock: MutableClock) -> None:
        self.clock = clock
        self.book_reads = 0
        self.market_reads = 0
        self.market = MarketDetails(
            id="market-1",
            slug=SLUG,
            question="Bitcoin Up or Down?",
            active=True,
            closed=False,
            accepting_orders=True,
            end_date=NOW + timedelta(minutes=10),
            outcomes=(
                MarketOutcomeSummary(
                    label="Up",
                    token_id=TOKEN,
                    price=Decimal("0.50"),
                ),
                MarketOutcomeSummary(
                    label="Down",
                    token_id="222222",
                    price=Decimal("0.50"),
                ),
            ),
            condition_id=CONDITION,
            enable_order_book=True,
            archived=False,
            start_date=NOW,
            fee_schedule=MarketFeeSchedule(enabled=False),
        )

    async def get_market_by_slug(self, slug: str) -> MarketDetails:
        assert slug == SLUG
        self.market_reads += 1
        return self.market

    async def get_order_book(self, token_id: str) -> MarketOrderBookSnapshot:
        assert token_id == TOKEN
        self.book_reads += 1
        return MarketOrderBookSnapshot(
            token_id=TOKEN,
            market_id=CONDITION,
            timestamp=self.clock(),
            bids=(OrderBookLevel(price=Decimal("0.46"), size=Decimal("20")),),
            asks=(OrderBookLevel(price=Decimal("0.50"), size=Decimal("20")),),
            minimum_order_size=Decimal("5"),
            tick_size=Decimal("0.01"),
        )


class CrossingFinalBookMarketPort(MarketPort):
    async def get_order_book(self, token_id: str) -> MarketOrderBookSnapshot:
        book = await super().get_order_book(token_id)
        if self.book_reads < 2:
            return book
        return book.model_copy(
            update={
                "asks": (OrderBookLevel(price=Decimal("0.47"), size=Decimal("20")),),
            }
        )


class WrongFinalMappingMarketPort(MarketPort):
    async def get_market_by_slug(self, slug: str) -> MarketDetails:
        market = await super().get_market_by_slug(slug)
        if self.market_reads < 2:
            return market
        return market.model_copy(
            update={
                "outcomes": (
                    MarketOutcomeSummary(
                        label="Up",
                        token_id="222222",
                        price=Decimal("0.50"),
                    ),
                    MarketOutcomeSummary(
                        label="Down",
                        token_id=TOKEN,
                        price=Decimal("0.50"),
                    ),
                )
            }
        )


class ExecutionPort:
    def __init__(self) -> None:
        self.connected = False
        self.entry_submitted = False
        self.entry_open = False
        self.exit_open = False
        self.limit_calls: list[dict[str, Any]] = []
        self.user_stream_probes = 0

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.connected = False

    async def read_clock_drift(self) -> Decimal:
        return Decimal("0")

    def identity(self) -> dict[str, object]:
        return {
            "active_wallet_source": "funder",
            "funder_configured": True,
            "signature_type_matches_sdk": True,
            "signer_configured": True,
        }

    async def get_balance_allowance(self, **kwargs: Any) -> dict[str, object]:
        if kwargs["asset_type"] == "COLLATERAL":
            return {
                "allowances": {"exchange": 10_000_000},
                "balance": 4_000_000,
            }
        return {
            "allowances": {"exchange": 10_000_000},
            "balance": 5_000_000 if self.entry_submitted else 0,
        }

    async def get_open_orders(self, **kwargs: Any) -> list[Any]:
        order_id = kwargs.get("order_id")
        orders = []
        if self.entry_open:
            orders.append({"id": "entry", "token_id": TOKEN})
        if self.exit_open:
            orders.append({"id": "exit", "token_id": TOKEN})
        if order_id is None:
            return orders
        return [order for order in orders if order["id"] == order_id]

    async def get_order(self, *, order_id: str) -> Any | None:
        return {"id": order_id}

    async def list_positions(self, **kwargs: Any) -> list[Any]:
        if not self.entry_submitted:
            return []
        return [{"condition_id": CONDITION, "size": "5", "token_id": TOKEN}]

    async def list_account_trades(self, **kwargs: Any) -> list[Any]:
        if not self.entry_submitted:
            return []
        return [
            {
                "maker_orders": [
                    {
                        "matched_amount": "5",
                        "order_id": "entry",
                        "price": "0.47",
                    }
                ],
                "price": "0.47",
                "status": "CONFIRMED",
                "taker_order_id": "other",
            }
        ]

    async def place_limit_order(self, **kwargs: Any) -> dict[str, object]:
        self.limit_calls.append(dict(kwargs))
        if kwargs["side"] == "BUY":
            assert kwargs["post_only"] is True
            assert kwargs["expiration"] is not None
            self.entry_submitted = True
            self.entry_open = True
            return {"ok": True, "order_id": "entry", "status": "LIVE"}
        assert kwargs["side"] == "SELL"
        assert kwargs["price"] == Decimal("0.52")
        assert kwargs["size"] == Decimal("5")
        self.exit_open = True
        return {"ok": True, "order_id": "exit", "status": "LIVE"}

    async def prepare_limit_order(self, **kwargs: Any) -> dict[str, object]:
        return dict(kwargs)

    async def post_prepared_limit_order(
        self,
        prepared_order: dict[str, object],
    ) -> dict[str, object]:
        return await self.place_limit_order(**prepared_order)

    async def place_market_order(self, **kwargs: Any) -> dict[str, object]:
        raise AssertionError("leader-close FOK is not expected in this slice")

    async def cancel_order(self, *, order_id: str) -> dict[str, object]:
        if order_id == "entry":
            self.entry_open = False
        elif order_id == "exit":
            self.exit_open = False
        return {"cancelled": [order_id]}

    async def cancel_all(self) -> dict[str, object]:
        self.entry_open = False
        self.exit_open = False
        return {"cancelled": True}

    async def probe_user_stream(self, *, market: str | None = None) -> None:
        del market
        self.user_stream_probes += 1


class DefinitivePostOnlyExecutionPort(ExecutionPort):
    async def place_limit_order(self, **kwargs: Any) -> dict[str, object]:
        self.limit_calls.append(dict(kwargs))
        return {
            "ok": False,
            "code": "post_only_would_cross",
            "message": "invalid post-only order: order crosses book",
        }


class AmbiguousSubmissionExecutionPort(ExecutionPort):
    async def place_limit_order(self, **kwargs: Any) -> dict[str, object]:
        self.limit_calls.append(dict(kwargs))
        raise TimeoutError("fixture submission outcome is unknown")


class UnfilledExecutionPort(ExecutionPort):
    async def list_positions(self, **kwargs: Any) -> list[Any]:
        del kwargs
        return []

    async def list_account_trades(self, **kwargs: Any) -> list[Any]:
        del kwargs
        return []


class Geoblock:
    async def check(self) -> GeoblockStatus:
        return GeoblockStatus(status="allowed", checked_at=NOW, blocked=False)


class SubmissionDelayGeoblock(Geoblock):
    def __init__(self, clock: MutableClock) -> None:
        self.clock = clock
        self.calls = 0

    async def check(self) -> GeoblockStatus:
        self.calls += 1
        if self.calls == 3:
            self.clock.now += timedelta(seconds=11)
        return await super().check()


class ObservedExecutionPort(ExecutionPort):
    def __init__(self) -> None:
        super().__init__()
        self.cancel_all_calls = 0

    async def cancel_all(self) -> dict[str, object]:
        self.cancel_all_calls += 1
        return await super().cancel_all()


class AlwaysUnavailableSource(Source):
    def __init__(self, clock: MutableClock) -> None:
        super().__init__(clock)
        self.read_purposes: list[LeaderReadPurpose] = []

    async def read_page(
        self,
        leader_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        page_size: int = 100,
        checkpoint: object | None = None,
        purpose: LeaderReadPurpose = LeaderReadPurpose.DISCOVERY,
    ) -> LeaderTradeReadPage:
        del leader_id, start_at, end_at, page_size, checkpoint
        self.read_purposes.append(purpose)
        raise TradesSourceUnavailableError(
            outage_started_at=NOW,
            retry_at=self.clock() + timedelta(seconds=1),
            reason="fixture public source unavailable",
        )


class RecoveringSource(AlwaysUnavailableSource):
    def __init__(self, clock: MutableClock, *, stale_event: bool = False) -> None:
        super().__init__(clock)
        self.stale_event = stale_event
        self.failures_remaining = 1

    async def read_page(
        self,
        leader_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        page_size: int = 100,
        checkpoint: object | None = None,
        purpose: LeaderReadPurpose = LeaderReadPurpose.DISCOVERY,
    ) -> LeaderTradeReadPage:
        self.read_purposes.append(purpose)
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise TradesSourceUnavailableError(
                outage_started_at=NOW,
                retry_at=self.clock() + timedelta(seconds=1),
                reason="fixture temporary outage",
            )
        if not self.stale_event:
            return LeaderTradeReadPage(
                events=(),
                next_checkpoint=None,
                raw_count=0,
                filtered_count=0,
                rejected_count=0,
                duplicate_count=0,
            )
        page = await Source.read_page(
            self,
            leader_id,
            start_at=start_at,
            end_at=end_at,
            page_size=page_size,
            checkpoint=checkpoint,
            purpose=purpose,
        )
        if not page.events:
            return page
        stale = page.events[0]
        return LeaderTradeReadPage(
            events=(
                LeaderTradeEvent(
                    event_id=stale.event_id,
                    source_id=stale.source_id,
                    leader_id=stale.leader_id,
                    market_reference=stale.market_reference,
                    outcome_reference=stale.outcome_reference,
                    trade_action=stale.trade_action,
                    position_effect=stale.position_effect,
                    executed_price=stale.executed_price,
                    executed_size=stale.executed_size,
                    executed_at=self.clock() - timedelta(seconds=11),
                    observed_at=self.clock(),
                    external_evidence_reference=stale.external_evidence_reference,
                ),
            ),
            next_checkpoint=None,
            raw_count=1,
            filtered_count=0,
            rejected_count=0,
            duplicate_count=0,
        )


class ActiveOutageSource(Source):
    def __init__(
        self,
        clock: MutableClock,
        execution: ObservedExecutionPort,
    ) -> None:
        super().__init__(clock)
        self.execution = execution
        self.read_purposes: list[LeaderReadPurpose] = []

    async def read_page(
        self,
        leader_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        page_size: int = 100,
        checkpoint: object | None = None,
        purpose: LeaderReadPurpose = LeaderReadPurpose.DISCOVERY,
    ) -> LeaderTradeReadPage:
        self.read_purposes.append(purpose)
        if purpose is LeaderReadPurpose.SELECTED_LEADER:
            assert self.execution.exit_open is True
            raise TradesSourceUnavailableError(
                outage_started_at=self.clock(),
                retry_at=self.clock() + timedelta(seconds=1),
                reason="fixture active-exposure public outage",
            )
        return await super().read_page(
            leader_id,
            start_at=start_at,
            end_at=end_at,
            page_size=page_size,
            checkpoint=checkpoint,
            purpose=purpose,
        )


class CountingSource(Source):
    def __init__(self, clock: MutableClock) -> None:
        super().__init__(clock)
        self.read_purposes: list[LeaderReadPurpose] = []

    async def read_page(
        self,
        leader_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        page_size: int = 100,
        checkpoint: object | None = None,
        purpose: LeaderReadPurpose = LeaderReadPurpose.DISCOVERY,
    ) -> LeaderTradeReadPage:
        self.read_purposes.append(purpose)
        return await super().read_page(
            leader_id,
            start_at=start_at,
            end_at=end_at,
            page_size=page_size,
            checkpoint=checkpoint,
            purpose=purpose,
        )


class TwoRoundSignalSource(Source):
    def __init__(self, clock: MutableClock) -> None:
        super().__init__(clock)
        self.discovery_calls = 0

    async def read_page(
        self,
        leader_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        page_size: int = 100,
        checkpoint: object | None = None,
        purpose: LeaderReadPurpose = LeaderReadPurpose.DISCOVERY,
    ) -> LeaderTradeReadPage:
        del start_at, end_at, page_size, checkpoint
        if purpose is not LeaderReadPurpose.DISCOVERY:
            return LeaderTradeReadPage(
                events=(),
                next_checkpoint=None,
                raw_count=0,
                filtered_count=0,
                rejected_count=0,
                duplicate_count=0,
            )
        round_index = self.discovery_calls // 48
        self.discovery_calls += 1
        expected_leader = "candidate-001" if round_index == 0 else "candidate-002"
        events: tuple[LeaderTradeEvent, ...] = ()
        if round_index < 2 and leader_id == expected_leader:
            events = (
                LeaderTradeEvent(
                    event_id=f"event-{round_index + 1}",
                    source_id="fixture",
                    leader_id=leader_id,
                    market_reference=CONDITION,
                    outcome_reference=TOKEN,
                    trade_action=LeaderTradeAction.BUY,
                    position_effect=LeaderPositionEffect.UNKNOWN,
                    executed_price=Decimal("0.50"),
                    executed_size=Decimal("5"),
                    executed_at=self.clock() - timedelta(seconds=1),
                    observed_at=self.clock(),
                    external_evidence_reference=f"sha256:evidence-{round_index + 1}",
                ),
            )
        return LeaderTradeReadPage(
            events=events,
            next_checkpoint=None,
            raw_count=len(events),
            filtered_count=0,
            rejected_count=0,
            duplicate_count=0,
        )


class DelayedBatchSource(Source):
    def __init__(self, clock: MutableClock) -> None:
        super().__init__(clock)
        self.release_delayed = asyncio.Event()
        self.completed_aliases = 0

    async def read_page(
        self,
        leader_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        page_size: int = 100,
        checkpoint: object | None = None,
        purpose: LeaderReadPurpose = LeaderReadPurpose.DISCOVERY,
    ) -> LeaderTradeReadPage:
        del start_at, end_at, page_size, checkpoint, purpose
        if leader_id == "candidate-001":
            self.clock.now = NOW + timedelta(seconds=7.53)
            self.completed_aliases += 1
            return LeaderTradeReadPage(
                events=(
                    LeaderTradeEvent(
                        event_id="streamed-event",
                        source_id="fixture",
                        leader_id=leader_id,
                        market_reference=CONDITION,
                        outcome_reference=TOKEN,
                        trade_action=LeaderTradeAction.BUY,
                        position_effect=LeaderPositionEffect.UNKNOWN,
                        executed_price=Decimal("0.50"),
                        executed_size=Decimal("5"),
                        executed_at=NOW,
                        observed_at=self.clock(),
                        external_evidence_reference="sha256:streamed-evidence",
                    ),
                ),
                next_checkpoint=None,
                raw_count=1,
                filtered_count=0,
                rejected_count=0,
                duplicate_count=0,
            )
        await self.release_delayed.wait()
        self.clock.now = NOW + timedelta(seconds=13.16)
        self.completed_aliases += 1
        return LeaderTradeReadPage(
            events=(),
            next_checkpoint=None,
            raw_count=0,
            filtered_count=0,
            rejected_count=0,
            duplicate_count=0,
        )


class StreamingMarketPort(MarketPort):
    def __init__(self, clock: MutableClock, source: DelayedBatchSource) -> None:
        super().__init__(clock)
        self.source = source
        self.signal_evaluated_before_batch = False

    async def get_market_by_slug(self, slug: str) -> MarketDetails:
        self.signal_evaluated_before_batch = self.source.completed_aliases == 1
        self.source.release_delayed.set()
        return await super().get_market_by_slug(slug)


def _candidate_file(path: Path) -> Path:
    candidate_path = path / "candidates.txt"
    candidate_path.write_text(
        "\n".join(f"0x{index:040x}" for index in range(1, 103)) + "\n",
        encoding="utf-8",
    )
    return candidate_path


def _live_config(
    tmp_path: Path,
    *,
    run_id: str,
    maximum_poll_cycles: int,
) -> TinyLiveCopyConfig:
    return TinyLiveCopyConfig(
        settings=AppSettings(
            _env_file=None,
            TRADING_MODE=TradingMode.LIVE,
            LIVE_TRADING_ENABLED=True,
            POLYMARKET_FUNDER_ADDRESS="0x1111111111111111111111111111111111111111",
            POLYMARKET_PRIVATE_KEY="fixture-key",
            POLYMARKET_SIGNATURE_TYPE=3,
        ),
        project_root=tmp_path,
        output_dir=tmp_path / "reports",
        database_path=tmp_path / "state.sqlite3",
        candidate_file=_candidate_file(tmp_path),
        run_id=run_id,
        dry_run=False,
        authorization_id="POLYSIA-TINY-LIVE-COPY-999",
        acknowledgement=True,
        verified_ci_commit="a" * 40,
        maximum_poll_cycles=maximum_poll_cycles,
        delete_candidate_file_on_terminal=False,
    )


@pytest.mark.asyncio
async def test_final_crossing_book_is_rejected_locally_without_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "polysia.execution.tiny_live_copy._assert_synchronized_main",
        lambda config, git_commit: None,
    )
    clock = MutableClock()
    market = CrossingFinalBookMarketPort(clock)
    execution = ExecutionPort()

    report = await run_tiny_live_copy(
        _live_config(
            tmp_path,
            run_id="tiny-live-copy-final-cross-local",
            maximum_poll_cycles=1,
        ),
        source=Source(clock),
        market_port=market,
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert report.total_entry_attempts == 0
    assert report.state == "MONITORING"
    assert execution.limit_calls == []
    assert market.book_reads == 2
    assert any(
        decision["action"] == "SIGNAL_REJECTED_POST_ONLY_LOCAL"
        for decision in report.decisions
    )


@pytest.mark.asyncio
async def test_final_wrong_outcome_mapping_is_rejected_without_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "polysia.execution.tiny_live_copy._assert_synchronized_main",
        lambda config, git_commit: None,
    )
    clock = MutableClock()
    market = WrongFinalMappingMarketPort(clock)
    execution = ExecutionPort()

    report = await run_tiny_live_copy(
        _live_config(
            tmp_path,
            run_id="tiny-live-copy-final-mapping-local",
            maximum_poll_cycles=1,
        ),
        source=Source(clock),
        market_port=market,
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert report.total_entry_attempts == 0
    assert execution.limit_calls == []
    assert market.market_reads == 2
    assert any(
        decision["action"] == "SIGNAL_REJECTED_FINAL_LOCAL_INELIGIBILITY"
        for decision in report.decisions
    )


@pytest.mark.asyncio
async def test_first_definitive_post_only_rejection_reconciles_and_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "polysia.execution.tiny_live_copy._assert_synchronized_main",
        lambda config, git_commit: None,
    )
    clock = MutableClock()
    execution = DefinitivePostOnlyExecutionPort()

    report = await run_tiny_live_copy(
        _live_config(
            tmp_path,
            run_id="tiny-live-copy-first-post-only-reject",
            maximum_poll_cycles=1,
        ),
        source=Source(clock),
        market_port=MarketPort(clock),
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert report.total_entry_attempts == 1
    assert report.state == "MONITORING"
    assert len(execution.limit_calls) == 1
    assert report.attempts[0]["state"] == "SUBMISSION_REJECTED_DEFINITIVE_POST_ONLY"
    assert any(
        decision["action"] == "ENTRY_POST_ONLY_REJECTED_DEFINITIVE"
        for decision in report.decisions
    )


@pytest.mark.asyncio
async def test_second_definitive_post_only_rejection_in_run_fails_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "polysia.execution.tiny_live_copy._assert_synchronized_main",
        lambda config, git_commit: None,
    )
    clock = MutableClock()
    execution = DefinitivePostOnlyExecutionPort()

    report = await run_tiny_live_copy(
        _live_config(
            tmp_path,
            run_id="tiny-live-copy-second-post-only-reject",
            maximum_poll_cycles=2,
        ),
        source=TwoRoundSignalSource(clock),
        market_port=MarketPort(clock),
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert report.total_entry_attempts == 2
    assert report.state == "FAILED_SAFE"
    assert report.classification == "FAILED_SAFE"
    assert len(execution.limit_calls) == 2
    assert "second definitive Post-only rejection" in str(report.stop_reason)


@pytest.mark.asyncio
async def test_ambiguous_submission_is_preserved_and_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "polysia.execution.tiny_live_copy._assert_synchronized_main",
        lambda config, git_commit: None,
    )
    clock = MutableClock()
    execution = AmbiguousSubmissionExecutionPort()

    report = await run_tiny_live_copy(
        _live_config(
            tmp_path,
            run_id="tiny-live-copy-ambiguous-submit",
            maximum_poll_cycles=1,
        ),
        source=Source(clock),
        market_port=MarketPort(clock),
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert report.total_entry_attempts == 1
    assert report.state == "FAILED_SAFE"
    assert report.attempts[0]["state"] == "SUBMISSION_OUTCOME_UNKNOWN"
    assert len(execution.limit_calls) == 1


@pytest.mark.asyncio
async def test_signal_is_processed_before_all_48_wallet_responses_complete(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    source = DelayedBatchSource(clock)
    market = StreamingMarketPort(clock, source)
    execution = ExecutionPort()
    settings = AppSettings(
        _env_file=None,
        POLYMARKET_FUNDER_ADDRESS="0x1111111111111111111111111111111111111111",
        POLYMARKET_PRIVATE_KEY="fixture-key",
        POLYMARKET_SIGNATURE_TYPE=3,
    )
    candidate_path = _candidate_file(tmp_path)

    report = await run_tiny_live_copy(
        TinyLiveCopyConfig(
            settings=settings,
            project_root=tmp_path,
            output_dir=tmp_path / "reports",
            database_path=tmp_path / "state.sqlite3",
            candidate_file=candidate_path,
            run_id="tiny-live-copy-streaming-regression",
            dry_run=True,
            maximum_poll_cycles=1,
        ),
        source=source,
        market_port=market,
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert market.signal_evaluated_before_batch is True
    assert source.completed_aliases == 48
    assert report.signal_count == 1
    assert report.total_entry_attempts == 0
    assert execution.limit_calls == []
    assert report.candidate_runtime_file_deleted is True
    assert not candidate_path.exists()
    assert any(decision["action"] == "ENTRY_APPROVED" for decision in report.decisions)
    assert not any(
        decision["action"]
        in {
            "SIGNAL_REJECTED_STALE_AT_EVALUATION",
            "SIGNAL_REJECTED_STALE_AT_SUBMISSION",
        }
        for decision in report.decisions
    )
    signal_metric = report.signal_latency_metrics[0]
    assert signal_metric["executed_to_observed_ms"] == 7_530
    assert signal_metric["observed_to_evaluation_ms"] == 0
    batch_metric = report.poll_batch_metrics[-1]
    assert batch_metric["response_count"] == 48
    assert batch_metric["full_batch_completion_ms"] == 13_160


@pytest.mark.asyncio
async def test_signal_that_really_exceeds_ten_seconds_before_submit_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "polysia.execution.tiny_live_copy._assert_synchronized_main",
        lambda config, git_commit: None,
    )
    clock = MutableClock()
    execution = ExecutionPort()
    report = await run_tiny_live_copy(
        TinyLiveCopyConfig(
            settings=AppSettings(
                _env_file=None,
                TRADING_MODE=TradingMode.LIVE,
                LIVE_TRADING_ENABLED=True,
                POLYMARKET_FUNDER_ADDRESS="0x1111111111111111111111111111111111111111",
                POLYMARKET_PRIVATE_KEY="fixture-key",
                POLYMARKET_SIGNATURE_TYPE=3,
            ),
            project_root=tmp_path,
            output_dir=tmp_path / "reports",
            database_path=tmp_path / "state.sqlite3",
            candidate_file=_candidate_file(tmp_path),
            run_id="tiny-live-copy-real-stale-regression",
            dry_run=False,
            authorization_id="POLYSIA-TINY-LIVE-COPY-999",
            acknowledgement=True,
            verified_ci_commit="a" * 40,
            maximum_poll_cycles=1,
            delete_candidate_file_on_terminal=False,
        ),
        source=Source(clock),
        market_port=MarketPort(clock),
        execution_port=execution,
        geoblock_port=SubmissionDelayGeoblock(clock),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert report.total_entry_attempts == 0
    assert execution.limit_calls == []
    assert any(
        decision["action"] == "SIGNAL_REJECTED_STALE_BEFORE_SUBMISSION"
        for decision in report.decisions
    )


@pytest.mark.asyncio
async def test_complete_fixture_dry_run_never_submits_an_order(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    source = CountingSource(clock)
    market = MarketPort(clock)
    execution = ExecutionPort()
    settings = AppSettings(
        _env_file=None,
        POLYMARKET_FUNDER_ADDRESS="0x1111111111111111111111111111111111111111",
        POLYMARKET_PRIVATE_KEY="fixture-key",
        POLYMARKET_SIGNATURE_TYPE=3,
    )

    report = await run_tiny_live_copy(
        TinyLiveCopyConfig(
            settings=settings,
            project_root=tmp_path,
            output_dir=tmp_path / "reports",
            database_path=tmp_path / "state.sqlite3",
            candidate_file=_candidate_file(tmp_path),
            run_id="tiny-live-copy-20260729T115959Z",
            dry_run=True,
            maximum_poll_cycles=1,
            delete_candidate_file_on_terminal=False,
        ),
        source=source,
        market_port=market,
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert report.classification == "DRY_RUN_BOUNDED_COMPLETE"
    assert report.total_entry_attempts == 0
    assert execution.limit_calls == []


@pytest.mark.asyncio
async def test_fixture_vertical_slice_proves_risk_execution_partial_fill_and_tp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "polysia.execution.tiny_live_copy._assert_synchronized_main",
        lambda config, git_commit: None,
    )
    clock = MutableClock()
    source = Source(clock)
    market = MarketPort(clock)
    execution = ExecutionPort()
    settings = AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_FUNDER_ADDRESS="0x1111111111111111111111111111111111111111",
        POLYMARKET_PRIVATE_KEY="fixture-key",
        POLYMARKET_SIGNATURE_TYPE=3,
    )

    report = await run_tiny_live_copy(
        TinyLiveCopyConfig(
            settings=settings,
            project_root=tmp_path,
            output_dir=tmp_path / "reports",
            database_path=tmp_path / "state.sqlite3",
            candidate_file=_candidate_file(tmp_path),
            run_id="tiny-live-copy-20260729T120000Z",
            dry_run=False,
            authorization_id="POLYSIA-TINY-LIVE-COPY-999",
            acknowledgement=True,
            verified_ci_commit="a" * 40,
            maximum_poll_cycles=2,
            delete_candidate_file_on_terminal=False,
        ),
        source=source,
        market_port=market,
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert report.classification == "DRY_RUN_BOUNDED_COMPLETE"
    assert report.total_entry_attempts == 1
    assert report.completed_live_cycles == 0
    assert report.state == "EXIT_PENDING"
    assert [call["side"] for call in execution.limit_calls] == ["BUY", "SELL"]
    assert execution.limit_calls[0]["post_only"] is True
    assert execution.limit_calls[0]["size"] == Decimal("5")
    assert execution.limit_calls[1]["size"] == Decimal("5")
    assert execution.user_stream_probes >= 2
    assert "0x0000000000000000000000000000000000000001" not in str(report.to_dict())

    restarted = await run_tiny_live_copy(
        TinyLiveCopyConfig(
            settings=settings,
            project_root=tmp_path,
            output_dir=tmp_path / "reports",
            database_path=tmp_path / "state.sqlite3",
            candidate_file=tmp_path / "candidates.txt",
            run_id="tiny-live-copy-20260729T120000Z",
            dry_run=False,
            authorization_id="POLYSIA-TINY-LIVE-COPY-999",
            acknowledgement=True,
            verified_ci_commit="a" * 40,
            maximum_poll_cycles=1,
            delete_candidate_file_on_terminal=False,
        ),
        source=source,
        market_port=market,
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert restarted.state == "EXIT_PENDING", restarted.to_dict()
    assert restarted.total_entry_attempts == 1
    assert [call["side"] for call in execution.limit_calls] == ["BUY", "SELL"]


@pytest.mark.asyncio
async def test_pending_entry_restart_never_submits_a_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "polysia.execution.tiny_live_copy._assert_synchronized_main",
        lambda config, git_commit: None,
    )
    clock = MutableClock()
    source = Source(clock)
    market = MarketPort(clock)
    execution = UnfilledExecutionPort()
    settings = AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_FUNDER_ADDRESS="0x1111111111111111111111111111111111111111",
        POLYMARKET_PRIVATE_KEY="fixture-key",
        POLYMARKET_SIGNATURE_TYPE=3,
    )
    config = TinyLiveCopyConfig(
        settings=settings,
        project_root=tmp_path,
        output_dir=tmp_path / "reports",
        database_path=tmp_path / "state.sqlite3",
        candidate_file=_candidate_file(tmp_path),
        run_id="tiny-live-copy-20260729T120001Z",
        dry_run=False,
        authorization_id="POLYSIA-TINY-LIVE-COPY-999",
        acknowledgement=True,
        verified_ci_commit="a" * 40,
        maximum_poll_cycles=1,
        delete_candidate_file_on_terminal=False,
    )

    first = await run_tiny_live_copy(
        config,
        source=source,
        market_port=market,
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )
    restarted = await run_tiny_live_copy(
        config,
        source=source,
        market_port=market,
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert first.state == "ENTRY_PENDING"
    assert restarted.state == "ENTRY_PENDING"
    assert restarted.total_entry_attempts == 1
    assert [call["side"] for call in execution.limit_calls] == ["BUY"]


@pytest.mark.asyncio
async def test_flat_public_outage_finalizes_inconclusive_at_120_seconds(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    source = AlwaysUnavailableSource(clock)
    execution = ObservedExecutionPort()
    settings = AppSettings(
        _env_file=None,
        POLYMARKET_FUNDER_ADDRESS="0x1111111111111111111111111111111111111111",
        POLYMARKET_PRIVATE_KEY="fixture-key",
        POLYMARKET_SIGNATURE_TYPE=3,
    )

    report = await run_tiny_live_copy(
        TinyLiveCopyConfig(
            settings=settings,
            project_root=tmp_path,
            output_dir=tmp_path / "reports",
            database_path=tmp_path / "state.sqlite3",
            candidate_file=_candidate_file(tmp_path),
            run_id="tiny-live-copy-20260729T120002Z",
            dry_run=True,
            maximum_poll_cycles=30,
            delete_candidate_file_on_terminal=False,
        ),
        source=source,
        market_port=MarketPort(clock),
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert report.classification == "INCONCLUSIVE_DATA_SOURCE"
    assert report.state == "FINALIZED"
    assert report.total_entry_attempts == 0
    assert execution.limit_calls == []
    assert execution.cancel_all_calls == 0
    assert source.read_purposes.count(LeaderReadPurpose.DISCOVERY) == 48
    assert all(purpose is LeaderReadPurpose.RECOVERY for purpose in source.read_purposes[48:])


@pytest.mark.asyncio
@pytest.mark.parametrize("stale_event", [False, True])
async def test_flat_public_source_recovers_without_stale_entry(
    tmp_path: Path,
    stale_event: bool,
) -> None:
    clock = MutableClock()
    source = RecoveringSource(clock, stale_event=stale_event)
    execution = ObservedExecutionPort()
    settings = AppSettings(
        _env_file=None,
        POLYMARKET_FUNDER_ADDRESS="0x1111111111111111111111111111111111111111",
        POLYMARKET_PRIVATE_KEY="fixture-key",
        POLYMARKET_SIGNATURE_TYPE=3,
    )

    report = await run_tiny_live_copy(
        TinyLiveCopyConfig(
            settings=settings,
            project_root=tmp_path,
            output_dir=tmp_path / "reports",
            database_path=tmp_path / "state.sqlite3",
            candidate_file=_candidate_file(tmp_path),
            run_id=f"tiny-live-copy-recovery-{int(stale_event)}",
            dry_run=True,
            maximum_poll_cycles=2,
            delete_candidate_file_on_terminal=False,
        ),
        source=source,
        market_port=MarketPort(clock),
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert report.classification == "DRY_RUN_BOUNDED_COMPLETE"
    assert report.source_availability == "available"
    assert report.total_entry_attempts == 0
    assert report.signal_count == 0
    assert execution.limit_calls == []
    assert any(
        decision["action"] == "PUBLIC_TRADES_SOURCE_RECOVERED" for decision in report.decisions
    )


@pytest.mark.asyncio
async def test_active_follower_management_precedes_public_leader_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "polysia.execution.tiny_live_copy._assert_synchronized_main",
        lambda config, git_commit: None,
    )
    clock = MutableClock()
    execution = ObservedExecutionPort()
    source = ActiveOutageSource(clock, execution)
    settings = AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_FUNDER_ADDRESS="0x1111111111111111111111111111111111111111",
        POLYMARKET_PRIVATE_KEY="fixture-key",
        POLYMARKET_SIGNATURE_TYPE=3,
    )

    report = await run_tiny_live_copy(
        TinyLiveCopyConfig(
            settings=settings,
            project_root=tmp_path,
            output_dir=tmp_path / "reports",
            database_path=tmp_path / "state.sqlite3",
            candidate_file=_candidate_file(tmp_path),
            run_id="tiny-live-copy-20260729T120003Z",
            dry_run=False,
            authorization_id="POLYSIA-TINY-LIVE-COPY-999",
            acknowledgement=True,
            verified_ci_commit="a" * 40,
            maximum_poll_cycles=2,
            delete_candidate_file_on_terminal=False,
        ),
        source=source,
        market_port=MarketPort(clock),
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert report.state == "EXIT_PENDING"
    assert report.active_management_priority_cycles == 1
    assert report.source_availability == "degraded_active_management_continues"
    assert execution.cancel_all_calls == 0
    assert source.read_purposes.count(LeaderReadPurpose.DISCOVERY) == 48
    assert source.read_purposes.count(LeaderReadPurpose.SELECTED_LEADER) == 1


@pytest.mark.asyncio
async def test_fixture_dry_run_records_one_unfilled_attempt_and_resumes_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "polysia.execution.tiny_live_copy._assert_synchronized_main",
        lambda config, git_commit: None,
    )
    clock = MutableClock()
    source = CountingSource(clock)
    execution = UnfilledExecutionPort()
    settings = AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_FUNDER_ADDRESS="0x1111111111111111111111111111111111111111",
        POLYMARKET_PRIVATE_KEY="fixture-key",
        POLYMARKET_SIGNATURE_TYPE=3,
    )
    output_dir = tmp_path / "reports"
    candidate_path = _candidate_file(tmp_path)

    report = await run_tiny_live_copy(
        TinyLiveCopyConfig(
            settings=settings,
            project_root=tmp_path,
            output_dir=output_dir,
            database_path=tmp_path / "state.sqlite3",
            candidate_file=candidate_path,
            run_id="tiny-live-copy-20260729T120004Z",
            dry_run=False,
            authorization_id="POLYSIA-TINY-LIVE-COPY-999",
            acknowledgement=True,
            verified_ci_commit="a" * 40,
            maximum_poll_cycles=17,
            delete_candidate_file_on_terminal=False,
        ),
        source=source,
        market_port=MarketPort(clock),
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert report.total_entry_attempts == 1
    assert report.current_order_or_fill_exists is False
    assert report.state == "MONITORING"
    assert any(decision["action"] == "ENTRY_UNFILLED_CANCELLED" for decision in report.decisions)
    assert execution.limit_calls[0]["side"] == "BUY"
    assert source.read_purposes.count(LeaderReadPurpose.DISCOVERY) == 96
    assert source.read_purposes.count(LeaderReadPurpose.SELECTED_LEADER) > 0
    for candidate in candidate_path.read_text(encoding="utf-8").splitlines():
        assert candidate not in "\n".join(
            path.read_text(encoding="utf-8")
            for path in output_dir.iterdir()
            if path.suffix in {".json", ".jsonl"}
        )
    for line in (output_dir / "checksum.sha256").read_text(encoding="utf-8").splitlines():
        expected, name = line.split("  ", maxsplit=1)
        assert hashlib.sha256((output_dir / name).read_bytes()).hexdigest() == expected


@pytest.mark.asyncio
async def test_restart_during_discovery_pause_restores_without_duplicate_entry(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    first_source = RecoveringSource(clock)
    execution = ObservedExecutionPort()
    settings = AppSettings(
        _env_file=None,
        POLYMARKET_FUNDER_ADDRESS="0x1111111111111111111111111111111111111111",
        POLYMARKET_PRIVATE_KEY="fixture-key",
        POLYMARKET_SIGNATURE_TYPE=3,
    )
    config = TinyLiveCopyConfig(
        settings=settings,
        project_root=tmp_path,
        output_dir=tmp_path / "reports",
        database_path=tmp_path / "state.sqlite3",
        candidate_file=_candidate_file(tmp_path),
        run_id="tiny-live-copy-20260729T120005Z",
        dry_run=True,
        maximum_poll_cycles=1,
        delete_candidate_file_on_terminal=False,
    )

    first = await run_tiny_live_copy(
        config,
        source=first_source,
        market_port=MarketPort(clock),
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )
    recovered_source = RecoveringSource(clock)
    recovered_source.failures_remaining = 0
    restarted = await run_tiny_live_copy(
        config,
        source=recovered_source,
        market_port=MarketPort(clock),
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert first.source_availability == "cooldown_flat"
    assert restarted.source_availability == "available"
    assert restarted.total_entry_attempts == 0
    assert restarted.signal_count == 0
    assert recovered_source.read_purposes == [LeaderReadPurpose.RECOVERY]
