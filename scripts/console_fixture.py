"""Shared producer/gateway fixture for Python, generated TypeScript and browser proof."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from polysia.monitoring.console import ConsoleApplication  # noqa: E402
from polysia.storage.console_commands import ConsoleCommandStore  # noqa: E402
from tests.fixtures.console_h1 import write_publication  # noqa: E402


def generate() -> str:
    with tempfile.TemporaryDirectory(prefix="polysia-console-producer-") as directory:
        root = Path(directory)
        now = datetime(2026, 10, 26, tzinfo=UTC)
        write_publication(root, now=now)
        commands = ConsoleCommandStore(root / "commands.sqlite3")
        commands.initialize()
        app = ConsoleApplication(
            root / "publication.json",
            origin="https://fixture.example.com",
            verify=lambda _: ("fixture-reader", "reader"),
            commands=commands,
            csrf_secret=b"fixture-only-no-real-account-key-00",
        )
        return (
            json.dumps(
                app._gateway.snapshot("fixture-reader", "reader", now).model_dump(),
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = ROOT / "frontend/tests/producer.json"
    expected = generate()
    if args.check:
        if target.read_text(encoding="utf-8") != expected:
            raise SystemExit("Shared Console producer fixture is stale")
    else:
        target.write_text(expected, encoding="utf-8", newline="\n")
