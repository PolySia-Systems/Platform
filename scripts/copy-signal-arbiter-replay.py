from __future__ import annotations

import argparse
import json
from pathlib import Path

from polysia.backtesting.copy_signal_arbiter_replay import (
    CopySignalArbiterReplay,
    load_copy_signal_replay_jsonl,
    write_copy_signal_replay_result,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the sanitized, walk-forward Copy Signal Arbiter comparison."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    dataset = load_copy_signal_replay_jsonl(arguments.input)
    result = CopySignalArbiterReplay().run(dataset)
    write_copy_signal_replay_result(result, arguments.output)
    print(
        json.dumps(
            {
                "conclusion": result.conclusion,
                "output": str(arguments.output),
                "status": "ok",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
