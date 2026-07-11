from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from pm_trader.monitoring.fill_simulation import (
    FillSimulationAuditConfig,
    FillSimulationAuditError,
    build_fill_simulation_audit,
    load_fill_simulation_records,
    render_fill_simulation_audit_html,
    render_fill_simulation_audit_json,
    render_fill_simulation_audit_markdown,
)


def fixed_clock() -> datetime:
    return datetime(2026, 7, 1, tzinfo=UTC)


def test_conservative_model_fills_marketable_order(tmp_path: Path) -> None:
    input_path = _write_orders(tmp_path, [_order()])

    report = build_fill_simulation_audit(
        FillSimulationAuditConfig(
            input_path=input_path,
            models=("conservative",),
        ),
        clock=fixed_clock,
    )

    model = report.models[0]
    assert report.classification == "FILL_MODEL_CONSERVATIVE_OK"
    assert model.simulated_order_count == 1
    assert model.simulated_fill_count == 1
    assert model.average_fill_price == Decimal("0.5200")
    assert model.average_slippage == Decimal("0.0150")
    assert model.fills[0].status == "filled"


def test_top_of_book_model_tracks_partial_fill(tmp_path: Path) -> None:
    input_path = _write_orders(tmp_path, [_order(size="5", ask_depth="2")])

    report = build_fill_simulation_audit(
        FillSimulationAuditConfig(
            input_path=input_path,
            models=("top-of-book",),
        ),
        clock=fixed_clock,
    )

    model = report.models[0]
    assert model.partial_fill_count == 1
    assert model.fills[0].filled_size == Decimal("2")
    assert model.fills[0].status == "partial"


def test_missed_fill_is_counted_when_order_does_not_cross(tmp_path: Path) -> None:
    input_path = _write_orders(tmp_path, [_order(price="0.51")])

    report = build_fill_simulation_audit(
        FillSimulationAuditConfig(
            input_path=input_path,
            models=("conservative",),
        ),
        clock=fixed_clock,
    )

    model = report.models[0]
    assert report.classification == "FILL_MODEL_NEEDS_MORE_DATA"
    assert model.missed_fill_count == 1
    assert model.simulated_fill_count == 0
    assert "did not cross" in model.fills[0].reason


def test_queue_aware_model_is_deterministic(tmp_path: Path) -> None:
    input_path = _write_orders(tmp_path, [_order(size="4", ask_depth="4")])

    report = build_fill_simulation_audit(
        FillSimulationAuditConfig(
            input_path=input_path,
            models=("queue-aware",),
            queue_penalty=Decimal("0.50"),
        ),
        clock=fixed_clock,
    )

    model = report.models[0]
    assert model.partial_fill_count == 1
    assert model.fills[0].filled_size == Decimal("2.0000")
    assert "queue penalty" in model.fills[0].reason


def test_fill_simulation_reports_are_sanitized(tmp_path: Path) -> None:
    payload = {"orders": [_order()], "secret": "not-for-output"}
    input_path = tmp_path / "orders.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    report = build_fill_simulation_audit(
        FillSimulationAuditConfig(input_path=input_path),
        clock=fixed_clock,
    )

    combined = (
        render_fill_simulation_audit_json(report)
        + render_fill_simulation_audit_markdown(report)
        + render_fill_simulation_audit_html(report)
    )
    assert "not-for-output" not in combined
    assert "No live trading" in combined


def test_fill_simulation_rejects_malformed_json(tmp_path: Path) -> None:
    input_path = tmp_path / "bad.json"
    input_path.write_text("{bad", encoding="utf-8")

    with pytest.raises(FillSimulationAuditError):
        load_fill_simulation_records(input_path)


def _write_orders(tmp_path: Path, orders: list[dict[str, object]]) -> Path:
    input_path = tmp_path / "orders.json"
    input_path.write_text(json.dumps({"orders": orders}), encoding="utf-8")
    return input_path


def _order(
    *,
    price: str = "0.53",
    size: str = "1",
    ask_depth: str = "10",
) -> dict[str, object]:
    return {
        "book": {
            "ask_depth": ask_depth,
            "best_ask": "0.52",
            "best_bid": "0.49",
            "bid_depth": "10",
        },
        "intent": {
            "price": price,
            "side": "BUY",
            "size": size,
            "token_id": "token-1",
        },
        "order_id": "order-1",
        "token_id": "token-1",
    }
