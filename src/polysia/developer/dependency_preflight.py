"""Offline, bounded projection of relevant dependency scan evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

INPUTS = (
    "pyproject.toml",
    "locks/requirements-runtime-py314.txt",
    "locks/requirements-dev-py314.txt",
    "environment.yml",
    "Dockerfile",
    "scripts/dependency_locks.py",
    "scripts/dependency_policy.py",
    "scripts/dependency_provenance.py",
    "scripts/dependency_lifecycle.py",
    "scripts/dependency_candidates.py",
    "scripts/dependency_publication.py",
    ".github/dependabot.yml",
    ".github/workflows/dependency-automation.yml",
    ".github/workflows/dependency-publish.yml",
)


def input_hashes(root: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in INPUTS
        if (root / name).is_file()
    }


def dependency_preflight(root: Path, scope: tuple[str, ...], now: datetime) -> dict[str, object]:
    deep = any(
        path in INPUTS
        or path.startswith(
            (
                "src/polysia/adapters/",
                "src/polysia/execution/",
                "src/polysia/risk/",
                "src/polysia/config/",
                "src/polysia/deployment/",
                "src/polysia/application/",
                "docs/04-architecture/",
                "src/polysia/domain/",
                "standards/",
            )
        )
        or path.startswith("scripts/dependency")
        for path in scope
    )
    evidence = root / "artifacts/dependency-scan.json"
    result: dict[str, object] = {
        "status": "CONSTRAINED_GO" if deep else "GO",
        "deep_check_required": deep,
        "network_executed": False,
        "scan": "UNKNOWN",
        "input_hashes": input_hashes(root),
        "next_action": "Run dependency discovery and affected CI"
        if deep
        else "Use scoped CI gates",
    }
    if not evidence.is_file() or evidence.is_symlink() or evidence.stat().st_size > 2_000_000:
        return result
    result["scan_digest"] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    try:
        report = json.loads(evidence.read_text(encoding="utf-8"))
        observed = datetime.fromisoformat(report["last_complete_scan"])
        if observed.tzinfo is None or observed > now:
            raise ValueError("invalid observation clock")
        matches = report.get("input_hashes") == result["input_hashes"]
        fresh = now - observed <= timedelta(days=9)
        complete = report.get("outcome") == "complete" and matches and fresh
        result["scan"] = "CURRENT" if complete else "STALE_OR_PARTIAL"
        result["last_complete_scan"] = observed.isoformat()
        if deep and complete:
            result["next_action"] = "Reuse metadata inventory; validate candidate with CI/OSV gates"
        if deep and any(
            item.get("current_yanked") or item.get("advisory_ids")
            for item in report.get("packages", [])
        ):
            result["status"] = "BLOCKED"
            result["next_action"] = (
                "Disposition yanked/advisory finding before dependency publication"
            )
    except KeyError, TypeError, ValueError, OSError:
        result["scan"] = "INVALID"
    return result
