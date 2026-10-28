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


def test_explicit_endpoint_grant_preserves_stop_and_consumed_allowance(tmp_path: Path) -> None:
    new_endpoint = "https://gamma-api.polymarket.com/events"
    path = tmp_path / "extended.sqlite3"
    authority = AcquisitionAuthority(path, policy())
    authority.initialize()
    authority.reserve(ENDPOINT, now=NOW, host="host")
    authority.stop()
    replacement = replace(policy(), policy_id="owner-new-route", endpoints=(ENDPOINT, new_endpoint))
    with pytest.raises(AcquisitionBlockedError, match="expand_endpoints"):
        authority.transition_policy(replacement, authorization_reference="owner-exact-new-route")
    updated = authority.transition_policy(
        replacement, authorization_reference="owner-exact-new-route",
        authorized_new_endpoints=(new_endpoint,),
    )
    assert updated.status()["requests_charged"] == 1
    assert updated.status()["bytes_charged"] == 1024
    assert updated.status()["stopped"] is True
    updated.resume(now=NOW, host="host")
    updated.reserve(new_endpoint, now=NOW, host="host")
    updated.reserve(ENDPOINT, now=NOW, host="host")
    with pytest.raises(AcquisitionBlockedError, match="request_budget"):
        updated.reserve(new_endpoint, now=NOW, host="host")
    restarted = AcquisitionAuthority(path, replacement)
    restarted.initialize()
    assert restarted.status()["requests_charged"] == 3


@pytest.mark.parametrize("authorized", [(), ("https://foreign.example/data",)])
def test_endpoint_grant_must_match_every_addition(
    tmp_path: Path, authorized: tuple[str, ...],
) -> None:
    authority = AcquisitionAuthority(tmp_path / "exact.sqlite3", policy())
    authority.initialize()
    with pytest.raises(AcquisitionBlockedError, match="expand_endpoints"):
        authority.transition_policy(
            replace(policy(), policy_id="new", endpoints=(ENDPOINT, "https://gamma.example/events")),
            authorization_reference="owner-new-route", authorized_new_endpoints=authorized,
        )
    assert authority.status()["policy_digest"] == policy().digest


def test_endpoint_grant_cannot_raise_other_limits(tmp_path: Path) -> None:
    endpoint = "https://gamma.example/events"
    authority = AcquisitionAuthority(tmp_path / "limits.sqlite3", policy())
    authority.initialize()
    with pytest.raises(AcquisitionBlockedError, match="raise_ceiling"):
        authority.transition_policy(
            replace(policy(), policy_id="new", endpoints=(ENDPOINT, endpoint), maximum_requests=4),
            authorization_reference="owner-new-route", authorized_new_endpoints=(endpoint,),
        )
    assert authority.status()["policy_digest"] == policy().digest


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


def test_explicit_continuation_preserves_charges_stop_and_numeric_ceilings(tmp_path: Path) -> None:
    authority = AcquisitionAuthority(tmp_path / "continuation.sqlite3", policy())
    authority.initialize()
    authority.reserve(ENDPOINT, now=NOW, host="host")
    authority.stop()
    replacement = replace(policy(), policy_id="followup",
                          starts_at=NOW + timedelta(hours=1),
                          expires_at=NOW + timedelta(hours=2))
    with pytest.raises(AcquisitionBlockedError, match="raise_ceiling"):
        authority.transition_policy(replace(replacement, maximum_requests=4),
                                    authorization_reference="owner-execution-test")
    updated = authority.transition_policy(
        replacement, authorization_reference="owner-execution-test",
    )
    updated.initialize()
    assert updated.status()["requests_charged"] == 1
    assert updated.status()["bytes_charged"] == 1024
    assert updated.status()["stopped"] is True
    with pytest.raises(AcquisitionBlockedError, match="mismatched"):
        authority.reserve(ENDPOINT, now=NOW, host="host")


def test_budget_windows_reject_non_UTC_clocks_before_reservation(tmp_path: Path) -> None:
    from datetime import timezone

    authority = AcquisitionAuthority(tmp_path / "clock.sqlite3", policy())
    authority.initialize()
    with pytest.raises(AcquisitionBlockedError, match="clock_not_UTC"):
        authority.reserve(ENDPOINT, now=NOW.astimezone(timezone(timedelta(hours=3))), host="host")
    assert authority.status()["requests_charged"] == 0


@pytest.mark.parametrize("changes,reason", [
    ({"window_seconds": 1}, "shorten_rate_window"),
    ({"retention_days": 1}, "retention_contract"),
    ({"backup_generations": 3}, "retention_contract"),
    ({"endpoints": (ENDPOINT, "https://example.com/new")}, "expand_endpoints"),
    ({"cadence_seconds": 1}, "reduce_reserve"),
    ({"cohort_limit": 3}, "raise_ceiling"),
    ({"window_maximum_requests": 301}, "raise_ceiling"),
    ({"window_maximum_bytes": 16_777_217}, "raise_ceiling"),
])
def test_continuation_cannot_weaken_any_standing_envelope(
    tmp_path: Path, changes: dict[str, object], reason: str,
) -> None:
    authority = AcquisitionAuthority(tmp_path / "rate.sqlite3", policy())
    authority.initialize()
    authority.reserve(ENDPOINT, now=NOW, host="host")
    with pytest.raises(AcquisitionBlockedError, match=reason):
        authority.transition_policy(
            replace(policy(), policy_id="changed", **changes),  # type: ignore[arg-type]
            authorization_reference="owner-test-continuation",
        )
    assert authority.status()["uncertain_requests"] == 1
    assert authority.status()["policy_digest"] == policy().digest


def test_stricter_continuation_preserves_hourly_window_and_uncertainty(tmp_path: Path) -> None:
    original = replace(policy(), window_maximum_requests=1)
    authority = AcquisitionAuthority(tmp_path / "standing.sqlite3", original)
    authority.initialize()
    authority.reserve(ENDPOINT, now=NOW, host="host")
    stricter = replace(original, policy_id="stricter", maximum_requests=2,
                       cadence_seconds=120, memory_max_bytes=90_000_000)
    continued = authority.transition_policy(stricter, authorization_reference="owner-test-stricter")
    restarted = AcquisitionAuthority(tmp_path / "standing.sqlite3", stricter)
    restarted.initialize()
    with pytest.raises(AcquisitionBlockedError, match="request_window"):
        restarted.reserve(ENDPOINT, now=NOW + timedelta(seconds=2), host="host")
    continued.stop()
    assert restarted.status()["stopped"] is True
    assert restarted.status()["uncertain_requests"] == 1
    assert restarted.status()["bytes_charged"] == 1024
