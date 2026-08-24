from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from polysia.domain.wallet_intelligence.candidate_intelligence import (
    CandidateStatus,
    DataReadinessStatus,
)
from polysia.domain.wallet_intelligence.copyability_selection import (
    CopyabilityEvidence,
    SelectionPoolId,
    SelectionStatus,
    select_copyability_pools,
)


def _evidence(
    wallet_id: str,
    *,
    metrics: dict[str, object],
    rank: int = 1,
    readiness: DataReadinessStatus = DataReadinessStatus.READY,
    rank_delta_7d: int | None = None,
    rank_delta_30d: int | None = None,
    score_delta_7d: Decimal | None = None,
    rank_stability: Decimal | None = None,
) -> CopyabilityEvidence:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    return CopyabilityEvidence(
        wallet_id=wallet_id,
        stage2_run_id="stage2-run",
        source_id="polycop",
        source_snapshot_id="snap-1",
        source_rank=rank,
        source_score=Decimal("80"),
        source_metrics_json=json.dumps(metrics, sort_keys=True),
        effective_at=now,
        observed_at=now,
        ingested_at=now,
        stage2_calculated_at=now,
        observation_count=1,
        observed_days=1,
        presence_ratio=Decimal("1"),
        rank_delta_7d=rank_delta_7d,
        rank_delta_30d=rank_delta_30d,
        score_delta_7d=score_delta_7d,
        score_delta_30d=None,
        rank_stability=rank_stability,
        score_stability=None,
        data_readiness_status=readiness,
        candidate_status=CandidateStatus.SELECTED
        if readiness is DataReadinessStatus.READY
        else CandidateStatus.WATCHLIST,
    )


def test_percentiles_keep_nulls_and_handle_negatives_and_ties() -> None:
    calculated_at = datetime(2026, 8, 24, 1, tzinfo=UTC)
    scores, memberships = select_copyability_pools(
        (
            _evidence("w-a", metrics={"actual_pnl": "-10", "copy_backtest_pnl": "5"}, rank=1),
            _evidence("w-b", metrics={"actual_pnl": "10", "copy_backtest_pnl": "50"}, rank=2),
            _evidence("w-c", metrics={"actual_pnl": "10", "copy_backtest_pnl": "50"}, rank=3),
            _evidence("w-d", metrics={"copy_backtest_pnl": "1"}, rank=4),
        ),
        calculated_at=calculated_at,
        alpha_size=2,
        stress_size=2,
    )
    by_id = {item.wallet_id: item for item in scores}
    assert by_id["w-a"].performance_score == Decimal("0")
    assert by_id["w-b"].performance_score == by_id["w-c"].performance_score == Decimal("75")
    assert by_id["w-d"].performance_score is None


def test_null_history_does_not_block_alpha_or_become_zero() -> None:
    calculated_at = datetime(2026, 8, 24, 1, tzinfo=UTC)
    scores, memberships = select_copyability_pools(
        (
            _evidence(
                "w-1",
                metrics={
                    "copy_backtest_pnl": "80",
                    "copy_loss_rate": "0.1",
                    "actual_pnl": "20",
                    "markets_traded": 10,
                    "trading_days": 20,
                    "trading_volume": "1000",
                },
            ),
        ),
        calculated_at=calculated_at,
        alpha_size=50,
        stress_size=100,
    )
    assert scores[0].status is SelectionStatus.SELECTED
    assert scores[0].alpha_score is not None
    assert "historical_windows_incomplete" in scores[0].reasons
    assert any(item.pool_id is SelectionPoolId.SHADOW_ALPHA for item in memberships)
    assert any(item.pool_id is SelectionPoolId.SHADOW_STRESS for item in memberships)


def test_missing_source_copyability_metrics_cannot_enter_alpha() -> None:
    calculated_at = datetime(2026, 8, 24, 1, tzinfo=UTC)
    scores, memberships = select_copyability_pools(
        tuple(
            _evidence(f"w-{index:03d}", metrics={}, rank=index + 1)
            for index in range(60)
        ),
        calculated_at=calculated_at,
    )

    assert all(score.copyability_score is None for score in scores)
    assert all("copyability_evidence_missing" in score.reasons for score in scores)
    assert not any(
        item.pool_id is SelectionPoolId.SHADOW_ALPHA for item in memberships
    )


def test_invalid_metrics_are_rejected_not_watchlisted() -> None:
    calculated_at = datetime(2026, 8, 24, 1, tzinfo=UTC)
    scores, memberships = select_copyability_pools(
        (
            _evidence("good", metrics={"copy_backtest_pnl": "10", "markets_traded": 3}),
            _evidence("bad", metrics={"hedged_pct": "150"}),
            _evidence(
                "invalid-ready",
                metrics={"copy_backtest_pnl": "1"},
                readiness=DataReadinessStatus.INVALID,
            ),
        ),
        calculated_at=calculated_at,
        alpha_size=50,
        stress_size=100,
    )
    by_id = {item.wallet_id: item for item in scores}
    assert by_id["bad"].status is SelectionStatus.REJECTED
    assert by_id["invalid-ready"].status is SelectionStatus.REJECTED
    assert by_id["good"].status is not SelectionStatus.REJECTED
    rejected = {
        item.wallet_id for item in memberships if item.pool_id is SelectionPoolId.REJECTED
    }
    assert rejected == {"bad", "invalid-ready"}


