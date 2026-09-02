from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from shutil import copy2

from polysia.storage.lifecycle_policy import (
    DEFAULT_STAGE4B_DATA_LIFECYCLE_POLICY,
    RECOVERY_BUNDLE_POLICY_VERSION,
    Stage4BDataLifecyclePolicy,
)

BUNDLE_MANIFEST_VERSION = 1
PINNED_BUNDLE_DIRNAME = "pinned"
ROTATING_BUNDLE_PREFIX = "bundle-"


@dataclass(frozen=True, slots=True)
class RecoveryDatabaseRecord:
    role: str
    filename: str
    sha256: str
    schema_version: int | None
    integrity: str
    created_at: str
    size_bytes: int
    counts: dict[str, object]


@dataclass(frozen=True, slots=True)
class RecoveryBundleManifest:
    manifest_version: int
    policy_version: str
    role: str
    created_at: datetime
    release_sha: str | None
    experiment_id: str | None
    watermark: str | None
    max_skew_seconds: int
    databases: tuple[RecoveryDatabaseRecord, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "created_at": self.created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "databases": [
                {
                    "counts": item.counts,
                    "created_at": item.created_at,
                    "filename": item.filename,
                    "integrity": item.integrity,
                    "role": item.role,
                    "schema_version": item.schema_version,
                    "sha256": item.sha256,
                    "size_bytes": item.size_bytes,
                }
                for item in self.databases
            ],
            "experiment_id": self.experiment_id,
            "manifest_version": self.manifest_version,
            "max_skew_seconds": self.max_skew_seconds,
            "policy_version": self.policy_version,
            "release_sha": self.release_sha,
            "role": self.role,
            "watermark": self.watermark,
        }


def bundle_manifest_path(bundle_dir: Path) -> Path:
    return bundle_dir / "recovery-bundle.json"


def write_bundle_manifest(bundle_dir: Path, manifest: RecoveryBundleManifest) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    path = bundle_manifest_path(bundle_dir)
    payload = json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")
    return path


def load_bundle_manifest(bundle_dir: Path) -> RecoveryBundleManifest:
    payload = json.loads(bundle_manifest_path(bundle_dir).read_text(encoding="utf-8"))
    databases = tuple(
        RecoveryDatabaseRecord(
            role=str(item["role"]),
            filename=str(item["filename"]),
            sha256=str(item["sha256"]),
            schema_version=(
                None if item.get("schema_version") is None else int(item["schema_version"])
            ),
            integrity=str(item["integrity"]),
            created_at=str(item["created_at"]),
            size_bytes=int(item["size_bytes"]),
            counts=dict(item.get("counts") or {}),
        )
        for item in payload["databases"]
    )
    created_at = datetime.fromisoformat(str(payload["created_at"]).replace("Z", "+00:00"))
    return RecoveryBundleManifest(
        manifest_version=int(payload["manifest_version"]),
        policy_version=str(payload["policy_version"]),
        role=str(payload["role"]),
        created_at=created_at,
        release_sha=None if payload.get("release_sha") is None else str(payload["release_sha"]),
        experiment_id=(
            None if payload.get("experiment_id") is None else str(payload["experiment_id"])
        ),
        watermark=None if payload.get("watermark") is None else str(payload["watermark"]),
        max_skew_seconds=int(payload["max_skew_seconds"]),
        databases=databases,
    )


def rotating_bundle_dir(backup_root: Path, created_at: datetime) -> Path:
    stamp = created_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return backup_root / f"{ROTATING_BUNDLE_PREFIX}{stamp}"


def pinned_bundle_dir(backup_root: Path, name: str) -> Path:
    return backup_root / PINNED_BUNDLE_DIRNAME / name


def prune_rotating_bundles(
    backup_root: Path,
    *,
    keep: int,
    policy: Stage4BDataLifecyclePolicy = DEFAULT_STAGE4B_DATA_LIFECYCLE_POLICY,
) -> list[Path]:
    if keep < 1:
        raise ValueError("keep must be at least 1")
    del policy
    bundles = sorted(
        (
            path
            for path in backup_root.glob(f"{ROTATING_BUNDLE_PREFIX}*")
            if path.is_dir() and bundle_manifest_path(path).is_file()
        ),
        key=lambda path: path.name,
        reverse=True,
    )
    removed: list[Path] = []
    for old in bundles[keep:]:
        for child in sorted(old.glob("*"), reverse=True):
            child.unlink()
        old.rmdir()
        removed.append(old)
    return removed


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"Recovery bundle file already exists: {destination}")
    try:
        os.link(source, destination)
    except OSError:
        copy2(source, destination)


