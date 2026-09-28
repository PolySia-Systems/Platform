"""Compact, deterministic prospective-replay reports and comparisons."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from polysia.backtesting.prospective_replay import RecordedExperimentReplay
from polysia.domain.research_evidence.economic_contract import CONTRACT_V1
from polysia.domain.research_evidence.replay import REPLAY_ENGINE_VERSION
from polysia.storage.research_evidence import ResearchEvidenceStore, ResearchExperiment

COMPACT_STDOUT_LIMIT = 5120


def wallet_evidence_diagnostics(
    store: ResearchEvidenceStore,
    *,
    run_id: str,
    selected_aliases: tuple[str, ...],
    replay: RecordedExperimentReplay,
    source_health: Mapping[str, object],
) -> dict[str, object]:
    """Join process scope, durable identity and economics without hiding zero wallets."""

    durable = store.wallet_evidence_diagnostics(run_id, selected_aliases)
    economics = {item.leader_alias: item.economics for item in replay.wallet_economics}
    wallets: dict[str, object] = {}
    for alias in selected_aliases:
        source_stages: dict[str, object] = {}
        for source_id, raw in source_health.items():
            if not isinstance(raw, Mapping):
                continue
            per_wallet = raw.get("wallet_diagnostics")
            if isinstance(per_wallet, Mapping) and isinstance(per_wallet.get(alias), Mapping):
                source_stages[source_id] = dict(per_wallet[alias])
        stored = durable[alias]
        economic = economics.get(alias)
        unknown = {} if economic is None else dict(economic.unknown_by_cause)
        reasons: list[str] = []
        if not source_stages:
            reasons.append("source_response_counts_unavailable")
        for stages in source_stages.values():
            if not isinstance(stages, Mapping):
                continue
            if int(str(stages.get("incomplete_windows", 0))):
                reasons.append("source_window_incomplete")
            if stages.get("last_outcome") == "success_filtered":
                reasons.append("source_rows_filtered")
        if int(str(stored["pending_unadmitted"])):
            reasons.append("pending_coverage_admission")
        if int(str(stored["durable_rejected"])):
            reasons.append("identity_or_mapping_rejected")
        if int(str(stored["accepted_invalid_interval"])):
            reasons.append("accepted_evidence_excluded_invalid_interval")
        if stored["admitted_accepted"] is None:
            reasons.append("historical_admission_time_unavailable")
        if int(str(stored["durable_accepted"])) == 0:
            if (
                stored["completed_source_boundaries"]
                and source_stages
                and all(
                    isinstance(stage, Mapping)
                    and stage.get("last_outcome") == "success_empty"
                    for stage in source_stages.values()
                )
            ):
                reasons.append("confirmed_empty_within_recorded_coverage")
            else:
                reasons.append("no_durable_wallet_events_cause_unknown")
        for cause in unknown:
            if cause in {"missing_quote", "stale_quote", "missing_depth", "insufficient_depth"}:
                reasons.append("missing_stale_book_or_depth")
            elif cause == "missing_fee":
                reasons.append("missing_market_fee")
            elif cause == "missing_market_token_mapping":
                reasons.append("market_token_mapping_unverified")
        wallets[alias] = {
            "source_process_window_occurrences": source_stages,
            "durable_unique_evidence": stored,
            "economic": {
                "eligible_observations": (
                    None if economic is None else economic.eligible_observations
                ),
                "evaluated_observations": (
                    None if economic is None else economic.evaluated_observations
                ),
                "unknown_by_cause": unknown,
                "status": "UNAVAILABLE" if economic is None else economic.economic_classification,
            },
            "reasons": sorted(set(reasons)),
        }
    return {
        "version": "wallet-evidence-diagnostics-v1",
        "source_count_scope": "process_window_occurrences_not_unique_events",
        "durable_count_scope": "unique_stored_evidence_with_recorded_run_id",
        "wallets": wallets,
    }


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def digest_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def detailed_replay_payload(
    scoped: RecordedExperimentReplay,
    *,
    experiment: ResearchExperiment,
    run_id: str,
    source_database_sha256: str,
    include_decision_rows: bool = True,
) -> dict[str, Any]:
    result = scoped.result
    economics = scoped.economics
    lineage = {
        "excluded_event_count": scoped.excluded_event_count,
        "invalid_interval_count": len(scoped.invalid_intervals),
        "invalid_interval_ids": [interval.interval_id for interval in scoped.invalid_intervals],
        "replayed_event_count": scoped.replayed_event_count,
        "valid_interval_count": len(scoped.valid_intervals),
        "valid_interval_ids": [interval.interval_id for interval in scoped.valid_intervals],
    }
    payload: dict[str, Any] = {
        "code_sha": experiment.code_sha,
        "configuration_digest": experiment.configuration_digest,
        "control_digest": result.control_digest,
        "economic": economics.to_dict(),
        "engine_version": REPLAY_ENGINE_VERSION,
        "evidence_lineage": lineage,
        "experiment_contract": CONTRACT_V1.to_dict(),
        "experiment_contract_digest": CONTRACT_V1.digest,
        "excluded_event_count": scoped.excluded_event_count,
        "invalid_interval_count": len(scoped.invalid_intervals),
        "invalidated": result.invalidated,
        "interval_scope": "valid_intervals_only",
        "replayed_event_count": scoped.replayed_event_count,
        "run_id": run_id,
        "source_database_sha256": source_database_sha256,
        "source_hash": source_database_sha256,
        "target_digest": result.target_digest,
        "unknown_count": result.unknown_count,
        "unknown_by_cause": dict(result.unknown_by_cause),
        "valid_interval_count": len(scoped.valid_intervals),
        "wallet_economics": [item.to_dict() for item in scoped.wallet_economics],
        "summary": {
            "control_net_pnl": economics.control.to_dict()["net_pnl"],
            "data_canary": economics.data_canary_status,
            "economic": economics.economic_classification,
            "execution_evidence_ratio": format(economics.execution_evidence_ratio, "f"),
            "target_net_pnl": economics.target.to_dict()["net_pnl"],
            "unknown_count": result.unknown_count,
        },
    }
    if include_decision_rows:
        payload["control_decisions"] = [
            {"evidence_id": evidence_id, "decision": decision.value}
            for evidence_id, decision in result.control_decisions
        ]
        payload["target_decisions"] = [
            {"evidence_id": evidence_id, "decision": str(decision)}
            for evidence_id, decision in result.target_decisions
        ]
        payload["decision_evidence"] = [
            {
                "control_decision": row.control_decision,
                "decision_time": row.decision_time.isoformat(),
                "first_observed_time": (
                    None if row.first_observed_time is None
                    else row.first_observed_time.isoformat()
                ),
                "admission_time": (
                    None if row.admission_time is None
                    else row.admission_time.isoformat()
                ),
                "source_time": (
                    None if row.source_time is None
                    else row.source_time.isoformat()
                ),
                "leader_alias": row.leader_alias,
                "market_reference": row.market_reference,
                "outcome_reference": row.outcome_reference,
                "side": row.side,
                "snapshot_evidence_id": (
                    None if row.execution is None else row.execution.snapshot_evidence_id
                ),
                "target_decision": row.target_decision,
                "unknown_reason": row.unknown_reason,
                "wallet_evidence_id": row.evidence_id,
            }
            for row in result.evaluations
        ]
    payload["result_hash"] = result_hash(payload)
    return payload


def compact_replay_payload(detailed: Mapping[str, Any]) -> dict[str, Any]:
    summary = detailed.get("summary")
    lineage = detailed.get("evidence_lineage")
    return {
        "code_sha": detailed.get("code_sha"),
        "configuration_digest": detailed.get("configuration_digest"),
        "contract_digest": detailed.get("experiment_contract_digest"),
        "engine_version": detailed.get("engine_version"),
        "evidence_diagnostics_sha256": detailed.get("evidence_diagnostics_sha256"),
        "evidence_lineage": lineage if isinstance(lineage, dict) else {},
        "result_hash": detailed.get("result_hash") or result_hash(detailed),
        "run_id": detailed.get("run_id"),
        "source_hash": detailed.get("source_hash") or detailed.get("source_database_sha256"),
        "summary": summary if isinstance(summary, dict) else {},
        "unknown_by_cause": detailed.get("unknown_by_cause") or {},
        "unknown_count": detailed.get("unknown_count"),
    }


def result_hash(payload: Mapping[str, Any]) -> str:
    identity = {
        "code_sha": payload.get("code_sha"),
        "configuration_digest": payload.get("configuration_digest"),
        "control_digest": payload.get("control_digest"),
        "economic_digest": None
        if not isinstance(payload.get("economic"), dict)
        else payload["economic"].get("digest"),
        "wallet_economics": payload.get("wallet_economics") or [],
        "engine_version": payload.get("engine_version"),
        "experiment_contract_digest": payload.get("experiment_contract_digest"),
        "run_id": payload.get("run_id"),
        "source_hash": payload.get("source_hash") or payload.get("source_database_sha256"),
        "target_digest": payload.get("target_digest"),
        "unknown_by_cause": payload.get("unknown_by_cause") or {},
        "unknown_count": payload.get("unknown_count"),
    }
    if "evidence_diagnostics_sha256" in payload:
        identity["evidence_diagnostics_sha256"] = payload["evidence_diagnostics_sha256"]
    return digest_payload(identity)


def compare_replay_reports(
    current: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    current_engine = str(current.get("engine_version") or "")
    baseline_engine = str(baseline.get("engine_version") or "")
    current_contract = str(current.get("experiment_contract_digest") or "")
    baseline_contract = str(baseline.get("experiment_contract_digest") or "")
    current_config = str(current.get("configuration_digest") or "")
    baseline_config = str(baseline.get("configuration_digest") or "")
    identity_changed = (
        current_engine != baseline_engine
        or current_contract != baseline_contract
        or current_config != baseline_config
    )
    decision_deltas = _decision_deltas(current, baseline)
    unknown_deltas = _mapping_deltas(
        _as_mapping(current.get("unknown_by_cause")),
        _as_mapping(baseline.get("unknown_by_cause")),
    )
    coverage_deltas = {
        "eligible_observations": _int_delta(
            _economic(current).get("eligible_observations"),
            _economic(baseline).get("eligible_observations"),
        ),
        "execution_evidence_ratio": _text_delta(
            _economic(current).get("execution_evidence_ratio"),
            _economic(baseline).get("execution_evidence_ratio"),
        ),
        "mapping_ratio": _text_delta(
            _economic(current).get("mapping_ratio"),
            _economic(baseline).get("mapping_ratio"),
        ),
        "unknown_count": _int_delta(current.get("unknown_count"), baseline.get("unknown_count")),
    }
    economic_deltas = {
        "control_net_pnl": _text_delta(
            _nested(current, "summary", "control_net_pnl"),
            _nested(baseline, "summary", "control_net_pnl"),
        ),
        "data_canary": _text_delta(
            _nested(current, "summary", "data_canary"),
            _nested(baseline, "summary", "data_canary"),
        ),
        "economic": _text_delta(
            _nested(current, "summary", "economic"),
            _nested(baseline, "summary", "economic"),
        ),
        "target_net_pnl": _text_delta(
            _nested(current, "summary", "target_net_pnl"),
            _nested(baseline, "summary", "target_net_pnl"),
        ),
    }
    current_source = str(current.get("source_hash") or current.get("source_database_sha256") or "")
    baseline_source = str(
        baseline.get("source_hash") or baseline.get("source_database_sha256") or ""
    )
    current_run = str(current.get("run_id") or "")
    baseline_run = str(baseline.get("run_id") or "")
    incompatible_reasons: list[str] = []
    if current_source and baseline_source and current_source != baseline_source:
        incompatible_reasons.append("source_evidence")
    if current_run and baseline_run and current_run != baseline_run:
        incompatible_reasons.append("capture_identity")
    wallet_delta = _mapping_deltas(_wallet_selection(current), _wallet_selection(baseline))
    captured_delta = {
        "run_id": _text_delta(current_run, baseline_run),
        "source_hash": _text_delta(current_source, baseline_source),
        "time_range": _text_delta(_captured_range(current), _captured_range(baseline)),
    }
    budget_delta = _mapping_deltas(
        _as_mapping(current.get("budgets")),
        _as_mapping(baseline.get("budgets")),
    )
    analysis_delta = {
        "analysis_id": _text_delta(current.get("analysis_id"), baseline.get("analysis_id")),
        "claim_class": _text_delta(current.get("claim_class"), baseline.get("claim_class")),
        "code_sha": _text_delta(
            current.get("analysis_code_sha") or current.get("code_sha"),
            baseline.get("analysis_code_sha") or baseline.get("code_sha"),
        ),
        "engine_version": _text_delta(current_engine, baseline_engine),
    }
    first_material = _first_material_difference(decision_deltas, unknown_deltas, economic_deltas)
    behavioral_difference = first_material is not None or any(
        item is not None for item in coverage_deltas.values()
    )
    if incompatible_reasons:
        classification = "incompatible_comparison"
    elif identity_changed:
        classification = "expected_version_change"
    elif behavioral_difference:
        classification = "regression_candidate"
    else:
        classification = "identical"
    return {
        "analysis": analysis_delta,
        "budgets": budget_delta,
        "captured": captured_delta,
        "causal_inference": "not_inferred",
        "classification": classification,
        "coverage_deltas": coverage_deltas,
        "decision_deltas": {
            "changed": len(decision_deltas),
            "first": None if not decision_deltas else decision_deltas[0],
        },
        "economic_deltas": economic_deltas,
        "engine_version": {"baseline": baseline_engine, "current": current_engine},
        "experiment_contract_digest": {
            "baseline": baseline_contract,
            "current": current_contract,
        },
        "configuration_digest": {"baseline": baseline_config, "current": current_config},
        "first_material_difference": first_material,
        "identity_changed": identity_changed,
        "incompatible": bool(incompatible_reasons),
        "incompatible_reasons": incompatible_reasons,
        "result_hash": {
            "baseline": baseline.get("result_hash") or result_hash(baseline),
            "current": current.get("result_hash") or result_hash(current),
        },
        "unknown_deltas": unknown_deltas,
        "wallet_selection": wallet_delta,
    }


def _wallet_selection(payload: Mapping[str, Any]) -> dict[str, object]:
    followed = payload.get("followed_wallet_selection") or payload.get("wallet_selection") or {}
    if not isinstance(followed, dict):
        return {}
    return {
        "configuration_digest": followed.get("configuration_digest")
        or payload.get("configuration_digest"),
        "identity_status": followed.get("identity_status") or "UNKNOWN",
        "policy": followed.get("selection_policy") or followed.get("policy"),
        "selection_digest": followed.get("selection_digest"),
        "wallet_count": followed.get("wallet_count"),
    }


def _captured_range(payload: Mapping[str, Any]) -> str | None:
    capture = payload.get("capture")
    if isinstance(capture, dict):
        started = capture.get("started_at")
        ended = capture.get("collection_ends_at")
        if started or ended:
            return f"{started}/{ended}"
    lineage = payload.get("evidence_lineage")
    if isinstance(lineage, dict):
        ids = lineage.get("valid_interval_ids")
        if isinstance(ids, list) and ids:
            return ",".join(str(item) for item in ids)
    return None


def _economic(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    economic = payload.get("economic")
    return economic if isinstance(economic, dict) else {}


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _nested(payload: Mapping[str, Any], *keys: str) -> object:
    current: object = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _int_delta(current: object, baseline: object) -> dict[str, object] | None:
    if current == baseline:
        return None
    return {"baseline": baseline, "current": current}


def _text_delta(current: object, baseline: object) -> dict[str, object] | None:
    if str(current) == str(baseline):
        return None
    return {"baseline": baseline, "current": current}


def _mapping_deltas(current: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, object]:
    keys = sorted(set(current) | set(baseline))
    changed: dict[str, object] = {
        key: {"baseline": baseline.get(key, 0), "current": current.get(key, 0)}
        for key in keys
        if current.get(key, 0) != baseline.get(key, 0)
    }
    return changed


def _decision_deltas(
    current: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> list[dict[str, object]]:
    current_rows = current.get("decision_evidence")
    baseline_rows = baseline.get("decision_evidence")
    if not isinstance(current_rows, list) or not isinstance(baseline_rows, list):
        current_control = {
            row["evidence_id"]: row["decision"]
            for row in current.get("control_decisions") or []
            if isinstance(row, dict) and "evidence_id" in row
        }
        baseline_control = {
            row["evidence_id"]: row["decision"]
            for row in baseline.get("control_decisions") or []
            if isinstance(row, dict) and "evidence_id" in row
        }
        ids = sorted(set(current_control) | set(baseline_control))
        return [
            {
                "evidence_id": evidence_id,
                "field": "control_decision",
                "baseline": baseline_control.get(evidence_id),
                "current": current_control.get(evidence_id),
            }
            for evidence_id in ids
            if current_control.get(evidence_id) != baseline_control.get(evidence_id)
        ]
    indexed_current = {
        str(row.get("wallet_evidence_id")): row
        for row in current_rows
        if isinstance(row, dict) and row.get("wallet_evidence_id") is not None
    }
    indexed_baseline = {
        str(row.get("wallet_evidence_id")): row
        for row in baseline_rows
        if isinstance(row, dict) and row.get("wallet_evidence_id") is not None
    }
    deltas: list[dict[str, object]] = []
    for evidence_id in sorted(set(indexed_current) | set(indexed_baseline)):
        left = indexed_current.get(evidence_id) or {}
        right = indexed_baseline.get(evidence_id) or {}
        for field in ("control_decision", "target_decision", "unknown_reason"):
            if left.get(field) != right.get(field):
                deltas.append(
                    {
                        "baseline": right.get(field),
                        "current": left.get(field),
                        "evidence_id": evidence_id,
                        "field": field,
                    }
                )
    return deltas


def _first_material_difference(
    decision_deltas: list[dict[str, object]],
    unknown_deltas: Mapping[str, object],
    economic_deltas: Mapping[str, object],
) -> dict[str, object] | None:
    if decision_deltas:
        first = decision_deltas[0]
        return {
            "evidence_id": first.get("evidence_id"),
            "field": first.get("field"),
            "kind": "decision",
            "baseline": first.get("baseline"),
            "current": first.get("current"),
        }
    if unknown_deltas:
        cause = next(iter(unknown_deltas))
        payload = unknown_deltas[cause]
        details = payload if isinstance(payload, dict) else {"current": payload}
        return {
            "evidence_id": None,
            "field": cause,
            "kind": "unknown",
            **details,
        }
    for field, payload in economic_deltas.items():
        if payload is not None:
            details = payload if isinstance(payload, dict) else {"current": payload}
            return {
                "evidence_id": None,
                "field": field,
                "kind": "economic",
                **details,
            }
    return None


__all__ = [
    "COMPACT_STDOUT_LIMIT",
    "canonical_json",
    "compact_replay_payload",
    "compare_replay_reports",
    "detailed_replay_payload",
    "digest_payload",
    "result_hash",
]
