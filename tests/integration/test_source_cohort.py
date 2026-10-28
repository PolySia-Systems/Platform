"""Offline source-neutral identity/selection slices against temporary stores."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from polysia.application.services.source_cohort import (
    SourceCohortService,
    retained_native_candidates,
)
from polysia.domain.wallet_intelligence import (
    CandidateWalletDataset,
    CandidateWalletRecord,
    normalize_evm_wallet,
)
from polysia.domain.wallet_intelligence.source_cohort import (
    CohortSelectionPolicy,
    FollowerQualificationEvidence,
    RetainedCandidateSnapshot,
)
from polysia.storage.candidate_intelligence import CandidateIntelligenceRepository
from polysia.storage.wallet_intelligence import WalletIntelligenceRepository

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
D = Decimal


def wallet(number: int) -> str:
    return f"0x{number:040x}"


def wallet_id(number: int) -> str:
    return normalize_evm_wallet("polygon", wallet(number))[0]


def snapshot(
    source: str,
    numbers: tuple[int, ...],
    *,
    at: datetime = NOW,
    score: str = "99999999999",
) -> RetainedCandidateSnapshot:
    records = tuple(
        CandidateWalletRecord(
            wallet(number),
            rank,
            1,
            {"score": score},
            hashlib.sha256(f"{number}:{source}:{score}".encode()).hexdigest(),
        )
        for rank, number in enumerate(numbers, 1)
    )
    dataset = CandidateWalletDataset(
        source,
        "fixture-v1",
        at,
        1,
        records,
        hashlib.sha256("".join(row.row_digest for row in records).encode()).hexdigest(),
    )
    return RetainedCandidateSnapshot(dataset, "polygon", None, at, True, "BOUNDED_FIXTURE", None)


def policy(size: int = 2) -> CohortSelectionPolicy:
    return CohortSelectionPolicy(
        "fixture-selection-v1",
        size,
        20,
        timedelta(hours=1),
        D("0.03"),
        D("0.10"),
        D("4"),
        D("0.5"),
        D("0.7"),
        D("0.8"),
        D("2"),
    )


def evidence(number: int, *, net: str = "0.1") -> FollowerQualificationEvidence:
    return FollowerQualificationEvidence(
        wallet_id(number),
        f"fixture-follower-replay-{number}",
        NOW - timedelta(minutes=30),
        NOW - timedelta(seconds=10),
        NOW + timedelta(minutes=1),
        NOW - timedelta(seconds=5),
        NOW - timedelta(seconds=20),
        40,
        D(net),
        D("0.02"),
        D("0.01"),
        D("10"),
        D("10"),
        D("1"),
        D("0.1"),
        D("0.2"),
        D("0.95"),
        D("0.005"),
        True,
        True,
        (),
    )


def service(tmp_path: Path, clock=lambda: NOW) -> SourceCohortService:
    database = tmp_path / "candidates.sqlite3"
    return SourceCohortService(
        WalletIntelligenceRepository(database),
        CandidateIntelligenceRepository(database),
        clock=clock,
    )


@pytest.mark.asyncio
async def test_two_sources_share_canonical_identity_and_preserve_raw_provenance(
    tmp_path: Path,
) -> None:
    selection = service(tmp_path)
    native = await selection.ingest(snapshot("polymarket-native", (1, 2), score="1"))
    polycop = await selection.ingest(snapshot("polycop", (1, 3)))
    result = selection.select(
        (polycop, native),
        {wallet_id(1): evidence(1), wallet_id(2): evidence(2, net="0.2")},
        policy(),
    )
    assert result.selected_wallet_ids == (wallet_id(2), wallet_id(1))
    overlapping = next(row for row in result.candidates if row.wallet_id == wallet_id(1))
    assert overlapping.sources == ("polycop", "polymarket-native")
    assert (
        next(row for row in result.candidates if row.wallet_id == wallet_id(3)).state == "EXCLUDED"
    )
    assert (
        result.digest
        == selection.select(
            (native, polycop),
            {wallet_id(2): evidence(2, net="0.2"), wallet_id(1): evidence(1)},
            policy(),
        ).digest
    )
    with sqlite3.connect(tmp_path / "candidates.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM canonical_wallets").fetchone()[0] == 3
        assert connection.execute("SELECT count(*) FROM wallet_source_links").fetchone()[0] == 4
        metrics = [
            json.loads(row[0])
            for row in connection.execute("SELECT metrics_json FROM candidate_wallet_snapshot_rows")
        ]
    assert {row["score"] for row in metrics} == {"1", "99999999999"}
    assert all(row["_selection_provenance"]["effective_at"] is None for row in metrics)
    assert all(row["_selection_provenance"]["observed_at"] == NOW.isoformat() for row in metrics)
    assert all(item["provider_scores_comparable"] is False for item in result.sources)
    console = result.to_console_dict()
    assert console["funnel"] == {
        "discovered": 3,
        "current_discovered": 3,
        "qualified": 2,
        "selected": 2,
        "monitored": None,
    }
    assert len(console["records"]) == 3
    assert all(
        row["execution_eligibility"] == "NOT_AUTHORIZED_BY_DISCOVERY_OR_SELECTION"
        for row in console["records"]
    )
    assert wallet(1) not in json.dumps(console)
    assert "raw_candidate" not in json.dumps(console)
    assert "follower_net_per_unit" not in json.dumps(console)


@pytest.mark.asyncio
async def test_missing_independent_evidence_never_becomes_skill_or_authority(
    tmp_path: Path,
) -> None:
    selection = service(tmp_path)
    acquired = await selection.ingest(snapshot("polycop", (1,)))
    result = selection.select((acquired,), {}, policy())
    assert result.selected_wallet_ids == ()
    assert result.candidates[0].reasons == ("independent_follower_evidence_missing",)
    assert "authority" not in result.to_dict()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"entry_depth": None}, "economics_depth_cost_or_confidence_unknown"),
        ({"cost_per_unit": None}, "economics_depth_cost_or_confidence_unknown"),
        ({"route_compatible": None}, "collateral_or_settlement_route_unverified"),
        (
            {"evaluation_start": NOW - timedelta(seconds=15)},
            "selection_and_evaluation_windows_overlap",
        ),
        (
            {"evaluation_start": NOW - timedelta(seconds=1)},
            "evaluation_already_started_before_selection",
        ),
        ({"sample_count": 2}, "insufficient_samples"),
        ({"exit_depth": D("1")}, "follower_size_exceeds_entry_or_exit_depth"),
        ({"labels": ("hedging", "unknown")}, "strategy_compatibility_uncertain:hedging,unknown"),
        ({"complete": False}, "qualification_evidence_incomplete"),
        ({"available_at": NOW + timedelta(seconds=1)}, "qualification_unavailable_at_decision"),
    ],
)
async def test_qualification_is_default_denied_with_explainable_reasons(
    tmp_path: Path,
    changes: dict,
    reason: str,
) -> None:
    selection = service(tmp_path)
    acquired = await selection.ingest(snapshot("polycop", (1,)))
    result = selection.select(
        (acquired,), {wallet_id(1): replace(evidence(1), **changes)}, policy()
    )
    assert result.selected_wallet_ids == ()
    assert reason in result.candidates[0].reasons


@pytest.mark.asyncio
async def test_same_day_replacement_preserves_disappeared_and_rejects_superseded_input(
    tmp_path: Path,
) -> None:
    ticks = [NOW]
    selection = service(tmp_path, lambda: ticks[0])
    previous = await selection.ingest(snapshot("polycop", (1,)))
    ticks[0] += timedelta(minutes=1)
    current = await selection.ingest(snapshot("polycop", (2,), at=ticks[0]))
    assert previous.stored.snapshot_id != current.stored.snapshot_id
    with pytest.raises(ValueError, match="superseded"):
        selection.select((previous,), {}, policy())
    result = selection.select((current,), {}, policy())
    disappeared = next(row for row in result.candidates if row.wallet_id == wallet_id(1))
    assert disappeared.state == "DISAPPEARED"
    assert disappeared.sources == ("polycop",)
    assert disappeared.current_sources == ()


@pytest.mark.asyncio
async def test_incomplete_source_never_replaces_last_healthy_snapshot(tmp_path: Path) -> None:
    selection = service(tmp_path)
    healthy = await selection.ingest(snapshot("polycop", (1,)))
    with pytest.raises(ValueError, match="incomplete"):
        await selection.ingest(replace(snapshot("polycop", (2,)), complete=False))
    assert (
        selection.source_store.source_state("polycop").current_snapshot_id
        == healthy.stored.snapshot_id
    )
    assert selection.select((healthy,), {}, policy()).candidates[0].wallet_id == wallet_id(1)


@pytest.mark.asyncio
async def test_replay_is_content_bound_and_does_not_duplicate_canonical_rows(
    tmp_path: Path,
) -> None:
    selection = service(tmp_path)
    first = await selection.ingest(snapshot("polycop", (1, 2)))
    second = await selection.ingest(snapshot("polycop", (1, 2)))
    assert first.stored.snapshot_id == second.stored.snapshot_id
    with sqlite3.connect(tmp_path / "candidates.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM canonical_wallets").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM candidate_source_runs").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_equal_raw_data_from_different_sources_cannot_collide_in_run_identity(
    tmp_path: Path,
) -> None:
    selection = service(tmp_path)
    first = snapshot("polycop", (1,))
    second = replace(first, dataset=replace(first.dataset, source_id="polymarket-native"))
    one = await selection.ingest(first)
    two = await selection.ingest(second)
    assert one.stored.run_id != two.stored.run_id
    assert one.wallet_ids == two.wallet_ids


@pytest.mark.asyncio
async def test_selection_digest_binds_exact_independent_qualification_evidence(
    tmp_path: Path,
) -> None:
    selection = service(tmp_path)
    acquired = await selection.ingest(snapshot("polycop", (1,)))
    first = selection.select((acquired,), {wallet_id(1): evidence(1)}, policy())
    second = selection.select((acquired,), {wallet_id(1): evidence(1, net="0.2")}, policy())
    assert first.selected_wallet_ids == second.selected_wallet_ids
    assert first.digest != second.digest
    assert first.to_dict()["qualification_evidence"][0]["follower_net_per_unit"] == "0.1"


@pytest.mark.asyncio
async def test_selection_digest_binds_the_full_policy_even_when_version_and_outcomes_match(
    tmp_path: Path,
) -> None:
    selection = service(tmp_path)
    acquired = await selection.ingest(snapshot("polycop", (1,)))
    original = policy()
    changed = replace(
        original,
        maximum_spread=D("0.04"),
        freshness=timedelta(minutes=45, microseconds=1),
    )
    qualification = {wallet_id(1): evidence(1)}
    first = selection.select((acquired,), qualification, original)
    second = selection.select((acquired,), qualification, changed)
    assert first.policy_version == second.policy_version
    assert first.candidates == second.candidates
    assert first.digest != second.digest
    assert first.selection_policy == original
    assert second.selection_policy == changed
    frozen = second.to_dict()["selection_policy"]
    assert frozen["maximum_spread"] == "0.04"
    assert frozen["freshness"] == {"days": 0, "seconds": 2700, "microseconds": 1}
    assert "selection_policy" not in second.to_console_dict()


@pytest.mark.asyncio
async def test_stale_discovery_cannot_be_refreshed_by_current_qualification(tmp_path: Path) -> None:
    selection = service(tmp_path)
    acquired = await selection.ingest(snapshot("polycop", (1,), at=NOW - timedelta(hours=2)))
    result = selection.select((acquired,), {wallet_id(1): evidence(1)}, policy())
    assert result.selected_wallet_ids == ()
    assert "all_discovery_observations_stale_or_future" in result.candidates[0].reasons


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [100, 500, 1000])
async def test_large_offline_discovery_pool_is_separate_from_selected_cohort(
    tmp_path: Path,
    count: int,
) -> None:
    selection = service(tmp_path)
    acquired = await selection.ingest(snapshot("polycop", tuple(range(1, count + 1))))
    result = selection.select(
        (acquired,),
        {wallet_id(number): evidence(number) for number in range(1, count + 1)},
        policy(size=3),
    )
    assert len(result.candidates) == count
    assert len(result.selected_wallet_ids) == 3
    assert sum(row.state == "QUALIFIED" for row in result.candidates) == count - 3
    assert "live_subscriptions" not in result.to_dict()


def test_native_retained_bridge_preserves_sample_warning_without_a_score() -> None:
    candidate = {
        "wallet_id": wallet_id(1),
        "address": wallet(1),
        "state": "ACTIVITY_CONFIRMED",
        "complete_activity_rows": 3,
        "last_qualifying_activity": NOW.isoformat(),
        "execution_eligibility": "ELIGIBLE_FOR_RESEARCH",
        "exclusions": [],
    }
    raw = {
        "source": "polymarket-native",
        "profile": "native-recent-activity/v1",
        "coverage": "COMPLETE_WALLET_ACTIVITY_WITH_SAMPLED_SEEDS",
        "cutoff": NOW.isoformat(),
        "window_start": (NOW - timedelta(minutes=5)).isoformat(),
        "candidates": [candidate],
        "seed_coverage": "FIRST_PAGE_SAMPLE_NOT_EXHAUSTIVE",
    }
    raw["digest"] = hashlib.sha256(
        json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    retained = retained_native_candidates(raw)
    assert retained.confidence is None and retained.effective_at is None
    metrics = retained.dataset.records[0].metrics
    assert metrics["skill_established"] is False
    assert "score" not in metrics
    assert "address" not in metrics["raw_candidate"]
    raw["candidates"][0]["address"] = wallet(2)
    with pytest.raises(ValueError, match="digest"):
        retained_native_candidates(raw)
