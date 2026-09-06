from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from polysia.execution.verified_live_state import (
    account_source_id_from_identity,
    snapshot_from_account_reads,
)
from polysia.risk.evidence import (
    LiveStateStaleError,
    LiveStateUnavailableError,
    MeasuredDecimal,
    MeasuredInt,
    VerifiedLiveRiskSnapshot,
)


def test_verified_zero_is_distinct_from_unknown() -> None:
    unknown = MeasuredDecimal.unknown()
    zero = MeasuredDecimal.verified(Decimal("0"), observed_at=datetime.now(UTC))

    assert unknown.value is None
    assert unknown.kind.value == "unknown"
    assert zero.value == Decimal("0")
    assert zero.kind.value == "verified"


def test_stale_verified_snapshot_is_rejected() -> None:
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    snapshot = VerifiedLiveRiskSnapshot(
        current_position=MeasuredDecimal.verified(Decimal("0"), observed_at=now),
        current_market_position=MeasuredDecimal.verified(Decimal("0"), observed_at=now),
        daily_pnl=MeasuredDecimal.verified(Decimal("0"), observed_at=now),
        open_order_count=MeasuredInt.verified(0, observed_at=now),
        market_data_observed_at=now,
        account_source_id="test:funder",
        observed_at=now,
    )

    with pytest.raises(LiveStateStaleError, match="exceeds max_stale_data_age_ms"):
        snapshot.require_fresh(now=now + timedelta(seconds=6), max_age_ms=5_000)


def test_snapshot_from_empty_account_reads_is_verified_zero() -> None:
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    snapshot = snapshot_from_account_reads(
        positions=[],
        open_orders=[],
        trades=[],
        token_id="token-1",
        market_id="condition-1",
        account_source_id="funder:EOA",
        market_data_observed_at=now,
        observed_at=now,
    )

    assert snapshot.current_position.value == Decimal("0")
    assert snapshot.daily_pnl.value == Decimal("0")
    assert snapshot.open_order_count.value == 0


def test_trade_without_timestamp_keeps_daily_pnl_unknown() -> None:
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    with pytest.raises(LiveStateUnavailableError, match="daily pnl is unknown"):
        snapshot_from_account_reads(
            positions=[],
            open_orders=[],
            trades=[{"side": "BUY", "price": "0.40", "size": "1"}],
            token_id="token-1",
            market_id="condition-1",
            account_source_id="funder:EOA",
            market_data_observed_at=now,
            observed_at=now,
        )


def test_account_source_id_from_identity() -> None:
    assert (
        account_source_id_from_identity(
            SimpleNamespace(active_wallet_source="funder", wallet_type="EOA")
        )
        == "funder:EOA"
    )
    with pytest.raises(LiveStateUnavailableError):
        account_source_id_from_identity(None)
