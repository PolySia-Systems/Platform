"""Shared integrity contract for retained report serving and cold recovery."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

MAX_REPORT_BYTES = 8_000_000
MAX_REPORT_ARCHIVE_BYTES = 33_554_432


def verify_analytical_digest(report: Any) -> None:
    if not isinstance(report, dict) or not isinstance(report.get("analytical"), dict):
        raise ValueError("invalid_analytical_report")
    encoded = json.dumps(report["analytical"], sort_keys=True, separators=(",", ":")).encode()
    if not hmac.compare_digest(
        hashlib.sha256(encoded).hexdigest(), str(report.get("analytical_digest", ""))
    ):
        raise ValueError("analytical_report_digest_differs")
