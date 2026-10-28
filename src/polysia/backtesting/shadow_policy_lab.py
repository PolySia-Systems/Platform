"""Bounded stateful policy comparison using the existing Shadow financial owner.

One retained event/book tape, common cost/capital/time assumptions, isolated
mutable portfolios and attribution. No venue, signer or acquisition dependency.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Any

from polysia.application.services.continuous_shadow import (
    _MutableAttribution,
    _MutablePortfolio,
    apply_shadow_event,
)
from polysia.domain.copytrading import LeaderTradeAction, LeaderTradeEvent
from polysia.domain.copytrading.continuous_shadow import (
    ContinuousPortfolioKind,
    ContinuousShadowConfig,
    ContinuousShadowLifecycle,
    calculate_verified_taker_fee,
)
from polysia.domain.copytrading.copy_policy import CopyPolicy, ShadowPositionAction
from polysia.domain.financial_session import SessionBlocked, digest, utc
from polysia.domain.market import MarketDetails, MarketOrderBookSnapshot

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class ShadowFrame:
    at: datetime
    market: MarketDetails
    book: MarketOrderBookSnapshot
    event: LeaderTradeEvent | None = None


def compare_policy_stream(
    frames: tuple[ShadowFrame, ...],
    policies: tuple[CopyPolicy, ...],
    *,
    config: ContinuousShadowConfig,
    leader_opening: Mapping[tuple[str, str], Decimal],
    maximum_frames: int = 10000,
) -> dict[str, Any]:
    if (
        not 2 <= len(policies) <= 4
        or len(frames) > maximum_frames
        or not frames
        or len({policy.fingerprint for policy in policies}) != len(policies)
    ):
        raise SessionBlocked("bounded_distinct_policy_comparison_required")
    if any(
        utc(first.at) > utc(second.at) for first, second in zip(frames, frames[1:], strict=False)
    ):
        raise SessionBlocked("comparison_stream_time_reversal")
    tape_id = digest(
        [
            {
                "at": frame.at,
                "market": frame.market.model_dump(mode="json"),
                "book": frame.book.model_dump(mode="json"),
                "event": None if frame.event is None else asdict(frame.event),
            }
            for frame in frames
        ]
    )
    results = []
    for policy in policies:
        portfolio = _MutablePortfolio(
            "follower",
            ContinuousPortfolioKind.FOLLOWER,
            None,
            config.follower_bankroll,
            config.follower_bankroll,
            ZERO,
            ZERO,
            config.follower_bankroll,
            ZERO,
            {},
        )
        assumptions = replace(config, copy_policy=policy, policy_version=policy.version)
        attribution: dict[tuple[str, str, str, str], _MutableAttribution] = {}
        leader = dict(leader_opening)
        entered: set[tuple[str, str]] = set()
        opened: dict[tuple[str, str], datetime] = {}
        decisions, valuations = [], []
        seen: set[str] = set()
        quotes: dict[str, MarketOrderBookSnapshot] = {}
        for frame in frames:
            if frame.book.timestamp > frame.at:
                raise SessionBlocked("comparison_future_book")
            quotes[frame.book.token_id] = frame.book
            consumed: dict[tuple[str, str], dict[Decimal, Decimal]] = {}
            actions: list[LeaderTradeEvent | ShadowPositionAction] = []
            if frame.event is not None and frame.event.event_id not in seen:
                if frame.event.observed_at > frame.at:
                    raise SessionBlocked("comparison_future_event")
                seen.add(frame.event.event_id)
                actions.append(frame.event)
            # Price/time triggers are distinct position actions, not fabricated
            # recent leader transactions. They are checked on every quote frame.
            for key, owned in list(attribution.items()):
                if (
                    owned.quantity <= 0
                    or key[3] != frame.book.token_id
                    or frame.book.best_bid is None
                ):
                    continue
                fee = calculate_verified_taker_fee(
                    frame.market, price=frame.book.best_bid.price, size=Decimal(1)
                )
                if fee.amount is None:
                    continue
                owner = (key[1], key[3])
                position = portfolio.positions.get((key[2], key[3]))
                trigger, size = policy.exit_decision(
                    held=owned.quantity,
                    reserved_sell=ZERO,
                    cost_basis=owned.cost_basis,
                    bid=frame.book.best_bid.price,
                    exit_fee_per_share=fee.amount,
                    entry_fees=ZERO
                    if position is None
                    else (position.entry_fees * owned.quantity / position.quantity),
                    opened_at=opened[owner],
                    now=frame.at,
                    leader_before=None,
                    leader_reduction=None,
                    share_quantum=policy.quantity_quantum,
                )
                if size:
                    actions.insert(
                        0,
                        ShadowPositionAction(
                            digest((owner, opened[owner])),
                            policy.fingerprint,
                            trigger,
                            key[1],
                            key[2],
                            key[3],
                            frame.book.best_bid.price,
                            size,
                            frame.at,
                            frame.at,
                        ),
                    )
            for event in actions:
                owner = (event.leader_id, event.outcome_reference)
                prior = attribution.get(
                    ("follower", event.leader_id, event.market_reference, event.outcome_reference)
                )
                owner_was_flat = prior is None or prior.quantity == 0
                baseline = leader.get(owner)
                evaluation, entry = apply_shadow_event(
                    assumptions,
                    portfolio,
                    event,
                    pool_class="ALPHA",
                    lifecycle=ContinuousShadowLifecycle.RUNNING,
                    exposure_increase_allowed=True,
                    market=frame.market,
                    book=frame.book,
                    attributions=attribution,
                    consumed_by_scope=consumed,
                    evaluated_at=frame.at,
                    leader_position_before=baseline,
                    policy_context_verified=True,
                    entered_before=owner in entered,
                    position_triggered=isinstance(event, ShadowPositionAction),
                    policy_opened_at=opened.get(owner),
                )
                decisions.append(
                    {
                        "input_kind": "POSITION_TRIGGER"
                        if isinstance(event, ShadowPositionAction)
                        else "LEADER_OCCURRENCE",
                        "event": event.event_id,
                        "at": frame.at,
                        "policy_digest": policy.fingerprint,
                        "status": evaluation.status.value,
                        "reason": evaluation.reason,
                        "shares": evaluation.filled_size,
                        "side": event.trade_action.value,
                        "cash": portfolio.cash,
                        "entry": None if entry is None else asdict(entry),
                    }
                )
                if evaluation.filled_size and event.trade_action is LeaderTradeAction.BUY:
                    entered.add(owner)
                    if owner_was_flat:
                        opened[owner] = frame.at
                if isinstance(event, LeaderTradeEvent):
                    if event.trade_action is LeaderTradeAction.BUY:
                        leader[owner] = (baseline or ZERO) + event.executed_size
                    elif baseline is not None:
                        leader[owner] = max(ZERO, baseline - event.executed_size)
            complete, equity = True, portfolio.cash
            for position in portfolio.positions.values():
                quote = quotes.get(position.outcome_reference)
                if (
                    quote is None
                    or quote.best_bid is None
                    or not 0
                    <= (frame.at - quote.timestamp).total_seconds()
                    <= config.maximum_quote_age_ms / 1000
                ):
                    complete = False
                else:
                    equity += position.quantity * quote.best_bid.price
            if complete:
                portfolio.high_water_nav = max(portfolio.high_water_nav, equity)
                portfolio.drawdown = max(portfolio.drawdown, portfolio.high_water_nav - equity)
            valuations.append({"at": frame.at, "equity": equity if complete else None})
        results.append(
            {
                "policy": asdict(policy),
                "policy_digest": policy.fingerprint,
                "initial_cash": config.follower_bankroll,
                "cash": portfolio.cash,
                "fees": portfolio.fees,
                "realized_pnl": portfolio.realized_pnl,
                "drawdown": portfolio.drawdown,
                "decisions": decisions,
                "valuations": valuations,
                "open_positions": [asdict(position) for position in portfolio.positions.values()],
                "censored_positions": len(portfolio.positions),
                "eligible_samples": sum(row["status"] == "SIMULATED" for row in decisions),
                "unknown_samples": sum(row["status"] == "UNKNOWN" for row in decisions),
                "calendar_seconds": (frames[-1].at - frames[0].at).total_seconds(),
                "active_seconds": sum(
                    min((right.at - left.at).total_seconds(), config.maximum_quote_age_ms / 1000)
                    for left, right in zip(frames, frames[1:], strict=False)
                ),
                "valuation_unknown_samples": sum(row["equity"] is None for row in valuations),
            }
        )
    return {
        "version": "stateful-shadow-policy-comparison/v1",
        "tape_digest": tape_id,
        "frame_count": len(frames),
        "acquisition_copies": 1,
        "results": results,
        "combined_portfolio_return": None,
        "accuracy_percent": None,
        "execution_evidence": "SIMULATED_FROM_RETAINED_BOOKS",
    }
