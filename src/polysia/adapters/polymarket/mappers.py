from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from polysia.domain.market import (
    MarketDetails,
    MarketFeeSchedule,
    MarketOrderBookSnapshot,
    MarketOutcomeSummary,
    MarketSummary,
    OrderBookLevel,
)


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
        state = getattr(market, "state", None)
        fees_enabled = getattr(trading, "fees_enabled", None)
        raw_fee_schedule = getattr(trading, "fee_schedule", None)
        fee_schedule = None
        if isinstance(fees_enabled, bool):
            fee_schedule = MarketFeeSchedule(
                enabled=fees_enabled,
                rate=getattr(raw_fee_schedule, "rate", None),
                exponent=getattr(raw_fee_schedule, "exponent", None),
                taker_only=getattr(raw_fee_schedule, "taker_only", None),
                rebate_rate=getattr(raw_fee_schedule, "rebate_rate", None),
            )

        return MarketDetails(
            **summary.model_dump(),
            condition_id=self.optional_str(getattr(market, "condition_id", None)),
            description=self.optional_str(getattr(market, "description", None)),
            image=self.optional_str(getattr(market, "image", None)),
            icon=self.optional_str(getattr(market, "icon", None)),
            minimum_order_size=getattr(trading, "minimum_order_size", None),
            minimum_tick_size=getattr(trading, "minimum_tick_size", None),
            enable_order_book=getattr(state, "enable_order_book", None),
            archived=getattr(state, "archived", None),
            start_date=getattr(state, "start_date", None),
            fee_schedule=fee_schedule,
            fee_type=self.optional_str(getattr(trading, "fee_type", None)),
            seconds_delay=getattr(trading, "seconds_delay", None),
            tags=self.to_tag_labels(market),
        )

    def to_order_book(self, book: Any) -> MarketOrderBookSnapshot:
        return MarketOrderBookSnapshot(
            token_id=str(book.token_id),
            market_id=self.optional_str(getattr(book, "market", None)),
            timestamp=self.to_datetime(getattr(book, "timestamp", None)),
            bids=self.to_levels(getattr(book, "bids", ())),
            asks=self.to_levels(getattr(book, "asks", ())),
            minimum_order_size=self.to_decimal(getattr(book, "min_order_size", None)),
            tick_size=self.to_decimal(getattr(book, "tick_size", None)),
            negative_risk=bool(getattr(book, "neg_risk", False)),
            book_hash=self.optional_str(getattr(book, "hash", None)),
        )

    def to_levels(self, levels: Any) -> tuple[OrderBookLevel, ...]:
        return tuple(
            OrderBookLevel(
                price=self.to_decimal(getattr(level, "price", None)),
                size=self.to_decimal(getattr(level, "size", None)),
            )
            for level in levels
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

    @staticmethod
    def to_decimal(value: object) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError) as error:
            raise ValueError("Polymarket numeric field is missing or invalid") from error
        return parsed

    @staticmethod
    def to_datetime(value: object) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        if isinstance(value, (int, str)) and str(value).isdigit():
            raw = int(value)
            seconds = raw / 1000 if raw >= 100_000_000_000 else raw
            return datetime.fromtimestamp(seconds, tz=UTC)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        raise ValueError("Polymarket order-book timestamp is missing or invalid")
