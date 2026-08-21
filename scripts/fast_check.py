from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ORIGIN_MAIN_REF = "refs/remotes/origin/main"


@dataclass(frozen=True)
class Check:
    label: str
    command: tuple[str, ...]
    required_ref: str | None = None


CommandRunner = Callable[[tuple[str, ...], Path], int]
ReferenceChecker = Callable[[str, Path], bool]
Clock = Callable[[], float]
Writer = Callable[[str], None]


def write_line(message: str) -> None:
    print(message, flush=True)


def build_checks(python_executable: str | None = None) -> tuple[Check, ...]:
    python = python_executable or sys.executable
    return (
        Check("Diff (working)", ("git", "diff", "--check")),
        Check("Diff (staged)", ("git", "diff", "--cached", "--check")),
        Check(
            "Diff (origin/main)",
            ("git", "diff", "--check", "origin/main...HEAD"),
            required_ref=ORIGIN_MAIN_REF,
        ),
        Check(
            "Standards",
            (python, "scripts/validate_standards.py", "--mode", "full"),
        ),
        Check("Secret Scan", (python, "-m", "polysia.security.secret_scan")),
        Check("Compile", (python, "-m", "compileall", "-q", "src", "tests", "scripts")),
        Check("Ruff", (python, "-m", "ruff", "check", ".")),
        Check("Mypy", (python, "-m", "mypy", "src")),
        Check("Pip Check", (python, "-m", "pip", "check")),
    )


def run_command(command: tuple[str, ...], repository: Path) -> int:
    return subprocess.run(command, cwd=repository, check=False).returncode


def local_reference_exists(reference: str, repository: Path) -> bool:
    result = subprocess.run(
        ("git", "rev-parse", "--verify", "--quiet", reference),
        cwd=repository,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _result_line(label: str, elapsed: float, result: str) -> str:
    return f"{label:<22} {elapsed:>6.1f}s  {result}"


def run_checks(
    checks: Iterable[Check],
    *,
    repository: Path = REPOSITORY_ROOT,
    runner: CommandRunner = run_command,
    reference_checker: ReferenceChecker = local_reference_exists,
    clock: Clock = time.perf_counter,
    write: Writer = write_line,
) -> int:
    total_started = clock()

    for check in checks:
        check_started = clock()
        if check.required_ref is not None:
            try:
                reference_exists = reference_checker(check.required_ref, repository)
            except OSError as error:
                elapsed = clock() - check_started
                write(_result_line(check.label, elapsed, "FAIL"))
                write(f"Unable to inspect {check.required_ref}: {error}")
                write(_result_line("Total", clock() - total_started, "FAIL"))
                return 1
            if not reference_exists:
                elapsed = clock() - check_started
                write(_result_line(check.label, elapsed, "SKIP"))
                write(
                    f"Local reference {check.required_ref} is unavailable; "
                    "no fetch was attempted."
                )
                continue

        try:
            exit_code = runner(check.command, repository)
        except OSError as error:
            elapsed = clock() - check_started
            write(_result_line(check.label, elapsed, "FAIL"))
            write(f"Unable to start command: {error}")
            write(_result_line("Total", clock() - total_started, "FAIL"))
            return 1

        elapsed = clock() - check_started
        if exit_code != 0:
            write(_result_line(check.label, elapsed, "FAIL"))
            command_text = subprocess.list2cmdline(check.command)
            write(f"Command exited with status {exit_code}: {command_text}")
            write(_result_line("Total", clock() - total_started, "FAIL"))
            return exit_code if exit_code > 0 else 1

        write(_result_line(check.label, elapsed, "PASS"))

    write(_result_line("Total", clock() - total_started, "PASS"))
    return 0


def main() -> int:
    return run_checks(build_checks())


if __name__ == "__main__":
    raise SystemExit(main())
