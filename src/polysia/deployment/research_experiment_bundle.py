"""Finalize one bounded research experiment into verified replayable evidence."""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from polysia.backtesting.prospective_analysis import (
    MANIFEST_NAME,
    byte_copy_sqlite,
    capture_protected_artifacts,
    load_bundle_manifest,
    open_recorded_experiment_store,
    verify_protected_unchanged,
)
from polysia.backtesting.prospective_replay import (
    RecordedExperimentReplay,
    replay_identity,
    replay_recorded_experiment,
)
from polysia.deployment.recovery_bundle import sha256_file
from polysia.deployment.research_scratch import operation_scratch, planned_scratch_bytes
from polysia.deployment.sqlite_backup import restore_sqlite_backup, verify_sqlite_backup
from polysia.domain.research_evidence.economic_contract import CONTRACT_V1
from polysia.storage.research_evidence import (
    ResearchEvidenceStore,
    ResearchEvidenceStoreError,
    ResearchExperiment,
)

OUTCOME_FINALIZED = "FINALIZED"
OUTCOME_FAILURE_ARCHIVED = "FAILURE_ARCHIVED"


@dataclass(frozen=True, slots=True)
class ResearchExperimentBundle:
    path: Path
    database_path: Path
    manifest_path: Path
    sha256: str
    outcome: str = OUTCOME_FINALIZED
    verified: bool = True
    replay: RecordedExperimentReplay | None = None


def finalize_research_experiment(
    database: Path,
    bundle_root: Path,
    *,
    run_id: str,
    finalized_at: datetime | None = None,
    wallet_selection: Mapping[str, object] | None = None,
) -> ResearchExperimentBundle:
    """Snapshot, restore, replay, and only then mark an experiment FINALIZED."""

    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id) is None:
        raise ValueError("run_id is not safe for an evidence bundle path")
    observed = (finalized_at or datetime.now(UTC)).astimezone(UTC)
    store = ResearchEvidenceStore(database)
    store.acquire_writer()
    staging = bundle_root / f".research-experiment-{uuid4().hex}.tmp"
    success_final = bundle_root / f"research-experiment-{run_id}"
    failure_final = bundle_root / f"research-experiment-{run_id}-failure"
    try:
        experiment = store.load_experiment(run_id)
        if experiment is None:
            raise ResearchEvidenceStoreError("research experiment not found")
        if experiment.status == OUTCOME_FINALIZED:
            return _reuse_existing_bundle(
                success_final,
                run_id=run_id,
                expected_sha256=experiment.bundle_sha256,
                require_verified=True,
            )
        if experiment.status == OUTCOME_FAILURE_ARCHIVED:
            return _reuse_existing_bundle(
                failure_final,
                run_id=run_id,
                expected_sha256=experiment.bundle_sha256,
                require_verified=False,
            )
        if experiment.status != "ACTIVE":
            raise ResearchEvidenceStoreError("research experiment is not active")
        if success_final.exists():
            bundle = _verify_published_bundle(success_final, run_id=run_id, require_verified=True)
            store.finalize_experiment_record(
                run_id,
                bundle_path=bundle.path,
                bundle_sha256=bundle.sha256,
                finalized_at=observed,
            )
            return bundle
        staging.mkdir(parents=True)
        database_copy = store.snapshot(staging / "research-evidence.sqlite3")
        replica = ResearchEvidenceStore(database_copy)
        replica.verify_integrity()
        first = replay_recorded_experiment(
            replica, run_id=run_id, retain_traces=False
        )
        first_identity = replay_identity(first)
        second = replay_recorded_experiment(
            replica, run_id=run_id, retain_traces=False
        )
        if replay_identity(second) != first_identity:
            raise ResearchEvidenceStoreError("experiment replay is not deterministic")
        del second
        verified = _replay_is_verified(first)
        if verified:
            replica.finalize_experiment_record(
                run_id,
                bundle_path=success_final,
                bundle_sha256="manifest-owned",
                finalized_at=observed,
            )
            replica.verify_integrity()
        checksum = sha256_file(database_copy)
        checksum_path = database_copy.with_suffix(f"{database_copy.suffix}.sha256")
        checksum_path.write_text(f"{checksum}  {database_copy.name}\n", encoding="ascii")
        _restrict(checksum_path)
        verify_sqlite_backup(database_copy)
        needed = planned_scratch_bytes(database_copy, copies=4)
        with operation_scratch(
            staging,
            prefix="polysia-research-restore-",
            needed_bytes=needed,
        ) as temporary:
            restored = Path(temporary) / database_copy.name
            restore_sqlite_backup(database_copy, restored)
            restored_store = ResearchEvidenceStore(restored)
            restored_store.verify_integrity()
            restored_replay = replay_recorded_experiment(
                restored_store, run_id=run_id, retain_traces=False
            )
            if replay_identity(restored_replay) != first_identity:
                raise ResearchEvidenceStoreError("restored experiment replay changed")
            del restored_replay
        manifest = _bundle_manifest(
            experiment=experiment,
            run_id=run_id,
            observed=observed,
            replica=replica,
            replay=first,
            checksum=checksum,
            database_name=database_copy.name,
            verified=verified,
            wallet_selection=wallet_selection,
        )
        manifest_path = staging / MANIFEST_NAME
        manifest_path.write_text(
            f"{json.dumps(manifest, indent=2, sort_keys=True)}\n", encoding="utf-8"
        )
        _restrict(manifest_path)
        bundle_root.mkdir(parents=True, exist_ok=True)
        if verified:
            os.replace(staging, success_final)
            store.finalize_experiment_record(
                run_id,
                bundle_path=success_final,
                bundle_sha256=checksum,
                finalized_at=observed,
            )
            return ResearchExperimentBundle(
                path=success_final,
                database_path=success_final / database_copy.name,
                manifest_path=success_final / MANIFEST_NAME,
                sha256=checksum,
                outcome=OUTCOME_FINALIZED,
                verified=True,
                replay=first,
            )
        if failure_final.exists():
            shutil.rmtree(staging)
            return _reuse_existing_bundle(
                failure_final,
                run_id=run_id,
                expected_sha256=None,
                require_verified=False,
            )
        os.replace(staging, failure_final)
        store.mark_experiment_terminal(
            run_id,
            status=OUTCOME_FAILURE_ARCHIVED,
            bundle_path=failure_final,
            bundle_sha256=checksum,
            at=observed,
            from_statuses=("ACTIVE",),
        )
        return ResearchExperimentBundle(
            path=failure_final,
            database_path=failure_final / database_copy.name,
            manifest_path=failure_final / MANIFEST_NAME,
            sha256=checksum,
            outcome=OUTCOME_FAILURE_ARCHIVED,
            verified=False,
            replay=first,
        )
    finally:
        store.release_writer()
        if staging.exists():
            shutil.rmtree(staging)


