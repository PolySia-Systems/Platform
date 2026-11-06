"""Reject active or malformed media without broadening static custody."""

from pathlib import Path

import pytest

from polysia.monitoring.console_bundle import validate_media


@pytest.mark.parametrize(
    "payload",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><script/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1" onload="x"/>',
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><image href="https://x"/></svg>',
        b"<!DOCTYPE svg><svg/>",
        b"not an svg",
    ],
)
def test_active_svg_is_rejected(payload):
    with pytest.raises(ValueError):
        validate_media("brand.svg", payload)


@pytest.mark.parametrize("name,payload", [("brand.png", b"invalid"), ("font.woff2", b"wOF2")])
def test_malformed_binary_is_rejected(name, payload):
    with pytest.raises(ValueError):
        validate_media(name, payload)


def test_selected_media_are_accepted_and_png_crc_is_checked():
    assets = Path("frontend/src/assets")
    for path in assets.rglob("*"):
        if path.is_file() and path.suffix in {".png", ".svg", ".woff2"}:
            validate_media(path.name, path.read_bytes())
    data = bytearray((assets / "brand/primary.png").read_bytes())
    data[-1] ^= 1
    with pytest.raises(ValueError):
        validate_media("brand.png", bytes(data))
