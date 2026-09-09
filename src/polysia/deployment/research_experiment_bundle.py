"""Finalize one bounded research experiment into verified replayable evidence."""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from polysia.backtesting.prospective_replay import replay_recorded_experiment
from polysia.deployment.recovery_bundle import sha256_file
from polysia.deployment.sqlite_backup import restore_sqlite_backup, verify_sqlite_backup
from polysia.domain.research_evidence.economic_contract import CONTRACT_V1
from polysia.storage.research_evidence import ResearchEvidenceStore, ResearchEvidenceStoreError


@dataclass(frozen=True, slots=True)
class ResearchExperimentBundle:
    path: Path
    database_path: Path
    manifest_path: Path
    sha256: str


def finalize_research_experiment(
    database: Path,
    bundle_root: Path,
    *,
    run_id: str,
    finalized_at: datetime | None = None,
) -> ResearchExperimentBundle:
    """Snapshot, restore, replay, and only then mark an experiment FINALIZED."""

    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id) is None:
        raise ValueError("run_id is not safe for an evidence bundle path")
    observed = (finalized_at or datetime.now(UTC)).astimezone(UTC)
    store = ResearchEvidenceStore(database)
    store.acquire_writer()
    staging = bundle_root / f".research-experiment-{uuid4().hex}.tmp"
    final = bundle_root / f"research-experiment-{run_id}"
    try:
        experiment = store.load_experiment(run_id)
        if experiment is None or experiment.status != "ACTIVE":
            raise ResearchEvidenceStoreError("active research experiment not found")
        if final.exists():
            raise FileExistsError(f"research experiment bundle already exists: {final}")
        staging.mkdir(parents=True)
        database_copy = store.snapshot(staging / "research-evidence.sqlite3")
        replica = ResearchEvidenceStore(database_copy)
        replica.verify_integrity()
        first = replay_recorded_experiment(replica, run_id=run_id)
        second = replay_recorded_experiment(replica, run_id=run_id)
        if first != second:
            raise ResearchEvidenceStoreError("experiment replay is not deterministic")
        replica.finalize_experiment_record(
            run_id,
            bundle_path=final,
            bundle_sha256="manifest-owned",
            finalized_at=observed,
        )
        replica.verify_integrity()
        checksum = sha256_file(database_copy)
        checksum_path = database_copy.with_suffix(f"{database_copy.suffix}.sha256")
        checksum_path.write_text(f"{checksum}  {database_copy.name}\n", encoding="ascii")
        _restrict(checksum_path)
        verify_sqlite_backup(database_copy)
        with TemporaryDirectory(
            prefix="polysia-research-restore-",
            dir=staging,
        ) as temporary:
            restored = Path(temporary) / database_copy.name
            restore_sqlite_backup(database_copy, restored)
            restored_store = ResearchEvidenceStore(restored)
            restored_store.verify_integrity()
            restored_replay = replay_recorded_experiment(restored_store, run_id=run_id)
            if restored_replay != first:
                raise ResearchEvidenceStoreError("restored experiment replay changed")
        invalid_reasons: dict[str, int] = {}
        for interval in first.invalid_intervals:
            key = f"{interval.validity.value}:{interval.reason}"
            invalid_reasons[key] = invalid_reasons.get(key, 0) + 1
        manifest = {
            "manifest_version": 2,
            "run_id": run_id,
            "started_at": experiment.started_at.isoformat(),
            "collection_ends_at": experiment.collection_ends_at.isoformat(),
            "finalized_at": observed.isoformat(),
            "code_sha": experiment.code_sha,
            "policy_version": experiment.policy_version,
            "configuration_digest": experiment.configuration_digest,
            "experiment_contract": CONTRACT_V1.to_dict(),
            "experiment_contract_digest": CONTRACT_V1.digest,
            "max_events": experiment.max_events,
            "max_bytes": experiment.max_bytes,
            "event_count": replica.experiment_event_count(run_id),
            "database": database_copy.name,
            "database_sha256": checksum,
            "intervals": {
                "invalid_event_bearing": len(first.invalid_intervals),
                "invalid_reasons": invalid_reasons,
                "valid_event_bearing": len(first.valid_intervals),
            },
            "replay": {
                "control_digest": first.result.control_digest,
                "excluded_event_count": first.excluded_event_count,
                "invalidated": first.result.invalidated,
                "replayed_event_count": first.replayed_event_count,
                "scope": "valid_intervals_only",
                "target_digest": first.result.target_digest,
                "unknown_count": first.result.unknown_count,
                "unknown_by_cause": dict(first.result.unknown_by_cause),
            },
            "economic": first.economics.to_dict(),
        }
        manifest_path = staging / "experiment-manifest.json"
        manifest_path.write_text(
            f"{json.dumps(manifest, indent=2, sort_keys=True)}\n", encoding="utf-8"
        )
        _restrict(manifest_path)
        bundle_root.mkdir(parents=True, exist_ok=True)
        os.replace(staging, final)
        store.finalize_experiment_record(
            run_id,
            bundle_path=final,
            bundle_sha256=checksum,
            finalized_at=observed,
        )
        return ResearchExperimentBundle(
            path=final,
            database_path=final / database_copy.name,
            manifest_path=final / manifest_path.name,
            sha256=checksum,
        )
    finally:
        store.release_writer()
        if staging.exists():
            shutil.rmtree(staging)


def _restrict(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o600)
