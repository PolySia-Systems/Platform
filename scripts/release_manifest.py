"""Bind a tested image archive to its immutable source identity."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def manifest(image: Path, *, image_id: str, commit: str) -> dict[str, object]:
    if re.fullmatch(r"[a-f0-9]{40}", commit) is None:
        raise ValueError("release requires exact source commit")
    if re.fullmatch(r"sha256:[a-f0-9]{64}", image_id) is None:
        raise ValueError("release requires exact image ID")
    with image.open("rb") as stream:
        archive_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "schema_version": "platform-release/v1", "commit": commit,
        "image_id": image_id, "archive_sha256": archive_digest,
        "archive_name": image.name,
        "python": ">=3.14,<3.15", "financial_schema": 9,
        "defaults": {"TRADING_MODE": "DATA_ONLY", "LIVE_TRADING_ENABLED": False},
        "standards_release": "v0.5.2",
        "standards_commit": "2ccbe4dbbcb3574db52e5a8eb73e968a9165a83c",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--image-id-file", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = manifest(args.image, image_id=args.image_id_file.read_text().strip(),
                      commit=args.commit)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
