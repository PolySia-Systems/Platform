"""Bounded provider-free operational projections from private retained receipts."""

from __future__ import annotations

import json
import math
import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from heapq import nlargest
from pathlib import Path
from typing import Any


def retained_diagnostics(
    authority: Path, discovery: dict[str, Any], *, database: Path | None = None,
) -> dict[str, Any]:
    try:
        result = _retained_diagnostics(authority, discovery)
        if database is not None and database.is_file():
            uri = database.resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as connection:
                row = connection.execute(
                    "SELECT request_telemetry_json FROM continuous_shadow_poll_runs "
                    "ORDER BY started_at DESC LIMIT 1"
                ).fetchone()
            result["latest_poll_requests"] = json.loads(row[0]) if row else {}
        return result
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
        return {"status": "UNAVAILABLE", "diagnostic_errors": 1, "provider_calls": 0}


def _retained_diagnostics(authority: Path, discovery: dict[str, Any]) -> dict[str, Any]:
    root = authority.parent
    endpoints: dict[str, dict[str, Any]] = {}
    index = root / "request-diagnostics.sqlite3"
    records = []
    window = datetime.now(UTC) - timedelta(hours=1)
    indexed = index.is_file()
    files = [] if indexed else list((root / "evidence").glob("*.metadata.json"))
    if not indexed:
        files += list((root / "evidence").glob("*.failure.json"))
    if indexed:
        with closing(sqlite3.connect(index.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            records = [dict(row) for row in connection.execute(
                "SELECT endpoint,observed_at,response_bytes AS bytes,duration_ms AS latency_ms,"
                "CASE WHEN status='COMPLETE' THEN NULL ELSE status END AS reason "
                "FROM requests WHERE observed_at>=? ORDER BY observed_at DESC LIMIT 1001",
                (window.isoformat(),),
            )]
            total = connection.execute(
                "SELECT COUNT(*) FROM requests WHERE observed_at>=?", (window.isoformat(),),
            ).fetchone()[0]
            attributed = connection.execute(
                "SELECT COUNT(*) FROM requests WHERE observed_at>=? "
                "AND poll_run_id IS NOT NULL AND experiment_id IS NOT NULL",
                (window.isoformat(),),
            ).fetchone()[0]
    else:
        total = len(files)
        attributed = None
    for path in ([] if indexed else nlargest(1000, files, key=lambda p: p.stat().st_mtime_ns)):
        if path.is_symlink() or path.stat().st_size > 65_536:
            continue
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    for value in records[:1000]:
        item = endpoints.setdefault(
            value["endpoint"],
            {
                "observed_requests": 0,
                "known_bytes": 0,
                "rate_limits": 0,
                "failures": 0,
                "latencies_ms": [],
                "unknown_latency_count": 0,
                "last_attempt": None,
            },
        )
        item["observed_requests"] += 1
        item["known_bytes"] += value.get("bytes") or 0
        item["rate_limits"] += value.get("reason") == "provider_http_429"
        item["failures"] += value.get("reason") is not None
        if type(value.get("latency_ms")) is int and value["latency_ms"] >= 0:
            item["latencies_ms"].append(value["latency_ms"])
        else:
            item["unknown_latency_count"] += 1
        item["last_attempt"] = max(item["last_attempt"] or "", value["observed_at"])
    for item in endpoints.values():
        samples = sorted(item.pop("latencies_ms"))
        item["latency_p95_ms"] = samples[math.ceil(len(samples) * 0.95) - 1] if samples else None
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
        "metadata_truncated": total > 1000,
        "metadata_total_in_window": total,
        "request_attribution": {"correlated": attributed, "observed": total,
                                "meaning": "poll/experiment bindings; preparation may be unbound"},
        "metadata_sampled": min(1000, len(records)),
        "metadata_window_start": window.isoformat() if indexed else None,
        "metadata_window_end": datetime.now(UTC).isoformat() if indexed else None,
        "metadata_coverage": "recent indexed attempts" if indexed else "legacy historical sample",
        "telemetry_health": _telemetry_health(root),
        "latency": _latency_summary(root, window),
        "active_database_and_WAL_bytes": sizes,
        "host_free_disk_bytes": shutil.disk_usage(root).free,
        "valuation_coverage": "see canonical report; UNKNOWN is never filled by diagnostics",
        "writer_wait": "nonblocking OS lock; contention fails this tick",
        "backup_restore_health": "separate supervised receipts; absent receipt means UNKNOWN",
    }


def _telemetry_health(root: Path) -> dict[str, Any]:
    path = root / "native-latency.health.json"
    try:
        if path.is_symlink() or path.stat().st_size > 4096:
            return {"status": "UNKNOWN"}
        return dict(json.loads(path.read_text()))
    except (OSError, ValueError, TypeError):
        return {"status": "UNKNOWN"}


def _latency_summary(root: Path, window: datetime) -> dict[str, Any]:
    path = root / "native-latency.sqlite3"
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
            rows = connection.execute(
                "SELECT component,operation,endpoint_id,COUNT(*),SUM(duration_ns),"
                "SUM(status!='ok') FROM latency_spans WHERE started_at_utc>=? "
                "AND operation!='poll' GROUP BY component,operation,endpoint_id "
                "ORDER BY SUM(duration_ns) DESC LIMIT 30", (window.isoformat(),),
            ).fetchall()
        stages = [{"component": row[0], "operation": row[1], "endpoint": row[2],
                   "samples": row[3], "total_duration_ns": row[4], "errors": row[5]}
                  for row in rows]
        return {"stages": stages, "largest_measured_stage": stages[0] if stages else None,
                "provider_publication_latency": "UNKNOWN",
                "meaning": "monotonic stage totals; event age and pending wait are separate"}
    except (OSError, sqlite3.Error):
        return {"status": "UNKNOWN", "missing_evidence": "native latency database unavailable"}
