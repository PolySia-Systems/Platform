"""Separate financial backup/isolated restore using the existing SQLite tools.

This never copies receipt custody, clears STOP, opens a writer or constructs a
signer. An isolated restore proves data integrity, not permission to resume.
Storage failure-domain and ACL commissioning remain operator evidence.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from polysia.deployment.sqlite_backup import (
    backup_sqlite_database,
    restore_sqlite_backup,
    verify_sqlite_backup,
)
from polysia.domain.financial_session import SessionBlocked, canonical_json, digest


def prepare_recovery(
    journal: Path,
    witness: Path,
    destination: Path,
    *,
    now: datetime,
    minimum_free_bytes: int,
) -> dict[str, Any]:
    from polysia.deployment.session_supervision import committed_checkpoint

    if destination.exists() or any(
        destination.resolve().is_relative_to(path.parent.resolve()) for path in (journal, witness)
    ):
        raise SessionBlocked("unused_separate_recovery_destination_required")
    before = committed_checkpoint(journal, witness)
    destination.mkdir(parents=True, mode=0o700)
    financial = backup_sqlite_database(
        journal,
        destination / "snapshots",
        prefix="financial-",
        now=now,
        minimum_free_bytes=minimum_free_bytes,
        timeout_seconds=30,
    )
    control = backup_sqlite_database(
        witness,
        destination / "snapshots",
        prefix="witness-",
        now=now,
        minimum_free_bytes=minimum_free_bytes,
        timeout_seconds=30,
    )
    restored_journal, restored_witness = (
        destination / "restore/session.sqlite3",
        destination / "restore/witness.sqlite3",
    )
    restore_sqlite_backup(financial.backup_path, restored_journal)
    restore_sqlite_backup(control.backup_path, restored_witness)
    restored = committed_checkpoint(restored_journal, restored_witness)
    after = committed_checkpoint(journal, witness)
    if not before == restored == after:
        raise SessionBlocked("financial_backup_capture_changed_retry_new_generation")
    result = {
        "version": "financial-recovery/v1",
        "authority_fingerprint": before.authority_fingerprint,
        "mode": "SEPARATE_FINANCIAL_RECOVERY",
        "observed_at": now.isoformat(),
        "checkpoint": asdict(before),
        "restore_verified": True,
        "artifacts": [str(financial.backup_path.resolve()), str(control.backup_path.resolve())],
        "artifact_sha256": digest((financial.sha256, control.sha256)),
        "restored": [str(restored_journal.resolve()), str(restored_witness.resolve())],
        "custody_included": False,
        "authority_reissued": False,
    }
    receipt = destination / "receipt.json"
    receipt.write_text(canonical_json(result), encoding="utf-8")
    receipt.chmod(0o600)
    return result


def verify_recovery(record: dict[str, Any]) -> None:
    from polysia.deployment.session_supervision import committed_checkpoint

    if (
        record.get("version") != "financial-recovery/v1"
        or record.get("custody_included") is not False
        or record.get("authority_reissued") is not False
        or len(record.get("artifacts", [])) != 2
        or len(record.get("restored", [])) != 2
    ):
        raise SessionBlocked("financial_restore_evidence_missing")
    artifacts = [Path(item) for item in record["artifacts"]]
    restored = [Path(item) for item in record["restored"]]
    if any(not path.is_absolute() or path.is_symlink() for path in artifacts + restored):
        raise SessionBlocked("financial_restore_paths_invalid")
    hashes = tuple(verify_sqlite_backup(path) for path in artifacts)
    if digest(hashes) != record["artifact_sha256"]:
        raise SessionBlocked("financial_backup_artifact_changed")
    if asdict(committed_checkpoint(*restored)) != record["checkpoint"]:
        raise SessionBlocked("financial_restore_checkpoint_changed")
    # Require the restored files to be the actual checked backup generation.
    # SQLite backup may change file header counters, so compare logical content.
    import sqlite3
    from contextlib import closing
    from itertools import zip_longest

    for source, target in zip(artifacts, restored, strict=True):
        with (
            closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as left,
            closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as right,
        ):
            if any(a != b for a, b in zip_longest(left.iterdump(), right.iterdump())):
                raise SessionBlocked("financial_restore_content_mismatch")
