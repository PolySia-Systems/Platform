"""One bounded, public-data Shadow tick over an owner's frozen selection."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from polysia.application.ports.copytrading import LeaderTradeSourcePort
from polysia.domain.copytrading.dynamic_shadow import (
    BPS,
    DynamicShadowConfig,
    DynamicShadowMode,
    ShadowEvaluationStatus,
    ShadowPosition,
    ShadowQuoteEvidence,
    evaluate_shadow_fill,
    quote_from_order_book,
)
from polysia.domain.copytrading.models import LeaderTradeAction
from polysia.domain.copytrading.watchlist_shadow import (
    FEE_BPS,
    LEGACY_SHADOW_MODEL,
    MAX_FILL_NOTIONAL,
    MAX_MARK_AGE_SECONDS,
    SHADOW_MODEL,
)
from polysia.domain.market import MarketDetails, MarketOrderBookSnapshot
from polysia.domain.market.settlement import verified_settlement_prices

_CONFIG = DynamicShadowConfig(
    fee_bps=Decimal(FEE_BPS), maximum_notional=Decimal(MAX_FILL_NOTIONAL),
    maximum_forward_delay_ms=180_000, policy_version=SHADOW_MODEL,
)
_MAX_EVENTS = 2_000
_QUOTE_LIMIT = 12
type SettlementReader = Callable[[str], Awaitable[MarketDetails]]


class PublicBooks(Protocol):
    async def get_order_book(self, token_id: str) -> MarketOrderBookSnapshot: ...


class RunStore(Protocol):
    def active(self) -> tuple[str, str, int, dict[str, Any]] | None: ...

    def apply(
        self, owner: str, run_id: str, revision: int, status: str, data: dict[str, Any]
    ) -> bool: ...


async def tick(
    runs: RunStore,
    source_factory: Callable[[Mapping[str, str]], LeaderTradeSourcePort],
    books: PublicBooks,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    settlement_reader: SettlementReader | None = None,
) -> str:
    active = runs.active()
    if active is None:
        return "IDLE"
    owner, run_id, revision, data = active
    now = clock()
    legacy = data["model"] == LEGACY_SHADOW_MODEL
    if not legacy and data["model"] != SHADOW_MODEL:
        raise ValueError("unsupported retained Shadow model")
    expiry = datetime.fromisoformat(data["ends_at"])
    if now >= expiry and legacy:
        # Finalization after expiry never invents a lookahead fill or ending mark.
        data["finished_at"] = now.isoformat()
        return "FINISHED" if runs.apply(owner, run_id, revision, "FINISHED", data) else "CHANGED"
    wallets = data["wallets"]
    aliases = {f"watchlist-{index}": wallet for index, wallet in enumerate(wallets)}
    source = source_factory(aliases)
    semaphore = asyncio.Semaphore(3)

    async def observe(alias: str, state: dict[str, Any]) -> bool:
        async with semaphore:
            prior = state["through"]
            try:
                await asyncio.wait_for(
                    _collect(
                        alias, state, source, books, min(now, expiry), expiry, clock,
                        legacy=legacy, settlement_reader=settlement_reader,
                    ),
                    timeout=20,
                )
            except (TimeoutError, OSError, RuntimeError, ValueError):
                state["read_errors"] += 1
                if not legacy and state["through"] == prior:
                    state["recovering"] = True
            return state["through"] != prior

    advanced = await asyncio.gather(
        *(observe(alias, wallets[wallet]) for alias, wallet in aliases.items())
    )
    if now >= expiry:
        data.update(
            finished_at=clock().isoformat(), cutoff_at=expiry.isoformat(), end_reason="time",
        )
        return "FINISHED" if runs.apply(owner, run_id, revision, "FINISHED", data) else "CHANGED"
    if not runs.apply(owner, run_id, revision, "RUNNING", data):
        return "CHANGED"
    return "OBSERVED" if any(advanced) else "NO_PROGRESS"


async def _collect(
    alias: str, state: dict[str, Any], source: LeaderTradeSourcePort, books: PublicBooks,
    through: datetime, expiry: datetime, clock: Callable[[], datetime], *,
    legacy: bool, settlement_reader: SettlementReader | None,
) -> None:
    start = datetime.fromisoformat(state["through"])
    if through <= start:
        return
    events = state["events"]
    gaps = state.get("gaps", {})
    if len(events) >= _MAX_EVENTS:
        gaps["event_budget"] = 1
        return
    # Bound recovery after a delayed or oversized window. Record any interval
    # skipped to keep the observation clock useful again.
    recent = through - timedelta(seconds=30)
    if not legacy and state.get("recovering") and start < recent:
        gaps["observation_gap"] = gaps.get("observation_gap", 0) + 1
        start = recent
    page = await source.read_page(alias, start_at=start, end_at=through)
    if page.next_checkpoint is not None or page.rejected_count:
        raise ValueError("incomplete observation window")
    if any(
        event.leader_id != alias or not start <= event.executed_at <= through
        for event in page.events
    ):
        raise ValueError("observation outside the frozen cohort or time window")
    quote_count = 0
    quotes: dict[str, tuple[ShadowQuoteEvidence, datetime]] = {}
    for event in sorted(page.events, key=lambda value: (value.executed_at, value.event_id)):
        if event.event_id in events:
            continue
        if len(events) >= _MAX_EVENTS:
            gaps["event_budget"] = 1
            return
        evaluated_at = clock()
        if not legacy:
            state["fills"][event.event_id] = {
                "outcome": event.outcome_reference, "market": event.market_reference,
                "side": event.trade_action.value, "signal_at": event.executed_at.isoformat(),
                "evaluated_at": evaluated_at.isoformat(),
            }
        if not legacy and evaluated_at >= expiry:
            events[event.event_id] = "observed_after_cutoff"
            continue
        key = event.outcome_reference
        if not legacy and state["marks"].get(key, {}).get("source") == "verified-settlement":
            events[event.event_id] = "market_settled"
            continue
        cash = Decimal(state["cash"])
        maximum = min(_CONFIG.maximum_notional, cash / (1 + _CONFIG.fee_bps / BPS))
        if event.trade_action is LeaderTradeAction.BUY and maximum <= 0:
            events[event.event_id] = "virtual_cash_exhausted"
            continue
        config = replace(_CONFIG, maximum_notional=maximum) if event.trade_action is (
            LeaderTradeAction.BUY
        ) else _CONFIG
        quote = None
        if (
            quote_count < _QUOTE_LIMIT
            and evaluated_at < expiry
            and evaluated_at - event.executed_at <= timedelta(
                milliseconds=config.maximum_forward_delay_ms
            )
        ):
            quote_count += 1
            evidence = await _read_quote(books, key, clock)
            if evidence is not None:
                quote, _ = evidence
                quotes[key] = evidence
        elif not legacy and quote_count >= _QUOTE_LIMIT:
            events[event.event_id] = "quote_budget"
            continue
        evaluated_at = clock()
        if evaluated_at >= expiry:
            events[event.event_id] = "past_cutoff"
            continue
        prior = state["positions"].get(key)
        position = (
            ShadowPosition(Decimal(prior[0]), Decimal(prior[1])) if prior else ShadowPosition()
        )
        result, updated = evaluate_shadow_fill(
            alias, event, position=position, mode=DynamicShadowMode.FORWARD,
            config=config, quote=quote, evaluated_at=evaluated_at,
        )
        events[event.event_id] = result.reason
        if result.status is not ShadowEvaluationStatus.SIMULATED:
            continue
        assert result.gross_notional is not None and result.fee is not None
        assert result.slippage is not None
        if event.trade_action is LeaderTradeAction.BUY:
            state["cash"] = str(cash - result.gross_notional - result.fee)
        else:
            state["cash"] = str(cash + result.gross_notional - result.fee)
        if updated.quantity:
            state["positions"][key] = [str(updated.quantity), str(updated.total_cost)]
        else:
            state["positions"].pop(key, None)
        if not legacy:
            state["marks"].pop(key, None)
            markets = state.setdefault("markets", {})
            if updated.quantity:
                markets[key] = event.market_reference
            else:
                markets.pop(key, None)
            if prior and not updated.quantity:
                state["closed"] += 1
            state["fills"][event.event_id] = {
                "outcome": key, "market": event.market_reference, "side": event.trade_action.value,
                "quantity": str(result.filled_size), "price": str(result.follower_price),
                "notional": str(result.gross_notional), "fee": str(result.fee),
                "slippage": str(result.slippage), "realized": str(result.realized_pnl or 0),
                "signal_at": event.executed_at.isoformat(),
                "evaluated_at": evaluated_at.isoformat(),
                "quote_at": quote.observed_at.isoformat() if quote else None,
                "quote_received_at": quotes[key][1].isoformat() if key in quotes else None,
            }
        state["realized"] = str(Decimal(state["realized"]) + (result.realized_pnl or 0))
        state["fees"] = str(Decimal(state["fees"]) + result.fee)
        state["slippage"] = str(Decimal(state["slippage"]) + result.slippage)
    state["through"] = through.isoformat()
    state["observations"] += 1
    state.pop("recovering", None)
    if not legacy and clock() < expiry:
        await _refresh_marks(
            state, books, quotes, _QUOTE_LIMIT - quote_count, expiry, clock, settlement_reader,
        )


async def _read_quote(
    books: PublicBooks, token: str, clock: Callable[[], datetime],
) -> tuple[ShadowQuoteEvidence, datetime] | None:
    try:
        book = await asyncio.wait_for(books.get_order_book(token), 2)
        quote = quote_from_order_book(book)
        return (quote, clock()) if quote.token_id == token else None
    except (TimeoutError, RuntimeError, ValueError, OSError):
        return None


async def _refresh_marks(
    state: dict[str, Any], books: PublicBooks,
    quotes: dict[str, tuple[ShadowQuoteEvidence, datetime]],
    budget: int, expiry: datetime, clock: Callable[[], datetime],
    settlement_reader: SettlementReader | None,
) -> None:
    marks = state["marks"]
    # Start with the oldest marks so quiet positions get time on the same budget.
    positions = sorted(
        state["positions"], key=lambda key: marks.get(key, {}).get("received_at", ""),
    )
    for token in positions:
        if marks.get(token, {}).get("source") == "verified-settlement":
            continue
        evidence = quotes.get(token)
        if evidence is None:
            if budget <= 0 or clock() >= expiry:
                state["gaps"]["valuation_budget"] = len(positions)
                break
            budget -= 1
            evidence = await _read_quote(books, token, clock)
        if evidence is None:
            market = state.get("markets", {}).get(token)
            if settlement_reader is not None and market and budget > 0 and clock() < expiry:
                budget -= 1
                try:
                    market_result = await asyncio.wait_for(settlement_reader(market), 2)
                    received = clock()
                    prices = verified_settlement_prices(market_result)
                except (TimeoutError, RuntimeError, ValueError, OSError):
                    continue
                if prices is not None and token in prices and received < expiry:
                    quantity = Decimal(state["positions"][token][0])
                    value = str(quantity * prices[token])
                    marks[token] = {
                        "quote_at": received.isoformat(), "received_at": received.isoformat(),
                        "quantity": str(quantity), "gross": value, "fee": "0",
                        "value": value, "source": "verified-settlement",
                    }
            continue
        quote, received = evidence
        if not quote.observed_at <= received < expiry or (
            received - quote.observed_at > timedelta(seconds=MAX_MARK_AGE_SECONDS)
        ):
            continue
        quantity = Decimal(state["positions"][token][0])
        remaining, gross = quantity, Decimal(0)
        for level in sorted(quote.bids, key=lambda item: item.price, reverse=True):
            shares = min(remaining, level.size)
            gross += shares * level.price
            remaining -= shares
            if not remaining:
                break
        fee = gross * _CONFIG.fee_bps / BPS
        marks[token] = {
            "quote_at": quote.observed_at.isoformat(), "received_at": received.isoformat(),
            "quantity": str(quantity - remaining), "gross": str(gross), "fee": str(fee),
            "value": str(gross - fee), "source": quote.source,
        }
