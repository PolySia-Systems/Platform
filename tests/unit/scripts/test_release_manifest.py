from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.release_manifest import manifest


def test_manifest_binds_exact_archive_and_source(tmp_path: Path) -> None:
    image = tmp_path / "image.tar.gz"
    image.write_bytes(b"tested archive")
    result = manifest(image, image_id="sha256:" + "b" * 64, commit="a" * 40)
    assert result["archive_sha256"] == hashlib.sha256(b"tested archive").hexdigest()
    assert result["commit"] == "a" * 40
    assert result["defaults"] == {"TRADING_MODE": "DATA_ONLY", "LIVE_TRADING_ENABLED": False}
    with pytest.raises(ValueError, match="exact source"):
        manifest(image, image_id="sha256:" + "b" * 64, commit="main")