def _replay_is_verified(replay: RecordedExperimentReplay) -> bool:
    return bool(replay.valid_intervals) and replay.replayed_event_count > 0


def _public_wallet_selection(selection: Mapping[str, object] | None) -> dict[str, object]:
    if not selection:
        return {"identity_status": "UNKNOWN"}
    values = {
        "selection_policy": selection.get("selection_policy"),
        "selection_digest": selection.get("selection_digest"),
        "wallet_count": selection.get("wallet_count"),
    }
    present = {key for key, value in values.items() if value is not None}
    if not present:
        return {"identity_status": "UNKNOWN"}
    if present != set(values):
        raise ResearchEvidenceStoreError("wallet selection identity is incomplete")
    policy = values["selection_policy"]
    digest = values["selection_digest"]
    count = values["wallet_count"]
    if not isinstance(policy, str) or not policy.strip():
        raise ResearchEvidenceStoreError("wallet selection policy is invalid")
    if (
        not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
    ):
        raise ResearchEvidenceStoreError("wallet selection digest is invalid")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ResearchEvidenceStoreError("wallet selection count is invalid")
    return {
        "identity_status": "RECORDED",
        "selection_digest": digest,
        "selection_policy": policy.strip(),
        "wallet_count": count,
    }


def _bundle_manifest(
    *,
    experiment: ResearchExperiment,
    run_id: str,
    observed: datetime,
    replica: ResearchEvidenceStore,
    replay: RecordedExperimentReplay,
    checksum: str,
    database_name: str,
    verified: bool,
    wallet_selection: Mapping[str, object] | None,
) -> dict[str, object]:
    started_at = experiment.started_at
    collection_ends_at = experiment.collection_ends_at
    code_sha = experiment.code_sha
    policy_version = experiment.policy_version
    configuration_digest = experiment.configuration_digest
    max_events = experiment.max_events
    max_bytes = experiment.max_bytes
    invalid_reasons: dict[str, int] = {}
    for interval in replay.invalid_intervals:
        key = f"{interval.validity.value}:{interval.reason}"
        invalid_reasons[key] = invalid_reasons.get(key, 0) + 1
    limitations = list(replay.economics.limitations)
    if not verified:
        limitations.insert(0, "no_valid_replayable_interval")
    return {
        "manifest_version": 2,
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "collection_ends_at": collection_ends_at.isoformat(),
        "finalized_at": observed.isoformat(),
        "code_sha": code_sha,
        "policy_version": policy_version,
        "configuration_digest": configuration_digest,
        "experiment_contract": CONTRACT_V1.to_dict(),
        "experiment_contract_digest": CONTRACT_V1.digest,
        "max_events": max_events,
        "max_bytes": max_bytes,
        "event_count": replica.experiment_event_count(run_id),
        "database": database_name,
        "database_sha256": checksum,
        "outcome": OUTCOME_FINALIZED if verified else OUTCOME_FAILURE_ARCHIVED,
        "verified": verified,
        "lifecycle": (
            "COLLECTED->BUNDLE_PUBLISHED->VERIFIED_ANALYSIS->FINALIZED"
            if verified
            else "COLLECTED->ANALYSIS_FAILED->FAILURE_ARCHIVED"
        ),
        "intervals": {
            "invalid_event_bearing": len(replay.invalid_intervals),
            "invalid_reasons": invalid_reasons,
            "valid_event_bearing": len(replay.valid_intervals),
        },
        "replay": {
            "control_digest": replay.result.control_digest,
            "excluded_event_count": replay.excluded_event_count,
            "invalidated": replay.result.invalidated,
            "replayed_event_count": replay.replayed_event_count,
            "scope": "valid_intervals_only",
            "target_digest": replay.result.target_digest,
            "unknown_count": replay.result.unknown_count,
            "unknown_by_cause": dict(replay.result.unknown_by_cause),
        },
        "economic": replay.economics.to_dict(),
        "limitations": limitations,
        "wallet_selection": _public_wallet_selection(wallet_selection),
    }


