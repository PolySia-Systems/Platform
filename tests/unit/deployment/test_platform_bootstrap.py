from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy.platform_bootstrap import container_command, service_text, verify_artifact
from scripts.release_manifest import manifest


def test_backup_mounts_campaign_without_exposing_other_configuration(tmp_path, monkeypatch):
    from deploy import platform_backup as backup

    monkeypatch.setattr(backup, "CONFIG_ROOT", tmp_path)
    plan = tmp_path / "nonlive-campaign.json"
    plan.write_text('{"contract":"nonlive-campaign/v1"}')
    assert backup.campaign_mounts({}) == []
    assert backup.campaign_mounts({"campaign": "/config/nonlive-campaign.json"}) == [
        "--volume", f"{plan}:/config/nonlive-campaign.json:ro",
    ]
    for path in ("/etc/shadow", "/config/../worker.json", "/config", "/config/missing.json", 1):
        with pytest.raises(ValueError):
            backup.campaign_mounts({"campaign": path})
    plan.write_bytes(b"x" * 16_385)
    with pytest.raises(ValueError, match="bound"):
        backup.campaign_mounts({"campaign": "/config/nonlive-campaign.json"})


def test_backup_disk_pressure_refuses_before_snapshot_without_using_host_disk(
    tmp_path,
    monkeypatch,
):
    from deploy import platform_backup as backup

    monkeypatch.setattr(backup, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(backup.os, "chown", lambda *args: None, raising=False)
    monkeypatch.setattr(
        backup.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(free=8_589_934_592 + backup.MAX_GENERATION),
    )

    def never_run(*args, **kwargs):
        raise AssertionError("disk-pressure refusal must precede snapshot, crypto or transport")

    monkeypatch.setattr(backup, "run", never_run)
    with pytest.raises(OSError, match="free-disk reserve"):
        backup._backup_generation({"mode": "local", "output": str(tmp_path / "backup-out")})


def test_verified_artifact_rejects_changed_archive_or_moving_ref(tmp_path: Path) -> None:
    image = tmp_path / "polysia-image.tar.gz"
    image.write_bytes(b"hosted artifact")
    identity = manifest(image, image_id="sha256:" + "b" * 64, commit="a" * 40)
    for name in ("platform_bootstrap.py", "platform_backup.py", "platform_admin.py"):
        (tmp_path / name).write_bytes((Path("deploy") / name).read_bytes())
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


@pytest.mark.parametrize("case", ["traversal", "symlink", "duplicate", "oversize"])
def test_recovery_rejects_unsafe_archive_before_extracting_outside_root(
    tmp_path: Path, case: str
) -> None:
    import io
    import tarfile

    from polysia.deployment.platform_recovery import MAX_BUNDLE_BYTES, extract_and_verify_recovery

    archive = tmp_path / "untrusted.tar"
    if case == "oversize":
        member = tarfile.TarInfo("large")
        member.size = MAX_BUNDLE_BYTES + 1
        archive.write_bytes(member.tobuf() + b"\0" * 1024)
    else:
        with tarfile.open(archive, "w") as tar:
            member = tarfile.TarInfo("../escape" if case == "traversal" else "entry")
            if case == "symlink":
                member.type = tarfile.SYMTYPE
                member.linkname = "../escape"
            else:
                member.size = 1
            tar.addfile(member, io.BytesIO(b"x") if member.isfile() else None)
            if case == "duplicate":
                tar.addfile(member, io.BytesIO(b"x"))
    trusted = tmp_path / "trusted.json"
    trusted.write_text("{}")
    with pytest.raises(ValueError, match="unsafe or duplicate|extraction limit"):
        extract_and_verify_recovery(
            archive, tmp_path / "isolated", trusted_release_manifest=trusted
        )
    assert not (tmp_path / "escape").exists()
