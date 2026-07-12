from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal
from typing import Literal

from polysia.domain.market import MarketDetails, MarketOrderBookSnapshot
from polysia.domain.strategy import StrategyDefinition, StrategyLifecycleStatus
from polysia.execution.intents import OrderIntent

STRATEGY_ID = "btc-15m-favorite-take-profit"
STRATEGY_VERSION = "0.1.0"
DecisionStatus = Literal["TRADE", "NO_TRADE"]


@dataclass(frozen=True, slots=True)
class FavoriteTakeProfitConfig:
    maximum_entry_notional: Decimal = Decimal("1.00")
    maximum_data_age_ms: int = 5_000
    maximum_spread: Decimal = Decimal("0.10")
    maximum_future_clock_skew_ms: int = 1_000
    exit_target_multiple: Decimal = Decimal("1.10")

    def __post_init__(self) -> None:
        if self.maximum_entry_notional <= 0 or self.maximum_entry_notional > Decimal("1.00"):
            raise ValueError("maximum_entry_notional must be within (0, 1.00]")
        if self.maximum_data_age_ms < 0:
            raise ValueError("maximum_data_age_ms must not be negative")
        if self.maximum_future_clock_skew_ms < 0:
            raise ValueError("maximum_future_clock_skew_ms must not be negative")
        if self.maximum_spread <= 0:
            raise ValueError("maximum_spread must be positive")
        if self.exit_target_multiple != Decimal("1.10"):
            raise ValueError("exit_target_multiple is fixed at 1.10 for this strategy")


@dataclass(frozen=True, slots=True)
class OutcomeQuoteEvidence:
    label: str
    token_id: str
    best_bid: Decimal
    best_ask: Decimal
    midpoint: Decimal
    spread: Decimal
    ask_size: Decimal
    timestamp: datetime
    freshness_ms: int
    tick_size: Decimal
    minimum_order_size: Decimal


@dataclass(frozen=True, slots=True)
class FavoriteDecision:
    status: DecisionStatus
    reason: str
    market_id: str
    market_slug: str
    selected_label: str | None
    selected_token_id: str | None
    entry_price: Decimal | None
    entry_size: Decimal | None
    entry_notional: Decimal | None
    confidence: Decimal
    quotes: tuple[OutcomeQuoteEvidence, ...]
    decided_at: datetime

    def to_intent(self) -> OrderIntent:
        if (
            self.status != "TRADE"
            or self.selected_token_id is None
            or self.entry_price is None
            or self.entry_size is None
        ):
            raise ValueError("NO_TRADE decision cannot create an order intent")
        return OrderIntent(
            strategy_id=STRATEGY_ID,
            token_id=self.selected_token_id,
            side="BUY",
            price=self.entry_price,
            size=self.entry_size,
            reason=self.reason,
            confidence=self.confidence,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "confidence": str(self.confidence),
            "decided_at": self.decided_at.isoformat(),
            "entry_notional": _decimal_text(self.entry_notional),
            "entry_price": _decimal_text(self.entry_price),
            "entry_size": _decimal_text(self.entry_size),
            "market_id": self.market_id,
            "market_slug": self.market_slug,
            "quotes": [
                {
                    "ask_size": str(quote.ask_size),
                    "best_ask": str(quote.best_ask),
                    "best_bid": str(quote.best_bid),
                    "freshness_ms": quote.freshness_ms,
                    "label": quote.label,
                    "midpoint": str(quote.midpoint),
                    "minimum_order_size": str(quote.minimum_order_size),
                    "spread": str(quote.spread),
                    "tick_size": str(quote.tick_size),
                    "timestamp": quote.timestamp.isoformat(),
                    "token_id": quote.token_id,
                }
                for quote in self.quotes
            ],
            "reason": self.reason,
            "selected_label": self.selected_label,
            "selected_token_id": self.selected_token_id,
            "status": self.status,
        }


