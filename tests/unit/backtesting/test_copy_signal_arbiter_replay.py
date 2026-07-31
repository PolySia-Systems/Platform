from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from polysia.backtesting.copy_signal_arbiter_replay import (
    CopySignalArbiterReplay,
    CopySignalReplayDataset,
    CopySignalReplayError,
    CopySignalReplayManifest,
    CopySignalReplayRecord,
    convert_tiny_live_events_to_unknown_replay,
    load_copy_signal_replay_jsonl,
)
from polysia.domain.copytrading.signal_arbiter import (
    ArbiterMode,
    ClosedSignalOutcome,
    ExecutableEvidence,
    FollowerExecutionOutcome,
    SignalCandidate,
    SignalContext,
)

NOW = datetime(2026, 8, 1, 10, tzinfo=UTC)
CONTEXT = SignalContext(market_type="btc-updown", timeframe_seconds=900)


def _record(
    *,
    snapshot: str,
    leader: str,
    sequence: int,
    decision_at: datetime,
    net_return: str | None,
    follower_pnl: str | None,
    executable_price: str | None = "0.47",
) -> CopySignalReplayRecord:
    executed_at = decision_at - timedelta(seconds=5)
    evidence = ExecutableEvidence(
        leader_price=Decimal("0.50"),
        executable_price=(
            None if executable_price is None else Decimal(executable_price)
        ),
        quantity=Decimal("5"),
        best_bid=Decimal("0.46"),
        best_ask=Decimal("0.50"),
        expected_fees=Decimal("0"),
        estimated_slippage=Decimal("0"),
        captured_at=decision_at,
    )
    candidate = SignalCandidate(
        signal_id=f"signal-{leader}-{sequence}",
        leader_key=leader,
        context=CONTEXT,
        executed_at=executed_at,
        observed_at=decision_at - timedelta(seconds=1),
        safety_eligible=True,
        safety_reason="independent gates passed",
        evidence=evidence,
    )
    closed_at = decision_at + timedelta(minutes=1)
    wallet_outcome = (
        None
        if net_return is None
        else ClosedSignalOutcome(
            outcome_id=f"outcome-{leader}-{sequence}",
            leader_key=leader,
            context=CONTEXT,
            opened_at=executed_at,
            closed_at=closed_at,
            net_return=Decimal(net_return),
            maximum_drawdown=Decimal("0.02"),
        )
    )
    follower_outcome = (
        None
        if follower_pnl is None
        else FollowerExecutionOutcome(
            execution_id=f"execution-{leader}-{sequence}",
            leader_key=leader,
            context=CONTEXT,
            closed_at=closed_at,
            filled=True,
            net_pnl=Decimal(follower_pnl),
            execution_cost=Decimal("0.01"),
            slippage=Decimal("0.00"),
            completed_cycle=True,
        )
    )
    return CopySignalReplayRecord(
        snapshot_id=snapshot,
        decision_at=decision_at,
        candidate=candidate,
        wallet_outcome=wallet_outcome,
        follower_outcome=follower_outcome,
    )


def _dataset(records: tuple[CopySignalReplayRecord, ...]) -> CopySignalReplayDataset:
    return CopySignalReplayDataset(
        manifest=CopySignalReplayManifest(
            schema_version="1",
            outcome_labeling_version="fixed-horizon-v1",
            evaluation_horizon_seconds=900,
            generated_at=NOW + timedelta(days=1),
        ),
        records=records,
    )


