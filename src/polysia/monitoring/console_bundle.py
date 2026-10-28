"""Verify shipped static custody, optionally against source. Standard library only."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

API = "console/v1"
RELEASE = "0.4.0"


def source_digest(root: Path) -> str:
    frontend = root / "frontend"
    paths = [
        *frontend.joinpath("src").rglob("*"),
        *frontend.joinpath("tests").rglob("*"),
        *frontend.joinpath("licenses").rglob("*"),
    ]
    paths += [
        frontend / name
        for name in (
            "package.json",
            "package-lock.json",
            "tsconfig.json",
            "vite.config.mjs",
            "build.mjs",
            ".npmrc",
            ".node-version",
        )
    ]
    paths.append(root / "src/polysia/monitoring/console_contract.py")
    hasher = hashlib.sha256()
    for path in sorted(
        (p for p in paths if p.is_file()), key=lambda p: p.relative_to(root).as_posix()
    ):
        hasher.update(path.relative_to(root).as_posix().encode())
        hasher.update(hashlib.sha256(path.read_bytes()).digest())
    return hasher.hexdigest()


def verify_bundle(
    directory: Path | None = None, *, source_root: Path | None = None
) -> dict[str, Any]:
    directory = directory or Path(__file__).with_name("human_console_assets")
    if directory.is_symlink() or any(p.is_symlink() for p in directory.iterdir()):
        raise ValueError("console_asset_symlink")
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink() or manifest_path.stat().st_size > 32_768:
        raise ValueError("invalid_console_manifest")
    manifest = json.loads(manifest_path.read_bytes())
    if (
        set(manifest) != {"version", "api", "release", "source", "files"}
        or manifest["version"] != 1
        or manifest["api"] != API
        or manifest["release"] != RELEASE
        or re.fullmatch(r"[a-f0-9]{64}", manifest["source"]) is None
    ):
        raise ValueError("incompatible_console_bundle")
    files = manifest["files"]
    if not isinstance(files, dict) or not 3 <= len(files) <= 16 or "index.html" not in files:
        raise ValueError("invalid_console_asset_inventory")
    for name, expected in files.items():
        if (
            re.fullmatch(r"[A-Za-z0-9_-]+\.(js|css)", name) is None
            and name not in {"index.html", "notices.txt"}
            or not isinstance(expected, str)
            or re.fullmatch(r"[a-f0-9]{64}", expected) is None
        ):
            raise ValueError("invalid_console_asset_path")
        asset = directory / name
        if (
            asset.is_symlink()
            or not asset.is_file()
            or asset.stat().st_size > 2_000_000
            or hashlib.sha256(asset.read_bytes()).hexdigest() != expected
        ):
            raise ValueError("console_asset_missing_or_changed")
    actual = {p.name for p in directory.iterdir() if p.is_file() and p.name != "manifest.json"}
    if set(files) != actual or any(p.is_dir() for p in directory.iterdir()):
        raise ValueError("unlisted_console_asset")
    document = (directory / "index.html").read_text(encoding="utf-8")
    if f'name="bundle-source" content="{manifest["source"]}"' not in document:
        raise ValueError("console_release_identity_differs")
    if source_root is not None and manifest["source"] != source_digest(source_root):
        raise ValueError("stale_console_source_build")
    return manifest
