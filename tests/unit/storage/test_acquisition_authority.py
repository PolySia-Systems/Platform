from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from polysia.domain.research_evidence.acquisition_policy import AcquisitionPolicy
from polysia.storage.acquisition_authority import AcquisitionAuthority, AcquisitionBlockedError

NOW = datetime(2026, 10, 16, tzinfo=UTC)
ENDPOINT = "https://data-api.polymarket.com/v2/activity"


def policy() -> AcquisitionPolicy:
    return AcquisitionPolicy(
        "platform-test", "host", NOW, NOW + timedelta(hours=1), (ENDPOINT,),
        3, 3072, 1024, 10, 4096, 2, 60, 30, 2, 100_000_000, 25,
    )


def test_restart_charges_uncertain_requests_and_preserves_stop(tmp_path: Path) -> None:
    path = tmp_path / "authority.sqlite3"
    first = AcquisitionAuthority(path, policy())
    first.initialize()
    first.reserve(ENDPOINT, now=NOW, host="host")
    restarted = AcquisitionAuthority(path, policy())
    restarted.initialize()
    assert restarted.status()["bytes_charged"] == 1024
    second = restarted.reserve(ENDPOINT, now=NOW, host="host")
    restarted.settle(second, response_bytes=128)
    restarted.reserve(ENDPOINT, now=NOW, host="host")
    with pytest.raises(AcquisitionBlockedError, match="request_budget"):
        restarted.reserve(ENDPOINT, now=NOW, host="host")
    restarted.stop()
    again = AcquisitionAuthority(path, policy())
    again.initialize()
    assert again.status()["stopped"] is True
    with pytest.raises(AcquisitionBlockedError, match="stopped"):
        again.reserve(ENDPOINT, now=NOW, host="host")


def test_manifest_cannot_replace_consumed_authority(tmp_path: Path) -> None:
    path = tmp_path / "authority.sqlite3"
    AcquisitionAuthority(path, policy()).initialize()
    with pytest.raises(AcquisitionBlockedError, match="policy_changed"):
        AcquisitionAuthority(path, replace(policy(), maximum_requests=4)).initialize()


def test_limits_expiry_host_and_endpoint_fail_before_reservation(tmp_path: Path) -> None:
    authority = AcquisitionAuthority(tmp_path / "a.sqlite3", policy())
    authority.initialize()
    for endpoint, when, host in (
        (ENDPOINT, NOW + timedelta(hours=1), "host"),
        (ENDPOINT, NOW, "foreign"),
        ("https://unapproved.example/data", NOW, "host"),
    ):
        with pytest.raises(AcquisitionBlockedError):
            authority.reserve(endpoint, now=when, host=host)
    assert authority.status()["requests_charged"] == 0
    request_id = authority.reserve(ENDPOINT, now=NOW, host="host")
    with pytest.raises(AcquisitionBlockedError, match="outside_reservation"):
        authority.settle(request_id, response_bytes=1025)
    assert authority.status()["bytes_charged"] == 1024


def test_byte_reserve_blocks_before_partial_request(tmp_path: Path) -> None:
    authority = AcquisitionAuthority(
        tmp_path / "bytes.sqlite3", replace(policy(), maximum_bytes=1024),
    )
    authority.initialize()
    authority.reserve(ENDPOINT, now=NOW, host="host")
    with pytest.raises(AcquisitionBlockedError, match="byte_budget"):
        authority.reserve(ENDPOINT, now=NOW, host="host")
    assert authority.status()["requests_charged"] == 1


def test_closure_and_window_limits_do_not_create_extra_authority(tmp_path: Path) -> None:
    bounded = replace(policy(), closure_request_reserve=1, closure_byte_reserve=1024,
                      window_maximum_requests=2)
    authority = AcquisitionAuthority(tmp_path / "reserve.sqlite3", bounded)
    authority.initialize()
    authority.reserve(ENDPOINT, now=NOW, host="host")
    authority.reserve(ENDPOINT, now=NOW, host="host")
    with pytest.raises(AcquisitionBlockedError, match="request_budget"):
        authority.reserve(ENDPOINT, now=NOW, host="host")
    with pytest.raises(AcquisitionBlockedError, match="request_window"):
        authority.reserve(ENDPOINT, now=NOW, host="host", closure=True)
    # A later accounting window renews only the window, not consumed totals.
    later = NOW + timedelta(seconds=3601)
    bounded = replace(bounded, expires_at=NOW + timedelta(hours=2))
    other = AcquisitionAuthority(tmp_path / "later.sqlite3", bounded)
    other.initialize()
    other.reserve(ENDPOINT, now=NOW, host="host")
    other.reserve(ENDPOINT, now=NOW, host="host")
    other.reserve(ENDPOINT, now=later, host="host", closure=True)
    assert other.status()["requests_charged"] == 3
    with pytest.raises(AcquisitionBlockedError, match="request_budget"):
        other.reserve(ENDPOINT, now=later, host="host", closure=True)


def test_resume_preserves_charges_and_cannot_extend_expiry(tmp_path: Path) -> None:
    authority = AcquisitionAuthority(tmp_path / "resume.sqlite3", policy())
    authority.initialize()
    authority.reserve(ENDPOINT, now=NOW, host="host")
    authority.stop()
    authority.resume(now=NOW, host="host")
    assert authority.status()["requests_charged"] == 1
    with pytest.raises(AcquisitionBlockedError, match="not_current"):
        authority.resume(now=NOW + timedelta(hours=2), host="host")
