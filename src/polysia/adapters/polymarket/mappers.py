from __future__ import annotations

from typing import Any

from polysia.domain.market import MarketDetails, MarketOutcomeSummary, MarketSummary


class PolymarketMarketMapper:
    """Translate official SDK objects into canonical PolySia market models."""

    def to_summary(self, market: Any) -> MarketSummary:
        state = getattr(market, "state", None)
        metrics = getattr(market, "metrics", None)
        prices = getattr(market, "prices", None)

        return MarketSummary(
            id=str(market.id),
            slug=self.optional_str(getattr(market, "slug", None)),
            question=self.optional_str(getattr(market, "question", None)),
            category=self.optional_str(getattr(market, "category", None)),
            active=getattr(state, "active", None),
            closed=getattr(state, "closed", None),
            accepting_orders=getattr(state, "accepting_orders", None),
            end_date=getattr(state, "end_date", None),
            liquidity=(
                getattr(metrics, "liquidity_num", None)
                or getattr(metrics, "liquidity", None)
            ),
            volume=getattr(metrics, "volume_num", None) or getattr(metrics, "volume", None),
            best_bid=getattr(prices, "best_bid", None),
            best_ask=getattr(prices, "best_ask", None),
            outcomes=self.to_outcomes(market),
        )

    def to_details(self, market: Any) -> MarketDetails:
        summary = self.to_summary(market)
        trading = getattr(market, "trading", None)

        return MarketDetails(
            **summary.model_dump(),
            condition_id=self.optional_str(getattr(market, "condition_id", None)),
            description=self.optional_str(getattr(market, "description", None)),
            image=self.optional_str(getattr(market, "image", None)),
            icon=self.optional_str(getattr(market, "icon", None)),
            minimum_order_size=getattr(trading, "minimum_order_size", None),
            minimum_tick_size=getattr(trading, "minimum_tick_size", None),
            tags=self.to_tag_labels(market),
        )

    def to_outcomes(self, market: Any) -> tuple[MarketOutcomeSummary, ...]:
        outcomes = getattr(market, "outcomes", None)
        normalized: list[MarketOutcomeSummary] = []

        for default_label, attribute_name in (("Yes", "yes"), ("No", "no")):
            outcome = getattr(outcomes, attribute_name, None)
            if outcome is None:
                continue
            normalized.append(
                MarketOutcomeSummary(
                    label=self.optional_str(getattr(outcome, "label", None)) or default_label,
                    token_id=self.optional_str(getattr(outcome, "token_id", None)),
                    price=getattr(outcome, "price", None),
                )
            )

        return tuple(normalized)

    def to_tag_labels(self, market: Any) -> tuple[str, ...]:
        tags: list[str] = []
        for tag in getattr(market, "tags", ()):
            label = self.optional_str(getattr(tag, "label", None))
            slug = self.optional_str(getattr(tag, "slug", None))
            if label is not None:
                tags.append(label)
            elif slug is not None:
                tags.append(slug)
        return tuple(tags)

    @staticmethod
    def optional_str(value: object) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text or None

