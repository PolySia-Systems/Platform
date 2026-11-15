from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy.platform_bootstrap import container_command, service_text, verify_artifact
from scripts.release_manifest import manifest


def image_archive(tmp_path, *, nested=0, corruption=None, legacy=False, attestation=False):
    import hashlib
    import io
    import tarfile

    config = b'{"architecture":"amd64","os":"linux"}'
    config_id = "sha256:" + hashlib.sha256(config).hexdigest()
    config_name = (config_id[7:] + ".json" if legacy else "blobs/sha256/" + config_id[7:])
    files = {config_name: config}
    docker = [{"Config": config_name, "RepoTags": ["polysia:ci"], "Layers": []}]
    files["manifest.json"] = json.dumps(docker).encode()

    def descriptor(value, kind):
        raw = json.dumps(value).encode()
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        files["blobs/sha256/" + digest[7:]] = raw
        return {"digest": digest, "size": len(raw), "mediaType": kind}

    leaf = descriptor({"schemaVersion": 2, "config": {
        "digest": config_id if corruption != "config-binding" else "sha256:" + "b" * 64,
    }}, "application/vnd.oci.image.manifest.v1+json")
    current = leaf
    if attestation:
        att = descriptor({"schemaVersion": 2, "config": {"digest": "sha256:" + "d" * 64}},
                         "application/vnd.oci.image.manifest.v1+json")
        att["platform"] = {"os": "unknown", "architecture": "unknown"}
        att["annotations"] = {
            "vnd.docker.reference.type": "attestation-manifest",
            "vnd.docker.reference.digest": leaf["digest"],
        }
        if corruption == "attestation-reference":
            att["annotations"]["vnd.docker.reference.digest"] = "sha256:" + "e" * 64
        if corruption == "attestation-platform":
            att["platform"]["os"] = "linux"
        if corruption == "attestation-bytes":
            files["blobs/sha256/" + att["digest"][7:]] = b" " * att["size"]
        current = descriptor({"schemaVersion": 2, "manifests": [leaf, att]},
                             "application/vnd.oci.image.index.v1+json")
    for _ in range(nested):
        current = descriptor({"schemaVersion": 2, "manifests": [current]},
                             "application/vnd.oci.image.index.v1+json")
    if not legacy:
        if corruption == "descriptor-size":
            current["size"] += 1
        if corruption == "blob-digest":
            files["blobs/sha256/" + current["digest"][7:]] = b" " * current["size"]
        index = {"schemaVersion": 2, "manifests": [current]}
        if corruption == "multiple":
            index["manifests"].append(current)
        files["index.json"] = json.dumps(index).encode()
    if corruption == "config-digest":
        files[config_name] = b"modified config"
    with tarfile.open(tmp_path / "polysia-image.tar.gz", "w:gz") as archive:
        for name, raw in files.items():
            item = tarfile.TarInfo(name)
            item.size = len(raw)
            archive.addfile(item, io.BytesIO(raw))
        if corruption == "duplicate":
            item = tarfile.TarInfo(config_name)
            item.size = len(config)
            archive.addfile(item, io.BytesIO(config))
    return config_id, current["digest"], leaf["digest"]


@pytest.mark.parametrize("nested", [0, 1, 3])
def test_archive_binds_config_and_nested_oci_identities(tmp_path, nested):
    from deploy.platform_bootstrap import archive_image_ids

    config, outer, leaf = image_archive(tmp_path, nested=nested)
    for identity in (config, outer, leaf):
        ids = archive_image_ids(tmp_path, {"image_id": identity})
        assert config in ids and outer in ids and leaf in ids


def test_legacy_docker_archive_remains_config_bound(tmp_path):
    from deploy.platform_bootstrap import archive_image_ids

    config, *_ = image_archive(tmp_path, legacy=True)
    assert archive_image_ids(tmp_path, {"image_id": config}) == (config,)


def test_archive_accepts_bound_non_runnable_buildkit_attestation(tmp_path):
    import tarfile

    from deploy.platform_bootstrap import archive_image_ids

    config, outer, leaf = image_archive(tmp_path, attestation=True)
    ids = archive_image_ids(tmp_path, {"image_id": outer})
    assert ids == (config, outer, leaf)
    with tarfile.open(tmp_path / "polysia-image.tar.gz", "r:gz") as archive:
        nested = json.load(archive.extractfile("blobs/sha256/" + outer[7:]))
        attestation_id = nested["manifests"][1]["digest"]
    with pytest.raises(ValueError, match="not bound"):
        archive_image_ids(tmp_path, {"image_id": attestation_id})


