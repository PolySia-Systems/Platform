from __future__ import annotations

import copy

import pytest

from scripts.classify_ci_changes import project_policy
from scripts.windows_validation import TRANSPORT_CASES, selected_tests


def test_transport_changes_retain_native_and_composed_session_cases() -> None:
    policy = project_policy(["src/polysia/adapters/polymarket/bounded_transport.py"])
    assert set(selected_tests(policy)) == set(TRANSPORT_CASES)
    assert len(selected_tests(policy)) == len(set(selected_tests(policy)))


@pytest.mark.parametrize("path", [
    "src/polysia/storage/atomic_files.py",
    "src/polysia/control/local_identity.py",
    "pyproject.toml",
    "src/polysia/deployment/session_supervision.py",
])
def test_broad_or_unmapped_native_changes_keep_full_suite(path: str) -> None:
    assert selected_tests(project_policy([path])) == ()


def test_mixed_change_cannot_narrow_other_native_work() -> None:
    assert selected_tests(project_policy([
        "src/polysia/adapters/polymarket/bounded_transport.py",
        "src/polysia/storage/atomic_files.py",
    ])) == ()
    assert set(selected_tests(project_policy([
        "README.md", "tests/integration/test_operational_session.py",
    ]))) == set(TRANSPORT_CASES)


def test_scheduled_and_manual_full_remain_full() -> None:
    assert selected_tests(project_policy(["README.md"], event="schedule")) == ()
    assert selected_tests(project_policy(
        ["README.md"], event="workflow_dispatch", validation_scope="full",
    )) == ()


def test_invalid_policy_or_unselected_windows_cannot_run() -> None:
    policy = project_policy(["src/polysia/adapters/polymarket/bounded_transport.py"])
    broken = copy.deepcopy(policy)
    broken["flags"]["windows"] = False
    with pytest.raises(ValueError):
        selected_tests(broken)
    with pytest.raises(ValueError, match="not selected"):
        selected_tests(project_policy(["README.md"]))
