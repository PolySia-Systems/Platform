"""Prospective selection to pre-risk opportunity; never financial authority."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from polysia.application.services.source_cohort import SharedCohortSelection
from polysia.domain.financial_session import SessionBlocked, SessionOpportunity, utc


def admit_cohort_opportunity(
    selection: SharedCohortSelection,
    opportunity: SessionOpportunity,
    *,
    now: datetime,
) -> SessionOpportunity:
    """Bind frozen qualification evidence without manufacturing prices or edge.

    Exits remain a separate holdings/authorization policy: a disappeared leader
    must not prevent management of an already-owned position.
    """
    if opportunity.event.side != "BUY":
        raise SessionBlocked("cohort_admission_is_for_entries")
    policy = selection.selection_policy
    if policy is None or not 0 <= (utc(now) - utc(selection.selected_at)).total_seconds() <= (
        policy.freshness.total_seconds()
    ):
        raise SessionBlocked("selection_policy_missing_or_stale")
    wallet = opportunity.event.wallet
    if wallet not in selection.selected_wallet_ids:
        raise SessionBlocked("wallet_not_in_frozen_selected_cohort")
    evidence = next(
        (item for item in selection.qualification_evidence if item.wallet_id == wallet), None
    )
    if (
        evidence is None
        or not selection.selected_at <= opportunity.event.occurred_at <= now
        or opportunity.event.occurred_at < evidence.evaluation_start
    ):
        raise SessionBlocked("event_outside_prospective_evaluation_window")
    return replace(
        opportunity, cohort_digest=selection.digest, qualification_evidence_id=evidence.evidence_id
    )
