"""Research report projection and atomic local output; no source acquisition."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path

from polysia.domain.wallet_intelligence.research_intake import ResearchIntakeReport

_ADDRESS = re.compile(r"0x[a-fA-F0-9]{40}(?![a-fA-F0-9])")
MISSING_ADMISSION_EVIDENCE = (
    "source_score",
    "copy_backtest_pnl",
    "r20_pnl",
    "r20_wr",
    "copy_loss_rate",
    "r20_slip",
)


def report_payload(
    report: ResearchIntakeReport, *, include_identities: bool = False
) -> dict[str, object]:
    publication = report.publication
    source = json.loads(publication.analytical_json)
    counts = Counter(decision.disposition.value for decision in report.decisions)
    rows = []
    for decision in report.decisions:
        record = decision.record
        rows.append(
            {
                "wallet_ref": hashlib.sha256(record.wallet_id.encode("utf-8")).hexdigest(),
                "producer_rank": record.producer_rank,
                "producer_outcome": record.producer_outcome,
                "research_disposition": decision.disposition.value,
                "research_reasons": list(decision.reasons),
                "source_record_projection": json.loads(record.source_record_json),
            }
        )
    payload: dict[str, object] = {
        "schema_version": "wallet-intelligence-research-intake/v1",
        "status": report.status,
        "assessed_at": report.assessed_at.isoformat(),
        "policy_id": report.policy_id,
        "allow_partial": report.allow_partial,
        "required_capabilities": list(report.required_capabilities),
        "reasons": list(report.reasons),
        "identity_redacted": not include_identities,
        "source_metadata": {
            key: value for key, value in source.items() if key not in {"records", "candidates"}
        },
        "source_snapshot_digest": publication.snapshot_digest,
        "producer_candidate_refs": [
            hashlib.sha256(wallet.encode("utf-8")).hexdigest() for wallet in source["candidates"]
        ],
        "counts": {name: counts[name] for name in ("ACCEPTED", "WATCHLIST", "REJECTED")},
        "admission": {
            "status": "NOT_ASSESSED",
            "shadow_alpha": "NOT_ADMITTED",
            "live": "NOT_ADMITTED",
            "unprovided_copyability_fields": list(MISSING_ADMISSION_EVIDENCE),
            "reason": "descriptive_research_does_not_establish_execution_or_copyability",
        },
        "rows": rows,
    }
    if not include_identities:
        # Source names, provenance URLs and error text can repeat protected identities.
        payload = json.loads(_ADDRESS.sub("[protected]", json.dumps(payload, ensure_ascii=False)))
    return payload


def write_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".research-intake-", delete=False
        ) as handle:
            temporary = handle.name
            json.dump(payload, handle, sort_keys=True, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
