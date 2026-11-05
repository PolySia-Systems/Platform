from __future__ import annotations

import pytest

from polysia.domain.copytrading.native_run_limits import NativeRunLimits


def test_native_capacity_defaults_and_explicit_envelope_are_distinct() -> None:
    assert NativeRunLimits.from_admission({}) == NativeRunLimits(10_000, 67_108_864)
    upper = NativeRunLimits(100_000, 268_435_456)
    assert NativeRunLimits.from_admission({"run_limits": upper.to_dict()}) == upper


@pytest.mark.parametrize("events,storage", [(0, 1), (100_001, 1), (True, 1),
    (1.5, 1), (1, 9_999_999), (1, 268_435_457), (1, True), (1, "100")])
def test_native_capacity_cannot_disable_or_exceed_limits(events, storage) -> None:
    with pytest.raises(ValueError):
        NativeRunLimits(events, storage)


@pytest.mark.parametrize("value", [None, {}, {"contract": "wrong"},
    {"contract": "native-period-capacity/v1", "period_max_events": 1,
     "period_max_storage_bytes": 1, "wallet_bankroll": "999999"}])
def test_native_capacity_rejects_unknown_or_financial_overrides(value) -> None:
    with pytest.raises(ValueError):
        NativeRunLimits.from_admission({"run_limits": value})