def _reuse_existing_bundle(
    path: Path,
    *,
    run_id: str,
    expected_sha256: str | None,
    require_verified: bool,
) -> ResearchExperimentBundle:
    if not path.is_dir():
        raise ResearchEvidenceStoreError("research experiment bundle is missing")
    bundle = _verify_published_bundle(
        path,
        run_id=run_id,
        require_verified=require_verified,
    )
    if expected_sha256 is not None and bundle.sha256.casefold() != expected_sha256.casefold():
        raise ResearchEvidenceStoreError("research experiment bundle checksum mismatch")
    return bundle


def _verify_published_bundle(
    path: Path,
    *,
    run_id: str,
    require_verified: bool,
) -> ResearchExperimentBundle:
    manifest_path = path / MANIFEST_NAME
    manifest = load_bundle_manifest(manifest_path)
    if str(manifest.get("run_id")) != run_id:
        raise ResearchEvidenceStoreError("research experiment bundle run_id mismatch")
    verified = manifest.get("verified") is True
    outcome = str(manifest.get("outcome") or OUTCOME_FINALIZED)
    if require_verified and not verified:
        raise ResearchEvidenceStoreError("research experiment bundle is not verified")
    if require_verified and outcome != OUTCOME_FINALIZED:
        raise ResearchEvidenceStoreError("research experiment bundle outcome is not FINALIZED")
    if not require_verified and verified:
        raise ResearchEvidenceStoreError("failure archive is labeled verified")
    database_name = str(manifest.get("database") or "research-evidence.sqlite3")
    database_path = path / database_name
    expected = str(manifest.get("database_sha256") or "")
    before = capture_protected_artifacts(
        database=database_path,
        bundle_root=path,
        manifest=manifest,
    )
    if sha256_file(database_path) != expected:
        raise ResearchEvidenceStoreError("research experiment bundle checksum mismatch")
    with open_recorded_experiment_store(
        database_path,
        bundle_root=path,
        expected_database_sha256=expected,
    ) as replica:
        replica.verify_integrity()
        confirmed = replay_recorded_experiment(
            replica, run_id=run_id, retain_traces=False
        )
        if require_verified and not _replay_is_verified(confirmed):
            raise ResearchEvidenceStoreError("verified bundle has no replayable analysis")
        declared_control = str(_mapping(manifest.get("replay")).get("control_digest") or "")
        declared_target = str(_mapping(manifest.get("replay")).get("target_digest") or "")
        declared_economic = str(_mapping(manifest.get("economic")).get("digest") or "")
        if declared_control and declared_control != confirmed.result.control_digest:
            raise ResearchEvidenceStoreError("research experiment bundle replay mismatch")
        if declared_target and declared_target != confirmed.result.target_digest:
            raise ResearchEvidenceStoreError("research experiment bundle replay mismatch")
        if declared_economic and declared_economic != confirmed.economics.digest:
            raise ResearchEvidenceStoreError("research experiment bundle replay mismatch")
    with operation_scratch(
        path,
        prefix="polysia-research-resume-",
        needed_bytes=planned_scratch_bytes(database_path, copies=4),
    ) as temporary:
        copied = byte_copy_sqlite(database_path, Path(temporary) / database_path.name)
        checksum_src = database_path.with_suffix(f"{database_path.suffix}.sha256")
        if checksum_src.is_file():
            shutil.copy2(checksum_src, copied.with_suffix(f"{copied.suffix}.sha256"))
        restored = Path(temporary) / f"restored-{database_path.name}"
        restore_sqlite_backup(copied, restored)
        restored_store = ResearchEvidenceStore(restored)
        restored_store.verify_integrity()
    after = capture_protected_artifacts(
        database=database_path,
        bundle_root=path,
        manifest=manifest,
    )
    verify_protected_unchanged(before, after)
    return ResearchExperimentBundle(
        path=path,
        database_path=database_path,
        manifest_path=manifest_path,
        sha256=expected,
        outcome=outcome,
        verified=verified,
        replay=confirmed,
    )


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _restrict(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o600)
