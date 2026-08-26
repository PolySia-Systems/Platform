from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from polysia.domain.copytrading import LeaderTradeAction
from polysia.domain.copytrading.continuous_shadow import ZERO


@dataclass(frozen=True, slots=True)
class RecordedShadowFill:
    """One already-simulated evaluation used for report-time counterfactuals."""

    evaluated_at: datetime
    wallet_id: str
    pool_class: str
    action: LeaderTradeAction
    leader_price: Decimal
    follower_price: Decimal | None
    filled_size: Decimal
    gross_notional: Decimal | None
    fee: Decimal | None
    price_movement: Decimal | None
    spread_cost: Decimal | None
    depth_impact: Decimal | None
    realized_pnl: Decimal | None
    status: str


@dataclass(frozen=True, slots=True)
class ShadowPolicySpec:
    policy_id: str
    description: str
    price_drift_max_ratio: Decimal | None = None
    entry_price_min: Decimal | None = None
    entry_price_max: Decimal | None = None
    max_cost_ratio: Decimal | None = None
    pools: frozenset[str] | None = None
    minimum_wallet_fills: int = 0


BASELINE_POLICY = ShadowPolicySpec(
    policy_id="baseline-unfiltered-v0.2",
    description="Recorded baseline fills with no extra eligibility filter.",
)

REPORT_POLICIES: tuple[ShadowPolicySpec, ...] = (
    BASELINE_POLICY,
    ShadowPolicySpec(
        policy_id="price-drift-2pct",
        description="Reject BUY fills whose adverse price move exceeds 2% of notional.",
        price_drift_max_ratio=Decimal("0.02"),
    ),
    ShadowPolicySpec(
        policy_id="price-drift-5pct",
        description="Reject BUY fills whose adverse price move exceeds 5% of notional.",
        price_drift_max_ratio=Decimal("0.05"),
    ),
    ShadowPolicySpec(
        policy_id="price-drift-10pct",
        description="Reject BUY fills whose adverse price move exceeds 10% of notional.",
        price_drift_max_ratio=Decimal("0.10"),
    ),
    ShadowPolicySpec(
        policy_id="entry-band-05-95",
        description="Follow BUY fills only when follower price is inside [0.05, 0.95].",
        entry_price_min=Decimal("0.05"),
        entry_price_max=Decimal("0.95"),
    ),
    ShadowPolicySpec(
        policy_id="entry-band-20-80",
        description="Follow BUY fills only when follower price is inside [0.20, 0.80].",
        entry_price_min=Decimal("0.20"),
        entry_price_max=Decimal("0.80"),
    ),
    ShadowPolicySpec(
        policy_id="alpha-only",
        description="Keep fills from Alpha or Alpha/Stress overlap wallets only.",
        pools=frozenset({"ALPHA", "ALPHA_STRESS"}),
    ),
    ShadowPolicySpec(
        policy_id="stress-only",
        description="Keep fills from Stress or Alpha/Stress overlap wallets only.",
        pools=frozenset({"STRESS", "ALPHA_STRESS"}),
    ),
    ShadowPolicySpec(
        policy_id="cost-aware-3pct",
        description="Reject BUY fills whose spread, depth, and fee exceed 3% of notional.",
        max_cost_ratio=Decimal("0.03"),
    ),
    ShadowPolicySpec(
        policy_id="wallet-min-evidence-3",
        description="Count a wallet only after three earlier simulated BUY fills.",
        minimum_wallet_fills=3,
    ),
)


def fill_passes_policy(
    fill: RecordedShadowFill,
    policy: ShadowPolicySpec,
    *,
    prior_wallet_buy_count: int,
) -> bool:
    if fill.status != "SIMULATED":
        return False
    if policy.pools is not None and fill.pool_class not in policy.pools:
        return False
    if policy.minimum_wallet_fills and prior_wallet_buy_count < policy.minimum_wallet_fills:
        return False
    if fill.action is not LeaderTradeAction.BUY:
        return True
    if fill.follower_price is None or fill.gross_notional is None or fill.gross_notional <= ZERO:
        return False
    if policy.entry_price_min is not None and fill.follower_price < policy.entry_price_min:
        return False
    if policy.entry_price_max is not None and fill.follower_price > policy.entry_price_max:
        return False
    if (
        policy.price_drift_max_ratio is not None
        and fill.price_movement is not None
        and fill.price_movement / fill.gross_notional > policy.price_drift_max_ratio
    ):
        return False
    if policy.max_cost_ratio is not None:
        cost = (fill.spread_cost or ZERO) + (fill.depth_impact or ZERO) + (fill.fee or ZERO)
        if cost / fill.gross_notional > policy.max_cost_ratio:
            return False
    return True


