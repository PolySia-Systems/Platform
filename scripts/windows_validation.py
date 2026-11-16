"""Run the full native suite only after verified manual opt-in."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.classify_ci_changes import validate_projection  # noqa: E402


def selected_tests(policy: object) -> tuple[str, ...]:
    value = validate_projection(policy)
    if not value["flags"]["windows"]:
        raise ValueError("Windows was not selected by the verified policy")
    return ()  # Deliberate opt-in always means the full native suite.


def main() -> int:
    selected_tests(json.loads(os.environ["CI_POLICY"]))
    print("Windows scope: full suite (explicit manual opt-in)", flush=True)
    Path("artifacts").mkdir(exist_ok=True)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-x", "--tb=short", "--durations=25",
         "--junitxml=artifacts/windows-pytest.xml"],
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
