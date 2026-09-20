"""Immutable additive reanalysis of captured research evidence.

Writes a separate analysis result. Never mutates the source Bundle.
Post-hoc analysis is EXPLORATORY unless a frozen hypothesis and independent
evidence are supplied.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from polysia.backtesting.prospective_analysis import (
    capture_protected_artifacts,
    open_recorded_experiment_store,
)
from polysia.backtesting.prospective_replay import replay_recorded_experiment
from polysia.backtesting.replay_report import detailed_replay_payload, digest_payload
from polysia.domain.research_evidence.economic_contract import CONTRACT_V1
from polysia.domain.research_evidence.replay import REPLAY_ENGINE_VERSION
from polysia.storage.immutable_sqlite import sha256_file
from polysia.storage.research_evidence import ResearchEvidenceStoreError

CLAIM_EXPLORATORY = "EXPLORATORY"
CLAIM_CONFIRMATORY = "CONFIRMATORY"
RESULT_NAME = "result.json"
PROVENANCE_NAME = "provenance.json"
ANALYSIS_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
HYPOTHESIS_FIELDS = ("hypothesis_id", "digest", "independent_evidence_hash")


class ProspectiveReanalysisError(RuntimeError):
    """Fail-closed additive reanalysis failure."""


def write_reanalysis(
    *,
    database: Path,
    run_id: str,
    analysis_code_sha: str,
    analysis_dir: Path,
    analysis_id: str | None = None,
    hypothesis: Mapping[str, object] | None = None,
    bundle_root: Path | None = None,
    observed: datetime | None = None,
) -> dict[str, object]:
    """Replay captured evidence into a new immutable analysis directory."""

    identifier = analysis_id or uuid4().hex
    if ANALYSIS_ID_RE.fullmatch(identifier) is None:
        raise ProspectiveReanalysisError("analysis_id is not a safe directory name")
    destination = analysis_dir / identifier
    if destination.exists():
        raise ProspectiveReanalysisError("research reanalysis result already exists")
    database_path = database.resolve()
    if destination.resolve() == database_path:
        raise ProspectiveReanalysisError("reanalysis must not write into the source Bundle")
    if bundle_root is not None:
        try:
            destination.resolve().relative_to(bundle_root.resolve())
        except ValueError:
            pass
        else:
            raise ProspectiveReanalysisError("reanalysis must not write into the source Bundle")
    claim_class = _claim_class(hypothesis)
    before = capture_protected_artifacts(database=database, bundle_root=bundle_root)
    source_hash = sha256_file(database)
    try:
        with open_recorded_experiment_store(
            database,
            bundle_root=bundle_root,
            expected_database_sha256=source_hash,
        ) as store:
            experiment = store.load_experiment(run_id)
            if experiment is None:
                raise ProspectiveReanalysisError("recorded experiment not found")
            scoped = replay_recorded_experiment(store, run_id=run_id)
            payload = detailed_replay_payload(
                scoped,
                experiment=experiment,
                run_id=run_id,
                source_database_sha256=source_hash,
            )
    except ResearchEvidenceStoreError as error:
        raise ProspectiveReanalysisError(str(error)) from error
    generated = (observed or datetime.now(UTC)).astimezone(UTC)
    provenance = {
        "analysis_code_sha": analysis_code_sha,
        "analysis_id": identifier,
        "capture_identity": {
            "bundle_sha256": experiment.bundle_sha256,
            "code_sha": experiment.code_sha,
            "collection_ends_at": experiment.collection_ends_at.isoformat().replace(
                "+00:00", "Z"
            ),
            "configuration_digest": experiment.configuration_digest,
            "max_bytes": experiment.max_bytes,
            "max_events": experiment.max_events,
            "run_id": experiment.run_id,
            "started_at": experiment.started_at.isoformat().replace("+00:00", "Z"),
        },
        "claim_class": claim_class,
        "configuration_digest": experiment.configuration_digest,
        "economic_contract_digest": CONTRACT_V1.digest,
        "economic_contract_version": CONTRACT_V1.version,
        "engine_version": REPLAY_ENGINE_VERSION,
        "generated_at": generated.isoformat().replace("+00:00", "Z"),
        "hypothesis": None if hypothesis is None else dict(hypothesis),
        "replay_engine_version": REPLAY_ENGINE_VERSION,
        "source_bundle_sha256": experiment.bundle_sha256,
        "source_evidence_hash": source_hash,
    }
    provenance["provenance_digest"] = digest_payload(provenance)
    result = {
        **payload,
        "analysis_code_sha": analysis_code_sha,
        "analysis_id": identifier,
        "budgets": {
            "max_bytes": experiment.max_bytes,
            "max_events": experiment.max_events,
        },
        "capture": provenance["capture_identity"],
        "claim_class": claim_class,
        "provenance_digest": provenance["provenance_digest"],
        "source_bundle_sha256": experiment.bundle_sha256,
        "wallet_selection": {
            "configuration_digest": experiment.configuration_digest,
        },
    }
    try:
        destination.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise ProspectiveReanalysisError("research reanalysis result already exists") from error
    _atomic_json(destination / RESULT_NAME, result)
    _atomic_json(destination / PROVENANCE_NAME, provenance)
    after = capture_protected_artifacts(database=database, bundle_root=bundle_root)
    if after.digests != before.digests:
        raise ProspectiveReanalysisError("protected research evidence artifacts changed")
    return {
        "analysis_id": identifier,
        "claim_class": claim_class,
        "path": str(destination),
        "provenance_digest": provenance["provenance_digest"],
        "result_hash": result["result_hash"],
        "source_evidence_hash": source_hash,
    }


def _claim_class(hypothesis: Mapping[str, object] | None) -> str:
    if hypothesis is None:
        return CLAIM_EXPLORATORY
    missing = [field for field in HYPOTHESIS_FIELDS if not str(hypothesis.get(field) or "").strip()]
    if missing:
        raise ProspectiveReanalysisError(
            "confirmatory hypothesis is missing frozen identity or independent evidence"
        )
    return CLAIM_CONFIRMATORY


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    text = json.dumps(dict(payload), sort_keys=True, default=str)
    temporary.write_text(f"{text}\n", encoding="utf-8")
    temporary.replace(path)
