from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from polysia.backtesting.copy_signal_arbiter_replay import (
    convert_tiny_live_events_to_unknown_replay,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Convert sanitized Tiny Live OPEN events into a fail-closed Replay input."
        )
    )
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    dataset = convert_tiny_live_events_to_unknown_replay(
        arguments.events,
        arguments.output,
        generated_at=datetime.now(UTC),
    )
    print(
        json.dumps(
            {
                "output": str(arguments.output),
                "record_count": len(dataset.records),
                "status": "ok",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
