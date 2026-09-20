"""Read-only Git identity for developer context packets."""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

GitRunner = Callable[[Path, Sequence[str]], str]


class DeveloperContextError(RuntimeError):
    """Fail-closed developer-context failure without secret values."""


@dataclass(frozen=True, slots=True)
class RepositoryIdentity:
    root: Path
    branch: str
    head: str
    dirty: bool
    dirty_fingerprint: str
    changed_paths: tuple[str, ...]


def inspect_repository(
    root: Path,
    *,
    git_runner: GitRunner | None = None,
) -> RepositoryIdentity:
    runner = git_runner or run_git
    discovered = Path(runner(root, ("git", "rev-parse", "--show-toplevel")).strip())
    if discovered.resolve() != root.resolve():
        raise DeveloperContextError("repository root does not match Git toplevel")
    head = runner(root, ("git", "rev-parse", "HEAD")).strip()
    if len(head) != 40 or any(char not in "0123456789abcdef" for char in head.lower()):
        raise DeveloperContextError("HEAD is not a 40-character SHA")
    branch = runner(root, ("git", "branch", "--show-current")).strip() or "HEAD"
    porcelain = runner(root, ("git", "status", "--porcelain=v1"))
    changed = tuple(_changed_paths(porcelain))
    fingerprint = hashlib.sha256(porcelain.encode("utf-8")).hexdigest()
    return RepositoryIdentity(
        root=root,
        branch=branch,
        head=head.lower(),
        dirty=bool(changed),
        dirty_fingerprint=fingerprint,
        changed_paths=changed,
    )


def run_git(root: Path, command: Sequence[str]) -> str:
    if not command or command[0] != "git":
        raise DeveloperContextError("Git runner accepts only git commands")
    try:
        result = subprocess.run(
            list(command),
            check=True,
            capture_output=True,
            cwd=root,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DeveloperContextError("Git identity is unavailable") from error
    return result.stdout


def _changed_paths(porcelain: str) -> list[str]:
    paths: list[str] = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        entry = line[3:]
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        paths.append(entry.replace("\\", "/"))
    return paths
