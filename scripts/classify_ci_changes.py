from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class ChangeMap:
    quality: bool
    python: bool
    package: bool
    container: bool
    dependencies: bool
    windows: bool
    comprehensive: bool

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
        )


PYTHON_PATTERNS = (
    "src/**",
    "tests/**",
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
    "environment.yml",
    "locks/**",
    "Makefile",
)
CONTAINER_PATTERNS = (
    "Dockerfile",
    "compose.yaml",
    "docker-compose.yml",
    ".dockerignore",
    ".env.example",
    "deploy/**",
    "locks/pip-runtime-py314.lock",
    "src/polysia/config/**",
    "src/polysia/deployment/**",
    "src/polysia/cli.py",
    "src/polysia/cli_commands/core.py",
)
DEPENDENCY_PATTERNS = (
    "pyproject.toml",
    "environment.yml",
    "locks/**",
    "Dockerfile",
    ".pre-commit-config.yaml",
    ".github/dependabot.yml",
    ".github/actions/supply-chain/**",
)
WINDOWS_PATTERNS = (
    "*.ps1",
    "**/*.ps1",
    "environment.yml",
    "locks/conda-win-64.lock",
    "locks/pip-py314.lock",
    "locks/pip-runtime-py314.lock",
    "pyproject.toml",
    ".python-version",
    ".github/actions/windows/**",
    "src/polysia/deployment/sqlite_backup.py",
    "tests/unit/deployment/test_sqlite_backup.py",
)
COMPREHENSIVE_PATTERNS = (
    ".github/workflows/**",
    "scripts/classify_ci_changes.py",
    "tests/unit/scripts/test_classify_ci_changes.py",
)
LIGHTWEIGHT_PATTERNS = (
    "*.md",
    "**/*.md",
    "docs/**",
    "plans/**",
    "prompts/**",
    "standards/**",
    ".github/CODEOWNERS",
    ".gitignore",
    ".gitattributes",
    "LICENSE",
    "LICENSE.*",
)


def _normalize(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return PurePosixPath(normalized).as_posix()


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def classify_paths(paths: Iterable[str]) -> ChangeMap:
    changed = tuple(dict.fromkeys(_normalize(path) for path in paths if path.strip()))
    if not changed:
        return ChangeMap.full()

    comprehensive = any(_matches(path, COMPREHENSIVE_PATTERNS) for path in changed)
    recognized = all(
        _matches(
            path,
            (
                *PYTHON_PATTERNS,
                *PACKAGE_PATTERNS,
                *CONTAINER_PATTERNS,
                *DEPENDENCY_PATTERNS,
                *WINDOWS_PATTERNS,
                *COMPREHENSIVE_PATTERNS,
                *LIGHTWEIGHT_PATTERNS,
            ),
        )
        for path in changed
    )
    if comprehensive or not recognized:
        return ChangeMap.full()

    return ChangeMap(
        quality=True,
        python=any(_matches(path, PYTHON_PATTERNS) for path in changed),
        package=any(_matches(path, PACKAGE_PATTERNS) for path in changed),
        container=any(_matches(path, CONTAINER_PATTERNS) for path in changed),
        dependencies=any(_matches(path, DEPENDENCY_PATTERNS) for path in changed),
        windows=any(_matches(path, WINDOWS_PATTERNS) for path in changed),
        comprehensive=False,
    )


def classify_event(
    event: str,
    paths: Iterable[str] = (),
    *,
    validation_scope: str = "auto",
) -> ChangeMap:
    if validation_scope == "full":
        return ChangeMap.full()
    if event == "schedule":
        return ChangeMap(
            quality=False,
            python=False,
            package=False,
            container=False,
            dependencies=True,
            windows=True,
            comprehensive=False,
        )
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
        choices=("github-output", "json"),
        default="json",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    change_map = classify_event(
        arguments.event,
        sys.stdin.read().splitlines(),
        validation_scope=arguments.validation_scope,
    )
    values = asdict(change_map)
    if arguments.format == "github-output":
        for key, value in values.items():
            print(f"{key}={str(value).lower()}")
    else:
        print(json.dumps(values, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
