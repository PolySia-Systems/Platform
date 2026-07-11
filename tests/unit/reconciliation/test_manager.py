from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from pm_trader.config.settings import AppSettings, TradingMode
from pm_trader.reconciliation import detectors, manager, reports
from pm_trader.reconciliation.manager import ReconciliationManager
from pm_trader.reconciliation.models import (
    ActualAccountState,
    InternalExpectedState,
    OrderSnapshot,
    PositionSnapshot,
    ReconciliationEventType,
    ReconciliationInput,
    ReconciliationStatus,
)
from pm_trader.reconciliation.reports import (
    ReconciliationReportConfig,
    write_reconciliation_reports,
)
from pm_trader.reconciliation.safety_pause import KillSwitchSafetyPause
from pm_trader.risk.kill_switch import KillSwitch

CHECKED_AT = datetime(2026, 7, 2, 15, 0, tzinfo=UTC)


def test_manual_order_cancel_is_detected_and_pauses_trading() -> None:
    kill_switch = KillSwitch()

    result = ReconciliationManager(
        safety_pause=KillSwitchSafetyPause(kill_switch)
    ).reconcile(
        make_input(
            internal=InternalExpectedState(
                open_orders=(OrderSnapshot(order_id="order-1"),),
                updated_at=CHECKED_AT,
            ),
            actual=ActualAccountState(open_orders=()),
            live_mode=True,
        )
    )

    assert result.status == ReconciliationStatus.BLOCKED
    assert result.manual_intervention_detected is True
    assert result.trading_should_pause is True
    assert result.requires_manual_acknowledgement is True
    assert result.safety_pause_activated is True
    assert kill_switch.is_active()
    assert has_event(result, ReconciliationEventType.MANUAL_ORDER_CANCEL_DETECTED)
    assert has_event(result, ReconciliationEventType.MISSING_OPEN_ORDER)


def test_manual_position_close_is_detected() -> None:
    result = ReconciliationManager().reconcile(
        make_input(
            internal=InternalExpectedState(
                positions=(PositionSnapshot(token_id="token-1", size=Decimal("1")),),
                updated_at=CHECKED_AT,
            ),
            actual=ActualAccountState(
                positions=(PositionSnapshot(token_id="token-1", size=Decimal("0")),)
            ),
            live_mode=True,
        )
    )

    assert result.status == ReconciliationStatus.BLOCKED
    assert result.manual_intervention_detected is True
    assert has_event(result, ReconciliationEventType.MANUAL_POSITION_CLOSE_DETECTED)


def test_unexpected_fill_is_detected() -> None:
    result = ReconciliationManager().reconcile(
        make_input(
            internal=InternalExpectedState(
                positions=(PositionSnapshot(token_id="token-1", size=Decimal("1")),),
                updated_at=CHECKED_AT,
            ),
            actual=ActualAccountState(
                positions=(PositionSnapshot(token_id="token-1", size=Decimal("2")),)
            ),
            live_mode=True,
        )
    )

    assert result.status == ReconciliationStatus.BLOCKED
    assert result.manual_intervention_detected is True
    assert has_event(result, ReconciliationEventType.UNEXPECTED_FILL_DETECTED)


def test_unexpected_open_order_is_detected() -> None:
    result = ReconciliationManager().reconcile(
        make_input(
            internal=InternalExpectedState(updated_at=CHECKED_AT),
            actual=ActualAccountState(
                open_orders=(OrderSnapshot(order_id="external-order-1"),)
            ),
            live_mode=True,
        )
    )

    assert result.status == ReconciliationStatus.BLOCKED
    assert result.manual_intervention_detected is True
    assert has_event(result, ReconciliationEventType.UNEXPECTED_OPEN_ORDER)
    assert has_event(result, ReconciliationEventType.UNKNOWN_EXTERNAL_ORDER)


