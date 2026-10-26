"""Versioned, operation-relative prerequisites. Configuration never proves authority."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

from polysia.domain.financial_session import utc

EvidenceState = Literal["MISSING", "CONFIGURED", "VERIFIED", "EXPIRED", "UNKNOWN", "REVOKED"]
CapabilityState = Literal["READY", "DEGRADED", "BLOCKED", "UNKNOWN", "DISABLED"]


@dataclass(frozen=True, slots=True)
class Requirement:
    identity: str
    obtain: str
    validate: str
    secret_reference_only: bool = False


CATALOG_VERSION = "operator-requirements/v1"
REQUIREMENTS = (
    Requirement(
        "qualification",
        "Retain point-in-time follower samples before evaluation",
        "Verify frozen selection, costs, sample confidence and model assumptions",
    ),
    Requirement(
        "configuration", "Prepare a bounded versioned configuration", "Validate exact digest"
    ),
    Requirement("worker", "Start the commissioned worker", "Check independent heartbeat expiry"),
    Requirement(
        "source", "Retain canonical occurrence evidence", "Complete bounded V2/RPC qualification"
    ),
    Requirement(
        "shadow", "Create a bounded Shadow experiment", "Verify lease, ledger and input coverage"
    ),
    Requirement(
        "account", "Commission one exact signer/funder mapping", "Read complete coherent account"
    ),
    Requirement(
        "authority",
        "Obtain a run-specific owner receipt outside Console",
        "Verify signature, binding and revocation",
    ),
    Requirement(
        "supervision", "Commission independent safety supervisor", "Verify current custody receipt"
    ),
    Requirement(
        "reconciliation",
        "Reconcile fills, cash, positions, orders and fees",
        "Resolve unknown external activity",
    ),
    Requirement(
        "recovery",
        "Retain checkpoint outside financial backups",
        "Compare exact retained sequence and digest",
    ),
    Requirement(
        "backup",
        "Enable separate financial recovery protection",
        "Retain current backup and restore evidence",
    ),
    Requirement(
        "capacity",
        "Set conservative fixed allocations",
        "Qualify workload, shared egress and protective headroom",
    ),
    Requirement(
        "credentials",
        "Configure protected secret references outside browser",
        "Verify mapped identity without exposing values",
        True,
    ),
)
CAPABILITIES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "startup": (("configuration",), ("backup",)),
    "liveness": (("worker", "supervision"), ()),
    "data": (("configuration", "source", "capacity"), ()),
    "shadow": (("configuration", "source", "shadow", "capacity"), ("backup",)),
    "account_reading": (("account", "credentials", "authority", "capacity"), ()),
    "new_entries": (
        (
            "account",
            "authority",
            "supervision",
            "reconciliation",
            "recovery",
            "backup",
            "capacity",
            "source",
            "qualification",
        ),
        (),
    ),
    "protective_actions": (
        ("account", "authority", "supervision", "reconciliation", "recovery", "backup", "capacity"),
        (),
    ),
    "recovery": (("authority", "recovery", "backup", "supervision", "account"), ()),
}


@dataclass(frozen=True, slots=True)
class CapabilityEvidence:
    requirement: str
    state: EvidenceState
    source: str
    observed_at: datetime | None
    expires_at: datetime | None
    reason: str
    scope: str
    next_action: str

    def current_state(self, now: datetime) -> EvidenceState:
        if self.observed_at is None or self.expires_at is None:
            return "UNKNOWN" if self.state == "VERIFIED" else self.state
        if utc(self.observed_at) > utc(now) or utc(self.expires_at) <= now:
            return "EXPIRED"
        return self.state


def capability_projection(
    evidence: Mapping[str, CapabilityEvidence],
    *,
    now: datetime,
    enabled: Mapping[str, bool],
) -> dict[str, object]:
    utc(now)
    result = []
    for capability, (required, optional) in CAPABILITIES.items():
        states = {
            name: evidence[name].current_state(now) if name in evidence else "MISSING"
            for name in required + optional
        }
        status: CapabilityState
        if enabled.get(capability) is not True:
            status = "DISABLED"
        elif any(
            states[name] in {"MISSING", "CONFIGURED", "EXPIRED", "REVOKED"} for name in required
        ):
            status = "BLOCKED"
        elif any(states[name] == "UNKNOWN" for name in required):
            status = "UNKNOWN"
        elif any(states[name] != "VERIFIED" for name in optional):
            status = "DEGRADED"
        else:
            status = "READY"
        result.append(
            {
                "capability": capability,
                "status": status,
                "required": list(required),
                "optional": list(optional),
                "requirements": [
                    {
                        "identity": name,
                        "state": state,
                        "evidence": asdict(evidence[name]) if name in evidence else None,
                    }
                    for name, state in states.items()
                ],
            }
        )
    return {
        "version": CATALOG_VERSION,
        "observed_at": now.isoformat(),
        "catalog": [asdict(item) for item in REQUIREMENTS],
        "capabilities": result,
    }
