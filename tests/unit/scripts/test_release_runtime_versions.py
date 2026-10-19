from __future__ import annotations

import json

import pytest

from scripts.release_manifest import manifest


@pytest.mark.parametrize("mismatch", [None, "sdk", "python"])
def test_release_binds_observed_image_versions_to_the_reviewed_stack(tmp_path, mismatch):
    observed = {
        "python": "3.14.8",
        "packages": {
            "polymarket-client": "0.13.0",
            "pydantic": "2.14.1",
            "pydantic-core": "2.50.1",
            "pydantic-settings": "2.15.0",
            "websockets": "15.0.1",
        },
    }
    if mismatch == "sdk":
        observed["packages"]["polymarket-client"] = "0.7.1"
    if mismatch == "python":
        observed["python"] = "3.14.7"
    versions = tmp_path / "runtime.json"
    versions.write_text(json.dumps(observed))
    image = tmp_path / "image.tar.gz"
    image.write_bytes(b"fixture archive bytes")
    args = {"image_id": "sha256:" + "a" * 64, "commit": "b" * 40, "runtime_packages": versions}
    if mismatch:
        with pytest.raises(ValueError, match="built image Python/dependencies differ"):
            manifest(image, **args)
    else:
        assert manifest(image, **args)["runtime_packages"] == observed["packages"]
