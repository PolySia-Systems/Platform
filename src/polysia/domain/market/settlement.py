"""Venue-neutral acceptance of a final 0/1 settlement."""

from __future__ import annotations

from decimal import Decimal

from polysia.domain.market.models import MarketDetails

ZERO = Decimal("0")
ONE = Decimal("1")


def verified_settlement_prices(market: MarketDetails | None) -> dict[str, Decimal] | None:
    """Accept final settlement only from an explicitly closed 0/1 outcome set."""

    if market is None or market.closed is not True or len(market.outcomes) < 2:
        return None
    prices: dict[str, Decimal] = {}
    for outcome in market.outcomes:
        if outcome.token_id is None or outcome.price not in {ZERO, ONE}:
            return None
        prices[outcome.token_id] = outcome.price
    if len(prices) != len(market.outcomes) or sum(prices.values(), ZERO) != ONE:
        return None
    return prices


__all__ = ["verified_settlement_prices"]
