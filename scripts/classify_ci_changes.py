from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class ChangeMap:
    quality: bool
    python: bool
    package: bool
    container: bool
    dependencies: bool
    windows: bool
    comprehensive: bool
    browser: bool = False

    @classmethod
    def full(cls) -> ChangeMap:
        return cls(
            quality=True,
            python=True,
            package=True,
            container=True,
            dependencies=True,
            windows=True,
            comprehensive=True,
            browser=True,
        )


PYTHON_PATTERNS = (
    "src/**",
    "tests/**",
    "deploy/**",
    "scripts/*.py",
    "scripts/**/*.py",
    "pyproject.toml",
    "environment.yml",
    "locks/**",
    "Makefile",
    ".pre-commit-config.yaml",
)
PACKAGE_PATTERNS = (
    "src/**",
    "pyproject.toml",
    "locks/requirements-runtime-py314.txt",
    "Makefile",
)
CONTAINER_PATTERNS = (
    "Makefile",
    "locks/requirements-dev-py314.txt",
    "scripts/release_manifest.py",
    "tests/unit/scripts/test_release_manifest.py",
    "scripts/*acceptance.py",
    "pyproject.toml",
    "Dockerfile",
    "compose.yaml",
    "docker-compose.yml",
    ".dockerignore",
    ".env.example",
    "deploy/**",
    "locks/requirements-runtime-py314.txt",
    "src/polysia/config/**",
    "src/polysia/deployment/**",
    "src/polysia/cli.py",
    "src/polysia/cli_commands/core.py",
    "src/polysia/cli_commands/platform_*.py",
    "src/polysia/cli_support/native_*.py",
)
DEPENDENCY_PATTERNS = (
    "scripts/dependency*.py",
    "src/polysia/developer/dependency_preflight.py",
    "tests/unit/scripts/test_dependency*.py",
    "pyproject.toml",
    "environment.yml",
    "locks/**",
    "Dockerfile",
    ".pre-commit-config.yaml",
    ".github/dependabot.yml",
    ".github/actions/supply-chain/**",
)
WINDOWS_PATTERNS = (
    "Dockerfile",
    "locks/**",
    "scripts/dependency*.py",
    "scripts/*bootstrap*",
    "src/polysia/deployment/**",
    "src/polysia/storage/**",
    "src/polysia/security/**",
    "src/polysia/cli_support/native_*.py",
    "tests/unit/deployment/**",
    "tests/unit/storage/**",
    "tests/unit/security/**",
    "deploy/**",
    "*.ps1",
    "**/*.ps1",
    "environment.yml",
    "locks/conda-win-64.lock",
    "locks/requirements-dev-py314.txt",
    "locks/requirements-runtime-py314.txt",
    "pyproject.toml",
    ".python-version",
    ".github/actions/windows/**",
    "src/polysia/deployment/sqlite_backup.py",
    "tests/unit/deployment/test_sqlite_backup.py",
)
COMPREHENSIVE_PATTERNS = (
    "scripts/check_changed_docs.py",
    ".python-version",
    "environment.yml",
    ".github/CODEOWNERS",
    ".github/actions/**",
    "AGENTS.md",
    "**/AGENTS.md",
    "**/AGENTS.override.md",
    "AGENTS.override.md",
    ".gitignore",
    ".gitattributes",
    "scripts/fast_check.py",
    "scripts/ci_policy_contract.py",
    "scripts/windows_health.py",
    "scripts/validate_standards.py",
    "src/polysia/security/secret_scan.py",
    "src/polysia/developer/**",
    ".github/workflows/**",
    "scripts/classify_ci_changes.py",
    "tests/unit/scripts/test_classify_ci_changes.py",
)
DOCUMENT_ASSET_PATTERNS = (
    "docs/03-requirements/**",
    "docs/04-architecture/adrs/**",
    "docs/10-operations/**",
    "docs/00-governance/**",
    "docs/05-security/**",
)
LIGHTWEIGHT_PATTERNS = (
    "*.md",
    "**/*.md",
    "docs/**/*.svg",
    "docs/**/*.mmd",
    ".github/CODEOWNERS",
    ".gitignore",
    ".gitattributes",
    "LICENSE",
    "LICENSE.*",
)

RECORD_PATHS = ("standards/adoption.toml", "standards/conformance.toml")
BROWSER_PATTERNS = (
    "src/polysia/application/services/report_integrity.py",
    "src/polysia/application/services/shadow_reporting.py",
    "tests/conftest.py",
    "tests/fixtures/**",
    "scripts/*browser*.py",
    ".env.example",
    "compose.yaml",
    "docker-compose.yml",
    "src/polysia/monitoring/**",
    "src/polysia/interfaces/**",
    "src/polysia/api/**",
    "src/polysia/console/**",
    "src/polysia/config/**",
    "src/polysia/storage/**",
    "src/polysia/cli*",
    "src/polysia/cli*/**",
    "tests/browser/**",
    "**/*.html",
    "**/*.css",
    "**/*.js",
    "**/*.ts",
    "pyproject.toml",
    "locks/**",
    "Dockerfile",
    "deploy/**",
)

