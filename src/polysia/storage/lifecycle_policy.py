from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

STAGE4B_DATA_LIFECYCLE_POLICY_VERSION = "stage4b-data-lifecycle-v1"
RECOVERY_BUNDLE_POLICY_VERSION = "recovery-bundle-v1"
MARK_HISTORY_RETENTION_DAYS = 30
RECOVERY_BUNDLE_KEEP = 3
DISK_SAFETY_FLOOR_BYTES = 4 * 1024 * 1024 * 1024
RECOVERY_BUNDLE_MAX_SKEW_SECONDS = 3600


def _as_int(value: object, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ValueError("lifecycle policy integer field is invalid")
    return int(value)


@dataclass(frozen=True, slots=True)
class Stage4BDataLifecyclePolicy:
    """Engine-independent Stage 4B storage lifecycle rules.

    SQLite is the current store. The policy is versioned application
    configuration so a later store can apply the same retention and recovery
    bounds without inheriting SQLite-specific meaning.
    """

    policy_version: str = STAGE4B_DATA_LIFECYCLE_POLICY_VERSION
    mark_history_retention_days: int = MARK_HISTORY_RETENTION_DAYS
    recovery_bundle_keep: int = RECOVERY_BUNDLE_KEEP
    disk_safety_floor_bytes: int = DISK_SAFETY_FLOOR_BYTES
    recovery_bundle_max_skew_seconds: int = RECOVERY_BUNDLE_MAX_SKEW_SECONDS

    def __post_init__(self) -> None:
        if self.mark_history_retention_days < 1:
            raise ValueError("mark_history_retention_days must be at least 1")
        if self.recovery_bundle_keep < 1:
            raise ValueError("recovery_bundle_keep must be at least 1")
        if self.disk_safety_floor_bytes < 1:
            raise ValueError("disk_safety_floor_bytes must be positive")
        if self.recovery_bundle_max_skew_seconds < 0:
            raise ValueError("recovery_bundle_max_skew_seconds must not be negative")

    @property
    def mark_history_retention(self) -> timedelta:
        return timedelta(days=self.mark_history_retention_days)

    def to_dict(self) -> dict[str, object]:
        return {
            "disk_safety_floor_bytes": self.disk_safety_floor_bytes,
            "mark_history_retention_days": self.mark_history_retention_days,
            "policy_version": self.policy_version,
            "recovery_bundle_keep": self.recovery_bundle_keep,
            "recovery_bundle_max_skew_seconds": self.recovery_bundle_max_skew_seconds,
            "recovery_bundle_policy_version": RECOVERY_BUNDLE_POLICY_VERSION,
        }

    @classmethod
    def from_mapping(
        cls, payload: Mapping[str, object] | None = None
    ) -> Stage4BDataLifecyclePolicy:
        data = dict(payload or {})
        return cls(
            policy_version=str(
                data.get("policy_version", STAGE4B_DATA_LIFECYCLE_POLICY_VERSION)
            ),
            mark_history_retention_days=_as_int(
                data.get("mark_history_retention_days"), MARK_HISTORY_RETENTION_DAYS
            ),
            recovery_bundle_keep=_as_int(
                data.get("recovery_bundle_keep"), RECOVERY_BUNDLE_KEEP
            ),
            disk_safety_floor_bytes=_as_int(
                data.get("disk_safety_floor_bytes"), DISK_SAFETY_FLOOR_BYTES
            ),
            recovery_bundle_max_skew_seconds=_as_int(
                data.get("recovery_bundle_max_skew_seconds"),
                RECOVERY_BUNDLE_MAX_SKEW_SECONDS,
            ),
        )


def history_cutoff(now: datetime, *, policy: Stage4BDataLifecyclePolicy) -> datetime:
    return now - policy.mark_history_retention


DEFAULT_STAGE4B_DATA_LIFECYCLE_POLICY = Stage4BDataLifecyclePolicy()

__all__ = [
    "DEFAULT_STAGE4B_DATA_LIFECYCLE_POLICY",
    "DISK_SAFETY_FLOOR_BYTES",
    "MARK_HISTORY_RETENTION_DAYS",
    "RECOVERY_BUNDLE_KEEP",
    "RECOVERY_BUNDLE_MAX_SKEW_SECONDS",
    "RECOVERY_BUNDLE_POLICY_VERSION",
    "STAGE4B_DATA_LIFECYCLE_POLICY_VERSION",
    "Stage4BDataLifecyclePolicy",
    "history_cutoff",
]
