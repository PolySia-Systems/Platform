"""Encrypted Platform recovery over coordinated SQLite Backup API snapshots."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from polysia.application.services.shadow_reporting import ShadowReportingService
from polysia.cli_support.wallet_intelligence_workflow import workflow_lock
from polysia.deployment.recovery_bundle import (
    RecoveryDatabaseRecord,
    assemble_recovery_bundle,
    load_bundle_manifest,
    sha256_file,
)
from polysia.deployment.sqlite_backup import backup_sqlite_database, verify_sqlite_backup
from polysia.storage.continuous_shadow import ContinuousShadowRepository

MAX_BUNDLE_BYTES = 536_870_912
MAX_PAYLOAD_BYTES = 503_316_480


def _authority_counts(path: Path) -> dict[str, Any]:
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        row = connection.execute("SELECT policy_digest, stopped FROM authority").fetchone()
        requests, charged = connection.execute(
            "SELECT COUNT(*),COALESCE(SUM(COALESCE(actual_bytes,reserved_bytes)),0) "
            "FROM reservations",
        ).fetchone()
    return {
        "policy_digest": row[0],
        "stopped": bool(row[1]),
        "requests_charged": requests,
        "bytes_charged": charged,
    }


def create_encrypted_backup(
    config: Path,
    *,
    image_archive: Path,
    release_manifest: Path,
    recipient: str,
    output: Path,
) -> dict[str, Any]:
    if not recipient.startswith("age1") or output.exists():
        raise ValueError("public recovery recipient and unused output path are required")
    if shutil.which("age") is None:
        raise OSError("age encryption runtime unavailable")
    value = json.loads(config.read_text())
    release = json.loads(release_manifest.read_text())
    if (
        release["commit"] != value["release_commit"]
        or sha256_file(image_archive) != release["archive_sha256"]
    ):
        raise ValueError("recovery artifact does not match runtime release")
    database = Path(value["database"])
    now = datetime.now(UTC)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (
        workflow_lock(database.with_suffix(".worker.lock")),
        TemporaryDirectory(
            prefix="polysia-recovery-",
            dir=output.parent,
        ) as temporary,
    ):
        stage = Path(temporary)
        records: list[RecoveryDatabaseRecord] = []
        sources: dict[str, Path] = {}
        report = None
        for role, source in (
            ("authority", Path(value["authority"])),
            ("commands", Path(value["commands"])),
            ("financial", database),
        ):
            if not source.is_file():
                if role == "financial":
                    continue
                raise ValueError("required recovery database missing")
            snapshot = backup_sqlite_database(
                source, stage, keep=1, prefix=role + "-", minimum_free_bytes=8_589_934_592
            )
            sources[snapshot.backup_path.name] = snapshot.backup_path
            records.append(
                RecoveryDatabaseRecord(
                    role=role,
                    filename=snapshot.backup_path.name,
                    sha256=snapshot.sha256,
                    schema_version=9 if role == "financial" else None,
                    integrity="ok",
                    created_at=now.isoformat(),
                    size_bytes=snapshot.backup_path.stat().st_size,
                    counts=_authority_counts(snapshot.backup_path) if role == "authority" else {},
                )
            )
            if role == "financial":
                experiment = ContinuousShadowRepository(snapshot.backup_path).latest_experiment(
                    value.get("source_id", "polymarket-native"),
                )
                if experiment:
                    report = ShadowReportingService(snapshot.backup_path).report(
                        experiment.experiment_id,
                    )
        bundle = assemble_recovery_bundle(
            stage / "bundles",
            created_at=now,
            databases=tuple(records),
            source_files=sources,
            release_sha=value["release_commit"],
            keep=2,
        )
        extras = {
            "worker-config.json": config,
            "policy.json": Path(value["manifest"]),
            "release.json": release_manifest,
            "polysia-image.tar.gz": image_archive,
        }
        cohort = Path(value["cohort"])
        if cohort.is_file():
            extras["cohort.json"] = cohort
        for name, source in extras.items():
            if source.is_symlink():
                raise ValueError("recovery assets cannot contain symlinks")
            shutil.copy2(source, bundle / name)
        for name in ("status", "publication"):
            retained_path = Path(value[name]) if name in value else None
            if retained_path is not None and retained_path.is_file():
                shutil.copy2(retained_path, bundle / (name + ".json"))
        evidence = Path(value["authority"]).parent / "evidence"
        if evidence.is_dir():
            for source in evidence.glob("*.json"):
                if source.is_symlink():
                    raise ValueError("evidence cannot contain symlinks")
                shutil.copy2(source, bundle / ("evidence-" + source.name))
        files = {path.name: sha256_file(path) for path in bundle.iterdir() if path.is_file()}
        total = sum(path.stat().st_size for path in bundle.iterdir())
        if total > MAX_PAYLOAD_BYTES:
            raise ValueError("recovery bundle exceeds reserved generation capacity")
        metadata = {
            "version": "platform-recovery/v1",
            "created_at": now.isoformat(),
            "release_commit": value["release_commit"],
            "files": files,
            "report_experiment_id": (
                None if report is None else report["analytical"]["experiment_id"]
            ),
            "analytical_digest": None if report is None else report["analytical_digest"],
            "restore_acquisition": "DISABLED_UNTIL_AUTHORITY_RECONCILIATION",
        }
        (bundle / "platform-recovery.json").write_text(json.dumps(metadata, sort_keys=True))
        encrypted = output.with_suffix(output.suffix + ".partial")
        try:
            process = subprocess.Popen(
                ["age", "--recipient", recipient, "--output", str(encrypted)],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            if process.stdin is None:
                raise OSError("encryption input unavailable")
            try:
                with tarfile.open(fileobj=process.stdin, mode="w|") as archive:
                    for path in sorted(bundle.iterdir()):
                        archive.add(path, arcname=path.name, recursive=False)
                process.stdin.close()
                returncode = process.wait(timeout=120)
            except BaseException:
                process.kill()
                process.wait()
                raise
            if returncode or not encrypted.is_file() or encrypted.stat().st_size > MAX_BUNDLE_BYTES:
                raise OSError("recovery encryption failed")
            encrypted.chmod(0o600)
            encrypted.replace(output)
        finally:
            encrypted.unlink(missing_ok=True)
    return {
        "status": "ENCRYPTED",
        "release_commit": value["release_commit"],
        "sha256": sha256_file(output),
        "size_bytes": output.stat().st_size,
        "created_at": now.isoformat(),
    }


def extract_and_verify_recovery(
    archive_path: Path,
    destination: Path,
    *,
    trusted_release_manifest: Path,
) -> dict[str, Any]:
    """Extract only bounded flat regular files into a new isolated recovery root."""
    if destination.exists():
        raise FileExistsError("recovery requires a new isolated root")
    destination.mkdir(parents=True, mode=0o700)
    with tarfile.open(archive_path, "r:") as archive:
        total = 0
        names: set[str] = set()
        for member in archive:
            if (
                not member.isfile()
                or Path(member.name).name != member.name
                or member.name in names
                or ":" in member.name
                or "\\" in member.name
            ):
                raise ValueError("unsafe or duplicate recovery member")
            total += member.size
            if total > MAX_BUNDLE_BYTES or len(names) >= 100_000:
                raise ValueError("recovery extraction limit exceeded")
            names.add(member.name)
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("recovery member unavailable")
            target = destination / member.name
            with target.open("xb") as output:
                shutil.copyfileobj(stream, output)
            if os.name != "nt":
                target.chmod(0o600)
    metadata = json.loads((destination / "platform-recovery.json").read_text())
    if metadata.get("version") != "platform-recovery/v1":
        raise ValueError("unsupported recovery version")
    if set(metadata["files"]) != names - {"platform-recovery.json"}:
        raise ValueError("recovery file inventory mismatch")
    for name, digest in metadata["files"].items():
        if Path(name).name != name or sha256_file(destination / name) != digest:
            raise ValueError("recovery file digest mismatch")
    bundle = load_bundle_manifest(destination)
    if not {"authority", "commands"} <= {record.role for record in bundle.databases}:
        raise ValueError("authority or command recovery state missing")
    release = json.loads((destination / "release.json").read_text())
    trusted = json.loads(trusted_release_manifest.read_text())
    if any(
        release.get(key) != trusted.get(key)
        for key in (
            "commit",
            "image_id",
            "archive_sha256",
            "financial_schema",
            "bootstrap_sha256",
        )
    ):
        raise ValueError("backup release differs from independently retained trusted release")
    if (
        release["commit"] != metadata["release_commit"]
        or sha256_file(destination / "polysia-image.tar.gz") != release["archive_sha256"]
    ):
        raise ValueError("restored release identity mismatch")
    for record in bundle.databases:
        if record.filename not in metadata["files"]:
            raise ValueError("database is outside verified recovery inventory")
        verify_sqlite_backup(destination / record.filename)
        if sha256_file(destination / record.filename) != record.sha256:
            raise ValueError("database recovery digest mismatch")
        if record.role == "authority" and _authority_counts(destination / record.filename) != (
            record.counts
        ):
            raise ValueError("restored STOP or consumed authority differs")
        if record.role == "financial" and metadata["report_experiment_id"]:
            report = ShadowReportingService(destination / record.filename).report(
                metadata["report_experiment_id"],
            )
            if report["analytical_digest"] != metadata["analytical_digest"]:
                raise ValueError("restored analytical replay differs")
    safe_config = json.loads((destination / "worker-config.json").read_text())
    for record in bundle.databases:
        safe_config["database" if record.role == "financial" else record.role] = str(
            destination / record.filename,
        )
    safe_config.update(
        manifest=str(destination / "policy.json"),
        cohort=str(destination / "cohort.json"),
        status=str(destination / "restored-status.json"),
        publication=str(destination / "restored-publication.json"),
    )
    if not any(record.role == "financial" for record in bundle.databases):
        safe_config["database"] = str(destination / "financial.sqlite3")
    safe_config["acquisition_enabled"] = False
    safe_config["recovery_requires_authority_reconciliation"] = True
    (destination / "recovery-runtime.json").write_text(json.dumps(safe_config, sort_keys=True))
    return {
        "status": "VERIFIED_ISOLATED_RESTORE",
        "release_commit": metadata["release_commit"],
        "analytical_digest": metadata["analytical_digest"],
        "acquisition_enabled": False,
        "real_orders": False,
    }