def test_replay_is_walk_forward_and_scores_unselected_wallet_signals() -> None:
    first = (
        _record(
            snapshot="snapshot-1",
            leader="leader-001",
            sequence=1,
            decision_at=NOW,
            net_return="-0.20",
            follower_pnl="-0.10",
        ),
        _record(
            snapshot="snapshot-1",
            leader="leader-002",
            sequence=1,
            decision_at=NOW,
            net_return="0.20",
            follower_pnl="0.10",
        ),
    )
    second_at = NOW + timedelta(minutes=2)
    second = (
        _record(
            snapshot="snapshot-2",
            leader="leader-001",
            sequence=2,
            decision_at=second_at,
            net_return="-0.10",
            follower_pnl="-0.05",
        ),
        _record(
            snapshot="snapshot-2",
            leader="leader-002",
            sequence=2,
            decision_at=second_at,
            net_return="0.10",
            follower_pnl="0.05",
        ),
    )

    result = CopySignalArbiterReplay().run(_dataset(first + second))
    full = next(mode for mode in result.modes if mode.mode is ArbiterMode.FULL)
    first_decision = full.decisions[0]
    second_decision = full.decisions[1]
    second_assessments = second_decision["assessments"]

    assert first_decision["selected_leader_key"] == "leader-001"
    assert second_decision["selected_leader_key"] == "leader-002"
    assert isinstance(second_assessments, list)
    leader_two = next(
        assessment
        for assessment in second_assessments
        if assessment["leader_key"] == "leader-002"
    )
    assert leader_two["wallet_score"]["sample_count"] == 1
    assert result.conclusion == "INCONCLUSIVE"


def test_replay_dataset_rejects_duplicate_signal_identifiers() -> None:
    record = _record(
        snapshot="snapshot-1",
        leader="leader-001",
        sequence=1,
        decision_at=NOW,
        net_return=None,
        follower_pnl=None,
    )

    with pytest.raises(ValueError, match="unique"):
        _dataset((record, record))


def test_replay_reports_consistent_chronological_pnl_windows() -> None:
    records = tuple(
        _record(
            snapshot=f"snapshot-{index}",
            leader=f"leader-{index:03d}",
            sequence=index,
            decision_at=NOW + timedelta(minutes=index * 2),
            net_return="0.10",
            follower_pnl="0.10",
        )
        for index in range(30)
    )

    result = CopySignalArbiterReplay().run(_dataset(records))

    assert all(mode.pnl_stability == "CONSISTENT" for mode in result.modes)
    assert all(len(mode.pnl_window_means) == 3 for mode in result.modes)


def test_current_mode_preserves_hard_one_leader_attempt_per_run() -> None:
    result = CopySignalArbiterReplay().run(
        _dataset(
            (
                _record(
                    snapshot="snapshot-1",
                    leader="leader-001",
                    sequence=1,
                    decision_at=NOW,
                    net_return="0.10",
                    follower_pnl="0.10",
                ),
                _record(
                    snapshot="snapshot-2",
                    leader="leader-001",
                    sequence=2,
                    decision_at=NOW + timedelta(minutes=2),
                    net_return="0.10",
                    follower_pnl="0.10",
                ),
            )
        )
    )
    current = next(mode for mode in result.modes if mode.mode is ArbiterMode.CURRENT)
    experimental = next(
        mode for mode in result.modes if mode.mode is ArbiterMode.COOLDOWN_ONLY
    )

    assert current.selected_count == 1
    assert experimental.selected_count == 2


def test_missing_book_evidence_remains_unknown_and_inconclusive() -> None:
    result = CopySignalArbiterReplay().run(
        _dataset(
            (
                _record(
                    snapshot="snapshot-1",
                    leader="leader-001",
                    sequence=1,
                    decision_at=NOW,
                    net_return=None,
                    follower_pnl=None,
                    executable_price=None,
                ),
            )
        )
    )

    assert result.conclusion == "INCONCLUSIVE"
    assert all(mode.selected_count == 0 for mode in result.modes)
    assert all(mode.unknown_evidence == 1 for mode in result.modes)


def test_filled_outcome_without_cost_evidence_is_not_comparable() -> None:
    base = _record(
        snapshot="snapshot-1",
        leader="leader-001",
        sequence=1,
        decision_at=NOW,
        net_return="0.10",
        follower_pnl=None,
    )
    record = CopySignalReplayRecord(
        snapshot_id=base.snapshot_id,
        decision_at=base.decision_at,
        candidate=base.candidate,
        wallet_outcome=base.wallet_outcome,
        follower_outcome=FollowerExecutionOutcome(
            execution_id="execution-incomplete",
            leader_key=base.candidate.leader_key,
            context=base.candidate.context,
            closed_at=NOW + timedelta(minutes=1),
            filled=True,
            net_pnl=Decimal("0.10"),
            execution_cost=None,
            slippage=None,
            completed_cycle=True,
        ),
    )

    result = CopySignalArbiterReplay().run(_dataset((record,)))

    assert all(mode.known_fill_count == 0 for mode in result.modes)
    assert all(mode.unknown_fill_count == 1 for mode in result.modes)
    assert result.conclusion == "INCONCLUSIVE"


