"""Canonical pip lock generation, verification, and Dependabot lock-sync."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Sequence
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.dependency_policy import (  # noqa: E402
    CONDA_LOCK,
    DEPENDABOT_LOGIN,
    DEV_LOCK,
    EXPECTED_BASE_BRANCH,
    EXPECTED_REPOSITORY,
    PYPROJECT,
    RUNTIME_LOCK,
    DependencyChange,
    RiskDecision,
    changed_lock_packages,
    classify_dependency_change,
    development_changes_are_low_risk,
    is_low_risk_version_bump,
    parse_lock_pins,
    parse_pep440_tuple,
    shared_pin_conflicts,
)

REPOSITORY_ROOT = _ROOT
LEGACY_RUNTIME_LOCK = Path("locks/pip-runtime-py314.lock")
LEGACY_DEV_LOCK = Path("locks/pip-py314.lock")
APPROVED_SDK_FILES = (
    Path("src/polysia/execution/tiny_live_round_trip.py"),
    Path("src/polysia/execution/tiny_live_copy.py"),
)
SDK_CONSTANT = re.compile(r'^APPROVED_SDK_VERSION = "([^"]+)"$', re.MULTILINE)
PIP_TOOLS_PIN = re.compile(r'"pip-tools==([^"]+)"')
LOCAL_PACKAGE_NAMES = frozenset({"polysia", "pm-trader", "pm_trader"})
UNSAFE_LOCK_MARKERS = (
    "-e ",
    "--editable",
    "git+",
    "hg+",
    "svn+",
    "bzr+",
    "file:",
    "--index-url",
    "--extra-index-url",
    "--find-links",
    "--trusted-host",
)
ALLOWED_PR_FILES = frozenset({PYPROJECT, RUNTIME_LOCK, DEV_LOCK})


def repository_root() -> Path:
    return REPOSITORY_ROOT


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.replace("\r\n", "\n"), encoding="utf-8", newline="\n")


def declared_pip_tools_version(root: Path | None = None) -> str:
    match = PIP_TOOLS_PIN.search(_read_text((root or repository_root()) / PYPROJECT))
    if match is None:
        raise RuntimeError("pyproject.toml must pin pip-tools exactly in the dev extra")
    return match.group(1)


def declared_sdk_version(root: Path | None = None) -> str:
    data = tomllib.loads(_read_text((root or repository_root()) / PYPROJECT))
    for requirement in data["project"]["dependencies"]:
        if requirement.startswith("polymarket-client=="):
            return requirement.split("==", 1)[1]
    raise RuntimeError("pyproject.toml must pin polymarket-client exactly")


def approved_sdk_versions(root: Path | None = None) -> dict[str, str]:
    base = root or repository_root()
    found: dict[str, str] = {}
    for relative in APPROVED_SDK_FILES:
        match = SDK_CONSTANT.search(_read_text(base / relative))
        if match is None:
            raise RuntimeError(f"{relative.as_posix()} must define APPROVED_SDK_VERSION")
        found[relative.as_posix()] = match.group(1)
    return found


def assert_sdk_pins_synchronized(root: Path | None = None) -> str:
    declared = declared_sdk_version(root)
    approved = approved_sdk_versions(root)
    mismatched = {path: version for path, version in approved.items() if version != declared}
    if mismatched:
        raise RuntimeError(
            "SDK approval pins are out of sync with pyproject.toml "
            f"(declared {declared}; found {mismatched})"
        )
    return declared


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=env,
    )


def _pip_compile_command(
    *,
    extra: str | None,
    output: Path,
    upgrade: bool,
    constraint: Path | None,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "piptools",
        "compile",
        PYPROJECT,
        "--output-file",
        output.as_posix(),
        "--newline",
        "lf",
        "--allow-unsafe",
        "--strip-extras",
        "--no-emit-index-url",
        "--no-emit-trusted-host",
        "--no-emit-options",
        "--no-config",
        "--pip-args",
        "--isolated",
        "--quiet",
    ]
    if extra:
        command.extend(["--extra", extra])
    if upgrade:
        command.append("--upgrade")
    if constraint is not None:
        command.extend(["--constraint", constraint.as_posix()])
    return command


def _sanitize_generated_lock(text: str) -> str:
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for marker in UNSAFE_LOCK_MARKERS:
            if marker in stripped:
                raise RuntimeError(f"generated lock contains forbidden marker: {marker}")
    pins = parse_lock_pins(text)
    unexpected = LOCAL_PACKAGE_NAMES.intersection(pins)
    if unexpected:
        raise RuntimeError(f"generated lock includes local project pins: {sorted(unexpected)}")
    return text.replace("\r\n", "\n")


def generate_pip_locks(
    root: Path,
    *,
    upgrade: bool,
    destination: Path | None = None,
) -> tuple[Path, Path]:
    dest = destination or root
    runtime_path = dest / RUNTIME_LOCK
    dev_path = dest / DEV_LOCK
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    if not runtime_path.exists() and (root / LEGACY_RUNTIME_LOCK).exists():
        shutil.copyfile(root / LEGACY_RUNTIME_LOCK, runtime_path)
    if not dev_path.exists() and (root / LEGACY_DEV_LOCK).exists():
        shutil.copyfile(root / LEGACY_DEV_LOCK, dev_path)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    _run(
        _pip_compile_command(
            extra=None,
            output=Path(RUNTIME_LOCK),
            upgrade=upgrade,
            constraint=None,
        ),
        cwd=root,
        env=env,
    )
    _write_text(runtime_path, _sanitize_generated_lock(_read_text(runtime_path)))
    _run(
        _pip_compile_command(
            extra="dev",
            output=Path(DEV_LOCK),
            upgrade=upgrade,
            constraint=Path(RUNTIME_LOCK),
        ),
        cwd=root,
        env=env,
    )
    _write_text(dev_path, _sanitize_generated_lock(_read_text(dev_path)))
    runtime_pins = parse_lock_pins(_read_text(runtime_path))
    dev_pins = parse_lock_pins(_read_text(dev_path))
    conflicts = shared_pin_conflicts(runtime_pins, dev_pins)
    if conflicts:
        raise RuntimeError("shared runtime/dev pins differ: " + "; ".join(conflicts))
    if "pip-tools" not in dev_pins:
        raise RuntimeError("development lock must include the pinned pip-tools resolver")
    if any(name in runtime_pins for name in ("pytest", "ruff", "mypy", "pip-tools", "pip-audit")):
        raise RuntimeError("runtime lock must exclude development/build/test tools")
    return runtime_path, dev_path


def check_pip_locks(root: Path | None = None) -> None:
    base = root or repository_root()
    assert_sdk_pins_synchronized(base)
    with tempfile.TemporaryDirectory(prefix="polysia-lock-check-") as raw:
        temp = Path(raw)
        work = temp / "src"
        shutil.copytree(
            base,
            work,
            ignore=shutil.ignore_patterns(
                ".git",
                ".venv",
                ".mypy_cache",
                ".pytest_cache",
                ".ruff_cache",
                "artifacts",
                "dist",
                "build",
            ),
            dirs_exist_ok=True,
        )
        generate_pip_locks(work, upgrade=False)
        for relative in (RUNTIME_LOCK, DEV_LOCK):
            committed = _read_text(base / relative)
            generated = _read_text(work / relative)
            if committed != generated:
                raise RuntimeError(
                    f"{relative} is not the deterministic pip-compile output of pyproject.toml"
                )


def refresh_pip_locks(*, upgrade: bool, root: Path | None = None) -> None:
    base = root or repository_root()
    assert_sdk_pins_synchronized(base)
    generate_pip_locks(base, upgrade=upgrade)


def refresh_conda_lock(root: Path | None = None) -> None:
    base = root or repository_root()
    conda = shutil.which("conda")
    if conda is None:
        raise RuntimeError("conda executable is required for --scope conda")
    result = _run((conda, "list", "--explicit", "-n", "PolySia"), cwd=base)
    output = result.stdout.replace("\r\n", "\n")
    if "@EXPLICIT" not in output:
        raise RuntimeError("conda list --explicit did not return an explicit spec")
    _write_text(base / CONDA_LOCK, output if output.endswith("\n") else output + "\n")


def _normalize_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _gh_json(args: Sequence[str]) -> object:
    result = subprocess.run(
        ("gh", "api", *args),
        check=True,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    return json.loads(result.stdout)


def _pr_changed_files(repository: str, number: int) -> tuple[str, ...]:
    payload = _gh_json((f"repos/{repository}/pulls/{number}/files", "--paginate"))
    if not isinstance(payload, list):
        raise RuntimeError("unexpected pull request files payload")
    return tuple(_normalize_path(str(item["filename"])) for item in payload)


def _git_text(repository: str, ref: str, path: str) -> str:
    payload = _gh_json((f"repos/{repository}/contents/{path}", "-F", f"ref={ref}"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"unable to read {path} at {ref}")
    return base64.b64decode(str(payload["content"])).decode("utf-8")


def _pyproject_sections(text: str) -> tuple[object, tuple[str, ...], str | None]:
    data = tomllib.loads(text)
    dependencies = tuple(
        str(item) for item in data.get("project", {}).get("dependencies", ())
    )
    sdk = next(
        (
            item.split("==", 1)[1]
            for item in dependencies
            if item.startswith("polymarket-client==")
        ),
        None,
    )
    return data.get("build-system"), dependencies, sdk


def _requirement_strings(text: str) -> tuple[str, ...]:
    data = tomllib.loads(text)
    items = [str(item) for item in data.get("project", {}).get("dependencies", ())]
    extras = data.get("project", {}).get("optional-dependencies", {})
    for extra in extras.values():
        items.extend(str(item) for item in extra)
    return tuple(items)


def _has_unsafe_requirements(text: str) -> bool:
    return any(
        req.startswith(("git+", "hg+", "svn+", "bzr+", "http://", "https://", "file:"))
        or req.startswith("-e ")
        or "@ git+" in req
        or " @ " in req
        for req in _requirement_strings(text)
    )


def is_github_actions_path(path: str) -> bool:
    normalized = _normalize_path(path)
    return (
        normalized.startswith(".github/workflows/")
        or normalized == ".github/dependabot.yml"
    )


def classify_lock_sync_intent(files: Sequence[str]) -> str:
    normalized = tuple(_normalize_path(path) for path in files if path.strip())
    if not normalized:
        return "reject"
    if all(is_github_actions_path(path) for path in normalized):
        return "actions"
    if any(path not in ALLOWED_PR_FILES for path in normalized):
        return "reject"
    if PYPROJECT in normalized and not (
        RUNTIME_LOCK in normalized and DEV_LOCK in normalized
    ):
        return "generate"
    return "noop"


def evaluate_lock_sync(
    *,
    repository: str,
    number: int,
    actor: str,
    base_branch: str,
    head_branch: str,
    base_sha: str,
    head_sha: str,
) -> dict[str, object]:
    if actor != DEPENDABOT_LOGIN:
        return {"status": "skip", "reason": "not a Dependabot pull request"}
    files = _pr_changed_files(repository, number)
    intent = classify_lock_sync_intent(files)
    if intent == "reject":
        return {
            "status": "reject",
            "reason": "dependency PR changes files outside the allowed declaration/lock set",
            "files": files,
        }
    if intent == "actions":
        return {
            "status": "noop",
            "reason": "GitHub Actions update does not require pip lock-sync",
            "ecosystem": "github_actions",
            "files": files,
        }
    pyproject_changed = PYPROJECT in files
    production_changed = False
    build_system_changed = False
    sdk_changed = False
    unsafe = False
    if pyproject_changed:
        base_pyproject = _git_text(repository, base_sha, PYPROJECT)
        head_pyproject = _git_text(repository, head_sha, PYPROJECT)
        base_build, base_deps, base_sdk = _pyproject_sections(base_pyproject)
        head_build, head_deps, head_sdk = _pyproject_sections(head_pyproject)
        build_system_changed = base_build != head_build
        production_changed = base_deps != head_deps
        sdk_changed = base_sdk != head_sdk
        unsafe = _has_unsafe_requirements(head_pyproject)
    if build_system_changed or unsafe:
        return {
            "status": "reject",
            "reason": "build-backend, registry, URL, VCS, or path dependency change",
            "files": files,
        }
    if intent == "generate":
        return {
            "status": "generate",
            "reason": "Dependabot changed pyproject.toml without complete generated locks",
            "files": files,
            "head_sha": head_sha,
            "head_branch": head_branch,
        }
    change, decision = build_change_from_lock_diff(
        actor=actor,
        repository=repository,
        base_branch=base_branch,
        head_branch=head_branch,
        changed_files=files,
        base_runtime=_git_text(repository, base_sha, RUNTIME_LOCK),
        head_runtime=_git_text(repository, head_sha, RUNTIME_LOCK),
        base_dev=_git_text(repository, base_sha, DEV_LOCK),
        head_dev=_git_text(repository, head_sha, DEV_LOCK),
        production_declaration_changed=production_changed,
        sdk_pin_changed=sdk_changed,
        package_ecosystem="pip",
    )
    return {
        "status": "noop",
        "reason": "Dependabot already supplied generated locks or no declaration change",
        "ecosystem": "pip",
        "decision": decision.action,
        "labels": list(decision.labels),
        "message": decision.reason,
        "affected": list(decision.affected),
        "files": files,
        "runtime_lock_changed": change.runtime_lock_changed,
        "development_lock_changed": change.development_lock_changed,
    }


def prepare_lock_sync_artifact(
    *,
    root: Path,
    repository: str,
    head_sha: str,
    destination: Path,
) -> None:
    overlay = destination / "work"
    shutil.copytree(
        root,
        overlay,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
        ),
    )
    _write_text(overlay / PYPROJECT, _git_text(repository, head_sha, PYPROJECT))
    generate_pip_locks(overlay, upgrade=False)
    artifact = destination / "locks"
    artifact.mkdir(parents=True, exist_ok=True)
    for relative in (RUNTIME_LOCK, DEV_LOCK):
        shutil.copyfile(overlay / relative, destination / Path(relative).name)
    shutil.copyfile(overlay / PYPROJECT, destination / "pyproject.toml")


def _artifact_file(directory: Path, relative: str) -> Path:
    nested = directory / relative
    flat = directory / Path(relative).name
    if nested.exists():
        return nested
    if flat.exists():
        return flat
    raise RuntimeError(f"lock artifact is missing {relative}")


def validate_lock_artifact(directory: Path) -> None:
    runtime = _read_text(_artifact_file(directory, RUNTIME_LOCK))
    development = _read_text(_artifact_file(directory, DEV_LOCK))
    runtime_pins = parse_lock_pins(_sanitize_generated_lock(runtime))
    dev_pins = parse_lock_pins(_sanitize_generated_lock(development))
    conflicts = shared_pin_conflicts(runtime_pins, dev_pins)
    if conflicts:
        raise RuntimeError("artifact shared pins differ: " + "; ".join(conflicts))
    pyproject = directory / "pyproject.toml"
    if pyproject.exists():
        data = tomllib.loads(_read_text(pyproject))
        backend = str(data.get("build-system", {}).get("build-backend", ""))
        if backend != "hatchling.build":
            raise RuntimeError("unexpected build backend in lock-sync artifact")


def commit_files_to_branch(
    *,
    repository: str,
    branch: str,
    files: dict[str, str],
    message: str,
) -> str:
    ref = _gh_json((f"repos/{repository}/git/ref/heads/{branch}",))
    if not isinstance(ref, dict):
        raise RuntimeError(f"unable to resolve branch {branch}")
    sha = str(ref["object"]["sha"])
    commit = _gh_json((f"repos/{repository}/git/commits/{sha}",))
    if not isinstance(commit, dict):
        raise RuntimeError("unable to read head commit")
    tree_sha = str(commit["tree"]["sha"])
    entries = []
    for path, content in files.items():
        created_blob = subprocess.run(
            ("gh", "api", "--method", "POST", f"repos/{repository}/git/blobs", "--input", "-"),
            check=True,
            text=True,
            encoding="utf-8",
            capture_output=True,
            input=json.dumps({"content": content, "encoding": "utf-8"}),
        )
        blob = json.loads(created_blob.stdout)
        entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    tree_payload = json.dumps({"base_tree": tree_sha, "tree": entries})
    tree = subprocess.run(
        ("gh", "api", "--method", "POST", f"repos/{repository}/git/trees", "--input", "-"),
        check=True,
        text=True,
        encoding="utf-8",
        capture_output=True,
        input=tree_payload,
    )
    new_tree = json.loads(tree.stdout)
    commit_payload = json.dumps(
        {"message": message, "tree": new_tree["sha"], "parents": [sha]}
    )
    created = subprocess.run(
        ("gh", "api", "--method", "POST", f"repos/{repository}/git/commits", "--input", "-"),
        check=True,
        text=True,
        encoding="utf-8",
        capture_output=True,
        input=commit_payload,
    )
    new_commit = json.loads(created.stdout)["sha"]
    subprocess.run(
        (
            "gh",
            "api",
            "--method",
            "PATCH",
            f"repos/{repository}/git/refs/heads/{branch}",
            "-f",
            f"sha={new_commit}",
        ),
        check=True,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    return str(new_commit)


def build_change_from_lock_diff(
    *,
    actor: str,
    repository: str,
    base_branch: str,
    head_branch: str,
    changed_files: tuple[str, ...],
    base_runtime: str,
    head_runtime: str,
    base_dev: str,
    head_dev: str,
    production_declaration_changed: bool,
    sdk_pin_changed: bool,
    package_ecosystem: str = "pip",
    update_type: str = "",
    dependency_names: tuple[str, ...] = (),
    security_update: bool = False,
) -> tuple[DependencyChange, RiskDecision]:
    runtime_diff = changed_lock_packages(base_runtime, head_runtime)
    dev_diff = changed_lock_packages(base_dev, head_dev)
    names = dependency_names or tuple(dict.fromkeys((*runtime_diff, *dev_diff)))
    zero_minor = False
    for name, (old, new) in {**dev_diff, **runtime_diff}.items():
        parsed_old = parse_pep440_tuple(old) if old else None
        parsed_new = parse_pep440_tuple(new) if new else None
        if (
            parsed_old
            and parsed_new
            and parsed_old[0] == 0
            and parsed_new[0] == 0
            and parsed_old[1] != parsed_new[1]
        ):
            zero_minor = True
        if (
            old
            and new
            and not is_low_risk_version_bump(old, new)
            and name in dev_diff
            and name not in runtime_diff
            and parsed_old
            and parsed_new
            and parsed_new[0] != parsed_old[0]
        ):
            update_type = update_type or "version-update:semver-major"
    change = DependencyChange(
        actor=actor,
        repository=repository,
        base_branch=base_branch,
        head_branch=head_branch,
        changed_files=changed_files,
        package_ecosystem=package_ecosystem,
        dependency_names=names,
        update_type=update_type,
        runtime_lock_changed=bool(runtime_diff),
        development_lock_changed=bool(dev_diff),
        pyproject_changed=PYPROJECT in changed_files,
        production_declaration_changed=production_declaration_changed,
        locks_complete=True,
        locks_valid=True,
        sdk_pin_changed=sdk_pin_changed,
        security_update=security_update,
        zero_version_minor=zero_minor,
        development_only_low_risk=(
            not runtime_diff and development_changes_are_low_risk(dev_diff)
        ),
    )
    return change, classify_dependency_change(change)


def classify_from_artifact(
    *,
    actor: str,
    head_branch: str,
    artifact: Path,
    base_root: Path,
    repository: str = EXPECTED_REPOSITORY,
    base_branch: str = EXPECTED_BASE_BRANCH,
    security_update: bool = False,
) -> tuple[DependencyChange, RiskDecision]:
    validate_lock_artifact(artifact)
    head_pyproject_path = artifact / PYPROJECT
    if not head_pyproject_path.exists():
        head_pyproject_path = artifact / "pyproject.toml"
    base_pyproject = _read_text(base_root / PYPROJECT)
    head_pyproject = (
        _read_text(head_pyproject_path)
        if head_pyproject_path.exists()
        else base_pyproject
    )
    _, base_deps, base_sdk = _pyproject_sections(base_pyproject)
    _, head_deps, head_sdk = _pyproject_sections(head_pyproject)
    return build_change_from_lock_diff(
        actor=actor,
        repository=repository,
        base_branch=base_branch,
        head_branch=head_branch,
        changed_files=(
            PYPROJECT,
            RUNTIME_LOCK,
            DEV_LOCK,
        ),
        base_runtime=_read_text(base_root / RUNTIME_LOCK),
        head_runtime=_read_text(_artifact_file(artifact, RUNTIME_LOCK)),
        base_dev=_read_text(base_root / DEV_LOCK),
        head_dev=_read_text(_artifact_file(artifact, DEV_LOCK)),
        production_declaration_changed=base_deps != head_deps,
        sdk_pin_changed=base_sdk != head_sdk,
        package_ecosystem="pip",
        security_update=security_update,
    )


def _emit_decision(decision: RiskDecision) -> int:
    print(json.dumps(decision.__dict__, indent=2, sort_keys=True, default=list))
    _github_output(
        {
            "action": decision.action,
            "reason": decision.reason,
            "labels": ",".join(decision.labels),
        }
    )
    return 0 if decision.action != "reject" else 1


def _github_output(values: dict[str, str]) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        for key, value in values.items():
            print(f"{key}={value}")
        return
    with Path(output).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            if "\n" in value:
                handle.write(f"{key}<<EOF\n{value}\nEOF\n")
            else:
                handle.write(f"{key}={value}\n")


def _add_arguments(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "check",
        help="verify committed pip locks without selecting newer versions",
    )
    refresh = sub.add_parser("refresh", help="regenerate lock outputs")
    refresh.add_argument("--scope", choices=("pip", "conda"), required=True)
    refresh.add_argument("--upgrade", action="store_true")
    evaluate = sub.add_parser("lock-sync-evaluate")
    evaluate.add_argument("--pr", type=int, required=True)
    prepare = sub.add_parser("lock-sync-prepare")
    prepare.add_argument("--head-sha", required=True)
    prepare.add_argument("--destination", required=True)
    validate = sub.add_parser("lock-sync-validate")
    validate.add_argument("--artifact", required=True)
    commit = sub.add_parser("lock-sync-commit")
    commit.add_argument("--branch", required=True)
    commit.add_argument("--artifact", required=True)
    commit.add_argument("--message", required=True)
    classify = sub.add_parser("classify")
    classify.add_argument("--actor", required=True)
    classify.add_argument("--head-branch", required=True)
    classify.add_argument("--package-ecosystem", default="")
    classify.add_argument("--update-type", default="")
    classify.add_argument("--dependency-names", default="")
    classify.add_argument("--changed-files", default="")
    classify.add_argument("--security-update", action="store_true")
    classify.add_argument("--runtime-lock-changed", action="store_true")
    classify.add_argument("--development-lock-changed", action="store_true")
    classify.add_argument("--pyproject-changed", action="store_true")
    classify.add_argument("--production-declaration-changed", action="store_true")
    classify.add_argument("--sdk-pin-changed", action="store_true")
    classify.add_argument("--locks-complete", action="store_true")
    classify.add_argument("--locks-valid", action="store_true")
    classify.add_argument("--previous-version", default="")
    classify.add_argument("--new-version", default="")
    from_locks = sub.add_parser("classify-from-locks")
    from_locks.add_argument("--actor", required=True)
    from_locks.add_argument("--head-branch", required=True)
    from_locks.add_argument("--artifact", required=True)
    from_locks.add_argument("--base-root", default=".")
    from_locks.add_argument("--security-update", action="store_true")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _add_arguments(parser)
    arguments = parser.parse_args(argv)
    root = repository_root()
    try:
        if arguments.command == "check":
            check_pip_locks(root)
            print("dependency locks match pyproject.toml")
            return 0
        if arguments.command == "refresh":
            if arguments.scope == "conda":
                refresh_conda_lock(root)
            else:
                refresh_pip_locks(upgrade=arguments.upgrade, root=root)
            print(f"refreshed {arguments.scope} locks")
            return 0
        if arguments.command == "lock-sync-evaluate":
            repository = os.environ.get("GITHUB_REPOSITORY", EXPECTED_REPOSITORY)
            evaluation = evaluate_lock_sync(
                repository=repository,
                number=arguments.pr,
                actor=os.environ.get("DEPENDENCY_PR_ACTOR", DEPENDABOT_LOGIN),
                base_branch=os.environ.get("DEPENDENCY_BASE_BRANCH", EXPECTED_BASE_BRANCH),
                head_branch=os.environ["DEPENDENCY_HEAD_BRANCH"],
                base_sha=os.environ["DEPENDENCY_BASE_SHA"],
                head_sha=os.environ["DEPENDENCY_HEAD_SHA"],
            )
            print(json.dumps(evaluation, indent=2, sort_keys=True, default=list))
            _github_output(
                {
                    "status": str(evaluation["status"]),
                    "reason": str(evaluation["reason"]),
                    "payload": json.dumps(evaluation, sort_keys=True, default=list),
                }
            )
            return 0
        if arguments.command == "lock-sync-prepare":
            destination = Path(arguments.destination)
            destination.mkdir(parents=True, exist_ok=True)
            prepare_lock_sync_artifact(
                root=root,
                repository=os.environ.get("GITHUB_REPOSITORY", EXPECTED_REPOSITORY),
                head_sha=arguments.head_sha,
                destination=destination,
            )
            return 0
        if arguments.command == "lock-sync-validate":
            validate_lock_artifact(Path(arguments.artifact))
            print("lock artifact accepted")
            return 0
        if arguments.command == "lock-sync-commit":
            artifact = Path(arguments.artifact)
            validate_lock_artifact(artifact)
            sha = commit_files_to_branch(
                repository=os.environ.get("GITHUB_REPOSITORY", EXPECTED_REPOSITORY),
                branch=arguments.branch,
                files={
                    RUNTIME_LOCK: _read_text(_artifact_file(artifact, RUNTIME_LOCK)),
                    DEV_LOCK: _read_text(_artifact_file(artifact, DEV_LOCK)),
                },
                message=arguments.message,
            )
            print(sha)
            _github_output({"head_sha": sha})
            return 0
        if arguments.command == "classify":
            names = tuple(
                item.strip()
                for item in arguments.dependency_names.split(",")
                if item.strip()
            )
            files = tuple(
                item.strip() for item in arguments.changed_files.split(",") if item.strip()
            )
            previous = arguments.previous_version.strip()
            current = arguments.new_version.strip()
            parsed_old = parse_pep440_tuple(previous) if previous else None
            parsed_new = parse_pep440_tuple(current) if current else None
            zero_minor = bool(
                parsed_old
                and parsed_new
                and parsed_old[0] == 0
                and parsed_new[0] == 0
                and parsed_old[1] != parsed_new[1]
            )
            change = DependencyChange(
                actor=arguments.actor,
                repository=os.environ.get("GITHUB_REPOSITORY", EXPECTED_REPOSITORY),
                base_branch=EXPECTED_BASE_BRANCH,
                head_branch=arguments.head_branch,
                changed_files=files,
                package_ecosystem=arguments.package_ecosystem,
                dependency_names=names,
                update_type=arguments.update_type,
                runtime_lock_changed=arguments.runtime_lock_changed,
                development_lock_changed=arguments.development_lock_changed,
                pyproject_changed=arguments.pyproject_changed,
                production_declaration_changed=arguments.production_declaration_changed,
                locks_complete=arguments.locks_complete,
                locks_valid=arguments.locks_valid,
                sdk_pin_changed=arguments.sdk_pin_changed,
                security_update=arguments.security_update,
                zero_version_minor=zero_minor,
            )
            return _emit_decision(classify_dependency_change(change))
        if arguments.command == "classify-from-locks":
            _change, decision = classify_from_artifact(
                actor=arguments.actor,
                head_branch=arguments.head_branch,
                artifact=Path(arguments.artifact),
                base_root=Path(arguments.base_root),
                repository=os.environ.get("GITHUB_REPOSITORY", EXPECTED_REPOSITORY),
                security_update=arguments.security_update,
            )
            return _emit_decision(decision)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr or exc.stdout or str(exc))
        return 1
    except (RuntimeError, ValueError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    raise AssertionError(f"unhandled command {arguments.command}")


if __name__ == "__main__":
    raise SystemExit(main())
