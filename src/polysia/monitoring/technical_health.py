"""Finite native technical-health observation; quiet is not an economic failure.

The stock single-writer worker owns these checks. Clock passage alone cannot pass:
completed source polls, durable tick history, telemetry and bound controls are required.
This contract never changes the historical economic-flow campaign controller.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from polysia.domain.copytrading.native_health import PURPOSE, RUNTIME, validate_health_admission
from polysia.domain.copytrading.native_run_limits import NativeRunLimits
from polysia.storage.acquisition_authority import AcquisitionAuthority
from polysia.storage.continuous_shadow import ContinuousShadowRepository

CONTRACT = "nonlive-technical-health/v1"
ACCEPTANCE: dict[str, Any] = {
    "version": "native-technical-health-matrix/v1",
    "observation_seconds": 172800,
    "minimum_poll_coverage_percent": 95,
    "maximum_progress_gap_seconds": 900,
    "maximum_consecutive_provider_failures": 3,
    "first_canary_rolling_windows": 2,
    "maximum_tick_seconds": 180,
    "opportunity_frequency_required": False,
    "complete_marks_required": False,
}
TERMINAL = {"FAILED", "EXPIRED", "OBSERVATION_COMPLETE_REVIEW_REQUIRED"}


def record_tick(path: Path, result: dict[str, Any], *, now: datetime) -> None:
    """Keep actual worker attempts in the already backed-up authority store.

    No financial schema change. At 60-second ticks the finite 72-hour run has
    at most 4,321 normal rows, with a hard 10,000-row bound for abnormal restarts.
    No pruning or rewriting adverse history occurs.
    """
    payload = {key: result.get(key) for key in (
        "status", "reason", "release_commit", "policy_digest", "last_poll_started_at",
        "last_success", "next_due_at", "retry_at", "transient_failures", "observation",
    )}
    raw = json.dumps(payload, sort_keys=True)
    if len(raw.encode()) > 8192:
        raise ValueError("health tick evidence too large")
    with closing(sqlite3.connect(path, timeout=1)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS technical_health_ticks "
            "(observed_at TEXT PRIMARY KEY,payload TEXT NOT NULL)"
        )
        if connection.execute("SELECT COUNT(*) FROM technical_health_ticks").fetchone()[0] >= 10000:
            raise ValueError("health tick capacity reached; preserve history")
        connection.execute("INSERT INTO technical_health_ticks VALUES(?,?)", (now.isoformat(), raw))


def _telemetry(database: Path, *, now: datetime, source: str) -> dict[str, Any]:
    path = database.with_name("native-latency.health.json")
    if path.is_symlink() or path.stat().st_size > 8192:
        raise ValueError("invalid native health evidence")
    value = json.loads(path.read_bytes())
    stamp = datetime.fromisoformat(value["last_successful_flush"])
    sample = value["process_capacity"]
    if (stamp.utcoffset() != timedelta(0) or not timedelta(0) <= now - stamp
            <= timedelta(seconds=ACCEPTANCE["maximum_progress_gap_seconds"])
            or value["process_capacity_summary"]["release_commit"] != source
            or not sample.get("sample_seconds", 0) > 0
            or not isinstance(sample.get("peak_process_rss_bytes"), int)
            or sample.get("process_cpu_percent_one_core") is None):
        raise ValueError("native telemetry missing, stale or mismatched")
    return value


def health_check(
    plan: dict[str, Any], previous: dict[str, Any], *, database: Path,
    authority: AcquisitionAuthority, now: datetime, controls: dict[str, Any],
) -> dict[str, Any]:
    policy = authority.policy
    start, end = policy.starts_at, policy.expires_at
    limits = NativeRunLimits.from_admission({"run_limits": plan["period_capacity"]})
    slot = plan["scheduled_poll_slot_seconds"]
    if (plan.get("contract") != CONTRACT or plan.get("purpose") != PURPOSE
            or policy.purpose != PURPOSE or plan.get("acceptance") != ACCEPTANCE
            or plan.get("policy_digest") != policy.digest
            or plan.get("starts_at") != start.isoformat()
            or plan.get("expires_at") != end.isoformat()
            or now.utcoffset() != timedelta(0) or end - start > timedelta(hours=72)
            or not 60 <= policy.cadence_seconds <= 180
            or type(slot) is not int or not policy.cadence_seconds <= slot
            <= policy.cadence_seconds + 60
            or policy.window_seconds != 3600
            or previous and previous.get("campaign_id") != plan["campaign_id"]):
        raise ValueError("health purpose, frozen criteria or campaign identity mismatch")
    result = {**previous, "contract": CONTRACT, "purpose": PURPOSE,
              "campaign_id": plan["campaign_id"], "checked_at": now.isoformat(),
              "phase": previous.get("phase", "PREPARING"), "final_review": "REQUIRED",
              "financial_authority": False}
    if result["phase"] in TERMINAL:
        return result

    def fail(reason: str, phase: str = "FAILED") -> dict[str, Any]:
        return {**result, "phase": phase, "reason": reason, "ended_at": now.isoformat()}

    if now >= end:
        return fail("finite_health_authority_expired", "EXPIRED")
    if now < start:
        return {**result, "reason": "campaign_not_started"}
    accounting = authority.status()
    result["accounting"] = accounting
    if accounting["uncertain_requests"]:
        return fail("health_shared_accounting_uncertain")
    charges = accounting.get("campaign")
    if not isinstance(charges, dict):
        return fail("health_separate_finite_grant_missing")
    if result["phase"] == "PREPARING" and now + timedelta(hours=48) > end:
        return fail("insufficient_remaining_real_health_observation_authority")
    if not database.exists():
        return {**result, "reason": "await_installed_continuous_poll"}
    experiment = ContinuousShadowRepository(database).active_experiment("polymarket-native")
    if experiment is None and result["phase"] == "PREPARING":
        # Initialization precedes qualification I/O. A bounded provider retry can
        # legitimately leave schema-only storage, not a lost running period.
        return {**result, "reason": "await_installed_continuous_poll"}
    if (experiment is None or experiment.config.runtime_version != RUNTIME
            or experiment.config.code_sha != plan["release_commit"]
            or experiment.config.selection_preflight_digest != plan["cohort_digest"]
            or experiment.config.period_max_events != limits.period_max_events
            or experiment.config.period_max_storage_bytes != limits.period_max_storage_bytes):
        return fail("health_installed_period_identity_mismatch")
    evidence = experiment.config.capacity_evidence or {}
    validate_health_admission(evidence, code_sha=plan["release_commit"],
                              watch_digest=plan["cohort_digest"], now=now)
    if evidence.get("policy_digest") != policy.digest:
        return fail("health_installed_admission_policy_mismatch")
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        polls = connection.execute(
            "SELECT started_at,completed_at,status,new_event_count "
            "FROM continuous_shadow_poll_runs WHERE experiment_id=? ORDER BY started_at",
            (experiment.experiment_id,),
        ).fetchall()
    successes = [row for row in polls if row[2] == "succeeded"]
    required = ("stop_zero_io", "resume", "restart", "recovery", "protected_controls")
    controls_ready = all(controls.get(key) is True for key in required)
    try:
        native = _telemetry(database, now=now, source=plan["release_commit"])
    except (OSError, ValueError, KeyError, TypeError):
        native = None
    if result["phase"] == "PREPARING":
        if (not successes or not native or not controls_ready or accounting["stopped"]
                or not timedelta(0) <= now - datetime.fromisoformat(successes[-1][1])
                <= timedelta(seconds=slot + 60)):
            return {**result, "reason": "await_real_poll_current_telemetry_and_actual_controls"}
        anchor = now
        baseline_events, baseline_storage = ContinuousShadowRepository(database).period_usage(
            experiment.experiment_id,
        )
        result.update(phase="HEALTH_OBSERVATION_RUNNING", experiment_id=experiment.experiment_id,
                      observation_started_at=anchor.isoformat(),
                      observation_ends_at=(anchor + timedelta(hours=48)).isoformat(),
                      anchor_poll_id_after=successes[-1][0],
                      baseline_events=baseline_events, baseline_storage_bytes=baseline_storage,
                      baseline_requests=charges["requests_charged"],
                      baseline_response_bytes=charges["bytes_charged"],
                      reason="installed_technical_health_collection_started")
    anchor = datetime.fromisoformat(result["observation_started_at"])
    if now < anchor:
        return fail("health_clock_regressed")
    if accounting["stopped"] or not controls_ready:
        return fail("health_authority_stopped_or_control_binding_lost")
    relevant = [p for p in polls if datetime.fromisoformat(p[0]) >= anchor]
    completed = [p for p in relevant if p[2] == "succeeded"]
    stamps = [anchor, *[datetime.fromisoformat(p[1]) for p in completed], now]
    gap = max((b - a).total_seconds() for a, b in zip(stamps, stamps[1:], strict=False))
    elapsed = int((now - anchor).total_seconds())
    expected = elapsed // slot
    coverage = min(100, 100 * len(completed) // max(1, expected)) if expected else 100
    with closing(sqlite3.connect(authority.path.as_uri() + "?mode=ro", uri=True)) as connection:
        ticks = connection.execute(
            "SELECT observed_at,payload FROM technical_health_ticks WHERE observed_at>=? "
            "ORDER BY observed_at", (anchor.isoformat(),),
        ).fetchall()
    history = [json.loads(row[1]) for row in ticks]
    tick_stamps = [anchor, *[datetime.fromisoformat(row[0]) for row in ticks], now]
    tick_gap = max((b - a).total_seconds() for a, b in zip(
        tick_stamps, tick_stamps[1:], strict=False,
    ))
    if any(row.get("release_commit") != plan["release_commit"]
           or row.get("policy_digest") != policy.digest for row in history):
        return fail("health_tick_identity_mismatch")
    events, storage = ContinuousShadowRepository(database).period_usage(experiment.experiment_id)
    peak_storage = max(storage, result.get("period_storage_peak_bytes", 0),
                       result["baseline_storage_bytes"])
    result.update(observed_seconds=elapsed, successful_polls=len(completed),
                  failed_polls=len(relevant) - len(completed),
                  complete_zero_new_event_polls=sum(p[3] == 0 for p in completed),
                  expected_poll_slots=expected, poll_coverage_percent=coverage,
                  maximum_progress_gap_seconds=gap, period_events=events,
                  period_storage_bytes=storage, native_telemetry=native,
                  period_storage_peak_bytes=peak_storage,
                  durable_ticks=len(ticks), maximum_tick_gap_seconds=tick_gap,
                  retry_ticks=sum(row.get("status") == "WAITING_RETRY" for row in history),
                  failed_worker_ticks=sum(row.get("status") in {"FAILED", "BLOCKED"}
                                          for row in history))
    if tick_gap > ACCEPTANCE["maximum_tick_seconds"]:
        return fail("health_worker_tick_history_gap_exceeded")
    if gap > ACCEPTANCE["maximum_progress_gap_seconds"] or not native:
        return fail("health_progress_or_telemetry_gap_exceeded")
    if (native["process_capacity"]["peak_process_rss_bytes"] > policy.memory_max_bytes
            or native["process_capacity"]["disk_free_bytes"] < policy.minimum_free_disk_bytes):
        return fail("health_resource_headroom_exhausted")
    if events >= limits.period_max_events or storage >= limits.period_max_storage_bytes:
        return fail("health_period_capacity_exhausted")
    if elapsed >= 900:
        # Advisory until measured growth threatens actual remaining headroom.
        remaining = max(0, 172800 - elapsed)
        def forecast(current: int, baseline: int) -> int:
            if current < baseline:
                raise ValueError("health accounting or period capacity regressed")
            return current + (current - baseline) * remaining // elapsed

        result["capacity_forecast"] = {
            "kind": "ADVISORY_LINEAR_STARTUP_INCLUSIVE",
            "period_events": forecast(events, result["baseline_events"]),
            "period_storage_bytes": forecast(peak_storage, result["baseline_storage_bytes"]),
            "campaign_requests": forecast(
                charges["requests_charged"], result["baseline_requests"],
            ),
            "campaign_bytes": forecast(
                charges["bytes_charged"], result["baseline_response_bytes"],
            ),
        }
        result["capacity_action_required"] = (
            result["capacity_forecast"]["period_events"] >= limits.period_max_events
            or result["capacity_forecast"]["period_storage_bytes"]
            >= limits.period_max_storage_bytes
            or result["capacity_forecast"]["campaign_requests"]
            > charges["requests_charged"] + charges["requests_remaining"]
            or result["capacity_forecast"]["campaign_bytes"]
            > charges["bytes_charged"] + charges["bytes_remaining"]
        )
        if result["capacity_action_required"] and (
            events * 10 >= limits.period_max_events * 9
            or storage * 10 >= limits.period_max_storage_bytes * 9
            or charges["requests_charged"] >= charges["requests_remaining"] * 9
            or charges["bytes_charged"] >= charges["bytes_remaining"] * 9
        ):
            return fail("health_capacity_forecast_unresolved_before_hard_ceiling")
    if elapsed >= 2 * policy.window_seconds:
        if coverage < ACCEPTANCE["minimum_poll_coverage_percent"]:
            return fail("health_scheduled_poll_coverage_insufficient")
        result.setdefault("canary_passed_at", now.isoformat())
    if elapsed >= 172800:
        result.update(phase="OBSERVATION_COMPLETE_REVIEW_REQUIRED", ended_at=now.isoformat(),
                      reason="real_technical_health_period_complete_review_required")
    return result