# Data files under documentation can be executable contracts. Only explicitly
# editorial formats above may skip behavioral checks; unknown paths fail closed.


def _normalize(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return PurePosixPath(normalized).as_posix()


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _known_path(path: str) -> bool:
    return _matches(path, (
        *PYTHON_PATTERNS, *PACKAGE_PATTERNS, *CONTAINER_PATTERNS, *DEPENDENCY_PATTERNS,
        *WINDOWS_PATTERNS, *COMPREHENSIVE_PATTERNS, *LIGHTWEIGHT_PATTERNS,
        *DOCUMENT_ASSET_PATTERNS, *RECORD_PATHS, *BROWSER_PATTERNS,
    ))


def classify_paths(paths: Iterable[str]) -> ChangeMap:
    changed = tuple(paths)
    if any(not valid_path(path) for path in changed):
        return ChangeMap.full()
    if not changed:
        return ChangeMap.full()

    # Prose about a control is not an executable control. AGENTS and actual
    # trust inputs still match independently; non-Markdown document assets
    # retain the full coverage previously assigned to their directories.
    comprehensive = any(
        _matches(path, COMPREHENSIVE_PATTERNS)
        or (_matches(path, DOCUMENT_ASSET_PATTERNS) and not path.endswith(".md"))
        for path in changed
    )
    recognized = all(_known_path(path) for path in changed)
    if comprehensive or not recognized:
        return ChangeMap.full()

    return ChangeMap(
        quality=True,
        python=any(
            _matches(path, (*PYTHON_PATTERNS, *BROWSER_PATTERNS, *DEPENDENCY_PATTERNS))
            for path in changed
        ),
        package=any(_matches(path, (*PACKAGE_PATTERNS, *DEPENDENCY_PATTERNS)) for path in changed),
        container=any(_matches(path, CONTAINER_PATTERNS) for path in changed),
        dependencies=any(_matches(path, DEPENDENCY_PATTERNS) for path in changed),
        windows=any(_matches(path, (*WINDOWS_PATTERNS, *DEPENDENCY_PATTERNS)) for path in changed),
        comprehensive=False,
        browser=any(_matches(path, BROWSER_PATTERNS) for path in changed),
    )


def classify_event(
    event: str,
    paths: Iterable[str] = (),
    *,
    validation_scope: str = "auto",
) -> ChangeMap:
    if validation_scope not in {"auto", "full"}:
        raise ValueError("invalid validation scope")
    if validation_scope == "full" or event == "schedule":
        return ChangeMap.full()
    if event == "workflow_dispatch":
        return ChangeMap(
            quality=False,
            python=False,
            package=False,
            container=False,
            dependencies=True,
            windows=True,
            comprehensive=False,
        )
    if event not in {"pull_request", "push"}:
        return ChangeMap.full()
    return classify_paths(paths)


POLICY_VERSION = 1
# Commands are data, never shell fragments. Applicability belongs only here.
# Contexts denote authority; running pytest on Windows cannot certify Linux.
CHECKS = (
    ("hygiene", "quality", "portable", ("python", "scripts/check_changed_docs.py", "--local")),
    (
        "standards",
        "quality",
        "portable",
        ("python", "scripts/validate_standards.py", "--mode", "full"),
    ),
    ("secrets", "quality", "portable", ("python", "-m", "polysia.security.secret_scan")),
    ("policy-contract", "always", "portable", ("python", "scripts/ci_policy_contract.py")),
    (
        "compile",
        "python",
        "portable",
        ("python", "-m", "compileall", "-q", "src", "tests", "scripts"),
    ),
    ("lint", "python", "portable", ("python", "-m", "ruff", "check", ".")),
    ("types", "python", "portable", ("python", "-m", "mypy", "src")),
    ("behavior", "python", "linux", ("python", "-m", "pytest", "-q")),
    ("integrity", "python", "portable", ("python", "-m", "pip", "check")),
    ("locks", "python", "portable", ("python", "scripts/dependency_locks.py", "check")),
    ("package", "package", "portable", ("python", "-m", "build")),
    ("wheel-install", "package", "linux-ci", ()),
    ("browser", "browser", "linux-ci", ()),
    ("image", "container", "container-ci", ()),
    ("install-recovery", "container", "linux-ci", ()),
    ("windows", "windows", "windows-ci", ()),
    (
        "audit",
        "dependencies",
        "portable",
        ("python", "-m", "pip_audit", "--strict", "--vulnerability-service", "osv"),
    ),
    (
        "sbom",
        "dependencies",
        "portable",
        (
            "cyclonedx-py",
            "environment",
            "--output-format",
            "JSON",
            "--output-file",
            "artifacts/sbom.json",
        ),
    ),
    ("allowed-install", "dependencies", "linux-ci", ()),
    ("ci-gate", "always", "native-ci", ()),
)
JOB_FLAGS = {
    "quality": "quality",
    "windows-compatibility": "windows",
    "container": "container",
    "supply-chain": "dependencies",
    "browser-acceptance": "browser",
    "installation-acceptance": "container",
}


def valid_path(path: object) -> bool:
    if not isinstance(path, str) or not path or path != path.strip():
        return False
    if any(ord(char) < 32 for char in path) or "\\" in path or ":" in path:
        return False
    if path.startswith("/") or any(p in {"", ".", ".."} for p in path.split("/")):
        return False
    # Canonical roots and known control names are case-sensitive on Linux.
    roots = {"src", "tests", "scripts", "docs", "standards", "locks", "deploy", ".github"}
    root = path.split("/")[0]
    if root.lower() in roots and root not in roots:
        return False
    if root in {"src", "tests", "scripts", "deploy", "standards", "locks"} and path != path.lower():
        return False
    known = {
        "readme.md": "README.md",
        "agents.md": "AGENTS.md",
        "dockerfile": "Dockerfile",
        "makefile": "Makefile",
    }
    return not (root.lower() in known and root != known[root.lower()])


def policy_identity() -> str:
    import hashlib

    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def project_policy(
    paths: Iterable[str],
    *,
    event: str = "local",
    base: str = "",
    head: str = "",
    validation_scope: str = "auto",
    diagnostics: Iterable[str] = (),
) -> dict:
    actual = list(dict.fromkeys(paths))
    problems = list(diagnostics)
    if not actual:
        problems.append("empty or unavailable diff; full validation")
    if any(not valid_path(path) for path in actual):
        problems.append("irregular path; full validation")
    if any(valid_path(path) and not _known_path(path) for path in actual):
        problems.append("unknown path; full validation")
    if event not in {"local", "push", "pull_request", "schedule", "workflow_dispatch"}:
        problems.append("unknown event; full validation")
    flags = classify_event(
        "push" if event == "local" else event,
        actual,
        validation_scope=validation_scope,
    )
    if problems:
        flags = ChangeMap.full()
    values = asdict(flags)
    return {
        "version": POLICY_VERSION,
        "policy": policy_identity(),
        "source": {
            "event": event,
            "base": base,
            "head": head,
            "validation_scope": validation_scope,
        },
        "paths": actual,
        "diagnostics": problems,
        "flags": values,
        "checks": checks_for(flags, actual),
    }


def checks_for(flags: ChangeMap, paths: Iterable[str] = ()) -> list[dict]:
    values = asdict(flags)
    per_path = [(path, asdict(classify_paths((path,)))) for path in paths]
    checks = []
    for check_id, flag, context, command in CHECKS:
        required = flag == "always" or values[flag]
        if flag in {"always", "quality"}:
            reason = "baseline contract"
        elif required:
            examples = [path for path, selected in per_path if selected[flag]][:3]
            reason = f"{flag}: " + (
                "changed " + ", ".join(examples)
                if examples else "event/scope or conservative full fallback"
            )
        else:
            reason = f"no {flag} input in complete diff/event"
        checks.append(
            {
                "id": check_id,
                "required": required,
                "context": context,
                "command": list(command),
                "reason": reason,
            }
        )
    return checks


def validate_projection(value: object) -> dict:
    if not isinstance(value, dict) or type(value.get("version")) is not int:
        raise ValueError("missing or invalid policy version")
    if value["version"] != POLICY_VERSION or value.get("policy") != policy_identity():
        raise ValueError("unsupported policy version or identity")
    source, paths, flags = value.get("source"), value.get("paths"), value.get("flags")
    if (
        not isinstance(source, dict)
        or set(source)
        != {
            "event",
            "base",
            "head",
            "validation_scope",
        }
        or not all(isinstance(v, str) for v in source.values())
    ):
        raise ValueError("invalid source identity")
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        raise ValueError("invalid actual paths")
    if not isinstance(flags, dict) or any(type(v) is not bool for v in flags.values()):
        raise ValueError("invalid policy flags")
    diagnostics = value.get("diagnostics")
    if not isinstance(diagnostics, list) or not all(isinstance(p, str) for p in diagnostics):
        raise ValueError("invalid fallback diagnostics")
    checks = value.get("checks")
    if not isinstance(checks, list) or any(
        not isinstance(check, dict) or type(check.get("required")) is not bool
        for check in checks
    ):
        raise ValueError("invalid policy check requirements")
    expected = project_policy(paths, **source, diagnostics=diagnostics)
    # Reprojection is strict: unknown IDs, missing checks and false flags fail closed.
    # Diagnostics must not duplicate when validating an already conservative policy.
    expected["diagnostics"] = diagnostics
    if value != expected:
        raise ValueError("inconsistent policy projection")
    return value


def _git(root: Path, *arguments: str) -> bytes:
    return subprocess.run(("git", *arguments), cwd=root, check=True, capture_output=True).stdout


def actual_diff(
    root: Path,
    *,
    base: str,
    head: str = "HEAD",
    local: bool = False,
    event: str = "push",
    validation_scope: str = "auto",
) -> dict:
    diagnostics: list[str] = []
    paths: list[str] = []
    resolved_base = ""
    resolved_head = _git(root, "rev-parse", "--verify", f"{head}^{{commit}}").decode().strip()
    try:
        if not base or set(base) == {"0"}:
            raise ValueError("missing base")
        resolved_base = _git(root, "rev-parse", "--verify", f"{base}^{{commit}}").decode().strip()
        if local or event == "pull_request":
            resolved_base = _git(root, "merge-base", resolved_base, resolved_head).decode().strip()
        paths += (
            _git(
                root,
                "diff",
                "--no-renames",
                "--name-only",
                "-z",
                resolved_base,
                resolved_head,
                "--",
            )
            .decode()
            .split("\0")[:-1]
        )
    except (subprocess.CalledProcessError, ValueError):
        # HEAD was verified. A tracked inventory is a trusted full fallback,
        # never an invented parent or an empty successful classification.
        diagnostics.append("comparison ref unavailable; tracked inventory/full validation")
        paths += _git(root, "ls-files", "-z").decode().split("\0")[:-1]
    if local:
        for arguments in (
            ("diff", "--no-renames", "--name-only", "-z"),
            ("diff", "--cached", "--no-renames", "--name-only", "-z"),
            ("ls-files", "--others", "--exclude-standard", "-z"),
        ):
            paths += _git(root, *arguments).decode().split("\0")[:-1]
    return project_policy(
        paths,
        event=event,
        base=resolved_base,
        head=resolved_head,
        validation_scope=validation_scope,
        diagnostics=diagnostics,
    )


def verify_gate(policy: object, needs: object, expected: dict | None = None) -> None:
    value = validate_projection(policy)
    if expected is not None and value != expected:
        raise ValueError("policy source/diff differs from independently collected inputs")
    if not isinstance(needs, dict) or needs.get("changes", {}).get("result") != "success":
        raise ValueError("changes job did not succeed")
    outputs = needs["changes"].get("outputs", {})
    for flag, required in value["flags"].items():
        if outputs.get(flag) != str(required).lower():
            raise ValueError(f"missing or inconsistent routing flag: {flag}")
    for job, flag in JOB_FLAGS.items():
        result = needs.get(job, {}).get("result")
        wanted = "success" if value["flags"][flag] else "skipped"
        if result != wanted:
            raise ValueError(f"{job}: required {wanted}, observed {result}")


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify CI work from changed paths.")
    parser.add_argument("--event", required=True)
    parser.add_argument(
        "--validation-scope",
        choices=("auto", "full"),
        default="auto",
    )
    parser.add_argument(
        "--format",
        choices=("github-output", "json", "projection"),
        default="json",
    )
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--verify-gate", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    if arguments.repository:
        projection = actual_diff(
            arguments.repository,
            base=arguments.base,
            head=arguments.head,
            local=arguments.local,
            event=arguments.event,
            validation_scope=arguments.validation_scope,
        )
    else:
        projection = project_policy(
            sys.stdin.read().splitlines(),
            event=arguments.event,
            validation_scope=arguments.validation_scope,
        )
    if arguments.verify_gate:
        if not arguments.repository:
            raise ValueError("Gate requires independently collected repository inputs")
        needs = json.loads(os.environ["NEEDS_JSON"])
        policy = json.loads(needs["changes"]["outputs"]["policy"])
        verify_gate(policy, needs, projection)
        print("All required CI jobs and policy contracts succeeded.")
        return 0
    values = projection["flags"]
    if arguments.format == "github-output":
        for key, value in values.items():
            print(f"{key}={str(value).lower()}")
        print("policy=" + json.dumps(projection, separators=(",", ":"), sort_keys=True))
    elif arguments.format == "projection":
        print(json.dumps(projection, sort_keys=True))
    else:
        print(json.dumps(values, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
