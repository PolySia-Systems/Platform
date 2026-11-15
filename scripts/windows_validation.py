"""Run native Windows cases once, with conservative full-suite fallback."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.classify_ci_changes import classify_paths, validate_projection  # noqa: E402

# Only proven transport seams use a narrower Windows suite initially. Storage,
# identity, packaging and unclassified native changes retain full coverage.
TRANSPORT_CASES = (
    "tests/unit/adapters/test_native_health_transport.py",
    "tests/integration/test_native_drain_transport.py",
    "tests/integration/test_native_platform_lifecycle.py",
    "tests/integration/test_operational_session.py",
)
FOCUSED_INPUTS = {
    "src/polysia/adapters/polymarket/bounded_transport.py": TRANSPORT_CASES,
    **{path: TRANSPORT_CASES for path in TRANSPORT_CASES},
}


def selected_tests(policy: object) -> tuple[str, ...]:
    value = validate_projection(policy)
    flags = value["flags"]
    if not flags["windows"]:
        raise ValueError("Windows was not selected by the verified policy")
    if flags["comprehensive"] or flags["dependencies"]:
        return ()
    selected: set[str] = set()
    for path in value["paths"]:
        if not classify_paths((path,)).windows:
            continue
        if path not in FOCUSED_INPUTS:
            return ()
        selected.update(FOCUSED_INPUTS[path])
    # Event-only requests and an unavailable mapping require full validation.
    return tuple(sorted(selected))


def main() -> int:
    tests = selected_tests(json.loads(os.environ["CI_POLICY"]))
    print("Windows scope: " + (", ".join(tests) if tests else "full suite"), flush=True)
    Path("artifacts").mkdir(exist_ok=True)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-x", "--tb=short", "--durations=25",
         "--junitxml=artifacts/windows-pytest.xml", *tests],
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
