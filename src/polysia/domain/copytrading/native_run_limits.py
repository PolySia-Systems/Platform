"""Explicit finite native-period capacity; financial and legacy defaults stay fixed."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NativeRunLimits:
    period_max_events: int = 10_000
    period_max_storage_bytes: int = 67_108_864

    def __post_init__(self) -> None:
        if (type(self.period_max_events) is not int
                or not 1 <= self.period_max_events <= 100_000
                or type(self.period_max_storage_bytes) is not int
                or not 10_000_000 <= self.period_max_storage_bytes <= 268_435_456):
            raise ValueError("native period capacity outside finite envelope")

    @classmethod
    def from_admission(cls, admission: Mapping[str, object]) -> NativeRunLimits:
        if "run_limits" not in admission:
            return cls()
        value = admission["run_limits"]
        if (not isinstance(value, dict)
                or set(value) != {"contract", "period_max_events", "period_max_storage_bytes"}
                or value["contract"] != "native-period-capacity/v1"):
            raise ValueError("native period capacity contract invalid")
        return cls(value["period_max_events"], value["period_max_storage_bytes"])

    def to_dict(self) -> dict[str, object]:
        return {"contract": "native-period-capacity/v1",
                "period_max_events": self.period_max_events,
                "period_max_storage_bytes": self.period_max_storage_bytes}
