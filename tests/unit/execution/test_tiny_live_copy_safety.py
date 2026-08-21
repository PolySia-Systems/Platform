from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from polysia.adapters.polymarket.geoblock import GeoblockStatus
from polysia.application.ports.cancellation import (
    CancellationResponse,
    OpenOrderEvidence,
    OrderDetailEvidence,
    OrderLookupStatus,
    OrderTradeEvidence,
)
from polysia.config.settings import AppSettings
from polysia.domain.copytrading import CopyExperimentState
from polysia.domain.market import (
    MarketDetails,
    MarketFeeSchedule,
    MarketOutcomeSummary,
)
from polysia.execution.tiny_live_copy import (
    TinyLiveCopyConfig,
    TinyLiveCopyError,
    _assert_market_mapping,
    _emergency_cancel_if_needed,
    _heartbeat_is_fresh,
    _refresh_active_health,
    _refresh_safety_gates,
)
from polysia.risk.kill_switch import KillSwitch
from polysia.storage.copytrading import CopyExperimentRepository
from polysia.storage.db import SQLiteDatabase
from polysia.storage.repositories import LiveOrderCheckpointRepository

NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)
CONDITION = "0x" + ("a" * 64)
TOKEN = "111"


def _market(**overrides: Any) -> MarketDetails:
    values: dict[str, Any] = {
        "id": "market",
        "slug": f"btc-updown-15m-{int(NOW.timestamp())}",
        "active": True,
        "closed": False,
        "accepting_orders": True,
        "end_date": NOW + timedelta(minutes=15),
        "start_date": NOW,
        "outcomes": (
            MarketOutcomeSummary(label="Up", token_id=TOKEN, price=Decimal("0.5")),
            MarketOutcomeSummary(label="Down", token_id="222", price=Decimal("0.5")),
        ),
        "condition_id": CONDITION,
        "enable_order_book": True,
        "fee_schedule": MarketFeeSchedule(enabled=False),
    }
    values.update(overrides)
    return MarketDetails(**values)


def test_strict_btc_15m_mapping_accepts_only_exact_current_market() -> None:
    market = _market()
    _assert_market_mapping(
        market,
        expected_slug=str(market.slug),
        expected_condition=CONDITION,
        token_id=TOKEN,
        expected_outcome_label="Up",
        expected_start=NOW,
        expected_end=NOW + timedelta(minutes=15),
        now=NOW,
    )

    with pytest.raises(TinyLiveCopyError, match="exact BTC"):
        _assert_market_mapping(
            _market(slug="not-btc-15m"),
            expected_slug="not-btc-15m",
            expected_condition=CONDITION,
            token_id=TOKEN,
            expected_outcome_label="Up",
            expected_start=NOW,
            expected_end=NOW + timedelta(minutes=15),
            now=NOW,
        )


def test_tiny_live_copy_market_time_gate_is_exactly_four_minutes() -> None:
    market = _market()
    _assert_market_mapping(
        market,
        expected_slug=str(market.slug),
        expected_condition=CONDITION,
        token_id=TOKEN,
        expected_outcome_label="Up",
        expected_start=NOW,
        expected_end=NOW + timedelta(minutes=15),
        now=NOW + timedelta(minutes=11),
    )

    with pytest.raises(TinyLiveCopyError, match="four minutes"):
        _assert_market_mapping(
            market,
            expected_slug=str(market.slug),
            expected_condition=CONDITION,
            token_id=TOKEN,
            expected_outcome_label="Up",
            expected_start=NOW,
            expected_end=NOW + timedelta(minutes=15),
            now=NOW + timedelta(minutes=11, milliseconds=1),
        )


def test_heartbeat_fails_closed_after_sixty_seconds() -> None:
    assert _heartbeat_is_fresh(NOW, NOW + timedelta(seconds=60))
    assert not _heartbeat_is_fresh(NOW, NOW + timedelta(seconds=61))


class _AllowedGeoblock:
    async def check(self) -> GeoblockStatus:
        return GeoblockStatus(status="allowed", checked_at=NOW, blocked=False)


class _StaleWebsocketExecution:
    async def read_clock_drift(self) -> Decimal:
        return Decimal("0")

    async def probe_user_stream(self, *, market: str | None = None) -> None:
        del market
        raise RuntimeError("stale user websocket")


