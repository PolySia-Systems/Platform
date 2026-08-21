from __future__ import annotations

import itertools
import sys
from pathlib import Path

from scripts.fast_check import Check, build_checks, run_checks


def test_build_checks_selects_commands_in_required_order() -> None:
    checks = build_checks()

    assert [check.label for check in checks] == [
        "Diff (working)",
        "Diff (staged)",
        "Diff (origin/main)",
        "Standards",
        "Secret Scan",
        "Compile",
        "Ruff",
        "Mypy",
        "Pip Check",
    ]
    assert checks[2].command == ("git", "diff", "--check", "origin/main...HEAD")
    assert all(check.command[0] == sys.executable for check in checks[3:])


def test_run_checks_executes_every_available_check_successfully(tmp_path: Path) -> None:
    commands: list[tuple[str, ...]] = []
    messages: list[str] = []
    timer = itertools.count(step=0.1)

    def runner(command: tuple[str, ...], repository: Path) -> int:
        assert repository == tmp_path
        commands.append(command)
        return 0

    result = run_checks(
        build_checks("python-test"),
        repository=tmp_path,
        runner=runner,
        reference_checker=lambda _reference, _repository: True,
        clock=lambda: next(timer),
        write=messages.append,
    )

    assert result == 0
    assert len(commands) == 9
    assert messages[-1].endswith("PASS")


def test_run_checks_propagates_failure_and_stops_immediately(tmp_path: Path) -> None:
    commands: list[tuple[str, ...]] = []
    messages: list[str] = []
    checks = (
        Check("First", ("first-command",)),
        Check("Second", ("second-command",)),
    )

    def runner(command: tuple[str, ...], _repository: Path) -> int:
        commands.append(command)
        return 7

    result = run_checks(
        checks,
        repository=tmp_path,
        runner=runner,
        clock=lambda: 1.0,
        write=messages.append,
    )

    assert result == 7
    assert commands == [("first-command",)]
    assert any(line.endswith("FAIL") for line in messages)
    assert "status 7" in "\n".join(messages)


def test_missing_origin_main_skips_only_committed_branch_diff(tmp_path: Path) -> None:
    commands: list[tuple[str, ...]] = []
    messages: list[str] = []

    result = run_checks(
        build_checks("python-test"),
        repository=tmp_path,
        runner=lambda command, _repository: commands.append(command) or 0,
        reference_checker=lambda _reference, _repository: False,
        clock=lambda: 1.0,
        write=messages.append,
    )

    assert result == 0
    assert ("git", "diff", "--check", "origin/main...HEAD") not in commands
    assert len(commands) == 8
    assert any("Diff (origin/main)" in line and line.endswith("SKIP") for line in messages)
    assert "no fetch was attempted" in "\n".join(messages)


def test_timing_output_reports_check_and_total_duration(tmp_path: Path) -> None:
    times = iter((10.0, 11.0, 12.3, 14.0))
    messages: list[str] = []

    result = run_checks(
        (Check("Example", ("example",)),),
        repository=tmp_path,
        runner=lambda _command, _repository: 0,
        clock=lambda: next(times),
        write=messages.append,
    )

    assert result == 0
    assert messages == [
        "Example                   1.3s  PASS",
        "Total                     4.0s  PASS",
    ]
