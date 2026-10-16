"""Provider-free reporting over a consistent, private financial snapshot."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from polysia.deployment.sqlite_backup import backup_sqlite_database
from polysia.storage.continuous_shadow import ContinuousShadowRepository


class ShadowReportingService:
    """Share canonical accounting between CLI, export jobs and Console."""

    def __init__(self, database: Path) -> None:
        self._database = database

    def report(self, experiment_id: str, *, limit: int = 100) -> dict[str, Any]:
        # Backup handles WAL consistently and bounds copy time. Never initialize
        # or migrate the input and never copy live DB/WAL files separately.
        with TemporaryDirectory(prefix="polysia-report-") as directory:
            snapshot = backup_sqlite_database(
                self._database, Path(directory), keep=1, timeout_seconds=20,
            )
            store = ContinuousShadowRepository(snapshot.backup_path)
            operational = store.results(experiment_id, limit=limit)
            comparison = store.opportunity_report(experiment_id)
        # Operational health is sampled against wall time and belongs outside
        # the analytical digest. A temporary filesystem path is not evidence ID.
        analytical = dict(comparison)
        raw_supporting = analytical.get("supporting_artifacts", {})
        if not isinstance(raw_supporting, dict):
            raise ValueError("invalid supporting evidence")
        supporting = dict(raw_supporting)
        supporting.pop("snapshot_database", None)
        analytical["supporting_artifacts"] = supporting
        canonical = json.dumps(analytical, sort_keys=True, separators=(",", ":"))
        return {
            "schema_version": "platform-shadow-report/v1",
            "scope": "single_financial_session_inception_to_retained_cutoff",
            "provider_calls": 0,
            "analytical": analytical,
            "analytical_digest": hashlib.sha256(canonical.encode()).hexdigest(),
            "operational": operational,
            "limitations": [
                "Separately funded financial sessions are not compounded.",
                "Unsupported calendar boundaries require retained opening state and marks.",
                "Zero simulations are no measurable profitability evidence.",
            ],
        }


def comparison_csv(report: dict[str, Any]) -> str:
    """Export the same canonical JSON fields without calculating another result."""
    economic = report["analytical"]["report"]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    fields = (
        "policy", "cash", "gross_pnl", "fees", "slippage", "net_pnl",
        "valuation_status", "evaluated", "rejected",
    )
    writer.writerow(("analytical_digest", *fields))
    for name in ("control", "target"):
        row = economic[name]
        writer.writerow((report["analytical_digest"], *(row.get(key) for key in fields)))
    return output.getvalue()
