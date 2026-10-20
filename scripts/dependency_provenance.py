"""Data-only dependency artifact contract, evaluated by trusted base code."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path

from scripts.dependency_policy import (
    DEV_LOCK,
    EXPECTED_REPOSITORY,
    PYPROJECT,
    RUNTIME_LOCK,
    parse_lock_pins,
    shared_pin_conflicts,
)

try:
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
except ModuleNotFoundError:
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.utils import canonicalize_name

FILES = (PYPROJECT, RUNTIME_LOCK, DEV_LOCK)
WORKFLOW = ".github/workflows/dependency-automation.yml"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_path(directory: Path, relative: str) -> Path:
    candidates = (directory / relative, directory / Path(relative).name)
    existing = tuple(dict.fromkeys(path for path in candidates if path.exists()))
    if len(existing) != 1 or existing[0].is_symlink() or not existing[0].is_file():
        raise ValueError(f"missing or ambiguous artifact file: {relative}")
    if existing[0].stat().st_size > 1_000_000:
        raise ValueError("oversized dependency artifact")
    return existing[0]


def binding(
    *, repository: str, actor: str, base: str, head: str, run: str, attempt: str
) -> dict[str, str]:
    if repository != EXPECTED_REPOSITORY or not actor:
        raise ValueError("unexpected artifact repository or actor")
    if not all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (base, head)):
        raise ValueError("artifact requires immutable base and head")
    if not all(re.fullmatch(r"[1-9][0-9]*", value) for value in (run, attempt)):
        raise ValueError("artifact requires run and attempt identity")
    return dict(
        repository=repository,
        actor=actor,
        base=base,
        head=head,
        run=run,
        attempt=attempt,
        workflow=WORKFLOW,
    )


def seal(directory: Path, root: Path, identity: dict[str, str]) -> None:
    payload = dict(
        schema=1,
        identity=identity,
        source={name: digest(root / name) for name in FILES},
        files={name: digest(artifact_path(directory, name)) for name in FILES},
    )
    (directory / "provenance.json").write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def validate(directory: Path, root: Path, expected: dict[str, str]) -> None:
    provenance = directory / "provenance.json"
    if provenance.is_symlink() or provenance.stat().st_size > 10_000:
        raise ValueError("invalid artifact provenance file")
    payload = json.loads(provenance.read_text(encoding="utf-8"))
    if payload.get("schema") != 1 or payload.get("identity") != expected:
        raise ValueError("artifact origin does not match assessed workflow/run/attempt")
    if payload.get("source") != {name: digest(root / name) for name in FILES}:
        raise ValueError("artifact source changed; regenerate from the assessed base")
    if payload.get("files") != {name: digest(artifact_path(directory, name)) for name in FILES}:
        raise ValueError("dependency artifact hash mismatch")
    allowed = {artifact_path(directory, name).resolve() for name in FILES} | {provenance.resolve()}
    if any(
        path.is_symlink() or (path.is_file() and path.resolve() not in allowed)
        for path in directory.rglob("*")
    ):
        raise ValueError("unexpected artifact path")
    validate_manifest(directory, root)


def validate_manifest(directory: Path, root: Path) -> None:
    original = tomllib.loads((root / PYPROJECT).read_text(encoding="utf-8"))
    candidate = tomllib.loads(artifact_path(directory, PYPROJECT).read_text(encoding="utf-8"))
    runtime = parse_lock_pins(artifact_path(directory, RUNTIME_LOCK).read_text(encoding="utf-8"))
    dev = parse_lock_pins(artifact_path(directory, DEV_LOCK).read_text(encoding="utf-8"))
    if not runtime or not dev or shared_pin_conflicts(runtime, dev):
        raise ValueError("empty or inconsistent lock pair")
    if any(dev.get(name) != version for name, version in runtime.items()):
        raise ValueError("development lock omits a runtime pin")
    for data in (original, candidate):
        project = data.get("project", {})
        production = project.pop("dependencies", [])
        development = project.get("optional-dependencies", {}).pop("dev", [])
        for requirements, pins in ((production, runtime), (development, dev)):
            if data is original:
                continue
            for text in requirements:
                requirement = Requirement(text)
                if requirement.url:
                    raise ValueError("direct dependency source is not permitted")
                # Platform has a portable closure; platform-marked declarations
                # still require a pin, avoiding publisher-host marker assumptions.
                version = pins.get(canonicalize_name(requirement.name))
                if version is None or not requirement.specifier.contains(version):
                    raise ValueError("lock does not satisfy declared dependency")
    if original != candidate:
        raise ValueError("candidate changes configuration outside dependency declarations")
    for text in candidate.get("build-system", {}).get("requires", []):
        requirement = Requirement(text)
        version = dev.get(canonicalize_name(requirement.name))
        if requirement.url or version is None or not requirement.specifier.contains(version):
            raise ValueError("lock does not satisfy build requirement")
