"""Server-owned finite observation checks on the existing worker scheduler."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from polysia.storage.acquisition_authority import AcquisitionAuthority


def campaign_check(
    plan: dict[str, Any],
    previous: dict[str, Any],
    *,
    database: Path,
    authority: AcquisitionAuthority,
    now: datetime,
    controls: dict[str, Any],
) -> dict[str, Any]:
    start = datetime.fromisoformat(plan["starts_at"])
    end = datetime.fromisoformat(plan["expires_at"])
    canary_end = datetime.fromisoformat(plan["canary_not_before"])
    if (
        plan.get("contract") != "nonlive-campaign/v1"
        or now.utcoffset() != timedelta(0)
        or start.utcoffset() != timedelta(0)
        or end.utcoffset() != timedelta(0)
        or end - start > timedelta(hours=72)
        or end <= start
        or canary_end - start < timedelta(seconds=2 * authority.policy.window_seconds)
        or plan["policy_digest"] != authority.policy.digest
        or start != authority.policy.starts_at
        or end != authority.policy.expires_at
        or plan["observation_seconds"] != 172800
        or not 60 <= plan["maximum_poll_gap_seconds"] <= 180
        or not 60 <= plan["maximum_input_age_seconds"] <= 300
    ):
        raise ValueError("campaign plan outside explicit finite contract")
    result = {
        **previous,
        "campaign_id": plan["campaign_id"],
        "checked_at": now.isoformat(),
        "phase": previous.get("phase", "CANARY"),
        "final_review": "REQUIRED",
        "financial_authority": False,
    }
    if result["phase"] in {"FAILED", "EXPIRED", "OBSERVATION_COMPLETE_REVIEW_REQUIRED"}:
        return result
    if now >= end:
        return {
            **result,
            "phase": "EXPIRED",
            "reason": "finite_authority_expired_partial_qualification",
        }
    if now < start:
        return {**result, "reason": "campaign_not_started"}
    observation_start = result.get("observation_started_at")
    cutoff = observation_start or plan["starts_at"]
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        polls = connection.execute(
            "SELECT started_at,completed_at,status,new_event_count "
            "FROM continuous_shadow_poll_runs "
            "WHERE started_at>=? ORDER BY started_at",
            (cutoff,),
        ).fetchall()
        fresh = connection.execute(
            "SELECT COUNT(*),MAX(p.completed_at) FROM continuous_shadow_evaluations e "
            "JOIN continuous_shadow_poll_runs p ON p.poll_run_id=e.poll_run_id "
            "WHERE p.started_at>=? AND p.status='succeeded' "
            "AND e.source_api_lag_ms<=? AND e.signal_delay_ms<=?",
            (
                cutoff,
                plan["maximum_input_age_seconds"] * 1000,
                plan["maximum_input_age_seconds"] * 1000,
            ),
        ).fetchone()
    successes = [row for row in polls if row[2] == "succeeded"]
    latest = datetime.fromisoformat(successes[-1][1] if successes else cutoff)
    gaps = [
        (datetime.fromisoformat(right[0]) - datetime.fromisoformat(left[0])).total_seconds()
        for left, right in zip(successes, successes[1:], strict=False)
    ]
    maximum_gap = max(gaps, default=0)
    if successes:
        maximum_gap = max(
            maximum_gap,
            (
                datetime.fromisoformat(successes[0][0]) - datetime.fromisoformat(cutoff)
            ).total_seconds(),
        )
    result.update(
        successful_polls=len(successes),
        failed_polls=len(polls) - len(successes),
        fresh_evaluations=fresh[0],
        last_useful_observation=fresh[1],
        maximum_poll_gap_seconds=maximum_gap,
    )
    reason = None
    if now - latest > timedelta(seconds=plan["maximum_poll_gap_seconds"]):
        reason = "useful_poll_flow_stalled"
    elif maximum_gap > plan["maximum_poll_gap_seconds"]:
        reason = "observation_poll_gap_exceeded"
    elif observation_start and now - datetime.fromisoformat(
        fresh[1] or observation_start,
    ) > timedelta(seconds=plan.get("maximum_useful_observation_gap_seconds", 900)):
        reason = "fresh_input_flow_stalled_or_cohort_quiet"
    elif observation_start and now >= datetime.fromisoformat(observation_start) + timedelta(
        seconds=plan["observation_seconds"],
    ):
        result.update(
            phase="OBSERVATION_COMPLETE_REVIEW_REQUIRED",
            ended_at=now.isoformat(),
            reason="real_observation_elapsed_review_required",
        )
    elif result["phase"] == "CANARY" and now >= canary_end:
        required = ("stop_zero_io", "resume", "restart", "recovery", "protected_controls")
        if any(controls.get(key) is not True for key in required):
            reason = "canary_control_evidence_incomplete"
        elif fresh[0] < plan["minimum_fresh_evaluations"]:
            reason = "canary_fresh_input_evidence_insufficient"
        elif fresh[1] is None or now - datetime.fromisoformat(fresh[1]) > timedelta(
            seconds=plan["maximum_input_age_seconds"],
        ):
            reason = "canary_latest_useful_input_stale"
        elif now + timedelta(seconds=plan["observation_seconds"]) > end:
            reason = "insufficient_remaining_real_observation_authority"
        else:
            charges = authority.status().get("campaign")
            elapsed = max(1, int((now - start).total_seconds()))
            if not isinstance(charges, dict):
                reason = "separate_campaign_accounting_missing"
            elif (
                charges["requests_charged"] * plan["observation_seconds"]
                > (charges["requests_remaining"] - authority.policy.closure_request_reserve)
                * elapsed
                or charges["bytes_charged"] * plan["observation_seconds"]
                > (charges["bytes_remaining"] - authority.policy.closure_byte_reserve) * elapsed
            ):
                reason = "measured_workload_cannot_fit_remaining_allowance"
            else:
                result.update(
                    phase="OBSERVING",
                    observation_started_at=now.isoformat(),
                    observation_ends_at=(
                        now
                        + timedelta(
                            seconds=plan["observation_seconds"],
                        )
                    ).isoformat(),
                    canary_passed_at=now.isoformat(),
                )
    if reason:
        result.update(phase="FAILED", reason=reason, failed_at=now.isoformat())
    return result


def supervise_campaign(
    value: dict[str, Any],
    *,
    database: Path,
    authority: AcquisitionAuthority,
    now: datetime,
) -> dict[str, Any] | None:
    if not value.get("campaign"):
        return None
    from polysia.cli_commands.platform_worker import atomic_json

    plan_path = Path(value["campaign"])
    state = database.with_name("nonlive-campaign-status.json")
    try:
        if plan_path.is_symlink() or plan_path.stat().st_size > 16_384:
            raise ValueError("invalid campaign plan")
        plan = json.loads(plan_path.read_text())
        configuration_digest = hashlib.sha256(json.dumps(
            value, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        if (plan.get("release_commit") != value["release_commit"]
                or plan.get("cohort_digest") != value["admission"]["cohort_digest"]
                or plan.get("configuration_digest") != configuration_digest):
            raise ValueError("campaign installed artifact/configuration/cohort binding mismatch")
        previous = json.loads(state.read_text()) if state.exists() else {}
        controls_path = database.with_name("nonlive-campaign-controls.json")
        controls = json.loads(controls_path.read_text()) if controls_path.exists() else {}
        result = campaign_check(
            plan, previous, database=database, authority=authority, now=now, controls=controls
        )
    except OSError, ValueError, KeyError, TypeError, sqlite3.Error:
        result = {
            "phase": "FAILED",
            "reason": "campaign_evidence_unavailable",
            "checked_at": now.isoformat(),
            "final_review": "REQUIRED",
        }
    if result["phase"] in {"FAILED", "EXPIRED", "OBSERVATION_COMPLETE_REVIEW_REQUIRED"}:
        authority.stop()
    atomic_json(state, result)
    return result