class _SafetyGateExecution:
    def __init__(
        self,
        *,
        balance: int,
        positions: list[Any] | None = None,
    ) -> None:
        self._balance = balance
        self._positions = positions or []

    async def read_clock_drift(self) -> Decimal:
        return Decimal("0")

    async def probe_user_stream(self, *, market: str | None = None) -> None:
        del market

    async def get_open_orders(self, **kwargs: Any) -> list[Any]:
        del kwargs
        return []

    async def list_positions(self, **kwargs: Any) -> list[Any]:
        del kwargs
        return self._positions

    async def get_balance_allowance(self, **kwargs: Any) -> dict[str, object]:
        if kwargs["asset_type"] == "COLLATERAL":
            return {
                "balance": self._balance,
                "allowances": {"exchange": 10_000_000},
            }
        return {"balance": 0, "allowances": {"exchange": 10_000_000}}


@pytest.mark.asyncio
async def test_stale_user_websocket_blocks_active_entry_health() -> None:
    with pytest.raises(RuntimeError, match="stale"):
        await _refresh_active_health(
            execution_port=_StaleWebsocketExecution(),  # type: ignore[arg-type]
            geoblock_port=_AllowedGeoblock(),
            kill_switch=KillSwitch(),
            settings=AppSettings(_env_file=None),
        )


@pytest.mark.asyncio
async def test_insufficient_remaining_balance_blocks_before_submission() -> None:
    with pytest.raises(TinyLiveCopyError, match="balance"):
        await _refresh_safety_gates(
            execution_port=_SafetyGateExecution(balance=1_000_000),  # type: ignore[arg-type]
            geoblock_port=_AllowedGeoblock(),
            kill_switch=KillSwitch(),
            token_id=TOKEN,
            required_size=Decimal("5"),
            required_debit=Decimal("2"),
            settings=AppSettings(_env_file=None),
            now=NOW,
        )


@pytest.mark.asyncio
async def test_high_wallet_balance_and_closed_zero_value_history_are_allowed() -> None:
    historical = {
        "size": "5",
        "currentValue": "0",
        "curPrice": "0",
        "redeemable": True,
        "mergeable": False,
        "endDate": "2026-07-28",
    }

    await _refresh_safety_gates(
        execution_port=_SafetyGateExecution(  # type: ignore[arg-type]
            balance=10_213_845,
            positions=[historical],
        ),
        geoblock_port=_AllowedGeoblock(),
        kill_switch=KillSwitch(),
        token_id=TOKEN,
        required_size=Decimal("5"),
        required_debit=Decimal("2"),
        settings=AppSettings(_env_file=None),
        now=NOW,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "position",
    [
        {
            "size": "5",
            "currentValue": "1",
            "curPrice": "0.2",
            "redeemable": False,
            "mergeable": False,
            "endDate": "2026-07-28",
        },
        {
            "size": "5",
            "currentValue": "5",
            "curPrice": "1",
            "redeemable": True,
            "mergeable": False,
            "endDate": "2026-07-28",
        },
        {
            "size": "5",
            "currentValue": "0",
            "curPrice": "0",
            "redeemable": False,
            "mergeable": False,
            "endDate": "2026-07-29",
        },
        {"size": "5"},
    ],
)
async def test_active_redeemable_or_ambiguous_position_still_blocks(
    position: dict[str, object],
) -> None:
    with pytest.raises(TinyLiveCopyError, match="position"):
        await _refresh_safety_gates(
            execution_port=_SafetyGateExecution(  # type: ignore[arg-type]
                balance=10_213_845,
                positions=[position],
            ),
            geoblock_port=_AllowedGeoblock(),
            kill_switch=KillSwitch(),
            token_id=TOKEN,
            required_size=Decimal("5"),
            required_debit=Decimal("2"),
            settings=AppSettings(_env_file=None),
            now=NOW,
        )


