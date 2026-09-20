"""Immutable additive reanalysis of captured research evidence.

Writes a separate analysis result. Never mutates the source Bundle.
Post-hoc analysis is EXPLORATORY unless a frozen hypothesis and independent
evidence are supplied.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from polysia.backtesting.prospective_analysis import (
    MANIFEST_NAME,
    capture_protected_artifacts,
    load_bundle_manifest,
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
IMMUTABLE_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
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
    if IMMUTABLE_SHA_RE.fullmatch(analysis_code_sha) is None:
        raise ProspectiveReanalysisError(
            "analysis_code_sha must be a lowercase 40-character Git SHA"
        )
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
    wallet_selection = _wallet_selection_identity(
        bundle_root,
        configuration_digest=experiment.configuration_digest,
    )
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
        "wallet_selection": wallet_selection,
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
        "wallet_selection": wallet_selection,
    }
    analysis_dir.mkdir(parents=True, exist_ok=True)
    staging = analysis_dir / f".{identifier}.{uuid4().hex}.tmp"
    try:
        staging.mkdir(exist_ok=False)
    except FileExistsError as error:
        raise ProspectiveReanalysisError("research reanalysis staging already exists") from error
    try:
        _atomic_json(staging / RESULT_NAME, result)
        _atomic_json(staging / PROVENANCE_NAME, provenance)
        after = capture_protected_artifacts(database=database, bundle_root=bundle_root)
        if after.digests != before.digests:
            raise ProspectiveReanalysisError("protected research evidence artifacts changed")
        try:
            staging.rename(destination)
        except OSError as error:
            if destination.exists():
                raise ProspectiveReanalysisError(
                    "research reanalysis result already exists"
                ) from error
            raise
        return {
            "analysis_id": identifier,
            "claim_class": claim_class,
            "path": str(destination),
            "provenance_digest": provenance["provenance_digest"],
            "result_hash": result["result_hash"],
            "source_evidence_hash": source_hash,
        }
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _claim_class(hypothesis: Mapping[str, object] | None) -> str:
    if hypothesis is None:
        return CLAIM_EXPLORATORY
    missing = [field for field in HYPOTHESIS_FIELDS if not str(hypothesis.get(field) or "").strip()]
    if missing:
        raise ProspectiveReanalysisError(
            "confirmatory hypothesis is missing frozen identity or independent evidence"
        )
    return CLAIM_CONFIRMATORY


def _wallet_selection_identity(
    bundle_root: Path | None,
    *,
    configuration_digest: str,
) -> dict[str, object]:
    unknown: dict[str, object] = {
        "configuration_digest": configuration_digest,
        "identity_status": "UNKNOWN",
    }
    if bundle_root is None:
        return unknown
    manifest_path = bundle_root / MANIFEST_NAME
    if not manifest_path.is_file():
        return unknown
    manifest = load_bundle_manifest(manifest_path)
    selection = manifest.get("wallet_selection")
    if not isinstance(selection, Mapping):
        return unknown
    status = str(selection.get("identity_status") or "UNKNOWN")
    if status == "UNKNOWN":
        return unknown
    policy = selection.get("selection_policy")
    digest = selection.get("selection_digest")
    count = selection.get("wallet_count")
    if (
        status != "RECORDED"
        or not isinstance(policy, str)
        or not policy.strip()
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count < 1
    ):
        raise ProspectiveReanalysisError("recorded wallet selection identity is invalid")
    return {
        "configuration_digest": configuration_digest,
        "identity_status": "RECORDED",
        "selection_digest": digest,
        "selection_policy": policy.strip(),
        "wallet_count": count,
    }


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    text = json.dumps(dict(payload), sort_keys=True, default=str)
    temporary.write_text(f"{text}\n", encoding="utf-8")
    temporary.replace(path)