@pytest.mark.parametrize(
    ("metrics", "reason"),
    (
        ({"buy_price": "1.01"}, "buy_price_out_of_range"),
        ({"copy_loss_rate": "-1"}, "copy_loss_rate_out_of_range"),
        ({"r20_slip": "-0.01"}, "r20_slip_out_of_range"),
        ({"r20_wr": "999"}, "r20_wr_out_of_range"),
        ({"win_rate": "100.01"}, "win_rate_out_of_range"),
    ),
)
def test_bounded_metrics_outside_source_units_are_rejected(
    metrics: dict[str, object],
    reason: str,
) -> None:
    calculated_at = datetime(2026, 8, 24, 1, tzinfo=UTC)
    scores, memberships = select_copyability_pools(
        (_evidence("bad-range", metrics=metrics),),
        calculated_at=calculated_at,
    )

    assert scores[0].status is SelectionStatus.REJECTED
    assert reason in scores[0].reasons
    assert memberships[0].pool_id is SelectionPoolId.REJECTED


def test_bounded_metric_endpoints_are_accepted() -> None:
    calculated_at = datetime(2026, 8, 24, 1, tzinfo=UTC)
    scores, _memberships = select_copyability_pools(
        (
            _evidence(
                "bounds",
                metrics={
                    "buy_price": "1",
                    "copy_loss_rate": "0",
                    "r20_slip": "100",
                    "r20_wr": "0",
                    "win_rate": "100",
                },
            ),
        ),
        calculated_at=calculated_at,
    )

    assert scores[0].status is not SelectionStatus.REJECTED


def test_alpha_and_stress_are_independent_and_live_review_is_empty() -> None:
    calculated_at = datetime(2026, 8, 24, 1, tzinfo=UTC)
    wallets = []
    for index in range(6):
        wallets.append(
            _evidence(
                f"w-{index:02d}",
                metrics={
                    "copy_backtest_pnl": str(100 - index),
                    "actual_pnl": str(50 - index),
                    "markets_traded": 100 + index,
                    "trading_days": 30,
                    "trading_volume": str(1000 + index),
                    "hedged": 0,
                    "hedged_pct": "0",
                },
                rank=index + 1,
            )
        )
    scores, memberships = select_copyability_pools(
        tuple(wallets),
        calculated_at=calculated_at,
        alpha_size=2,
        stress_size=2,
    )
    alpha = [
        item.wallet_id
        for item in memberships
        if item.pool_id is SelectionPoolId.SHADOW_ALPHA
    ]
    stress = [
        item.wallet_id
        for item in memberships
        if item.pool_id is SelectionPoolId.SHADOW_STRESS
    ]
    assert alpha == ["w-00", "w-01"]
    assert stress == ["w-05", "w-04"]
    live_review = {
        item.wallet_id
        for item in memberships
        if item.pool_id is SelectionPoolId.LIVE_REVIEW_CANDIDATE
    }
    assert not live_review
    watchlist = {item.wallet_id for item in scores if item.status is SelectionStatus.WATCHLIST}
    assert "w-02" in watchlist
    overlap = set(alpha) & set(stress)
    assert overlap == set()


def test_high_hedge_proxy_excludes_alpha_but_does_not_reject() -> None:
    calculated_at = datetime(2026, 8, 24, 1, tzinfo=UTC)
    scores, memberships = select_copyability_pools(
        (
            _evidence(
                "hedged",
                metrics={
                    "copy_backtest_pnl": "90",
                    "markets_traded": 5,
                    "hedged": 1,
                    "hedged_pct": "80",
                },
            ),
        ),
        calculated_at=calculated_at,
    )
    assert scores[0].status is not SelectionStatus.REJECTED
    assert not any(item.pool_id is SelectionPoolId.SHADOW_ALPHA for item in memberships)
    assert "polycop_hedge_proxy_high" in scores[0].reasons


def test_inverted_loss_rate_ranks_low_loss_higher() -> None:
    calculated_at = datetime(2026, 8, 24, 1, tzinfo=UTC)
    scores, _memberships = select_copyability_pools(
        (
            _evidence("low-loss", metrics={"copy_backtest_pnl": "10", "copy_loss_rate": "0.1"}),
            _evidence("high-loss", metrics={"copy_backtest_pnl": "10", "copy_loss_rate": "0.9"}),
        ),
        calculated_at=calculated_at,
        alpha_size=2,
        stress_size=2,
    )
    by_id = {item.wallet_id: item for item in scores}
    assert by_id["low-loss"].copyability_score is not None
    assert by_id["high-loss"].copyability_score is not None
    assert by_id["low-loss"].copyability_score > by_id["high-loss"].copyability_score


def test_alpha_and_stress_may_overlap() -> None:
    calculated_at = datetime(2026, 8, 24, 1, tzinfo=UTC)
    scores, memberships = select_copyability_pools(
        (
            _evidence(
                "both",
                metrics={
                    "copy_backtest_pnl": "90",
                    "markets_traded": 90,
                    "trading_days": 90,
                    "trading_volume": "9000",
                },
            ),
            _evidence(
                "other",
                metrics={
                    "copy_backtest_pnl": "10",
                    "markets_traded": 10,
                    "trading_days": 10,
                    "trading_volume": "100",
                },
            ),
        ),
        calculated_at=calculated_at,
        alpha_size=2,
        stress_size=2,
    )
    alpha = {
        item.wallet_id for item in memberships if item.pool_id is SelectionPoolId.SHADOW_ALPHA
    }
    stress = {
        item.wallet_id for item in memberships if item.pool_id is SelectionPoolId.SHADOW_STRESS
    }
    assert "both" in alpha
    assert "both" in stress
    selected = {item.wallet_id for item in scores if item.status is SelectionStatus.SELECTED}
    assert "both" in selected
