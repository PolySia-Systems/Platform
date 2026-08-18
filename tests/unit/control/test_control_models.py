from __future__ import annotations

import pytest
from pydantic import ValidationError

from polysia.control.models import OperationalState, StrategyControlKey
from polysia.domain.strategy import StrategyLifecycleStatus


def test_lifecycle_and_operational_state_are_distinct_contracts() -> None:
    assert StrategyLifecycleStatus.SHADOW.value == "shadow"
    assert OperationalState.PAUSED.value == "PAUSED"
    assert OperationalState.RUNNING.value == "RUNNING"
    assert not issubclass(OperationalState, StrategyLifecycleStatus)


@pytest.mark.parametrize("runtime_mode", ["PAPER", "LIVE"])
def test_control_key_rejects_every_non_shadow_mode(runtime_mode: str) -> None:
    with pytest.raises(ValidationError, match="runtime_mode"):
        StrategyControlKey(
            strategy_id="stale-price",
            strategy_version="0.1.0",
            runtime_mode=runtime_mode,  # type: ignore[arg-type]
        )
