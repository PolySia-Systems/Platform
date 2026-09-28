from __future__ import annotations

from decimal import Decimal

import pytest

from polysia.adapters.polymarket.research_sources import (
    MarketDiscoverySnapshot,
    OfficialMarketStreamSource,
)
from polysia.cli_commands import research_evidence_cli
from polysia.domain.market import MarketDetails, MarketFeeSchedule, MarketOutcomeSummary


@pytest.mark.asyncio
async def test_terminal_settlement_composition_requires_full_market_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "token-yes"
    condition = "condition-1"
    fee = MarketFeeSchedule(enabled=False)

    class Discovery:
        def __init__(self, *_args: object) -> None:
            pass

        async def refresh(self) -> MarketDiscoverySnapshot:
            return MarketDiscoverySnapshot(
                token_markets={token: condition}, fee_schedules={token: fee}
            )

    class Adapter:
        def __init__(self) -> None:
            self.ambiguous = True

        async def get_order_books(self, _tokens: tuple[str, ...]) -> dict[str, object]:
            return {}

        async def get_market_by_condition_id(self, _condition: str) -> MarketDetails:
            return MarketDetails(
                id=condition, condition_id=condition, closed=True,
                outcomes=(
                    MarketOutcomeSummary(label="Yes", token_id=token, price=Decimal("1")),
                    MarketOutcomeSummary(
                        label="No", token_id="token-no",
                        price=Decimal("1" if self.ambiguous else "0"),
                    ),
                ),
            )

    adapter = Adapter()
    monkeypatch.setattr(
        research_evidence_cli, "PolymarketPublicAdapter", lambda: adapter
    )
    monkeypatch.setattr(
        "polysia.adapters.polymarket.research_sources.FollowedMarketDiscovery", Discovery
    )
    sources, _ = await research_evidence_cli.build_persistent_sources_from_aliases(
        {"pub-test": "0x" + "1" * 40}, transport=object()  # type: ignore[arg-type]
    )
    stream = next(source for source in sources if isinstance(source, OfficialMarketStreamSource))
    assert await stream.capture_terminal_evidence(
        run_id="run", token_markets={token: condition}
    ) == ()
    adapter.ambiguous = False
    accepted = await stream.capture_terminal_evidence(
        run_id="run", token_markets={token: condition}
    )
    assert len(accepted) == 1
    assert accepted[0].provenance["settlement_price"] == "1"
