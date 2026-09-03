"""Risk classification for PolySia dependency automation.

Unattended merge is opt-in and fail-closed. This module is pure policy: it
never talks to GitHub, never writes locks, and never executes package code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

RiskAction = Literal["auto_merge", "human_review", "reject"]

EXPECTED_REPOSITORY = "PolySia-Systems/Platform"
EXPECTED_BASE_BRANCH = "main"
DEPENDABOT_LOGIN = "dependabot[bot]"
SCHEDULED_BRANCH_PREFIX = "codex/scheduled-lock-refresh-"
DEPENDABOT_BRANCH_PREFIXES = (
    "dependabot/pip/",
    "dependabot/github_actions/",
    "dependabot/docker/",
    "dependabot/conda/",
)

RUNTIME_LOCK = "locks/requirements-runtime-py314.txt"
DEV_LOCK = "locks/requirements-dev-py314.txt"
PYPROJECT = "pyproject.toml"
CONDA_LOCK = "locks/conda-win-64.lock"
ENVIRONMENT = "environment.yml"

SENSITIVE_RUNTIME_PACKAGES = frozenset(
    {
        "polymarket-client",
        "pydantic",
        "pydantic-core",
        "pydantic-settings",
        "eth-abi",
        "eth-account",
        "eth-hash",
        "eth-keyfile",
        "eth-keys",
        "eth-rlp",
        "eth-typing",
        "eth-utils",
        "pycryptodome",
        "ckzg",
        "bitarray",
        "hexbytes",
        "rlp",
        "cytoolz",
        "websockets",
        "httpx",
        "h11",
        "anyio",
        "typer",
        "structlog",
        "rich",
        "python-dotenv",
    }
)

UNSAFE_REQUIREMENT = re.compile(
    r"""(?ix)
    (?:^|\s)(?:-e\s+|--editable\s+)
    |(?:git\+|hg\+|svn\+|bzr\+)
    |(?:https?://)
    |(?:file:)
    |(?:@\s*git\+)
    |(?:\s@\s)
    """
)
PIN_LINE = re.compile(
    r"^([A-Za-z0-9_.-]+)==([^\\\s;]+)(?:\s*;\s*[^#]+)?\s*(?:\\)?$"
)
VERSION_SPLIT = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?")


@dataclass(frozen=True)
class RiskDecision:
    action: RiskAction
    reason: str
    labels: tuple[str, ...]
    affected: tuple[str, ...]


@dataclass(frozen=True)
class DependencyChange:
    actor: str
    repository: str
    base_branch: str
    head_branch: str
    changed_files: tuple[str, ...]
    package_ecosystem: str = ""
    dependency_names: tuple[str, ...] = ()
    update_type: str = ""
    runtime_lock_changed: bool = False
    development_lock_changed: bool = False
    pyproject_changed: bool = False
    production_declaration_changed: bool = False
    build_system_changed: bool = False
    unsafe_requirement: bool = False
    locks_complete: bool = False
    locks_valid: bool = False
    sdk_pin_changed: bool = False
    conda_or_python_changed: bool = False
    docker_changed: bool = False
    workflow_or_permission_changed: bool = False
    security_update: bool = False
    zero_version_minor: bool = False
    development_only_low_risk: bool = False


def _labels(*values: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def parse_lock_pins(text: str) -> dict[str, str]:
    pins: dict[str, str] = {}
    continuation = False
    for raw in text.splitlines():
        line = raw.strip()
        if continuation:
            continuation = line.endswith("\\")
            continue
        if not line or line.startswith("#"):
            continue
        if line.startswith("-"):
            raise ValueError(f"unsupported lock directive: {line}")
        if UNSAFE_REQUIREMENT.search(line):
            raise ValueError(f"unsafe requirement: {line}")
        match = PIN_LINE.match(line)
        if match is None:
            raise ValueError(f"malformed lock pin: {line}")
        name = match.group(1).lower().replace("_", "-")
        version = match.group(2).strip()
        if name in {"polysia", "pm-trader", "pm_trader"}:
            raise ValueError("generated locks must exclude the editable project")
        pins[name] = version
        continuation = line.endswith("\\")
    return pins


def shared_pin_conflicts(
    runtime_pins: dict[str, str],
    dev_pins: dict[str, str],
) -> tuple[str, ...]:
    conflicts: list[str] = []
    for name, version in runtime_pins.items():
        other = dev_pins.get(name)
        if other is not None and other != version:
            conflicts.append(f"{name}: runtime={version} dev={other}")
    return tuple(conflicts)


def parse_pep440_tuple(version: str) -> tuple[int, int, int] | None:
    match = VERSION_SPLIT.match(version.lstrip("vV"))
    if match is None:
        return None
    major = int(match.group(1))
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)
    return major, minor, patch


def is_low_risk_version_bump(previous: str, current: str) -> bool:
    parsed_previous = parse_pep440_tuple(previous)
    parsed_current = parse_pep440_tuple(current)
    if parsed_previous is None or parsed_current is None:
        return False
    prev_major, prev_minor, prev_patch = parsed_previous
    cur_major, cur_minor, cur_patch = parsed_current
    if (cur_major, cur_minor, cur_patch) < (prev_major, prev_minor, prev_patch):
        return False
    if cur_major != prev_major:
        return False
    return not (prev_major == 0 and cur_minor != prev_minor)


def is_trusted_dependency_actor(actor: str, head_branch: str) -> bool:
    return (
        actor == DEPENDABOT_LOGIN and head_branch.startswith(DEPENDABOT_BRANCH_PREFIXES)
    ) or head_branch.startswith(SCHEDULED_BRANCH_PREFIX)


def classify_dependency_change(change: DependencyChange) -> RiskDecision:
    if (
        change.repository != EXPECTED_REPOSITORY
        or change.base_branch != EXPECTED_BASE_BRANCH
    ):
        return RiskDecision(
            "reject",
            "unexpected repository or base branch",
            _labels("risk:reject"),
            (),
        )
    if not is_trusted_dependency_actor(change.actor, change.head_branch):
        return RiskDecision(
            "reject",
            "unexpected actor or branch for unattended dependency automation",
            _labels("risk:reject"),
            change.dependency_names,
        )
    if change.workflow_or_permission_changed or change.docker_changed:
        return RiskDecision(
            "reject",
            "workflow, permission, Docker, or safety path changed in a dependency PR",
            _labels("risk:reject"),
            change.changed_files,
        )
    if change.build_system_changed or change.unsafe_requirement:
        return RiskDecision(
            "reject",
            "build-backend, registry, URL, VCS, or path dependency change",
            _labels("risk:reject"),
            change.dependency_names,
        )
    if change.pyproject_changed and not change.locks_complete:
        return RiskDecision(
            "reject",
            "pyproject.toml changed without complete generated pip locks",
            _labels("risk:reject"),
            (PYPROJECT,),
        )
    if not change.locks_valid:
        return RiskDecision(
            "reject",
            "generated lock files are missing, malformed, or do not match pyproject.toml",
            _labels("risk:reject"),
            tuple(path for path in (RUNTIME_LOCK, DEV_LOCK) if path in change.changed_files),
        )

    affected = change.dependency_names or tuple(change.changed_files)
    sensitive = tuple(
        name
        for name in change.dependency_names
        if name.lower().replace("_", "-") in SENSITIVE_RUNTIME_PACKAGES
    )
    if change.package_ecosystem == "github_actions":
        if change.update_type == "version-update:semver-patch":
            return RiskDecision(
                "auto_merge",
                "GitHub Actions patch with complete required checks",
                _labels("risk:auto-merge", "deps:github-actions"),
                affected,
            )
        return RiskDecision(
            "human_review",
            "GitHub Actions minor/major or ambiguous Actions update",
            _labels("risk:human-review", "deps:github-actions"),
            affected,
        )

    requires_human = (
        change.runtime_lock_changed
        or change.production_declaration_changed
        or change.sdk_pin_changed
        or change.conda_or_python_changed
        or bool(sensitive)
        or change.update_type == "version-update:semver-major"
        or change.zero_version_minor
        or (
            change.security_update
            and (
                change.runtime_lock_changed
                or change.production_declaration_changed
                or change.sdk_pin_changed
            )
        )
    )
    if requires_human:
        return RiskDecision(
            "human_review",
            "runtime, SDK, major, 0.x minor, Conda/Python, or sensitive security change",
            _labels(
                "risk:human-review",
                "deps:runtime" if change.runtime_lock_changed else "deps:development",
            ),
            affected or sensitive,
        )

    metadata_patch_or_stable_minor = change.update_type in {
        "version-update:semver-patch",
        "version-update:semver-minor",
    } and not change.zero_version_minor
    development_only = (
        not change.runtime_lock_changed and not change.production_declaration_changed
    )
    if change.development_only_low_risk or (
        development_only
        and change.locks_complete
        and change.locks_valid
        and (change.development_lock_changed or change.pyproject_changed)
        and metadata_patch_or_stable_minor
    ):
        return RiskDecision(
            "auto_merge",
            "development-only low-risk update with complete valid locks",
            _labels("risk:auto-merge", "deps:development"),
            affected,
        )

    return RiskDecision(
        "human_review",
        "ambiguous dependency classification",
        _labels("risk:human-review"),
        affected,
    )


def changed_lock_packages(before: str, after: str) -> dict[str, tuple[str, str]]:
    previous = parse_lock_pins(before)
    current = parse_lock_pins(after)
    names = set(previous) | set(current)
    diff: dict[str, tuple[str, str]] = {}
    for name in sorted(names):
        old = previous.get(name, "")
        new = current.get(name, "")
        if old != new:
            diff[name] = (old, new)
    return diff


def development_changes_are_low_risk(package_diffs: dict[str, tuple[str, str]]) -> bool:
    if not package_diffs:
        return True
    for name, (old, new) in package_diffs.items():
        if name in SENSITIVE_RUNTIME_PACKAGES:
            return False
        if old and new and not is_low_risk_version_bump(old, new):
            return False
        if not old or not new:
            return False
    return True
