from __future__ import annotations

import json
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from polysia.cli_commands.platform_worker import platform_stop, worker_tick
from polysia.domain.research_evidence.acquisition_policy import AcquisitionPolicy
from polysia.storage.acquisition_authority import AcquisitionAuthority
from polysia.storage.console_commands import ConsoleCommandStore


def test_stop_is_applied_even_with_missing_cohort_and_without_acquisition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    policy = AcquisitionPolicy(
        "worker-test", socket.gethostname(), now - timedelta(minutes=1),
        now + timedelta(hours=1), ("https://data-api.polymarket.com/v2/trades",),
        10, 10_240, 1024, 10, 4096, 1, 60, 30, 2, 100_000_000, 25,
    )
    manifest = tmp_path / "policy.json"
    manifest.write_text(json.dumps(policy.to_dict()))
    authority_path = tmp_path / "authority.sqlite3"
    authority = AcquisitionAuthority(authority_path, policy)
    authority.initialize()
    commands_path = tmp_path / "commands.sqlite3"
    commands = ConsoleCommandStore(commands_path)
    commands.initialize()
    commands.submit(subject="owner", action="stop", expected_revision=0,
                    idempotency_key="stop-before-any-data")
    config = tmp_path / "worker.json"
    config.write_text(json.dumps({
        "database": str(tmp_path / "financial.sqlite3"), "release_commit": "a" * 40,
        "manifest": str(manifest), "authority": str(authority_path),
        "commands": str(commands_path), "status": str(tmp_path / "status.json"),
        "cohort": str(tmp_path / "missing.json"), "acquisition_enabled": False,
    }))
    original = Path.read_text

    def read(path: Path, *args: object, **kwargs: object) -> str:
        if path.as_posix() == "/opt/polysia/BUILD_COMMIT":
            return "a" * 40
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    result = worker_tick(config)
    assert result["status"] == "STOPPED"
    assert authority.status()["stopped"] is True
    assert authority.status()["requests_charged"] == 0
    assert commands.status()["receipts"][0]["status"] == "APPLIED"
    assert not (tmp_path / "financial.sqlite3").exists()
    authority.resume(now=datetime.now(UTC), host=socket.gethostname())
    platform_stop(config)
    assert authority.status()["stopped"] is True
    assert authority.status()["requests_charged"] == 0
    assert commands.status()["receipts"][0]["status"] == "APPLIED"


def test_export_bounds_are_durable_and_do_not_modify_stop(tmp_path: Path) -> None:
    commands = ConsoleCommandStore(tmp_path / "commands.sqlite3")
    commands.initialize()
    bounds = {"start": "2026-10-16T00:00:00+00:00", "end": "2026-10-16T01:00:00+00:00"}
    receipt = commands.submit(subject="owner", action="export", expected_revision=0,
                              idempotency_key="retained-range-request", parameters=bounds)
    assert commands.parameters(int(receipt["revision"])) == bounds
    with pytest.raises(ValueError, match="unsupported_command_parameters"):
        commands.submit(subject="owner", action="stop", expected_revision=1,
                        idempotency_key="stop-cannot-carry-range", parameters=bounds)
    commands.finish(1, status="BLOCKED", result={"reason": "UNSUPPORTED_RANGE"})
    assert commands.status()["receipts"][0]["result"] == {"reason": "UNSUPPORTED_RANGE"}
    assert commands.pending() == []
