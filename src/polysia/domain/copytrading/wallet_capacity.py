"""Shared software envelope and evidence-bound operational wallet admission."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping

CAPACITY_CONTRACT_VERSION = "wallet-capacity-v1"
SOFTWARE_WALLET_LIMIT = 40
LEGACY_OPERATIONAL_WALLET_LIMIT = 3
_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class WalletCapacityError(ValueError):
    """The requested count lacks a matching operational capacity record."""


def require_software_count(count: int) -> int:
    if (
        isinstance(count, bool) or not isinstance(count, int)
        or not 1 <= count <= SOFTWARE_WALLET_LIMIT
    ):
        raise WalletCapacityError(
            f"wallet_count must be within the software envelope [1, {SOFTWARE_WALLET_LIMIT}]"
        )
    return count


def workload_digest(profile: str, runtime: Mapping[str, object]) -> str:
    """Bind a capacity measurement to cadence and source budgets, not count."""

    payload = {"profile": profile, "runtime": dict(runtime)}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def capacity_status(
    count: int,
    *,
    code_sha: str,
    workload_digest: str,
    evidence: Mapping[str, object] | None,
) -> dict[str, object]:
    """Keep software support distinct from measured admission for this workload."""

    require_software_count(count)
    if evidence is None:
        return {
            "version": CAPACITY_CONTRACT_VERSION,
            "requested_count": count,
            "software_limit": SOFTWARE_WALLET_LIMIT,
            "operational_status": "unverified",
            "validated_count": None,
            "reason": "matching_operational_capacity_evidence_required",
        }
    if evidence.get("version") != CAPACITY_CONTRACT_VERSION:
        raise WalletCapacityError("capacity evidence version is unsupported")
    if not isinstance(code_sha, str) or _SHA.fullmatch(code_sha) is None:
        raise WalletCapacityError("capacity code SHA must be immutable")
    if not isinstance(workload_digest, str) or _DIGEST.fullmatch(workload_digest) is None:
        raise WalletCapacityError("capacity workload digest is invalid")
    if evidence.get("code_sha") != code_sha:
        raise WalletCapacityError("capacity evidence code SHA does not match")
    if evidence.get("workload_digest") != workload_digest:
        raise WalletCapacityError("capacity evidence workload does not match")
    validated = evidence.get("validated_count")
    if isinstance(validated, bool) or not isinstance(validated, int):
        raise WalletCapacityError("validated_count must be an integer")
    require_software_count(validated)
    if not isinstance(evidence.get("digest"), str) or (
        _DIGEST.fullmatch(str(evidence["digest"])) is None
    ):
        raise WalletCapacityError("capacity evidence digest is missing")
    digest_payload = {key: value for key, value in evidence.items() if key != "digest"}
    actual_digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if actual_digest != evidence["digest"]:
        raise WalletCapacityError("capacity evidence digest mismatch")
    required_measures = (
        "polls_observed", "max_queue_delay_ms", "p95_decision_latency_ms",
        "peak_memory_bytes", "storage_growth_bytes", "other_consumer_requests",
        "data_requests", "clob_requests", "gamma_requests", "rate_limited_requests",
    )
    for field in required_measures:
        value = evidence.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise WalletCapacityError(f"capacity evidence {field} is missing or invalid")
    if (
        int(str(evidence["polls_observed"])) < 2
        or int(str(evidence["rate_limited_requests"])) > 0
    ):
        raise WalletCapacityError("capacity probe lacks repeated clean polls")
    if evidence.get("result") != "PASS":
        raise WalletCapacityError("capacity evidence has no passing measured result")
    if count > validated:
        raise WalletCapacityError(
            f"requested {count} wallets exceeds measured {validated}; use at most "
            f"{validated} or run an authorized bounded capacity probe"
        )
    return {
        "version": CAPACITY_CONTRACT_VERSION,
        "requested_count": count,
        "software_limit": SOFTWARE_WALLET_LIMIT,
        "operational_status": "measured",
        "validated_count": validated,
        "evidence_digest": evidence.get("digest"),
    }


def require_operational_capacity(status: Mapping[str, object]) -> None:
    if status.get("operational_status") != "measured":
        raise WalletCapacityError(
            "operational wallet capacity is unverified for this code and workload; "
            "use a matching measured capacity record or a bounded DATA_ONLY probe"
        )
