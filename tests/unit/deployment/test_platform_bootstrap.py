from __future__ import annotations

import json
from pathlib import Path

import pytest

from deploy.platform_bootstrap import container_command, service_text, verify_artifact
from scripts.release_manifest import manifest


def test_verified_artifact_rejects_changed_archive_or_moving_ref(tmp_path: Path) -> None:
    image = tmp_path / "polysia-image.tar.gz"
    image.write_bytes(b"hosted artifact")
    identity = manifest(image, image_id="sha256:" + "b" * 64, commit="a" * 40)
    (tmp_path / "manifest.json").write_text(json.dumps(identity))
    assert verify_artifact(tmp_path, commit="a" * 40)["image_id"] == "sha256:" + "b" * 64
    with pytest.raises(ValueError, match="exact source"):
        verify_artifact(tmp_path, commit="main")
    image.write_bytes(b"modified artifact")
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_artifact(tmp_path, commit="a" * 40)


def test_process_mounts_enforce_web_and_publisher_boundaries() -> None:
    image = "sha256:" + "a" * 64
    web = container_command(image, role="web", hostname="host")
    worker = container_command(image, role="worker", hostname="host")
    publisher = container_command(image, role="publisher", hostname="host")
    assert not any("/state" in argument or "docker.sock" in argument for argument in web)
    assert "/var/lib/polysia-platform/publication:/publication:ro" in web
    assert "/var/lib/polysia-platform/worker:/state:rw" in publisher
    assert publisher[publisher.index("--network") + 1] == "none"
    assert "/var/lib/polysia-platform/worker:/state:rw" in worker
    assert "Restart=on-failure" in service_text(image, role="web", hostname="host")
    with pytest.raises(ValueError, match="unsafe systemd"):
        service_text(image, role="worker", hostname="bad host")


def test_backup_job_isolated_mounts_and_immutable_image() -> None:
    from deploy.platform_backup import checked_root, isolated

    args = isolated("sha256:" + "a" * 64, "/private:/run/recovery-key:ro", user="0:0")
    assert args[args.index("--network") + 1] == "none"
    assert "--read-only" in args
    assert "/private:/run/recovery-key:ro" in args
    with pytest.raises(ValueError, match="immutable"):
        isolated("polysia:latest")
    with pytest.raises(ValueError, match="dedicated allocation"):
        checked_root("/var/lib/../", "/srv/polysia-platform-backups")
