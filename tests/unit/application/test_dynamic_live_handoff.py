from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from polysia.application.ports.dynamic_shadow import (
    DynamicShadowRunRecord,
    DynamicShadowWalletResult,
    ProtectedShadowCandidate,
)
from polysia.application.services.dynamic_live_handoff import (
    DynamicLiveHandoffError,
    DynamicLiveHandoffService,
)
from polysia.domain.copytrading.dynamic_shadow import DynamicShadowMode
from polysia.domain.copytrading.live_experiment import load_candidate_bank

NOW = datetime(2026, 8, 25, 0, 0, tzinfo=UTC)


class _Store:
    def __init__(self, count: int = 110) -> None:
        self.initialized = False
        self.selection_run_id = "selection-run"
        self.candidates = tuple(_candidate(index) for index in range(1, count + 1))
        self.results = tuple(_result(index) for index in range(1, count + 1))
        self.run = _run()

    def initialize(self) -> None:
        self.initialized = True

    def current_candidates(
        self,
        source_id: str,
    ) -> tuple[str, tuple[ProtectedShadowCandidate, ...]]:
        assert source_id == "polycop"
        return self.selection_run_id, self.candidates

    def current_run(
        self,
        source_id: str,
        *,
        mode: DynamicShadowMode,
    ) -> DynamicShadowRunRecord | None:
        assert source_id == "polycop"
        assert mode is DynamicShadowMode.HISTORICAL
        return self.run

    def current_wallet_results(
        self,
        source_id: str,
        *,
        mode: DynamicShadowMode,
        limit: int = 100,
    ) -> tuple[DynamicShadowWalletResult, ...]:
        assert source_id == "polycop"
        assert mode is DynamicShadowMode.HISTORICAL
        return self.results[:limit]


def test_publishes_exact_versioned_protected_bank_without_address_output(
    tmp_path: Path,
) -> None:
    store = _Store()
    candidate_file = tmp_path / "runtime" / "candidates.txt"
    manifest_dir = tmp_path / "runtime" / "candidate-banks"

    outcome = DynamicLiveHandoffService(store).prepare(
        "polycop",
        candidate_file=candidate_file,
        manifest_dir=manifest_dir,
        now=NOW,
    )

    bank = load_candidate_bank(candidate_file.read_text(encoding="utf-8"))
    manifest = json.loads(outcome.manifest_file.read_text(encoding="utf-8"))
    assert store.initialized is True
    assert outcome.candidate_count == 102
    assert outcome.qualified_count == 110
    assert outcome.source_digest == bank.source_digest
    assert manifest["source_digest"] == bank.source_digest
    assert manifest["values_redacted"] is True
    assert "0x" not in json.dumps(outcome.to_dict())
    assert "0x" not in json.dumps(manifest)
    assert candidate_file.stat().st_nlink >= 2
    if os.name != "nt":
        assert candidate_file.stat().st_mode & 0o777 == 0o600
        assert manifest_dir.stat().st_mode & 0o777 == 0o700

    replay = DynamicLiveHandoffService(store).prepare(
        "polycop",
        candidate_file=candidate_file,
        manifest_dir=manifest_dir,
        now=NOW,
    )
    assert replay.source_digest == outcome.source_digest
    assert load_candidate_bank(candidate_file.read_text(encoding="utf-8")).source_digest == (
        outcome.source_digest
    )


def test_insufficient_evidence_preserves_last_known_good_file(tmp_path: Path) -> None:
    store = _Store(count=101)
    candidate_file = tmp_path / "runtime" / "candidates.txt"
    candidate_file.parent.mkdir(parents=True)
    candidate_file.write_text("last-known-good\n", encoding="utf-8")

    with pytest.raises(DynamicLiveHandoffError, match="Too few") as raised:
        DynamicLiveHandoffService(store).prepare(
            "polycop",
            candidate_file=candidate_file,
            manifest_dir=tmp_path / "runtime" / "candidate-banks",
            now=NOW,
        )

    assert raised.value.error_code == "insufficient_shadow_evidence"
    assert candidate_file.read_text(encoding="utf-8") == "last-known-good\n"


def test_rejects_historical_evidence_for_a_different_selection(tmp_path: Path) -> None:
    store = _Store()
    store.selection_run_id = "new-selection"

    with pytest.raises(DynamicLiveHandoffError, match="does not match") as raised:
        DynamicLiveHandoffService(store).prepare(
            "polycop",
            candidate_file=tmp_path / "candidates.txt",
            manifest_dir=tmp_path / "candidate-banks",
            now=NOW,
        )

    assert raised.value.error_code == "selection_shadow_mismatch"


def _candidate(index: int) -> ProtectedShadowCandidate:
    alpha = index <= 50
    stress = index > 50 or index == 1
    pools = tuple(
        pool
        for pool, included in (("SHADOW_ALPHA", alpha), ("SHADOW_STRESS", stress))
        if included
    )
    return ProtectedShadowCandidate(
        wallet_id=f"wallet-{index:03d}",
        address=f"0x{index:040x}",
        pools=pools,
        alpha_rank=index if alpha else None,
        stress_rank=(1 if index == 1 else index - 50) if stress else None,
    )


def _result(index: int) -> DynamicShadowWalletResult:
    candidate = _candidate(index)
    return DynamicShadowWalletResult(
        run_id="historical-run",
        wallet_id=candidate.wallet_id,
        mode=DynamicShadowMode.HISTORICAL,
        pools=candidate.pools,
        alpha_rank=candidate.alpha_rank,
        stress_rank=candidate.stress_rank,
        event_count=5,
        simulated_count=5,
        unknown_count=0,
        rejected_count=0,
        buy_count=3,
        sell_count=2,
        realized_pnl=Decimal(index) / Decimal("100"),
        fees=Decimal("0.01"),
        slippage=Decimal("0.01"),
        open_notional=Decimal("0"),
        policy_version="dynamic-shadow-v0.1",
        cost_model_version="cost-v1",
        window_start=NOW - timedelta(days=7),
        window_end=NOW,
    )


def _run() -> DynamicShadowRunRecord:
    return DynamicShadowRunRecord(
        run_id="historical-run",
        source_id="polycop",
        selection_run_id="selection-run",
        mode=DynamicShadowMode.HISTORICAL,
        policy_version="dynamic-shadow-v0.1",
        cost_model_version="cost-v1",
        window_start=NOW - timedelta(days=7),
        window_end=NOW,
        started_at=NOW - timedelta(minutes=2),
        completed_at=NOW - timedelta(minutes=1),
        status="succeeded",
        candidate_count=110,
        event_count=550,
        simulated_count=550,
        unknown_count=0,
        rejected_count=0,
        realized_pnl=Decimal("1"),
        fees=Decimal("1"),
        slippage=Decimal("1"),
    )
