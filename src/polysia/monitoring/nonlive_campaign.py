"""Server-owned finite observation checks on the existing worker scheduler."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from polysia.domain.copytrading.native_run_limits import NativeRunLimits
from polysia.storage.acquisition_authority import AcquisitionAuthority
from polysia.storage.continuous_shadow import ContinuousShadowRepository

READINESS_MARGIN_SECONDS = 1800
REPAIR_RECEIPT = "nonlive-campaign-repair-receipt.json"


def configuration_digest(value: dict[str, Any]) -> str:
    """Bind a root-owned repair definition without a self-referential hash."""
    bound = dict(value)
    if isinstance(value.get("campaign_repair"), dict):
        bound["campaign_repair"] = {
            key: item for key, item in value["campaign_repair"].items()
            if key != "configuration_digest"
        }
    return hashlib.sha256(json.dumps(
        bound, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def effective_plan(value: dict[str, Any], raw: bytes) -> dict[str, Any]:
    """Keep the original plan immutable; admit only an explicitly bound repair."""
    plan = json.loads(raw)
    repair = value.get("campaign_repair")
    digest = configuration_digest(value)
    if repair is not None:
        if (not isinstance(repair, dict)
                or repair.get("contract") != "nonlive-campaign-repair/v1"
                or repair.get("original_plan_sha256") != hashlib.sha256(raw).hexdigest()
                or repair.get("configuration_digest") != digest
                or repair.get("release_commit") != value["release_commit"]
                or repair.get("policy_digest") != plan["policy_digest"]
                or repair.get("cohort_digest") != plan["cohort_digest"]
                or not re.fullmatch(r"[0-9a-f]{64}", repair.get("previous_status_sha256", ""))
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", repair.get("image", ""))
                or not 8 <= len(repair.get("authorization_reference", "")) <= 128
                or not 20 <= len(repair.get("reason", "")) <= 1024):
            raise ValueError("campaign repair definition mismatch")
        attempt = hashlib.sha256(json.dumps(
            repair, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        plan = {**plan, "release_commit": repair["release_commit"],
                "image": repair["image"], "configuration_digest": digest,
                "repair_attempt_id": attempt}
    if (plan.get("release_commit") != value["release_commit"]
            or plan.get("cohort_digest") != value["admission"]["cohort_digest"]
            or plan.get("configuration_digest") != digest):
        raise ValueError("campaign installed artifact/configuration/cohort binding mismatch")
    if plan.get("contract") == "nonlive-campaign/v2" and (
        plan.get("period_capacity") != NativeRunLimits.from_admission(value["admission"]).to_dict()
    ):
        raise ValueError("campaign period capacity binding mismatch")
    return plan


def _period_capacity(database: Path, plan: dict[str, Any]) -> tuple[int, int]:
    limits = NativeRunLimits.from_admission({"run_limits": plan["period_capacity"]})
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        rows = connection.execute(
            "SELECT experiment_id,config_json FROM continuous_shadow_experiments "
            "WHERE source_id='polymarket-native' AND lifecycle IN ('RUNNING','DRAINING')"
        ).fetchall()
    if len(rows) != 1:
        raise ValueError("one active native period required for capacity proof")
    config = json.loads(rows[0][1])
    if (config["period_max_events"] != limits.period_max_events
            or config["period_max_storage_bytes"] != limits.period_max_storage_bytes):
        raise ValueError("persisted native period capacity mismatch")
    return ContinuousShadowRepository(database).period_usage(rows[0][0])


def _capacity_projection(
    result: dict[str, Any], plan: dict[str, Any], *, database: Path,
    authority: AcquisitionAuthority, now: datetime, canary_end: datetime,
) -> str | None:
    """Forecast remaining actual authority and period capacity with 25% headroom."""
    start = datetime.fromisoformat(result["canary_started_at"])
    if now < start:
        raise ValueError("campaign clock regressed before useful canary anchor")
    elapsed = max(1, int((now - start).total_seconds()))
    events, storage = _period_capacity(database, plan)
    peak = max(storage, result.get("period_storage_peak_bytes", 0))
    result.update(
        period_events=events, period_storage_bytes=storage, period_storage_peak_bytes=peak,
    )
    if elapsed < 900:
        return None  # Tiny startup samples are not a sustained capacity model.
    if result.get("observation_started_at"):
        remaining = max(0, int((datetime.fromisoformat(result["observation_started_at"])
            + timedelta(seconds=plan["observation_seconds"]) - now).total_seconds()))
    else:
        remaining = plan["observation_seconds"] + max(0, int((canary_end - now).total_seconds()))

    def forecast(current: int, baseline: int) -> int:
        if current < baseline:
            raise ValueError("campaign capacity or accounting regressed")
        growth = current - baseline
        return current + (growth * remaining * 5 + elapsed * 4 - 1) // (elapsed * 4)

    projected_events = forecast(events, result["canary_event_baseline"])
    projected_storage = forecast(peak, result["canary_storage_baseline_bytes"])
    accounting = authority.status()
    if accounting["uncertain_requests"]:
        return "campaign_acquisition_accounting_uncertain"
    charges = accounting["campaign"]
    if not isinstance(charges, dict):
        raise ValueError("finite campaign accounting required")
    projected_requests = forecast(charges["requests_charged"], result["canary_requests_baseline"])
    projected_bytes = forecast(charges["bytes_charged"], result["canary_bytes_baseline"])
    result["capacity_projection"] = {"headroom_ratio": "1.25", "elapsed_seconds": elapsed,
        "remaining_seconds": remaining, "total_events": projected_events,
        "period_storage_bytes": projected_storage, "campaign_requests": projected_requests,
        "campaign_response_bytes": projected_bytes}
    limits = NativeRunLimits.from_admission({"run_limits": plan["period_capacity"]})
    if projected_events >= limits.period_max_events:
        return "measured_event_growth_cannot_fit_period_limit"
    if projected_storage >= limits.period_max_storage_bytes:
        return "measured_storage_growth_cannot_fit_period_limit"
    if (projected_requests > charges["requests_charged"] + charges["requests_remaining"]
            - authority.policy.closure_request_reserve
            or projected_bytes > charges["bytes_charged"] + charges["bytes_remaining"]
            - authority.policy.closure_byte_reserve):
        return "measured_workload_cannot_fit_remaining_allowance"
    return None


def validate_repair_receipt(
    receipt: dict[str, Any], value: dict[str, Any], plan: dict[str, Any],
) -> None:
    repair = value["campaign_repair"]
    retained = receipt["prior_status_raw"]
    if (receipt.get("contract") != "nonlive-campaign-repair-receipt/v1"
            or receipt.get("attempt_id") != plan["repair_attempt_id"]
            or receipt.get("original_plan_sha256") != repair["original_plan_sha256"]
            or receipt.get("prior_status_sha256") != repair["previous_status_sha256"]
            or hashlib.sha256(retained.encode()).hexdigest() != repair["previous_status_sha256"]
            or json.loads(retained) != receipt["prior_status"]
            or receipt["prior_status"].get("phase") != "FAILED"
            or receipt.get("reason") != repair["reason"]
            or receipt.get("authorization_reference") != repair["authorization_reference"]
            or receipt.get("financial_authority") is not False
            or receipt["authority_before"].get("stopped") is not True):
        raise ValueError("campaign repair receipt binding mismatch")


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
        plan.get("contract") not in {"nonlive-campaign/v1", "nonlive-campaign/v2"}
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
    fresh_campaign = plan["contract"] == "nonlive-campaign/v2"
    if fresh_campaign:
        NativeRunLimits.from_admission({"run_limits": plan["period_capacity"]})
        if (plan.get("maximum_useful_observation_gap_seconds") != 900
                or previous and previous.get("campaign_id") != plan["campaign_id"]):
            raise ValueError("fresh campaign criteria or retained identity mismatch")
    result = {
        **previous,
        "campaign_id": plan["campaign_id"],
        "checked_at": now.isoformat(),
        "phase": previous.get("phase", "PREPARING" if fresh_campaign else "CANARY"),
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
    repairing = "repair_attempt_id" in plan
    if repairing and result.get("attempt_id") != plan["repair_attempt_id"]:
        raise ValueError("audited campaign repair initialization required")
    anchored = repairing or fresh_campaign
    preparing = anchored and result["phase"] == "PREPARING"
    observation_start = result.get("observation_started_at")
    canary_start = result.get("canary_started_at") if anchored else None
    if anchored and not preparing:
        if canary_start is None:
            raise ValueError("campaign repair canary anchor missing")
        canary_end = datetime.fromisoformat(canary_start) + timedelta(
            seconds=2 * authority.policy.window_seconds,
        )
    cutoff = observation_start or canary_start or result.get(
        "attempt_started_at", plan["starts_at"],
    )
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
    if preparing:
        needed = 2 * authority.policy.window_seconds + plan["observation_seconds"]
        if now + timedelta(seconds=needed + READINESS_MARGIN_SECONDS) >= end:
            return {**result, "phase": "FAILED", "failed_at": now.isoformat(),
                    "reason": "insufficient_remaining_real_observation_authority"}
        required = ("stop_zero_io", "resume", "restart", "recovery", "protected_controls")
        health_path = database.with_name("native-latency.health.json")
        health: dict[str, Any] = {}
        try:
            if health_path.is_symlink() or health_path.stat().st_size > 4096:
                raise ValueError("invalid native readiness health")
            health = json.loads(health_path.read_bytes())
            stamp = datetime.fromisoformat(health["last_successful_flush"])
            telemetry_ready = (
                stamp.utcoffset() == timedelta(0) and timedelta(0) <= now - stamp
                <= timedelta(seconds=plan["maximum_input_age_seconds"])
                and health.get("telemetry_errors") == 0
                and health.get("dropped_measurements") == 0
                and health.get("process_capacity_summary", {}).get("release_commit")
                == plan["release_commit"]
                and health.get("process_capacity_summary", {}).get("samples", 0) > 0
                and health.get("process_capacity", {}).get("sample_seconds", 0) > 0
                and health.get("process_capacity", {}).get("peak_process_rss_bytes") is not None
                and health.get("process_capacity", {}).get("process_cpu_percent_one_core")
                is not None
            )
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            telemetry_ready = False
        if (successes and timedelta(0) <= now - latest
                <= timedelta(seconds=plan["maximum_poll_gap_seconds"])
                and fresh[0] >= plan["minimum_fresh_evaluations"] and fresh[1] is not None
                and timedelta(0) <= now - datetime.fromisoformat(fresh[1])
                <= timedelta(seconds=plan["maximum_input_age_seconds"])
                and all(controls.get(key) is True for key in required)
                and telemetry_ready):
            charges = authority.status().get("campaign")
            if not isinstance(charges, dict):
                raise ValueError("repair requires existing finite campaign accounting")
            capacity = {}
            if fresh_campaign:
                events, storage = _period_capacity(database, plan)
                capacity = {"canary_event_baseline": events,
                            "canary_storage_baseline_bytes": storage,
                            "period_storage_peak_bytes": storage}
            return {**result, **capacity, "phase": "CANARY", "canary_started_at": now.isoformat(),
                    "canary_requests_baseline": charges["requests_charged"],
                    "canary_bytes_baseline": charges["bytes_charged"],
                    "reason": "readiness_verified_real_canary_started"}
        return {**result, "reason": "await_qualified_input_controls_and_telemetry"}
    capacity_reason = _capacity_projection(
        result, plan, database=database, authority=authority, now=now, canary_end=canary_end,
    ) if fresh_campaign else None
    reason = None
    if now - latest > timedelta(seconds=plan["maximum_poll_gap_seconds"]):
        reason = "useful_poll_flow_stalled"
    elif maximum_gap > plan["maximum_poll_gap_seconds"]:
        reason = "observation_poll_gap_exceeded"
    elif (observation_start or fresh_campaign) and now - datetime.fromisoformat(
        str(fresh[1] or observation_start or canary_start),
    ) > timedelta(seconds=plan.get("maximum_useful_observation_gap_seconds", 900)):
        reason = "fresh_input_flow_stalled_or_cohort_quiet"
    elif capacity_reason:
        reason = capacity_reason
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
            anchor = datetime.fromisoformat(canary_start) if canary_start else start
            elapsed = max(1, int((now - anchor).total_seconds()))
            used_requests = 0 if not isinstance(charges, dict) else charges["requests_charged"]
            used_bytes = 0 if not isinstance(charges, dict) else charges["bytes_charged"]
            if anchored and isinstance(charges, dict):
                used_requests -= result["canary_requests_baseline"]
                used_bytes -= result["canary_bytes_baseline"]
                if used_requests < 0 or used_bytes < 0:
                    raise ValueError("campaign accounting regressed")
            if not isinstance(charges, dict):
                reason = "separate_campaign_accounting_missing"
            elif charges.get("first_attempt_at") is None or now < datetime.fromisoformat(
                charges["first_attempt_at"],
            ) + timedelta(seconds=2 * authority.policy.window_seconds):
                result["reason"] = "await_two_actual_acquisition_window_boundaries"
            elif (
                used_requests * plan["observation_seconds"]
                > (charges["requests_remaining"] - authority.policy.closure_request_reserve)
                * elapsed
                or used_bytes * plan["observation_seconds"]
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
        plan = effective_plan(value, plan_path.read_bytes())
        previous = json.loads(state.read_text()) if state.exists() else {}
        if "repair_attempt_id" in plan:
            receipt_path = database.with_name(REPAIR_RECEIPT)
            if receipt_path.is_symlink() or receipt_path.stat().st_size > 16_384:
                raise ValueError("campaign repair receipt unavailable")
            receipt = json.loads(receipt_path.read_bytes())
            validate_repair_receipt(receipt, value, plan)
            if (receipt.get("attempt_id") != plan["repair_attempt_id"]
                    or previous.get("attempt_id") != receipt["attempt_id"]):
                raise ValueError("campaign repair audit mismatch")
        controls_path = database.with_name("nonlive-campaign-controls.json")
        controls = json.loads(controls_path.read_text()) if controls_path.exists() else {}
        keys: tuple[str, ...] = (
            "campaign_id", "release_commit", "policy_digest", "cohort_digest",
        )
        if plan.get("contract") == "nonlive-campaign/v2":
            keys += ("configuration_digest", "image")
        if any(controls.get(key) != plan.get(key) for key in keys) or (
            "repair_attempt_id" in plan
            and controls.get("attempt_id") != plan["repair_attempt_id"]
        ):
            controls = {}  # A prior release/campaign's controls cannot commission this one.
        result = campaign_check(
            plan, previous, database=database, authority=authority, now=now, controls=controls
        )
    except OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error:
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
