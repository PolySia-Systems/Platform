"""Versioned bounded profiles for the research experiment Runner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from polysia.domain.research_evidence.economic_contract import CONTRACT_V1

PROFILE_CANARY = "canary"
PROFILE_MAIN = "main"
CANARY_PROFILE_VERSION = "canary-v1"
MAIN_PROFILE_VERSION = "main-v1"
RUNNER_MANIFEST_VERSION = "research-runner-manifest-v1"
DEFAULT_WARMUP = timedelta(seconds=30)
DEFAULT_WINDOW = timedelta(minutes=10)
MAIN_DURATION = timedelta(hours=4)
MAIN_WINDOWS = 24
CANARY_WINDOWS = 2
MAIN_MAX_EVENTS = 750_000
MAIN_MAX_BYTES = 805_306_368
CANARY_MAX_EVENTS = 75_000
CANARY_MAX_BYTES = 80_530_636
DEFAULT_MEMORY_BYTES = 2 * 1024 * 1024 * 1024
FINALIZATION_GRACE = timedelta(minutes=30)
SAFETY_MARGIN_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class RunnerProfile:
    name: str
    version: str
    window: timedelta
    window_count: int
    warmup: timedelta
    max_events: int
    max_bytes: int
    memory_bytes: int

    def __post_init__(self) -> None:
        if self.window.total_seconds() <= 0 or self.window_count < 1:
            raise ValueError("runner profile window bounds must be positive")
        if self.warmup.total_seconds() < 0:
            raise ValueError("runner profile warm-up must not be negative")
        if self.max_events < 1 or self.max_bytes < 1 or self.memory_bytes < 1:
            raise ValueError("runner profile resource bounds must be positive")
        if self.name == PROFILE_MAIN and self.duration > MAIN_DURATION:
            raise ValueError("main research profile cannot exceed four hours")

    @property
    def duration(self) -> timedelta:
        return self.window * self.window_count

    @property
    def collection_deadline_offset(self) -> timedelta:
        return self.duration

    @property
    def valuation_cutoff_offset(self) -> timedelta:
        return self.duration

    @property
    def finalization_deadline_offset(self) -> timedelta:
        return self.duration + FINALIZATION_GRACE

    def to_dict(self) -> dict[str, object]:
        return {
            "acceptance_thresholds": {
                "canary_execution_ratio": format(CONTRACT_V1.canary_execution_ratio, "f"),
                "canary_mapping_ratio": format(CONTRACT_V1.canary_mapping_ratio, "f"),
                "canary_min_eligible": CONTRACT_V1.canary_min_eligible,
            },
            "duration_seconds": int(self.duration.total_seconds()),
            "max_bytes": self.max_bytes,
            "max_events": self.max_events,
            "memory_bytes": self.memory_bytes,
            "name": self.name,
            "version": self.version,
            "warmup_seconds": int(self.warmup.total_seconds()),
            "window_count": self.window_count,
            "window_seconds": int(self.window.total_seconds()),
        }


CANARY_PROFILE = RunnerProfile(
    name=PROFILE_CANARY,
    version=CANARY_PROFILE_VERSION,
    window=DEFAULT_WINDOW,
    window_count=CANARY_WINDOWS,
    warmup=DEFAULT_WARMUP,
    max_events=CANARY_MAX_EVENTS,
    max_bytes=CANARY_MAX_BYTES,
    memory_bytes=DEFAULT_MEMORY_BYTES,
)
MAIN_PROFILE = RunnerProfile(
    name=PROFILE_MAIN,
    version=MAIN_PROFILE_VERSION,
    window=DEFAULT_WINDOW,
    window_count=MAIN_WINDOWS,
    warmup=DEFAULT_WARMUP,
    max_events=MAIN_MAX_EVENTS,
    max_bytes=MAIN_MAX_BYTES,
    memory_bytes=DEFAULT_MEMORY_BYTES,
)
PROFILES = {PROFILE_CANARY: CANARY_PROFILE, PROFILE_MAIN: MAIN_PROFILE}


def resolve_profile(name: str) -> RunnerProfile:
    profile = PROFILES.get(name)
    if profile is None:
        raise ValueError("research runner profile is not supported")
    return profile
