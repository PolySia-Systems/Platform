from __future__ import annotations

from datetime import datetime

from polysia.execution.canonical_order import (
    ApprovedOrder,
    CanonicalMarketOrderRequest,
    bind_approved_order,
    risk_intent_from_canonical,
)
from polysia.execution.intents import OrderIntent
from polysia.execution.live_broker import LiveBrokerError
from polysia.risk.checks import RiskContext, RiskEngine


def approve_live_market_order(
    risk_engine: RiskEngine,
    intent: OrderIntent,
    canonical: CanonicalMarketOrderRequest,
    context: RiskContext,
    *,
    approved_at: datetime,
) -> ApprovedOrder:
    """Evaluate the canonical request under Risk and freeze the approved exposure."""

    decision = risk_engine.evaluate(risk_intent_from_canonical(intent, canonical), context)
    if not decision.approved or decision.adjusted_size is None:
        reason = decision.reason if not decision.approved else "missing adjusted size"
        raise LiveBrokerError(f"risk engine blocked live order: {reason}")
    return bind_approved_order(
        canonical,
        adjusted_size=decision.adjusted_size,
        risk_reason=decision.reason,
        approved_at=approved_at,
    )
