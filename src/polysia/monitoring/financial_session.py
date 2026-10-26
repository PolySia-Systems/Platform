"""Redacted retained financial-session view; no file access or signing authority."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal
from typing import Any

from polysia.application.services.financial_session import TERMINAL, session_ledger
from polysia.config.settings import TradingMode
from polysia.domain.financial_session import SessionAuthorization, utc
from polysia.portfolio.pnl import calculate_portfolio_pnl

ZERO = Decimal("0")


def financial_session_view(
    state: dict[str, Any],
    authority: SessionAuthorization,
    *,
    now: datetime,
    discovery_counts: dict[str, int] | None = None,
    latency: dict[str, Any] | None = None,
    sources: list[dict[str, Any]] | None = None,
    trading_mode: TradingMode = TradingMode.DATA_ONLY,
) -> dict[str, Any]:
    """Trusted publisher takes a snapshot; Console receives only this projection.

    A partial mark never becomes zero or a complete net result. Full source and
    account evidence remains in the private mandatory journal, outside web code.
    """
    utc(now)
    ledger = session_ledger(state)
    orders = state["orders"]
    active = [row for row in orders.values() if row["state"] not in TERMINAL]
    reserved = sum((Decimal(row["reservation"]) for row in active), ZERO)
    held_cost = sum((p.size * p.avg_price for p in ledger.positions.values()), ZERO)
    latest = state["equity"][-1] if state["equity"] else None
    valuation_fresh = (
        latest is not None
        and 0
        <= (now - datetime.fromisoformat(latest["at"])).total_seconds()
        <= authority.max_evidence_age_seconds
    )
    marks = (
        {token: Decimal(mark) for token, mark in latest["marks"].items()}
        if (valuation_fresh and latest is not None)
        else {}
    )
    pnl = calculate_portfolio_pnl(ledger, marks)
    quarantined = bool(state.get("quarantined_fills") or state.get("quarantined_finality")
                       or state.get("quarantined_cash_events"))
    decisions = state["decisions"]
    counts = discovery_counts or {}
    reasons = Counter(row["reason"] for row in decisions.values() if row["reason"])
    unknown = sum(row["state"] == "UNCERTAIN_SUBMIT" for row in orders.values())
    opening_cash = Decimal(state["opening"]["cash"])
    peak, drawdown = opening_cash, ZERO
    measured = 0
    incomplete_valuations = 0
    for sample in state["equity"]:
        if sample["value"] is None:
            incomplete_valuations += 1
            continue
        measured += 1
        value = Decimal(sample["value"])
        peak = max(peak, value)
        drawdown = max(drawdown, peak - value)
    fill_counts = Counter(fill["intent_id"] for fill in state["fills"])
    divergence = []
    for identity in orders:
        leader = decisions[identity]["evidence"]["event"].get("leader_price")
        fills = [fill for fill in state["fills"] if fill["intent_id"] == identity]
        quantity = sum((Decimal(fill["shares"]) for fill in fills), ZERO)
        average = (
            sum((Decimal(fill["price"]) * Decimal(fill["shares"]) for fill in fills), ZERO)
            / quantity
            if quantity
            else None
        )
        divergence.append(
            {
                "intent_id": identity,
                "leader_price": leader,
                "follower_average_price": None if average is None else str(average),
                "price_difference": None
                if average is None or leader is None
                else str(average - Decimal(leader)),
            }
        )
    return {
        "version": "financial-session-view/v1",
        "as_of": now.isoformat(),
        "scope": "bounded session library; publication does not activate execution",
        "activation": "NOT_COMMISSIONED",
        "trading_mode": trading_mode.value,
        "status": state["mode"],
        "remaining_authority": {
            "status": "DENIED"
            if not authority.granted
            else "EXPIRED"
            if now >= authority.expires_at
            else "NOT_STARTED"
            if now < authority.starts_at
            else "WITHIN_WINDOW",
            "expires_at": authority.expires_at.isoformat(),
            "protective_until": authority.protective_until.isoformat(),
            "attempts": authority.max_attempts - state["attempts"],
            "turnover": str(authority.max_turnover - Decimal(state["turnover"])),
            "requests": authority.max_requests - state["requests"],
            "protective_actions": sorted(authority.protective_actions),
        },
        "exposure": {
            "cash": None if quarantined else str(ledger.cash),
            "expected_cash": str(ledger.cash),
            "observed_cash": state.get("last_account", {}).get("cash"),
            "open_exposure": str(held_cost + reserved),
            "reserved": str(reserved),
            "positions": len(ledger.positions),
            "unknown_orders": unknown,
            "reconciliation": "MATCHED" if state["reconciliation_ok"] else "BLOCKED",
        },
        "incidents": [
            {
                "reason": row["reason"],
                "scope": row.get("intent", "account"),
                "at": row.get("at"),
                "next_action": "Preserve evidence; reconcile through the protected operator route.",
            }
            for row in state["incidents"]
        ],
        "orders": [
            {
                "intent_id": identity,
                "order_id": row["order_id"],
                "state": row["state"],
                "side": row["side"],
                "token": row["token"],
                "updated_at": max(row.get("timeline", {}).values(), key=datetime.fromisoformat)
                if row.get("timeline")
                else row["created_at"],
                "timeline": row.get("timeline", {}),
                "fill_state": row.get("fill_state", "UNKNOWN"),
                "settlement_state": row.get("settlement_state", "UNKNOWN"),
                "reason": decisions[identity]["reason"],
            }
            for identity, row in orders.items()
        ],
        "funnel": {
            "discovered": counts.get("discovered"),
            "qualified": counts.get("qualified"),
            "monitored": counts.get("monitored"),
            "attributable_timely_events": sum(row["timely"] for row in decisions.values()),
            "eligible_decisions": sum(row["eligible"] for row in decisions.values()),
            "risk_approved": sum(
                bool(row.get("risk") and row["risk"]["approved"]) for row in decisions.values()
            ),
            "submitted": sum(
                "UNCERTAIN_SUBMIT" in row.get("timeline", {}) for row in orders.values()
            ),
            "filled": len(fill_counts),
            "finalized": sum(row["state"] == "FINALIZED" for row in orders.values()),
            "rejected_reasons": dict(sorted(reasons.items())),
        },
        "economics": {
            "status": "UNKNOWN_QUARANTINED_FINANCIAL_EVIDENCE"
            if quarantined
            else "NO_FINANCIAL_OBSERVATIONS"
            if not state["fills"]
            else "COMPLETE"
            if pnl.valuation_complete
            else "PARTIAL_UNKNOWN_MARKS",
            "realized_pnl": None if quarantined else str(pnl.realized_pnl),
            "fees": None if quarantined else str(pnl.fees),
            "known_accounted_fees": str(pnl.fees),
            "unrealized_pnl": str(pnl.unrealized_pnl)
            if pnl.valuation_complete and not quarantined
            else None,
            "net_pnl": str(pnl.net_pnl)
            if pnl.valuation_complete and state["fills"] and not quarantined
            else None,
            "cash": None if quarantined else str(ledger.cash),
            "drawdown": str(drawdown) if measured else None,
            "drawdown_samples": measured,
            "incomplete_valuations": incomplete_valuations,
            "open_positions": len(ledger.positions),
            "censored_orders": len(active),
            "provider_cost": None,
            "infrastructure_cost": None,
            "provider_cost_reserved": state["source_cost"],
            "valuation_method": latest["method"]
            if valuation_fresh and latest is not None
            else None,
            "valued_at": latest["at"] if valuation_fresh and latest is not None else None,
            "leader_follower_divergence": divergence,
            "source_value": "UNKNOWN; source-removal replay is counterfactual, not causal P&L",
            "accounting": "Actual fill prices contain spread/slippage; recorded fees charged once.",
        },
        "latency": latency
        or {
            "bottleneck": None,
            "sample_count": 0,
            "missing_count": None,
            "censored_count": len(active),
            "clock_quality": "UNKNOWN",
        },
        "sources": sources or [],
    }
