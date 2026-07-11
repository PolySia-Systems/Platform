from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class KillSwitchState:
    active: bool
    reason: str | None
    activated_at: datetime | None


class KillSwitch:
    """In-process kill switch that blocks order intents when active."""

    def __init__(self) -> None:
        self._active = False
        self._reason: str | None = None
        self._activated_at: datetime | None = None

    def activate(self, reason: str) -> None:
        if not reason:
            raise ValueError("kill switch reason must not be empty")
        self._active = True
        self._reason = reason
        self._activated_at = datetime.now(UTC)

    def deactivate(self) -> None:
        self._active = False
        self._reason = None
        self._activated_at = None

    def is_active(self) -> bool:
        return self._active

    @property
    def reason(self) -> str | None:
        return self._reason

    @property
    def state(self) -> KillSwitchState:
        return KillSwitchState(
            active=self._active,
            reason=self._reason,
            activated_at=self._activated_at,
        )
