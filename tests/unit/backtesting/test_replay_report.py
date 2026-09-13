from __future__ import annotations

import json

from polysia.backtesting.replay_report import (
    compact_replay_payload,
    compare_replay_reports,
    result_hash,
)


def _report(
    *,
    engine: str = "same-observation-replay-v1",
    decision: str = "ADMIT",
) -> dict[str, object]:
    payload = {
        "code_sha": "a" * 40,
        "configuration_digest": "config",
        "control_digest": "control",
        "engine_version": engine,
        "experiment_contract_digest": "contract",
        "run_id": "run",
        "source_hash": "b" * 64,
        "target_digest": "target",
        "unknown_count": 1,
        "unknown_by_cause": {"stale_quote": 1},
        "summary": {
            "control_net_pnl": "0",
            "data_canary": "FAIL",
            "economic": "INSUFFICIENT_DATA",
            "target_net_pnl": None,
        },
        "economic": {
            "digest": "econ",
            "eligible_observations": 1,
            "execution_evidence_ratio": "0",
            "mapping_ratio": "1",
        },
        "decision_evidence": [
            {
                "control_decision": decision,
                "target_decision": decision,
                "unknown_reason": "stale_quote",
                "wallet_evidence_id": "ev-1",
            }
        ],
    }
    payload["result_hash"] = result_hash(payload)
    return payload


def test_compare_same_identity_with_delta_is_regression_candidate() -> None:
    current = _report(decision="UNKNOWN")
    baseline = _report(decision="ADMIT")
    compared = compare_replay_reports(current, baseline)
    assert compared["classification"] == "regression_candidate"
    assert compared["first_material_difference"]["evidence_id"] == "ev-1"
    assert compared["identity_changed"] is False


def test_compare_version_change_still_reports_delta() -> None:
    current = _report(engine="same-observation-replay-v2", decision="UNKNOWN")
    baseline = _report(decision="ADMIT")
    compared = compare_replay_reports(current, baseline)
    assert compared["classification"] == "expected_version_change"
    assert compared["first_material_difference"] is not None
    assert compared["identity_changed"] is True


def test_compact_payload_omits_decision_rows() -> None:
    compact = compact_replay_payload(_report())
    encoded = json.dumps(compact, sort_keys=True)
    assert "decision_evidence" not in compact
    assert "control_decisions" not in compact
    assert "engine_version" in compact
    assert "result_hash" in compact
    assert len(encoded.encode()) < 5120