class _EmergencyExecution:
    def __init__(self) -> None:
        self.open = True
        self.cancel_calls = 0

    @property
    def is_connected(self) -> bool:
        return True

    async def get_open_orders(self, **kwargs: Any) -> list[dict[str, str]]:
        del kwargs
        return [{"id": "open"}] if self.open else []

    async def observe_open_orders(
        self,
        *,
        order_id: str | None = None,
    ) -> tuple[OpenOrderEvidence, ...]:
        if not self.open or order_id not in {None, "open"}:
            return ()
        return (
            OpenOrderEvidence(
                order_id="open",
                token_id=TOKEN,
                side="BUY",
                status="LIVE",
                original_size=Decimal("5"),
                matched_size=Decimal("0"),
            ),
        )

    async def observe_order_detail(self, *, order_id: str) -> OrderDetailEvidence:
        assert order_id == "open"
        return OrderDetailEvidence(
            status=OrderLookupStatus.FOUND,
            order=OpenOrderEvidence(
                order_id="open",
                token_id=TOKEN,
                side="BUY",
                status="LIVE" if self.open else "CANCELED",
                original_size=Decimal("5"),
                matched_size=Decimal("0"),
            ),
        )

    async def observe_order_trades(self, **kwargs: Any) -> tuple[OrderTradeEvidence, ...]:
        del kwargs
        return ()

    async def observe_position_size(self, *, token_id: str) -> Decimal:
        assert token_id == TOKEN
        return Decimal("0")

    async def cancel_all(self) -> dict[str, bool]:
        self.cancel_calls += 1
        self.open = False
        return {"cancelled": True}

    async def cancel_all_for_finality(self) -> CancellationResponse:
        await self.cancel_all()
        return CancellationResponse(("open",), {})

    async def list_positions(self, **kwargs: Any) -> list[Any]:
        del kwargs
        return []


@pytest.mark.asyncio
async def test_emergency_cancel_all_is_confirmed_and_persisted(tmp_path: Path) -> None:
    with SQLiteDatabase(tmp_path / "state.sqlite3") as database:
        repository = CopyExperimentRepository(database.connection)
        repository.create(
            run_id="tiny-live-copy-test",
            authorization_id="test-authorization",
            started_at=NOW,
            signal_window_end=NOW + timedelta(hours=12),
            payload={},
        )
        repository.set_state(
            "tiny-live-copy-test",
            CopyExperimentState.MONITORING,
            updated_at=NOW,
        )
        execution = _EmergencyExecution()
        report = SimpleNamespace(emergency_cancel_status="not_invoked")

        async def no_sleep(seconds: float) -> None:
            del seconds

        await _emergency_cancel_if_needed(
            execution,  # type: ignore[arg-type]
            repository=repository,
            run_id="tiny-live-copy-test",
            report=report,  # type: ignore[arg-type]
            clock=lambda: NOW,
            sleeper=no_sleep,
            finality_checkpoints=LiveOrderCheckpointRepository(database.connection),
        )

        snapshot = repository.get("tiny-live-copy-test")
        assert execution.cancel_calls == 1
        assert report.emergency_cancel_status == "invoked_confirmed"
        assert snapshot is not None
        assert snapshot.state is CopyExperimentState.FAILED_SAFE
        checkpoints = LiveOrderCheckpointRepository(database.connection).list_for_run(
            "tiny-live-copy-test"
        )
        finality = next(
            item for item in checkpoints if str(item["phase"]).startswith("cancellation_finality:")
        )
        assert finality["payload"]["outcome"] == "CONFIRMED_NO_FILL"  # type: ignore[index]


def test_copy_runtime_cannot_bypass_risk_or_execution() -> None:
    source = Path("src/polysia/execution/tiny_live_copy.py").read_text(encoding="utf-8")

    assert "RiskEngine(" in source
    assert "LiveBroker(" in source
    assert "execution_port.place_limit_order" not in source
    assert "execution_port.place_market_order" not in source


def test_live_authorization_is_runtime_supplied_and_not_hardcoded(tmp_path: Path) -> None:
    common = {
        "settings": AppSettings(_env_file=None),
        "project_root": tmp_path,
        "output_dir": tmp_path / "reports",
        "database_path": tmp_path / "state.sqlite3",
        "candidate_file": tmp_path / "candidates.txt",
        "run_id": "tiny-live-copy-authorization-test",
        "dry_run": False,
    }
    with pytest.raises(ValueError, match="runtime authorization"):
        TinyLiveCopyConfig(**common)

    with pytest.raises(ValueError, match="runtime acknowledgement"):
        TinyLiveCopyConfig(
            **common,
            authorization_id="POLYSIA-TINY-LIVE-COPY-003",
        )

    config = TinyLiveCopyConfig(
        **common,
        authorization_id="POLYSIA-TINY-LIVE-COPY-003",
        acknowledgement=True,
    )
    assert config.authorization_id == "POLYSIA-TINY-LIVE-COPY-003"

    compose = Path("compose.yaml").read_text(encoding="utf-8")
    assert "POLYSIA_COPY_AUTHORIZATION_ID" in compose
    assert '--authorization-id "$${POLYSIA_COPY_AUTHORIZATION_ID}"' in compose
    assert "POLYSIA-TINY-LIVE-COPY-002" not in compose