def assemble_recovery_bundle(
    backup_root: Path,
    *,
    created_at: datetime,
    databases: tuple[RecoveryDatabaseRecord, ...],
    source_files: Mapping[str, Path],
    role: str = "rotating",
    release_sha: str | None = None,
    experiment_id: str | None = None,
    watermark: str | None = None,
    keep: int = DEFAULT_STAGE4B_DATA_LIFECYCLE_POLICY.recovery_bundle_keep,
    policy: Stage4BDataLifecyclePolicy = DEFAULT_STAGE4B_DATA_LIFECYCLE_POLICY,
) -> Path:
    """Materialize one coordinated bundle and prune older rotating bundles only."""

    bundle_dir = rotating_bundle_dir(backup_root, created_at)
    for record in databases:
        source = source_files[record.filename]
        _link_or_copy(source, bundle_dir / record.filename)
        checksum = source.with_suffix(source.suffix + ".sha256")
        if checksum.is_file():
            _link_or_copy(checksum, bundle_dir / checksum.name)
    write_bundle_manifest(
        bundle_dir,
        RecoveryBundleManifest(
            manifest_version=BUNDLE_MANIFEST_VERSION,
            policy_version=RECOVERY_BUNDLE_POLICY_VERSION,
            role=role,
            created_at=created_at,
            release_sha=release_sha,
            experiment_id=experiment_id,
            watermark=watermark,
            max_skew_seconds=policy.recovery_bundle_max_skew_seconds,
            databases=databases,
        ),
    )
    verify_bundle_checksums(bundle_dir)
    prune_rotating_bundles(backup_root, keep=keep, policy=policy)
    return bundle_dir


def verify_bundle_checksums(bundle_dir: Path) -> RecoveryBundleManifest:
    manifest = load_bundle_manifest(bundle_dir)
    for record in manifest.databases:
        path = bundle_dir / record.filename
        if not path.is_file():
            raise FileNotFoundError(f"Recovery bundle file is missing: {record.filename}")
        actual = sha256_file(path)
        if actual != record.sha256:
            raise ValueError(f"Recovery bundle checksum mismatch: {record.filename}")
    return manifest


def capacity_payload(
    *,
    databases: Mapping[str, Mapping[str, object]],
    backup_count: int,
    backup_bytes: int,
    disk_free_bytes: int | None,
    policy: Stage4BDataLifecyclePolicy,
    daily_growth_bytes: int | None = None,
) -> dict[str, object]:
    estimated = None
    if (
        daily_growth_bytes is not None
        and daily_growth_bytes > 0
        and disk_free_bytes is not None
        and disk_free_bytes > policy.disk_safety_floor_bytes
    ):
        remaining = disk_free_bytes - policy.disk_safety_floor_bytes
        estimated = remaining / daily_growth_bytes
    return {
        "backup_bytes": backup_bytes,
        "backup_count": backup_count,
        "daily_growth_bytes": daily_growth_bytes,
        "databases": dict(databases),
        "disk_free_bytes": disk_free_bytes,
        "disk_safety_floor_bytes": policy.disk_safety_floor_bytes,
        "estimated_days_to_safety_floor": estimated,
        "policy_version": policy.policy_version,
        "recovery_bundle_keep": policy.recovery_bundle_keep,
        "recovery_bundle_policy_version": RECOVERY_BUNDLE_POLICY_VERSION,
    }


__all__ = [
    "BUNDLE_MANIFEST_VERSION",
    "PINNED_BUNDLE_DIRNAME",
    "ROTATING_BUNDLE_PREFIX",
    "RecoveryBundleManifest",
    "RecoveryDatabaseRecord",
    "assemble_recovery_bundle",
    "bundle_manifest_path",
    "capacity_payload",
    "load_bundle_manifest",
    "pinned_bundle_dir",
    "prune_rotating_bundles",
    "rotating_bundle_dir",
    "sha256_file",
    "verify_bundle_checksums",
    "write_bundle_manifest",
]
