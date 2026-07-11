from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from pm_trader.risk.kill_switch import KillSwitch


class SafetyPause(Protocol):
    def activate(self, reason: str) -> None:
        """Activate a safety pause without trading side effects."""


@dataclass(frozen=True, slots=True)
class SafetyPauseState:
    active: bool
    reason: str | None
    activated_at: datetime | None


class InMemorySafetyPause:
    def __init__(self) -> None:
        self._active = False
        self._reason: str | None = None
        self._activated_at: datetime | None = None

    def activate(self, reason: str) -> None:
        self._active = True
        self._reason = reason
        self._activated_at = datetime.now(UTC)

    @property
    def state(self) -> SafetyPauseState:
        return SafetyPauseState(
            active=self._active,
            activated_at=self._activated_at,
            reason=self._reason,
        )


class KillSwitchSafetyPause:
    def __init__(self, kill_switch: KillSwitch) -> None:
        self._kill_switch = kill_switch

    def activate(self, reason: str) -> None:
        self._kill_switch.activate(reason)
