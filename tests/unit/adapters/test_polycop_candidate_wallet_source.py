from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request

import pytest

import polysia.adapters.polycop.candidate_wallet_source as polycop_source
from polysia.adapters.polycop.candidate_wallet_source import (
    POLYCOP_LEADERBOARD_PATH,
    PolyCopCandidateWalletSource,
    PolyCopSchemaChangedError,
    PolyCopSnapshotUnstableError,
    PolyCopSourceError,
    UrllibPolyCopTransport,
    _RejectRedirectHandler,
)


class FakeTransport:
    def __init__(self, pages: dict[int, list[dict[str, Any]]]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, dict[str, str | int]]] = []

    async def get_json(self, path: str, params: dict[str, str | int]) -> Any:
        copied = dict(params)
        self.calls.append((path, copied))
        page = int(params["page"])
        responses = self.pages[page]
        return responses.pop(0) if len(responses) > 1 else responses[0]


def _row(number: int) -> dict[str, object]:
    return {
        "actual_pnl": Decimal("123.40"),
        "address": f"0x{number:040x}",
        "all_pnl_json": "[]",
        "avg_invest": Decimal("10.5"),
        "avg_pnl_m": Decimal("2.5"),
        "avg_profit_loss_ratio": Decimal("1.2"),
        "buy_price": Decimal("0.42"),
        "copy_backtest_pnl": Decimal("8.1"),
        "copy_loss_rate": Decimal("0.1"),
        "daily_stats_json": "[]",
        "hedged": 1038,
        "hedged_pct": Decimal("0"),
        "hold_time": Decimal("15.25"),
        "last_2d": Decimal("3.75"),
        "last_active": "2026-08-22T00:00:00",
        "markets_traded": 12,
        "r20_pnl": Decimal("4.2"),
        "r20_slip": Decimal("0.01"),
        "r20_wr": Decimal("0.6"),
        "roi": Decimal("0.3"),
        "score": 90,
        "trading_days": 30,
        "trading_volume": Decimal("1000.25"),
        "win_rate": Decimal("0.7"),
    }


def _page(page: int, total_pages: int, rows: list[dict[str, object]]) -> dict[str, object]:
    return {"data": rows, "page": page, "status": "success", "total_pages": total_pages}


@pytest.mark.asyncio
async def test_fetches_every_dynamic_page_and_normalizes_without_address_leakage() -> None:
    first_page = _page(1, 2, [_row(1), _row(2)])
    transport = FakeTransport(
        {
            1: [first_page, first_page],
            2: [_page(2, 2, [_row(3)])],
        }
    )
    source = PolyCopCandidateWalletSource(
        transport=transport,
        clock=lambda: datetime(2026, 8, 22, tzinfo=UTC),
        page_delay_seconds=0,
        consistency_attempts=1,
    )

    dataset = await source.fetch_snapshot()

    assert dataset.source_id == "polycop"
    assert dataset.source_total_pages == 2
    assert [record.source_rank for record in dataset.records] == [1, 2, 3]
    assert [record.source_page for record in dataset.records] == [1, 1, 2]
    assert dataset.records[0].metrics["actual_pnl"] == "123.4"
    assert dataset.records[0].metrics["hedged"] == 1038
    assert all("address" not in record.metrics for record in dataset.records)
    assert [call[1]["page"] for call in transport.calls] == [1, 2, 1]
    assert all(call[0] == POLYCOP_LEADERBOARD_PATH for call in transport.calls)
    assert all(call[1]["full"] == 1 for call in transport.calls)


@pytest.mark.asyncio
async def test_rejects_schema_change_with_bounded_evidence() -> None:
    changed = _row(1)
    changed["new_metric"] = 1
    payload = _page(1, 1, [changed])
    source = PolyCopCandidateWalletSource(
        transport=FakeTransport({1: [payload, payload]}),
        page_delay_seconds=0,
        consistency_attempts=1,
    )

    with pytest.raises(PolyCopSchemaChangedError) as raised:
        await source.fetch_snapshot()

    assert raised.value.reason_code == "row_fields_changed"
    assert raised.value.schema_fingerprint
    assert "0x" not in str(raised.value)


@pytest.mark.asyncio
async def test_rejects_wallet_identity_embedded_in_ordinary_metrics() -> None:
    changed = _row(1)
    changed["all_pnl_json"] = f'["{changed["address"]}"]'
    payload = _page(1, 1, [changed])
    source = PolyCopCandidateWalletSource(
        transport=FakeTransport({1: [payload, payload]}),
        page_delay_seconds=0,
        consistency_attempts=1,
    )

    with pytest.raises(PolyCopSchemaChangedError) as raised:
        await source.fetch_snapshot()

    assert raised.value.reason_code == "wallet_value_outside_identity_field"


