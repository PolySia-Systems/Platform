from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from polysia.application.services.research_readiness import research_readiness

T0 = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("elapsed", "eligible", "mapping", "execution", "source_ok", "invalid", "expected"),
    [
        (1200, 20, "0.95", "0.90", True, 0, "PROVISIONALLY_SUFFICIENT"),
        (1199, 20, "0.95", "0.90", True, 0, "WAITING_MINIMUM_PERIOD"),
        (1200, 19, "1", "1", True, 0, "INSUFFICIENT_DATA"),
        (1200, 20, "0.94", "0.90", True, 0, "INSUFFICIENT_DATA"),
        (1200, 20, "0.95", "0.89", True, 0, "INSUFFICIENT_DATA"),
        (1200, 20, "0.95", "0.90", False, 0, "BLOCKED_COVERAGE"),
        (1200, 20, "0.95", "0.90", True, 1, "BLOCKED_COVERAGE"),
    ],
)
def test_provisional_readiness_requires_closed_coverage_and_minimum_period(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    elapsed: int,
    eligible: int,
    mapping: str,
    execution: str,
    source_ok: bool,
    invalid: int,
    expected: str,
) -> None:
    import polysia.application.services.research_readiness as module

    monkeypatch.setattr(module, "replay_recorded_experiment", lambda *_args, **_kwargs:
        SimpleNamespace(
            valid_intervals=(object(),), invalid_intervals=(object(),) * invalid,
            economics=SimpleNamespace(
                eligible_observations=eligible,
                mapping_ratio=Decimal(mapping),
                execution_evidence_ratio=Decimal(execution),
                data_canary_status=(
                    "PASS" if eligible >= 20 and Decimal(mapping) >= Decimal("0.95")
                    and Decimal(execution) >= Decimal("0.90") else "FAIL"
                ),
            ),
        )
    )
    progress = research_readiness(
        tmp_path / "unused.sqlite3", run_id="run", t0=T0,
        observed_at=T0 + timedelta(seconds=elapsed),
        minimum_observation_seconds=1200, hard_limit_seconds=14400,
        source_health={"research_data_eligible": source_ok},
    )
    assert progress["status"] == expected
    assert progress["economic_status"] == "NOT_FINALIZED"
    assert progress["missing_eligible_observations"] == max(0, 20 - eligible)