def test_account_read_failure_warns_or_blocks_by_runtime_mode() -> None:
    data_only_result = ReconciliationManager().reconcile(
        make_input(
            actual=ActualAccountState(
                account_error_type="offline",
                account_readable=False,
                open_orders_readable=False,
                positions_readable=False,
            ),
            live_mode=False,
        )
    )
    live_result = ReconciliationManager().reconcile(
        make_input(
            actual=ActualAccountState(
                account_error_type="offline",
                account_readable=False,
                open_orders_readable=False,
                positions_readable=False,
            ),
            live_mode=True,
        )
    )

    assert data_only_result.status == ReconciliationStatus.WARNING
    assert live_result.status == ReconciliationStatus.BLOCKED
    assert live_result.trading_should_pause is True
    assert has_event(live_result, ReconciliationEventType.ACCOUNT_READ_FAILURE)
    assert has_event(live_result, ReconciliationEventType.LIVE_STATE_UNAVAILABLE)


def test_geoblock_failure_and_stale_internal_state_are_detected() -> None:
    result = ReconciliationManager().reconcile(
        make_input(
            internal=InternalExpectedState(updated_at=CHECKED_AT - timedelta(minutes=10)),
            actual=ActualAccountState(
                geoblock_error_type="TimeoutError",
                geoblock_readable=False,
            ),
            live_mode=True,
        )
    )

    assert result.status == ReconciliationStatus.BLOCKED
    assert has_event(result, ReconciliationEventType.GEOBLOCK_CHECK_FAILURE)
    assert has_event(result, ReconciliationEventType.STALE_INTERNAL_STATE)


def test_report_json_markdown_are_sanitized(tmp_path: Path) -> None:
    result = ReconciliationManager().reconcile(
        make_input(
            internal=InternalExpectedState(
                open_orders=(OrderSnapshot(order_id="order-1"),),
                updated_at=CHECKED_AT,
            ),
            actual=ActualAccountState(open_orders=()),
            live_mode=True,
        )
    )

    write_reconciliation_reports(
        ReconciliationReportConfig(settings=safe_settings(), output_dir=tmp_path),
        result,
    )

    json_path = tmp_path / "reconciliation-report.json"
    markdown_path = tmp_path / "reconciliation-report.md"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    combined = (
        json_path.read_text(encoding="utf-8")
        + markdown_path.read_text(encoding="utf-8")
    )
    assert payload["status"] == "blocked"
    assert markdown_path.is_file()
    assert "not-for-output" not in combined
    assert "0x2222222222222222222222222222222222222222" not in combined
    assert "0x3333333333333333333333333333333333333333" not in combined
    assert "5797652204687091435321040411695795253208330542199837124800358911" not in combined
    assert "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in combined


def test_reconciliation_code_never_references_live_submit_or_cancel() -> None:
    source = (
        inspect.getsource(detectors)
        + inspect.getsource(manager)
        + inspect.getsource(reports)
    )

    assert "LiveBroker" not in source
    assert "place_market_order" not in source
    assert "place_limit_order" not in source
    assert "cancel_order" not in source
    assert "cancel_market_orders" not in source


def make_input(
    *,
    actual: ActualAccountState,
    internal: InternalExpectedState | None = None,
    live_mode: bool,
) -> ReconciliationInput:
    return ReconciliationInput(
        actual=actual,
        checked_at=CHECKED_AT,
        internal=internal or InternalExpectedState(updated_at=CHECKED_AT),
        live_mode=live_mode,
    )


def has_event(result, event_type: ReconciliationEventType) -> bool:
    return any(event.event_type == event_type for event in result.detected_events)


def safe_settings() -> AppSettings:
    return AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.DATA_ONLY,
        LIVE_TRADING_ENABLED=False,
        POLYMARKET_FUNDER_ADDRESS="0x3333333333333333333333333333333333333333",
        POLYMARKET_LIVE_TOKEN_ALLOWLIST=(
            "5797652204687091435321040411695795253208330542199837124800358911"
        ),
        POLYMARKET_WALLET_ADDRESS="0x2222222222222222222222222222222222222222",
        **{"POLYMARKET_PRIVATE_KEY": "not-for-output"},
    )
