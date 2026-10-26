from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from polysia.domain.copytrading import LeaderTradeAction
from polysia.domain.copytrading.continuous_shadow import ContinuousShadowConfig
from polysia.domain.financial_session import SessionBlocked
from polysia.domain.market import OrderBookLevel
from polysia.storage.dynamic_shadow import DynamicShadowRepository
from polysia.storage.follower_samples import retained_follower_samples
from tests.integration.test_continuous_shadow_portfolio import (
    NOW,
    _Clock,
    _EventSpec,
    _MarketPort,
    _Scenario,
    _seed_stage3,
    _service,
    _shadow_database,
    _Source,
)


@pytest.mark.asyncio
async def test_samples_are_produced_from_committed_causal_quotes_and_reject_tampering(
    tmp_path: Path,
) -> None:
    database = tmp_path / "source.sqlite3"
    _seed_stage3(database)
    clock, scenario = _Clock(NOW), _Scenario()

    class Market(_MarketPort):
        async def get_order_book(self, token_id):
            original = await super().get_order_book(token_id)
            later = self.clock.value >= NOW + timedelta(minutes=4)
            return original.model_copy(
                update={
                    "bids": (
                        OrderBookLevel(
                            price=Decimal("0.6") if later else Decimal("0.39"), size=Decimal(20)
                        ),
                    ),
                    "asks": (
                        OrderBookLevel(
                            price=Decimal("0.61") if later else Decimal("0.41"), size=Decimal(20)
                        ),
                    ),
                }
            )

    class Source(_Source):
        async def read_page(self, *args, **kwargs):
            page = await super().read_page(*args, **kwargs)
            return replace(
                page,
                events=tuple(
                    replace(
                        row,
                        schema_version="corroborated-ctf-v2/v1",
                        source_occurrence_id=row.event_id,
                    )
                    for row in page.events
                ),
            )

    service = _service(
        database, scenario, Market(clock), clock, config=ContinuousShadowConfig(code_sha="a" * 40)
    )
    service._source_factory = lambda leaders: Source(dict(leaders), scenario)
    experiment = service.start("polycop")
    _, candidates = DynamicShadowRepository(database).current_candidates("polycop")
    leader = candidates[0].wallet_id
    for index in (1, 2):
        scenario.events.setdefault(leader, []).append(
            _EventSpec(
                str(index),
                LeaderTradeAction.BUY,
                NOW + timedelta(seconds=index * 120 - 20),
                Decimal("0.4"),
            )
        )
        clock.value = NOW + timedelta(minutes=index * 2)
        await service.poll("polycop")
    samples = retained_follower_samples(
        _shadow_database(database),
        experiment.experiment_id,
        selection_start=NOW,
        selection_end=NOW + timedelta(minutes=5),
        horizon_seconds=120,
        tolerance_seconds=30,
    )
    assert len(samples) == 1
    assert samples[0].complete and samples[0].forward_bid == Decimal("0.6")
    assert samples[0].entry_price == Decimal("0.41")
    assert samples[0].cost_per_share > 0
    assert samples[0].entry_depth == samples[0].exit_depth == 20
    with sqlite3.connect(_shadow_database(database)) as connection:
        connection.execute(
            "UPDATE continuous_shadow_opportunities SET evidence_digest=?", ("0" * 64,)
        )
    with pytest.raises(SessionBlocked, match="binding_changed"):
        retained_follower_samples(
            _shadow_database(database),
            experiment.experiment_id,
            selection_start=NOW,
            selection_end=NOW + timedelta(minutes=5),
            horizon_seconds=120,
            tolerance_seconds=30,
        )
