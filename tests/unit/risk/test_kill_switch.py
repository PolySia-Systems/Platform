from __future__ import annotations

import pytest

from pm_trader.risk.kill_switch import KillSwitch


def test_kill_switch_activates_and_deactivates() -> None:
    kill_switch = KillSwitch()

    kill_switch.activate("manual stop")

    assert kill_switch.is_active() is True
    assert kill_switch.reason == "manual stop"
    assert kill_switch.state.active is True
    assert kill_switch.state.activated_at is not None

    kill_switch.deactivate()

    assert kill_switch.is_active() is False
    assert kill_switch.reason is None
    assert kill_switch.state.activated_at is None


def test_kill_switch_requires_reason() -> None:
    kill_switch = KillSwitch()

    with pytest.raises(ValueError, match="reason"):
        kill_switch.activate("")