class Btc15mFavoriteTakeProfitStrategy:
    """Pure execution-validation strategy; it never calls a venue or broker."""

    strategy_id = STRATEGY_ID
    version = STRATEGY_VERSION

    def __init__(self, config: FavoriteTakeProfitConfig | None = None) -> None:
        self.config = config or FavoriteTakeProfitConfig()

    @staticmethod
    def definition(*, created_at: datetime | None = None) -> StrategyDefinition:
        return StrategyDefinition(
            strategy_id=STRATEGY_ID,
            name="BTC 15m Favorite Take-Profit",
            version=STRATEGY_VERSION,
            family="execution-validation",
            category="directional-test",
            description=(
                "Selects the current higher implied-probability BTC 15m outcome for one "
                "bounded entry and one actual-fill-based take-profit exit."
            ),
            hypothesis=(
                "The current executable favorite provides a deterministic, liquid-enough "
                "subject for validating the complete bounded live execution path."
            ),
            supported_market_types=("btc-updown-15m",),
            supported_venues=("polymarket",),
            decision_horizon="single 15-minute market",
            allowed_runtime_modes=("paper", "shadow", "limited_live"),
            lifecycle_status=StrategyLifecycleStatus.EXPERIMENTAL,
            risk_class="bounded-micro-live",
            parameter_schema={
                "exit_target_multiple": {"const": "1.10", "type": "decimal"},
                "maximum_entry_notional": {"maximum": "1.00", "type": "decimal"},
                "maximum_entry_attempts": {"const": 1, "type": "integer"},
            },
            tags=("btc", "15m", "execution-validation", "bounded-live"),
            owner="PolySia owner",
            created_at=created_at or datetime.now(UTC),
            code_reference=(
                "src/polysia/strategies/btc_15m_favorite_take_profit.py"
            ),
            test_reference=(
                "tests/unit/strategies/test_btc_15m_favorite_take_profit.py"
            ),
        )

    def decide(
        self,
        market: MarketDetails,
        books: tuple[MarketOrderBookSnapshot, ...],
        *,
        now: datetime,
    ) -> FavoriteDecision:
        market_slug = market.slug or ""
        if len(market.outcomes) != 2 or len(books) != 2:
            return self._no_trade(market, (), now, "exactly two outcomes and books are required")
        books_by_token = {book.token_id: book for book in books}
        if len(books_by_token) != 2:
            return self._no_trade(market, (), now, "outcome books must use distinct token ids")

        quotes: list[OutcomeQuoteEvidence] = []
        for outcome in market.outcomes:
            if outcome.token_id is None or outcome.token_id not in books_by_token:
                return self._no_trade(
                    market,
                    tuple(quotes),
                    now,
                    "outcome token mapping is incomplete or ambiguous",
                )
            book = books_by_token[outcome.token_id]
            if (
                market.condition_id is not None
                and book.market_id is not None
                and book.market_id != market.condition_id
            ):
                return self._no_trade(
                    market,
                    tuple(quotes),
                    now,
                    "order-book market identity does not match the selected market",
                )
            quote = self._quote(outcome.label, book, now=now)
            if isinstance(quote, str):
                return self._no_trade(market, tuple(quotes), now, quote)
            quotes.append(quote)

        if market.seconds_delay not in (None, 0):
            return self._no_trade(
                market,
                tuple(quotes),
                now,
                "market execution delay is incompatible with the bounded test",
            )
        if market.minimum_order_size is not None and any(
            quote.minimum_order_size != market.minimum_order_size for quote in quotes
        ):
            return self._no_trade(
                market,
                tuple(quotes),
                now,
                "market and order-book minimum order size disagree",
            )
        if market.minimum_tick_size is not None and any(
            quote.tick_size != market.minimum_tick_size for quote in quotes
        ):
            return self._no_trade(
                market,
                tuple(quotes),
                now,
                "market and order-book tick size disagree",
            )

        ordered = sorted(quotes, key=lambda quote: (quote.best_ask, quote.midpoint), reverse=True)
        selected, other = ordered
        if selected.best_ask == other.best_ask:
            return self._no_trade(market, tuple(quotes), now, "favorite is tied at executable ask")
        if selected.midpoint <= other.midpoint:
            return self._no_trade(
                market,
                tuple(quotes),
                now,
                "executable ask and midpoint do not identify the same favorite",
            )

        fee_per_share = self._fee_per_share(market, selected.best_ask)
        if fee_per_share is None:
            return self._no_trade(
                market,
                tuple(quotes),
                now,
                "market fee schedule is missing or invalid",
            )
        entry_size = (
            self.config.maximum_entry_notional / (selected.best_ask + fee_per_share)
        ).quantize(
            Decimal("0.000001"),
            rounding=ROUND_FLOOR,
        )
        entry_notional = entry_size * selected.best_ask
        expected_fee = self.expected_fee(
            market,
            price=selected.best_ask,
            size=entry_size,
        )
        while entry_size > 0 and entry_notional + expected_fee > self.config.maximum_entry_notional:
            entry_size -= Decimal("0.000001")
            entry_notional = entry_size * selected.best_ask
            expected_fee = self.expected_fee(
                market,
                price=selected.best_ask,
                size=entry_size,
            )
        if entry_size < selected.minimum_order_size:
            return self._no_trade(
                market,
                tuple(quotes),
                now,
                "venue minimum order size cannot be satisfied within the 1.00 cap",
            )
        if selected.ask_size < entry_size:
            return self._no_trade(
                market,
                tuple(quotes),
                now,
                "favorite ask liquidity is insufficient for a full bounded fill",
            )
        if entry_notional + expected_fee > self.config.maximum_entry_notional:
            return self._no_trade(market, tuple(quotes), now, "entry notional exceeds cap")

        confidence = min(Decimal("1"), selected.midpoint - other.midpoint)
        return FavoriteDecision(
            status="TRADE",
            reason=(
                f"{selected.label} is the current favorite: higher executable ask "
                f"{selected.best_ask} and midpoint {selected.midpoint}"
            ),
            market_id=market.id,
            market_slug=market_slug,
            selected_label=selected.label,
            selected_token_id=selected.token_id,
            entry_price=selected.best_ask,
            entry_size=entry_size,
            entry_notional=entry_notional,
            confidence=confidence,
            quotes=tuple(quotes),
            decided_at=now,
        )

    def no_trade_decision(
        self,
        market: MarketDetails,
        *,
        now: datetime,
        reason: str,
    ) -> FavoriteDecision:
        """Create an evidence-bearing rejection without producing an intent."""

        return self._no_trade(market, (), now, reason)

    @staticmethod
    def expected_fee(market: MarketDetails, *, price: Decimal, size: Decimal) -> Decimal:
        fee_per_share = Btc15mFavoriteTakeProfitStrategy._fee_per_share(market, price)
        if fee_per_share is None:
            raise ValueError("market fee schedule is missing or invalid")
        return (size * fee_per_share).quantize(Decimal("0.00001"))

    @staticmethod
    def _fee_per_share(market: MarketDetails, price: Decimal) -> Decimal | None:
        fee = market.fee_schedule
        if fee is None:
            return None
        if not fee.enabled:
            return Decimal("0")
        if fee.rate is None or fee.exponent is None or fee.rate < 0 or fee.exponent < 0:
            return None
        return fee.rate * ((price * (Decimal("1") - price)) ** fee.exponent)

    def _quote(
        self,
        label: str,
        book: MarketOrderBookSnapshot,
        *,
        now: datetime,
    ) -> OutcomeQuoteEvidence | str:
        best_bid = book.best_bid
        best_ask = book.best_ask
        if best_bid is None or best_ask is None:
            return f"{label} order book has no executable two-sided quote"
        if best_bid.price <= 0 or best_ask.price >= 1 or best_bid.price >= best_ask.price:
            return f"{label} order book is invalid or crossed"
        spread = best_ask.price - best_bid.price
        if spread > self.config.maximum_spread:
            return f"{label} spread exceeds the configured maximum"
        if book.tick_size <= 0 or book.minimum_order_size <= 0:
            return f"{label} venue tick or minimum size is invalid"
        if best_bid.price % book.tick_size != 0 or best_ask.price % book.tick_size != 0:
            return f"{label} executable price is not tick aligned"
        timestamp = (
            book.timestamp
            if book.timestamp.tzinfo is not None
            else book.timestamp.replace(tzinfo=UTC)
        )
        age_ms = int((now - timestamp).total_seconds() * 1000)
        if age_ms < -self.config.maximum_future_clock_skew_ms:
            return f"{label} order-book timestamp is ahead of the system clock"
        freshness_ms = max(0, age_ms)
        if freshness_ms > self.config.maximum_data_age_ms:
            return f"{label} order book is stale"
        return OutcomeQuoteEvidence(
            label=label,
            token_id=book.token_id,
            best_bid=best_bid.price,
            best_ask=best_ask.price,
            midpoint=(best_bid.price + best_ask.price) / Decimal("2"),
            spread=spread,
            ask_size=best_ask.size,
            timestamp=timestamp,
            freshness_ms=freshness_ms,
            tick_size=book.tick_size,
            minimum_order_size=book.minimum_order_size,
        )

    def _no_trade(
        self,
        market: MarketDetails,
        quotes: tuple[OutcomeQuoteEvidence, ...],
        now: datetime,
        reason: str,
    ) -> FavoriteDecision:
        return FavoriteDecision(
            status="NO_TRADE",
            reason=reason,
            market_id=market.id,
            market_slug=market.slug or "",
            selected_label=None,
            selected_token_id=None,
            entry_price=None,
            entry_size=None,
            entry_notional=None,
            confidence=Decimal("0"),
            quotes=quotes,
            decided_at=now,
        )


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


__all__ = [
    "Btc15mFavoriteTakeProfitStrategy",
    "FavoriteDecision",
    "FavoriteTakeProfitConfig",
    "OutcomeQuoteEvidence",
    "STRATEGY_ID",
    "STRATEGY_VERSION",
]