@pytest.mark.asyncio
async def test_rejects_uppercase_prefix_wallet_in_ordinary_metrics() -> None:
    changed = _row(1)
    changed["all_pnl_json"] = f'["{str(changed["address"]).upper()}"]'
    payload = _page(1, 1, [changed])
    source = PolyCopCandidateWalletSource(
        transport=FakeTransport({1: [payload, payload]}),
        page_delay_seconds=0,
        consistency_attempts=1,
    )

    with pytest.raises(PolyCopSchemaChangedError) as raised:
        await source.fetch_snapshot()

    assert raised.value.reason_code == "wallet_value_outside_identity_field"


@pytest.mark.asyncio
async def test_rejects_page_shift_instead_of_publishing_mixed_snapshot() -> None:
    first = _page(1, 2, [_row(1)])
    changed_guard = _page(1, 2, [_row(4)])
    source = PolyCopCandidateWalletSource(
        transport=FakeTransport(
            {
                1: [first, changed_guard],
                2: [_page(2, 2, [_row(2)])],
            }
        ),
        page_delay_seconds=0,
        consistency_attempts=1,
    )

    with pytest.raises(PolyCopSnapshotUnstableError, match="page 1 changed"):
        await source.fetch_snapshot()


@pytest.mark.asyncio
async def test_rejects_duplicate_wallet_across_pages() -> None:
    first = _page(1, 2, [_row(1)])
    source = PolyCopCandidateWalletSource(
        transport=FakeTransport(
            {
                1: [first, first],
                2: [_page(2, 2, [_row(1)])],
            }
        ),
        page_delay_seconds=0,
        consistency_attempts=1,
    )

    with pytest.raises(PolyCopSnapshotUnstableError, match="duplicate"):
        await source.fetch_snapshot()


@pytest.mark.asyncio
async def test_record_cap_is_enforced_before_later_pages_are_fetched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _page(1, 3, [_row(1)])
    transport = FakeTransport(
        {
            1: [first, first],
            2: [_page(2, 3, [_row(2)])],
            3: [_page(3, 3, [_row(3)])],
        }
    )
    source = PolyCopCandidateWalletSource(
        transport=transport,
        page_delay_seconds=0,
        consistency_attempts=1,
    )
    monkeypatch.setattr(polycop_source, "_MAX_TOTAL_RECORDS", 1)

    with pytest.raises(PolyCopSourceError, match="record count"):
        await source.fetch_snapshot()

    assert [call[1]["page"] for call in transport.calls] == [1, 2]


@pytest.mark.asyncio
async def test_rejects_naive_adapter_clock() -> None:
    payload = _page(1, 1, [_row(1)])
    source = PolyCopCandidateWalletSource(
        transport=FakeTransport({1: [payload, payload]}),
        clock=lambda: datetime(2026, 8, 22),
        page_delay_seconds=0,
        consistency_attempts=1,
    )

    with pytest.raises(PolyCopSourceError, match="timezone-aware"):
        await source.fetch_snapshot()


@pytest.mark.asyncio
async def test_transport_retries_only_bounded_retryable_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []
    attempts = 0

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    def read_json(_url: str) -> dict[str, str]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise HTTPError("safe", 500, "server", None, None)
        return {"status": "success"}

    transport = UrllibPolyCopTransport(
        max_attempts=2,
        backoff_seconds=0.5,
        sleeper=sleeper,
    )
    monkeypatch.setattr(transport, "_read_json", read_json)

    result = await transport.get_json(POLYCOP_LEADERBOARD_PATH, {"page": 1})

    assert result == {"status": "success"}
    assert attempts == 2
    assert delays == [0.5]


@pytest.mark.asyncio
async def test_transport_does_not_retry_non_retryable_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def read_json(_url: str) -> dict[str, str]:
        nonlocal attempts
        attempts += 1
        raise HTTPError("safe", 404, "missing", None, None)

    transport = UrllibPolyCopTransport(max_attempts=3)
    monkeypatch.setattr(transport, "_read_json", read_json)

    with pytest.raises(PolyCopSourceError, match="HTTP 404"):
        await transport.get_json(POLYCOP_LEADERBOARD_PATH, {"page": 1})
    assert attempts == 1


def test_transport_redirect_handler_refuses_all_redirect_destinations() -> None:
    handler = _RejectRedirectHandler()
    transport = UrllibPolyCopTransport()

    redirected = handler.redirect_request(
        Request("https://polycop.fun/api/leaderboard"),
        None,
        302,
        "Found",
        None,
        "http://127.0.0.1/internal",
    )

    assert redirected is None
    assert any(
        isinstance(opener_handler, _RejectRedirectHandler)
        for opener_handler in transport._opener.handlers
    )
