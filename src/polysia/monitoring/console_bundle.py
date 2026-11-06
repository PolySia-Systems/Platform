"""Verify shipped static custody, optionally against source. Standard library only."""

from __future__ import annotations

import hashlib
import json
import re
import struct
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from typing import Any

MEDIA_TYPES = {
    ".css": "text/css",
    ".js": "text/javascript",
    ".txt": "text/plain",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
}


def validate_media(name: str, data: bytes) -> None:
    """Bounded admission profile for selected static artwork, never an upload sanitizer."""
    suffix = Path(name).suffix
    if suffix == ".png":
        if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
            raise ValueError("invalid_console_png")
        offset, compressed = 8, bytearray()
        ended = False
        while offset + 12 <= len(data):
            length = struct.unpack(">I", data[offset : offset + 4])[0]
            kind = data[offset + 4 : offset + 8]
            end = offset + 12 + length
            if end > len(data):
                raise ValueError("truncated_console_png")
            chunk = data[offset + 8 : offset + 8 + length]
            crc = struct.unpack(">I", data[offset + 8 + length : end])[0]
            if zlib.crc32(kind + chunk) != crc:
                raise ValueError("invalid_console_png_crc")
            if kind == b"IDAT":
                compressed.extend(chunk)
            if kind == b"IEND":
                ended = end == len(data)
                break
            offset = end
        if not ended or not compressed:
            raise ValueError("incomplete_console_png")
        width, height = struct.unpack(">II", data[16:24])
        if not 1 <= width <= 2048 or not 1 <= height <= 2048:
            raise ValueError("invalid_console_image_dimensions")
        try:
            decoder = zlib.decompressobj()
            decoder.decompress(compressed, 32_000_001)
            if not decoder.eof or decoder.unconsumed_tail:
                raise ValueError("oversized_console_png")
        except zlib.error as error:
            raise ValueError("invalid_console_png_data") from error
    elif suffix == ".woff2":
        if len(data) < 48 or data[:4] != b"wOF2" or struct.unpack(">I", data[8:12])[0] != len(data):
            raise ValueError("invalid_console_font")
    elif suffix == ".svg":
        if len(data) > 64_000 or b"<!" in data:
            raise ValueError("invalid_console_svg")
        try:
            document = ET.fromstring(data)
        except ET.ParseError as error:
            raise ValueError("invalid_console_svg") from error
        allowed = {"svg", "title", "desc", "path", "g"}
        attributes = {
            "width",
            "height",
            "viewBox",
            "role",
            "aria-label",
            "d",
            "fill",
            "fill-rule",
            "clip-rule",
            "transform",
        }
        if document.tag != "{http://www.w3.org/2000/svg}svg" or not document.get("viewBox"):
            raise ValueError("invalid_console_svg")
        for element in document.iter():
            if element.tag.removeprefix("{http://www.w3.org/2000/svg}") not in allowed:
                raise ValueError("active_console_svg")
            if any(
                key not in attributes or "url(" in value.lower()
                for key, value in element.attrib.items()
            ):
                raise ValueError("active_console_svg")


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
            re.fullmatch(r"[A-Za-z0-9_-]+\.(js|css|png|svg|woff2)", name) is None
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
        validate_media(name, asset.read_bytes())
    actual = {p.name for p in directory.iterdir() if p.is_file() and p.name != "manifest.json"}
    if set(files) != actual or any(p.is_dir() for p in directory.iterdir()):
        raise ValueError("unlisted_console_asset")
    document = (directory / "index.html").read_text(encoding="utf-8")
    if f'name="bundle-source" content="{manifest["source"]}"' not in document:
        raise ValueError("console_release_identity_differs")
    if source_root is not None and manifest["source"] != source_digest(source_root):
        raise ValueError("stale_console_source_build")
    return manifest
