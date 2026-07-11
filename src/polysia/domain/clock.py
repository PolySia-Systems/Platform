from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


class SystemClock:
    """Production clock using timezone-aware UTC."""

    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class FixedClock:
    """Deterministic clock for tests and replay."""

    value: datetime

    def now(self) -> datetime:
        if self.value.tzinfo is None:
            return self.value.replace(tzinfo=UTC)
        return self.value

