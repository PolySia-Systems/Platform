"""One redacted capability projection from committed session/custody evidence."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast

from polysia.domain.financial_session import SessionAuthorization
from polysia.monitoring.capabilities import CapabilityEvidence, capability_projection


def operational_capabilities(
    state: dict[str, Any],
    authority: SessionAuthorization,
    custody: dict[str, object],
    *,
    now: datetime,
    capacity_verified: bool,
    source_verified_at: datetime | None,
    capacity_observed_at: datetime | None = None,
    capacity_expires_at: datetime | None = None,
    qualification_verified: bool = False,
    qualification_observed_at: datetime | None = None,
) -> dict[str, object]:
    scope = authority.run_id
    evidence = {}

    def add(
        name: str,
        verified: bool | None,
        source: str,
        at: datetime | None,
        reason: str,
        next_action: str,
        *,
        until: datetime | None = None,
    ) -> None:
        evidence[name] = CapabilityEvidence(
            name,
            "VERIFIED" if verified else ("UNKNOWN" if verified is None else "MISSING"),
            source,
            at,
            until
            or (
                (at or now)
                + timedelta(
                    seconds=(
                        authority.supervision_timeout_seconds
                        if name in {"worker", "supervision", "recovery", "backup"}
                        else authority.max_evidence_age_seconds
                    )
                )
            ),
            reason,
            scope,
            next_action,
        )

    stamp = custody.get("supervised_at")
    supervised = datetime.fromisoformat(stamp) if isinstance(stamp, str) else None
    alive = supervised is not None and 0 <= (now - supervised).total_seconds() <= (
        authority.supervision_timeout_seconds
    )
    valid_authority = not custody.get("revoked") and not custody.get("stopped")
    account_at = state.get("reconciled_at")
    observed_account = datetime.fromisoformat(account_at) if account_at else None
    add(
        "configuration",
        True,
        "signed-exact-run-binding",
        now,
        "Exact configuration and package tree verified",
        "Revalidate after any change",
    )
    add(
        "worker",
        alive,
        "independent-custody",
        supervised,
        "Independent worker liveness",
        "Inspect supervisor heartbeat",
    )
    add(
        "supervision",
        alive and valid_authority,
        "independent-custody",
        supervised,
        "Durable STOP/revocation and independent health",
        "Resolve independent STOP or lost supervision",
    )
    add(
        "authority",
        bool(valid_authority),
        "verified-owner-receipt-and-custody",
        supervised,
        "Configured authority is separate from verified signature and current custody",
        "Obtain a separately scoped current owner receipt",
        until=authority.protective_until,
    )
    add(
        "account",
        bool(state["reconciliation_ok"]),
        "exact-finalized-chain-and-authenticated-CLOB",
        observed_account,
        "Exact account mapping and coherent complete evidence required",
        "Resolve financial uncertainty and re-read exact account",
        until=(observed_account or now) + timedelta(seconds=authority.max_evidence_age_seconds),
    )
    add(
        "credentials",
        bool(state["reconciliation_ok"]),
        "successful-mapped-account-read",
        observed_account,
        "Secret values are never published",
        "Validate protected references and identity",
    )
    add(
        "reconciliation",
        bool(state["reconciliation_ok"] and not state["incidents"]),
        "financial-journal",
        observed_account,
        "Account uncertainty blocks dependent actions",
        "Reconcile positions, cash, orders and fees",
    )
    add(
        "recovery",
        custody.get("checkpoint") is not None,
        "independent-checkpoint-custody",
        supervised,
        "Exact checkpoint required for fenced cold recovery",
        "Compare retained checkpoint before recovery",
    )
    add(
        "backup",
        alive and custody.get("reason") == "supervisor_checks_passed",
        "independent-supervisor",
        supervised,
        "Required financial protection was checked by the supervisor",
        "Inspect dated backup and independent restore evidence",
    )
    add(
        "capacity",
        capacity_verified,
        "bounded-fixed-allocation-qualification",
        capacity_observed_at,
        "A software ceiling is not MaximumVerified capacity",
        "Run a separately bounded qualification",
        until=capacity_expires_at,
    )
    add(
        "source",
        source_verified_at is not None,
        "corroborated-finalized-occurrences",
        source_verified_at,
        "Only complete current source windows can admit entries",
        "Complete source and edge qualification",
    )
    add(
        "qualification",
        qualification_verified,
        "frozen-selection-and-retained-follower-samples",
        qualification_observed_at,
        "Discovery membership does not prove usable follower edge",
        "Complete the predeclared selection and model qualification before evaluation",
        until=authority.expires_at,
    )
    add(
        "shadow",
        None,
        "separate-shadow-store",
        None,
        "Financial session liveness does not prove Shadow readiness",
        "Inspect the selected Shadow experiment",
    )
    result = capability_projection(
        evidence,
        now=now,
        enabled={
            "startup": True,
            "liveness": True,
            "data": True,
            "shadow": False,
            "account_reading": True,
            "new_entries": now < authority.expires_at,
            "protective_actions": bool(authority.protective_actions)
            and now < authority.protective_until,
            "recovery": True,
        },
    )
    if state["mode"] != "RUNNING":
        for row in cast(list[dict[str, Any]], result["capabilities"]):
            if row["capability"] == "new_entries":
                row["status"] = "BLOCKED" if now < authority.expires_at else "DISABLED"
    return result