def test_jsonl_loader_requires_manifest_and_rejects_wallet_values(tmp_path) -> None:
    no_manifest = tmp_path / "no-manifest.jsonl"
    no_manifest.write_text(
        json.dumps({"record_type": "signal"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CopySignalReplayError, match="frozen manifest"):
        load_copy_signal_replay_jsonl(no_manifest)

    wallet = tmp_path / "wallet.jsonl"
    wallet.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "record_type": "manifest",
                        "schema_version": "1",
                        "outcome_labeling_version": "fixed-v1",
                        "evaluation_horizon_seconds": 900,
                        "generated_at": NOW.isoformat(),
                    }
                ),
                json.dumps(
                    {
                        "record_type": "signal",
                        "leader_key": "0x1111111111111111111111111111111111111111",
                    }
                ),
            )
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CopySignalReplayError, match="wallet-like"):
        load_copy_signal_replay_jsonl(wallet)


def test_jsonl_loader_freezes_labeling_and_parses_sanitized_record(tmp_path) -> None:
    path = tmp_path / "replay.jsonl"
    path.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "record_type": "manifest",
                        "schema_version": "1",
                        "outcome_labeling_version": "fixed-v1",
                        "evaluation_horizon_seconds": 900,
                        "generated_at": (NOW + timedelta(hours=1)).isoformat(),
                    }
                ),
                json.dumps(
                    {
                        "record_type": "signal",
                        "market_reference": "0x" + ("a" * 64),
                        "snapshot_id": "snapshot-1",
                        "signal_id": "signal-1",
                        "leader_key": "candidate-001",
                        "context": {
                            "market_type": "btc-updown",
                            "timeframe_seconds": 900,
                        },
                        "executed_at": (NOW - timedelta(seconds=5)).isoformat(),
                        "observed_at": (NOW - timedelta(seconds=1)).isoformat(),
                        "decision_at": NOW.isoformat(),
                        "safety_eligible": True,
                        "safety_reason": "independent gates passed",
                        "evidence": {
                            "leader_price": "0.50",
                            "executable_price": "0.47",
                            "quantity": "5",
                            "best_bid": "0.46",
                            "best_ask": "0.50",
                            "expected_fees": "0",
                            "estimated_slippage": "0",
                            "captured_at": NOW.isoformat(),
                        },
                    }
                ),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    dataset = load_copy_signal_replay_jsonl(path)

    assert dataset.manifest.outcome_labeling_version == "fixed-v1"
    assert dataset.records[0].candidate.leader_key == "candidate-001"


def test_legacy_converter_preserves_unknown_evidence_and_filters_increases(
    tmp_path,
) -> None:
    source = tmp_path / "events.jsonl"
    target = tmp_path / "replay.jsonl"
    market_reference = "0x" + ("a" * 64)
    source.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "event_id": "open-1",
                        "executed_at": (NOW - timedelta(seconds=5)).isoformat(),
                        "leader_alias": "candidate-001",
                        "market_reference": market_reference,
                        "observed_at": NOW.isoformat(),
                        "position_effect": "OPEN",
                        "trade_action": "BUY",
                    }
                ),
                json.dumps(
                    {
                        "event_id": "increase-1",
                        "executed_at": (NOW - timedelta(seconds=4)).isoformat(),
                        "leader_alias": "candidate-001",
                        "market_reference": market_reference,
                        "observed_at": NOW.isoformat(),
                        "position_effect": "INCREASE",
                        "trade_action": "BUY",
                    }
                ),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    dataset = convert_tiny_live_events_to_unknown_replay(
        source,
        target,
        generated_at=NOW + timedelta(hours=1),
    )
    result = CopySignalArbiterReplay().run(dataset)

    assert dataset.manifest.outcome_labeling_version == "legacy-no-outcomes-v1"
    assert len(dataset.records) == 1
    assert dataset.records[0].candidate.evidence.leader_price is None
    assert all(mode.unknown_evidence == 1 for mode in result.modes)
    assert all(mode.pnl_stability == "UNKNOWN" for mode in result.modes)
    assert result.conclusion == "INCONCLUSIVE"
