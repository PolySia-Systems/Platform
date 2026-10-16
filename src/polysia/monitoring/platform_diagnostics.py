"""Bounded provider-free operational projections from private retained receipts."""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any


def retained_diagnostics(authority: Path, discovery: dict[str, Any]) -> dict[str, Any]:
    root = authority.parent
    endpoints: dict[str, dict[str, Any]] = {}
    files = sorted((root / "evidence").glob("*.metadata.json"))
    files += sorted((root / "evidence").glob("*.failure.json"))
    for path in files[:1000]:
        if path.is_symlink() or path.stat().st_size > 65_536:
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        item = endpoints.setdefault(
            value["endpoint"],
            {
                "observed_requests": 0,
                "known_bytes": 0,
                "rate_limits": 0,
                "failures": 0,
                "latencies_ms": [],
                "last_attempt": None,
            },
        )
        item["observed_requests"] += 1
        item["known_bytes"] += value.get("bytes", 0)
        item["rate_limits"] += value.get("reason") == "provider_http_429"
        item["failures"] += "reason" in value
        item["latencies_ms"].append(value["latency_ms"])
        item["last_attempt"] = max(item["last_attempt"] or "", value["observed_at"])
    for item in endpoints.values():
        samples = sorted(item.pop("latencies_ms"))
        item["latency_p95_ms"] = samples[math.ceil(len(samples) * 0.95) - 1]
        item["latency_sample_count"] = len(samples)
    candidates = discovery.get("candidates", [])
    coverage = {"candidate_denominator": len(candidates)}
    for field in ("mapping_verified", "fee_known", "book_current"):
        coverage[field] = sum(row.get(field) is True for row in candidates)
    sizes = {path.name: path.stat().st_size for path in root.glob("*.sqlite3*") if path.is_file()}
    return {
        "provider_calls": 0,
        "endpoint_receipts": endpoints,
        "coverage": coverage,
        "metadata_sample_limit": 1000,
        "metadata_truncated": len(files) > 1000,
        "active_database_and_WAL_bytes": sizes,
        "host_free_disk_bytes": shutil.disk_usage(root).free,
        "valuation_coverage": "see canonical report; UNKNOWN is never filled by diagnostics",
        "writer_wait": "nonblocking OS lock; contention fails this tick",
        "backup_restore_health": "separate supervised receipts; absent receipt means UNKNOWN",
    }