@pytest.mark.parametrize("case", [
    "attestation-reference", "attestation-platform", "attestation-bytes",
])
def test_attestations_cannot_weaken_single_image_binding(tmp_path, case):
    from deploy.platform_bootstrap import archive_image_ids

    _, outer, _ = image_archive(tmp_path, corruption=case, attestation=True)
    with pytest.raises(ValueError):
        archive_image_ids(tmp_path, {"image_id": outer})


@pytest.mark.parametrize("case, reason", [
    ("config-binding", "config identities differ"),
    ("config-digest", "config digest mismatch"),
    ("descriptor-size", "size or digest mismatch"),
    ("blob-digest", "size or digest mismatch"),
    ("multiple", "one platform descriptor"),
    ("duplicate", "duplicate image metadata"),
])
def test_archive_rejects_inconsistent_or_ambiguous_identity(tmp_path, case, reason):
    from deploy.platform_bootstrap import archive_image_ids

    config, *_ = image_archive(tmp_path, nested=1, corruption=case)
    with pytest.raises(ValueError, match=reason):
        archive_image_ids(tmp_path, {"image_id": config})


def test_archive_refuses_excessive_nesting_and_unbound_runner_identity(tmp_path):
    from deploy.platform_bootstrap import archive_image_ids

    config, *_ = image_archive(tmp_path, nested=8)
    with pytest.raises(ValueError, match="nesting limit"):
        archive_image_ids(tmp_path, {"image_id": config})
    image_archive(tmp_path, nested=1)
    with pytest.raises(ValueError, match="not bound"):
        archive_image_ids(tmp_path, {"image_id": "sha256:" + "c" * 64})


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


def test_backup_child_diagnostic_is_allowlisted_and_redacted() -> None:
    from subprocess import CalledProcessError

    from deploy.platform_backup import JobFailure

    prefix = {"contract": "platform-recovery-diagnostic/v1", "error_code": "INVALID_EVIDENCE"}
    accepted = JobFailure("snapshot", CalledProcessError(
        1, ["secret-command"], stderr=json.dumps({**prefix, "stage": "encryption"}),
    ))
    assert (accepted.stage, accepted.error_code, accepted.exit_status) == (
        "encryption", "INVALID_EVIDENCE", 1,
    )
    rejected = JobFailure("snapshot", CalledProcessError(
        1, ["secret-command"], stderr=json.dumps({**prefix, "stage": "secret-data"}),
    ))
    assert str(rejected) == "snapshot:PROCESS_FAILED"


def test_standalone_backup_loads_its_own_release_helper(tmp_path, monkeypatch):
    from runpy import run_path

    for name in ("platform_bootstrap.py", "platform_backup.py"):
        (tmp_path / name).write_bytes((Path("deploy") / name).read_bytes())
    monkeypatch.chdir(tmp_path)
    job = run_path(str(tmp_path / "platform_backup.py"))
    assert job["campaign_mounts"]({}) == []
    assert job["_campaign_mounts"].__globals__["__file__"] == str(
        tmp_path / "platform_bootstrap.py",
    )


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


@pytest.mark.parametrize("role", ["worker", "publisher"])
def test_campaign_plan_reaches_scheduled_processes_as_read_only(tmp_path, monkeypatch, role):
    from deploy import platform_bootstrap as core

    monkeypatch.setattr(core, "CONFIG_ROOT", tmp_path)
    worker = tmp_path / "worker.json"
    worker.write_text(json.dumps({"campaign": "/config/nonlive-campaign.json"}))
    plan = tmp_path / "nonlive-campaign.json"
    plan.write_text('{"contract":"nonlive-campaign/v1"}')
    image = "sha256:" + "a" * 64
    args = core.container_command(image, role=role, hostname="host")
    assert f"{plan}:/config/nonlive-campaign.json:ro" in args
    assert f"{tmp_path}:/config:ro" not in args
    assert f"{plan}:/config/nonlive-campaign.json:ro" not in core.container_command(
        image, role="web", hostname="host",
    )
    plan.unlink()
    with pytest.raises(ValueError, match="missing"):
        core.container_command(image, role=role, hostname="host")


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
