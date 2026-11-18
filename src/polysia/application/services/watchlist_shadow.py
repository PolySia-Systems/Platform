"""One bounded, public-data Shadow tick over an owner's frozen selection."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
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
    evaluate_shadow_fill,
    quote_from_order_book,
)
from polysia.domain.copytrading.models import LeaderTradeAction
from polysia.domain.copytrading.watchlist_shadow import SHADOW_MODEL
from polysia.domain.market import MarketOrderBookSnapshot

_CONFIG = DynamicShadowConfig(maximum_forward_delay_ms=180_000, policy_version=SHADOW_MODEL)
_MAX_EVENTS = 2_000
_QUOTE_LIMIT = 12


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
) -> str:
    active = runs.active()
    if active is None:
        return "IDLE"
    owner, run_id, revision, data = active
    now = clock()
    if data["model"] != SHADOW_MODEL:
        raise ValueError("unsupported retained Shadow model")
    expiry = datetime.fromisoformat(data["ends_at"])
    if now >= expiry:
        # Finalization after expiry never invents a lookahead fill or ending mark.
        data["finished_at"] = now.isoformat()
        return "FINISHED" if runs.apply(owner, run_id, revision, "FINISHED", data) else "CHANGED"
    wallets = data["wallets"]
    aliases = {f"watchlist-{index}": wallet for index, wallet in enumerate(wallets)}
    source = source_factory(aliases)
    semaphore = asyncio.Semaphore(3)

    async def observe(alias: str, state: dict[str, Any]) -> None:
        async with semaphore:
            try:
                await asyncio.wait_for(
                    _collect(alias, state, source, books, min(now, expiry), expiry, clock),
                    timeout=20,
                )
            except (TimeoutError, OSError, RuntimeError, ValueError):
                state["read_errors"] += 1

    await asyncio.gather(*(observe(alias, wallets[wallet]) for alias, wallet in aliases.items()))
    return "OBSERVED" if runs.apply(owner, run_id, revision, "RUNNING", data) else "CHANGED"


async def _collect(
    alias: str, state: dict[str, Any], source: LeaderTradeSourcePort, books: PublicBooks,
    through: datetime, expiry: datetime, clock: Callable[[], datetime],
) -> None:
    start = datetime.fromisoformat(state["through"])
    if through <= start:
        return
    events = state["events"]
    if len(events) >= _MAX_EVENTS:
        return
    page = await source.read_page(alias, start_at=start, end_at=through)
    if page.next_checkpoint is not None or page.rejected_count:
        raise ValueError("incomplete observation window")
    if any(
        event.leader_id != alias or not start <= event.executed_at <= through
        for event in page.events
    ):
        raise ValueError("observation outside the frozen cohort or time window")
    quote_count = 0
    for event in sorted(page.events, key=lambda value: (value.executed_at, value.event_id)):
        if event.event_id in events:
            continue
        if len(events) >= _MAX_EVENTS:
            return
        evaluated_at = clock()
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
            try:
                book = await asyncio.wait_for(books.get_order_book(event.outcome_reference), 2)
                quote = quote_from_order_book(book)
            except (TimeoutError, RuntimeError, ValueError, OSError):
                pass
        evaluated_at = clock()
        if evaluated_at >= expiry:
            events[event.event_id] = "past_cutoff"
            continue
        key = event.outcome_reference
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
        state["realized"] = str(Decimal(state["realized"]) + (result.realized_pnl or 0))
        state["fees"] = str(Decimal(state["fees"]) + result.fee)
        state["slippage"] = str(Decimal(state["slippage"]) + result.slippage)
    state["through"] = through.isoformat()
    state["observations"] += 1