def _window_summary(fills: tuple[RecordedShadowFill, ...]) -> dict[str, object]:
    buys = tuple(item for item in fills if item.action is LeaderTradeAction.BUY)
    closes = tuple(
        item
        for item in fills
        if item.action is LeaderTradeAction.SELL and item.realized_pnl is not None
    )
    realized = sum((item.realized_pnl or ZERO for item in closes), ZERO)
    fees = sum((item.fee or ZERO for item in fills), ZERO)
    adverse = tuple(
        item
        for item in buys
        if item.price_movement is not None
        and item.gross_notional is not None
        and item.gross_notional > ZERO
        and item.price_movement / item.gross_notional > Decimal("0.02")
    )
    return {
        "accepted_fill_count": len(fills),
        "buy_count": len(buys),
        "close_count": len(closes),
        "fee_total": format(fees, "f"),
        "recorded_close_realized_pnl": format(realized, "f"),
        "recorded_close_net": format(realized - fees, "f"),
        "substantial_adverse_buy_count": len(adverse),
        "wallet_count": len({item.wallet_id for item in fills}),
    }


def walk_forward_policy_report(
    fills: tuple[RecordedShadowFill, ...],
    *,
    split_at: datetime | None = None,
) -> dict[str, object]:
    """Score versioned filters on already-recorded fills without look-ahead.

    In-sample fills before ``split_at`` are reported only as context. The
    out-of-sample window is the decision-relevant result. This is not a full
    book resimulation and is not a profitability claim.
    """

    ordered = tuple(sorted(fills, key=lambda item: (item.evaluated_at, item.wallet_id)))
    simulated = tuple(item for item in ordered if item.status == "SIMULATED")
    if split_at is None:
        if not simulated:
            split_at = datetime.min
        else:
            midpoint = (len(simulated) - 1) // 2
            split_at = simulated[midpoint].evaluated_at
    policies = []
    for policy in REPORT_POLICIES:
        in_sample: list[RecordedShadowFill] = []
        out_of_sample: list[RecordedShadowFill] = []
        prior_buys: dict[str, int] = {}
        for fill in simulated:
            prior = prior_buys.get(fill.wallet_id, 0)
            accepted = fill_passes_policy(fill, policy, prior_wallet_buy_count=prior)
            if fill.evaluated_at <= split_at:
                if accepted:
                    in_sample.append(fill)
            elif accepted:
                out_of_sample.append(fill)
            if fill.action is LeaderTradeAction.BUY and fill.evaluated_at <= split_at:
                prior_buys[fill.wallet_id] = prior + 1
        policies.append(
            {
                "description": policy.description,
                "in_sample": _window_summary(tuple(in_sample)),
                "out_of_sample": _window_summary(tuple(out_of_sample)),
                "policy_id": policy.policy_id,
            }
        )
    return {
        "claim": "not_a_profitability_or_live_promotion_result",
        "look_ahead": False,
        "policies": policies,
        "semantics": (
            "Walk-forward fill filters on recorded SIMULATED evaluations. "
            "In-sample fills never update out-of-sample selection. Close P&L is "
            "the recorded evaluation value, not a resimulated inventory path."
        ),
        "split_at": None if not simulated else split_at.isoformat(),
        "source_fill_count": len(simulated),
    }


__all__ = [
    "BASELINE_POLICY",
    "REPORT_POLICIES",
    "RecordedShadowFill",
    "ShadowPolicySpec",
    "fill_passes_policy",
    "walk_forward_policy_report",
]
