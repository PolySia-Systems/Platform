"""Operation-owned scratch for large research restore and analysis copies."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from tempfile import TemporaryDirectory

from polysia.deployment.research_run_profiles import SAFETY_MARGIN_BYTES

DEFAULT_PREFIX = "polysia-research-op-"


class ResearchScratchError(RuntimeError):
    """Scratch preflight or cleanup failure."""


def planned_scratch_bytes(*paths: Path, copies: int = 4) -> int:
    total = 0
    for path in paths:
        if path.is_file():
            total += path.stat().st_size
        for companion in (Path(f"{path}-wal"), Path(f"{path}-shm")):
            if companion.is_file():
                total += companion.stat().st_size
    return total * copies + SAFETY_MARGIN_BYTES


def preflight_scratch(directory: Path, needed_bytes: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        with suppress(OSError):
            directory.chmod(0o700)
    usage = shutil.disk_usage(directory)
    if usage.free < needed_bytes:
        raise ResearchScratchError("insufficient disk capacity for research scratch")


@contextmanager
def operation_scratch(
    parent: Path,
    *,
    prefix: str = DEFAULT_PREFIX,
    needed_bytes: int,
) -> Iterator[Path]:
    preflight_scratch(parent, needed_bytes)
    with TemporaryDirectory(prefix=prefix, dir=parent) as temporary:
        yield Path(temporary)
