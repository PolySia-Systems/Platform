"""Open finalized research evidence without mutating the source bundle."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from polysia.storage.immutable_sqlite import sha256_file
from polysia.storage.research_evidence import ResearchEvidenceStore, ResearchEvidenceStoreError

MANIFEST_NAME = "experiment-manifest.json"


@dataclass(frozen=True, slots=True)
class ProtectedArtifactSet:
    digests: dict[str, str]
    paths: tuple[Path, ...]


def sqlite_companion_paths(database: Path) -> tuple[Path, ...]:
    return (
        database,
        Path(f"{database}-wal"),
        Path(f"{database}-shm"),
        database.with_name(f"{database.name}.lock"),
    )


def existing_paths(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    return tuple(path for path in paths if path.exists())


def digest_paths(paths: tuple[Path, ...]) -> dict[str, str]:
    return {path.name: sha256_file(path) for path in paths if path.is_file()}


def protected_bundle_paths(
    root: Path,
    *,
    manifest: Mapping[str, object] | None = None,
) -> tuple[Path, ...]:
    names = [MANIFEST_NAME]
    database_name = "research-evidence.sqlite3"
    if manifest is not None:
        listed = manifest.get("database")
        if isinstance(listed, str) and listed:
            database_name = listed
        extra = manifest.get("protected_files")
        if isinstance(extra, list):
            names.extend(str(item) for item in extra if str(item))
    names.extend((database_name, f"{database_name}.sha256"))
    unique: list[Path] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        unique.append(root / name)
    return tuple(unique)


def capture_protected_artifacts(
    *,
    database: Path,
    bundle_root: Path | None = None,
    manifest: Mapping[str, object] | None = None,
) -> ProtectedArtifactSet:
    paths = list(existing_paths(sqlite_companion_paths(database)))
    if bundle_root is not None:
        paths.extend(
            path
            for path in protected_bundle_paths(bundle_root, manifest=manifest)
            if path.exists()
        )
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return ProtectedArtifactSet(digest_paths(tuple(unique)), tuple(unique))


def load_bundle_manifest(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ResearchEvidenceStoreError("research experiment manifest is invalid")
    return payload


def verify_protected_unchanged(
    before: ProtectedArtifactSet,
    after: ProtectedArtifactSet,
) -> None:
    if after.digests != before.digests:
        raise ResearchEvidenceStoreError("protected research evidence artifacts changed")
    after_names = {path.name for path in after.paths}
    before_names = {path.name for path in before.paths}
    if after_names != before_names:
        raise ResearchEvidenceStoreError("protected research evidence companions changed")


def byte_copy_sqlite(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{source}{suffix}")
        if sidecar.is_file():
            shutil.copy2(sidecar, Path(f"{destination}{suffix}"))
    return destination


def verify_declared_bundle_artifacts(
    *,
    database: Path,
    bundle_root: Path,
    manifest: Mapping[str, object],
) -> None:
    """Require every manifest-protected file and matching checksums."""

    missing = [
        path.name
        for path in protected_bundle_paths(bundle_root, manifest=manifest)
        if not path.is_file()
    ]
    if missing:
        raise ResearchEvidenceStoreError(
            "protected research evidence artifact is missing: " + ",".join(sorted(missing))
        )
    declared = str(manifest.get("database_sha256") or "")
    actual = sha256_file(database)
    if declared and declared.casefold() != actual.casefold():
        raise ResearchEvidenceStoreError(
            "research evidence database SHA-256 does not match the declared bundle"
        )
    checksum_path = database.with_suffix(f"{database.suffix}.sha256")
    if checksum_path.is_file():
        token = checksum_path.read_text(encoding="ascii").split()[0]
        if token.casefold() != actual.casefold():
            raise ResearchEvidenceStoreError(
                "research evidence checksum sidecar does not match the database"
            )


@contextmanager
def open_recorded_experiment_store(
    database: Path,
    *,
    bundle_root: Path | None = None,
    expected_database_sha256: str | None = None,
) -> Iterator[ResearchEvidenceStore]:
    """Open source evidence without initializing, migrating, or journaling it."""

    if not database.is_file():
        raise ResearchEvidenceStoreError("research evidence database is missing")
    manifest: dict[str, object] | None = None
    if bundle_root is not None:
        manifest_path = bundle_root / MANIFEST_NAME
        if manifest_path.is_file():
            manifest = load_bundle_manifest(manifest_path)
            verify_declared_bundle_artifacts(
                database=database,
                bundle_root=bundle_root,
                manifest=manifest,
            )
    before = capture_protected_artifacts(
        database=database,
        bundle_root=bundle_root,
        manifest=manifest,
    )
    if expected_database_sha256 is not None:
        actual = sha256_file(database)
        if actual.casefold() != expected_database_sha256.casefold():
            raise ResearchEvidenceStoreError(
                "research evidence database SHA-256 does not match the declared bundle"
            )
    sidecars = existing_paths((Path(f"{database}-wal"), Path(f"{database}-shm")))
    temporary: TemporaryDirectory[str] | None = None
    work = database
    try:
        if sidecars:
            temporary = _analysis_scratch(database)
            work = byte_copy_sqlite(database, Path(temporary.name) / database.name)
            store = ResearchEvidenceStore(work)
            store.initialize()
            store.verify_integrity()
        else:
            store = ResearchEvidenceStore(database, read_only=True, immutable=True)
            try:
                store.verify_integrity()
            except ResearchEvidenceStoreError:
                temporary = _analysis_scratch(database)
                work = byte_copy_sqlite(database, Path(temporary.name) / database.name)
                store = ResearchEvidenceStore(work)
                store.initialize()
                store.verify_integrity()
        yield store
    finally:
        after = capture_protected_artifacts(
            database=database,
            bundle_root=bundle_root,
            manifest=manifest,
        )
        if temporary is not None:
            temporary.cleanup()
        verify_protected_unchanged(before, after)


def _analysis_scratch(database: Path) -> TemporaryDirectory[str]:
    parent = database.parent
    parent.mkdir(parents=True, exist_ok=True)
    size = database.stat().st_size if database.is_file() else 0
    for companion in (Path(f"{database}-wal"), Path(f"{database}-shm")):
        if companion.is_file():
            size += companion.stat().st_size
    needed = size * 4 + 64 * 1024 * 1024
    if shutil.disk_usage(parent).free < needed:
        raise ResearchEvidenceStoreError("insufficient disk capacity for research scratch")
    return TemporaryDirectory(prefix="polysia-research-analysis-", dir=parent)


__all__ = [
    "MANIFEST_NAME",
    "ProtectedArtifactSet",
    "byte_copy_sqlite",
    "capture_protected_artifacts",
    "digest_paths",
    "load_bundle_manifest",
    "open_recorded_experiment_store",
    "protected_bundle_paths",
    "sha256_file",
    "sqlite_companion_paths",
    "verify_declared_bundle_artifacts",
    "verify_protected_unchanged",
]
