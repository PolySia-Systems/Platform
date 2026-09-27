"""Immutable, causal opportunity evidence for the read-only Shadow worker."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from polysia.domain.copytrading import LeaderTradeAction, LeaderTradeEvent
from polysia.domain.market import MarketDetails, MarketOrderBookSnapshot


def opportunity_payload(
    event: LeaderTradeEvent,
    *,
    admission_at: datetime,
    decision_at: datetime,
    selection_digest: str,
    config: dict[str, object],
    market: MarketDetails | None,
    book: MarketOrderBookSnapshot | None,
) -> dict[str, object]:
    """Capture source, admission and decision facts before ledger publication."""

    if not event.executed_at <= event.observed_at <= admission_at <= decision_at:
        raise ValueError("Shadow opportunity timestamps violate causal order")
    if book is not None and book.token_id != event.outcome_reference:
        raise ValueError("Shadow opportunity book token differs from the trade")
    if book is not None and book.market_id not in {None, event.market_reference}:
        raise ValueError("Shadow opportunity book market differs from the trade")
    market_bound = (
        market is not None
        and event.market_reference in {market.condition_id, market.id}
        and any(
            outcome.token_id == event.outcome_reference for outcome in market.outcomes
        )
    )
    fee = market.fee_schedule if market_bound and market is not None else None
    levels = None
    bids = None
    if book is not None and market_bound:
        side = book.asks if event.trade_action is LeaderTradeAction.BUY else book.bids
        levels = [
            {"price": format(level.price, "f"), "size": format(level.size, "f")}
            for level in side
        ]
        bids = [
            {"price": format(level.price, "f"), "size": format(level.size, "f")}
            for level in book.bids
        ]
    encoded_config = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return {
        "version": "shadow-opportunity-v1",
        "event_id": event.event_id,
        "source_id": event.source_id,
        "wallet_id": event.leader_id,
        "market_reference": event.market_reference,
        "outcome_reference": event.outcome_reference,
        "side": event.trade_action.value,
        "price": format(event.executed_price, "f"),
        "size": format(event.executed_size, "f"),
        "source_at": event.executed_at.isoformat(),
        "first_observed_at": event.observed_at.isoformat(),
        "admission_at": admission_at.isoformat(),
        "decision_at": decision_at.isoformat(),
        "selection_digest": selection_digest,
        "config_digest": hashlib.sha256(encoded_config.encode()).hexdigest(),
        "code_sha": config.get("code_sha"),
        "policy_version": config["policy_version"],
        "cost_model_version": config["cost_model_version"],
        "maximum_quote_age_ms": config["maximum_quote_age_ms"],
        "book_at": None if book is None else book.timestamp.isoformat(),
        "book_hash": None if book is None else book.book_hash,
        "book_levels": levels,
        "book_bids": bids,
        "market_token_binding": "VERIFIED" if market_bound else "UNKNOWN",
        "fee_enabled": None if fee is None else fee.enabled,
        "fee_rate": None if fee is None or fee.rate is None else format(fee.rate, "f"),
        "fee_exponent": (
            None if fee is None or fee.exponent is None else format(fee.exponent, "f")
        ),
        "fee_taker_only": None if fee is None else fee.taker_only,
    }
