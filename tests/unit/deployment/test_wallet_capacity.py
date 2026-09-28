from __future__ import annotations

import hashlib
import json

import pytest

from polysia.domain.copytrading.wallet_capacity import (
    CAPACITY_CONTRACT_VERSION,
    WalletCapacityError,
    capacity_status,
    require_operational_capacity,
    require_software_count,
    workload_digest,
)


def _evidence(*, validated_count: int = 20) -> dict[str, object]:
    evidence: dict[str, object] = {
        "version": CAPACITY_CONTRACT_VERSION,
        "code_sha": "a" * 40,
        "workload_digest": workload_digest("canary", {"poll_interval_seconds": 3}),
        "validated_count": validated_count,
        "result": "PASS",
        "polls_observed": 3,
        "max_queue_delay_ms": 1,
        "p95_decision_latency_ms": 1,
        "peak_memory_bytes": 1024,
        "storage_growth_bytes": 1024,
        "other_consumer_requests": 1,
        "data_requests": 50,
        "clob_requests": 2,
        "gamma_requests": 2,
        "rate_limited_requests": 0,
    }
    evidence["digest"] = hashlib.sha256(json.dumps(
        evidence, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    return evidence


@pytest.mark.parametrize("count", [5, 10, 20, 40])
def test_software_envelope_is_not_operational_admission(count: int) -> None:
    assert require_software_count(count) == count
    pending = capacity_status(
        count, code_sha="a" * 40,
        workload_digest=workload_digest("canary", {"poll_interval_seconds": 3}),
        evidence=None,
    )
    with pytest.raises(WalletCapacityError, match="unverified"):
        require_operational_capacity(pending)


def test_measured_capacity_matches_code_workload_and_count() -> None:
    evidence = _evidence()
    fingerprint = workload_digest("canary", {"poll_interval_seconds": 3})
    status = capacity_status(
        10, code_sha="a" * 40, workload_digest=fingerprint, evidence=evidence
    )
    require_operational_capacity(status)
    assert status["validated_count"] == 20
    with pytest.raises(WalletCapacityError, match="exceeds measured"):
        capacity_status(40, code_sha="a" * 40, workload_digest=fingerprint, evidence=evidence)
    with pytest.raises(WalletCapacityError, match="workload"):
        capacity_status(10, code_sha="a" * 40, workload_digest="b" * 64, evidence=evidence)
    with pytest.raises(WalletCapacityError, match="code SHA"):
        capacity_status(10, code_sha="b" * 40, workload_digest=fingerprint, evidence=evidence)
