from __future__ import annotations

import argparse
import json
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
                    f"Local reference {check.required_ref} is unavailable; no fetch was attempted."
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
    parser = argparse.ArgumentParser(
        description="Local validation; native CI owns OS/artifact proof."
    )
    parser.add_argument("--mode", choices=("scoped", "full-local"))
    parser.add_argument("--base", default="origin/main")
    parser.add_argument(
        "--plan", action="store_true", help="Print policy without executing checks."
    )
    arguments = parser.parse_args()
    if arguments.mode is None:
        write_line("Legacy fast check: omits pytest/build; not comprehensive validation.")
        return run_checks(build_checks())
    sys.path.insert(0, str(REPOSITORY_ROOT))
    from scripts.classify_ci_changes import actual_diff

    policy = actual_diff(
        REPOSITORY_ROOT,
        base=arguments.base,
        local=True,
        event="local",
        validation_scope="full" if arguments.mode == "full-local" else "auto",
    )
    if arguments.plan:
        print(json.dumps(policy, indent=2, sort_keys=True))
        return 0
    checks, pending = scoped_checks(policy)
    write_line(f"Policy {policy['policy']} / source {policy['source']}")
    for message in policy["diagnostics"]:
        write_line(f"Conservative fallback: {message}")
    for check_id in pending:
        write_line(f"PENDING {check_id}: requires native CI execution context")
    result = run_checks(checks)
    if result == 0 and pending:
        write_line("Local checks passed; native contexts remain PENDING (exit 2).")
        return 2
    return result


def scoped_checks(policy: dict, python_executable: str | None = None) -> tuple:
    sys.path.insert(0, str(REPOSITORY_ROOT))
    from scripts.classify_ci_changes import validate_projection

    validate_projection(policy)
    checks, pending = [], []
    for item in policy["checks"]:
        if not item["required"]:
            continue
        context = item["context"]
        if context != "portable" and not (context == "linux" and sys.platform == "linux"):
            pending.append(item["id"])
            continue
        command = tuple(
            python_executable or sys.executable if part == "python" else part
            for part in item["command"]
        )
        if item["id"] == "hygiene" and policy["source"]["base"]:
            command += ("--base", policy["source"]["base"])
        if item["id"] == "sbom":
            (REPOSITORY_ROOT / "artifacts").mkdir(exist_ok=True)
        checks.append(Check(item["id"], command))
    return tuple(checks), tuple(pending)


if __name__ == "__main__":
    raise SystemExit(main())
