"""Versioned observation authority, independent of economic entry qualification."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timedelta

RUNTIME = "continuous-shadow-native-health-v1"
PURPOSE = "TECHNICAL_HEALTH_V1"
WATCH_PROFILE = "native-observation-watch/v1"
ADMISSION = "native-health-admission/v1"


def validate_health_admission(
    value: Mapping[str, object],
    *,
    code_sha: str | None,
    watch_digest: str | None,
    now: datetime,
) -> None:
    if (
        not isinstance(code_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", code_sha)
        or not isinstance(watch_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", watch_digest)
        or value.get("resource_admitted") is not True
        or value.get("contract") != ADMISSION
        or value.get("purpose") != PURPOSE
        or value.get("mode") != "CONTINUOUS"
        or value.get("code_sha") != code_sha
        or value.get("cohort_digest") != watch_digest
        or value.get("financial_authority") is not False
        or "persisted_simulations" in value
        or now.utcoffset() != timedelta(0)
    ):
        raise ValueError("native health admission purpose or identity mismatch")
    expiry = datetime.fromisoformat(str(value.get("expires_at", "")))
    if expiry.utcoffset() != timedelta(0) or expiry <= now:
        raise ValueError("native health admission expired or non-UTC")
