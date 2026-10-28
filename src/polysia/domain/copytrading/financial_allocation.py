"""Leader/policy ownership inside the existing session financial state.

Quantity follows confirmed fills. Cost uses the existing account pooled-average
basis; the last sorted owner retains Decimal residuals. This is an ownership
projection, not another ledger or independently spendable cash balance.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import Any

from polysia.domain.financial_session import SessionBlocked, digest

ZERO = Decimal("0")


def pending_entry_debit(state: dict[str, Any]) -> Decimal:
    """Conservative cash hold for active BUYs; terminal orders reserve nothing.

    Keep the full approved debit while any remainder is unresolved. Actual held
    cash and independent Risk/exposure checks still own final admission.
    """
    return sum(
        (
            Decimal(order["reservation"])
            for order in state["orders"].values()
            if order["side"] == "BUY"
            and order["state"] not in {"REJECTED", "CANCELLED", "FINALIZED"}
        ),
        ZERO,
    )


def allocation_key(account: str, token: str, wallet: str, policy: str) -> str:
    return digest((account, token, wallet, policy))


def allocations(
    state: dict[str, Any],
    *,
    account: str,
    aggregate: dict[str, tuple[Decimal, Decimal]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    timeline = [(row["confirmed_at"], "fill", row) for row in state["fills"]]
    timeline += [(row["occurred_at"], "redemption", row) for row in state.get("cash_events", [])]
    for _, kind, fill in sorted(
        timeline, key=lambda item: (item[0], tuple(item[2].get("chain_order") or (-1, -1)))
    ):
        if kind == "redemption":
            for token, removed in fill["removed"]:
                owners = sorted(
                    (key, row)
                    for key, row in result.items()
                    if row["token"] == token and row["quantity"] > 0
                )
                total = sum((row["quantity"] for _, row in owners), ZERO)
                remaining = Decimal(removed)
                if remaining > total:
                    raise SessionBlocked("redemption_exceeds_allocated_inventory")
                for index, (_, row) in enumerate(owners):
                    share = (
                        remaining
                        if index == len(owners) - 1
                        else (Decimal(removed) * row["quantity"] / total).quantize(
                            Decimal("0.000001"), rounding=ROUND_DOWN
                        )
                    )
                    # The last sorted owner retains the exact residual. Never
                    # allocate a later BUY to an earlier cash observation.
                    row["fees"] *= (row["quantity"] - share) / row["quantity"]
                    row["quantity"] -= share
                    remaining -= share
            continue
        order = state["orders"][fill["intent_id"]]
        policy = order.get("policy_digest", state["authorization"]["binding"]["policy"])
        key = allocation_key(account, fill["token"], order["wallet"], policy)
        row = result.setdefault(
            key,
            {
                "account": account,
                "token": fill["token"],
                "wallet": order["wallet"],
                "policy": policy,
                "quantity": ZERO,
                "cost_basis": ZERO,
                "fees": ZERO,
                "opened_at": fill["confirmed_at"],
                "pending_buy": ZERO,
                "pending_sell": ZERO,
            },
        )
        shares = Decimal(fill["shares"])
        if fill["side"] == "BUY":
            if row["quantity"] == 0:
                row["opened_at"] = fill["confirmed_at"]
            row["quantity"] += shares
            row["fees"] += Decimal(fill["fee"])
        else:
            if shares > row["quantity"]:
                raise SessionBlocked("leader_allocation_oversold")
            row["fees"] *= (row["quantity"] - shares) / row["quantity"]
            row["quantity"] -= shares
        if row["quantity"] < 0:
            raise SessionBlocked("leader_allocation_oversold")
    for identity, order in state["orders"].items():
        if order["state"] in {"REJECTED", "CANCELLED", "FINALIZED"}:
            continue
        policy = order.get("policy_digest", state["authorization"]["binding"]["policy"])
        key = allocation_key(account, order["token"], order["wallet"], policy)
        row = result.setdefault(
            key,
            {
                "account": account,
                "token": order["token"],
                "wallet": order["wallet"],
                "policy": policy,
                "quantity": ZERO,
                "cost_basis": ZERO,
                "fees": ZERO,
                "opened_at": order["created_at"],
                "pending_buy": ZERO,
                "pending_sell": ZERO,
            },
        )
        filled = sum(
            (Decimal(fill["shares"]) for fill in state["fills"] if fill["intent_id"] == identity),
            ZERO,
        )
        field = "pending_buy" if order["side"] == "BUY" else "pending_sell"
        row[field] += max(ZERO, Decimal(order["shares"]) - filled)
    for token in set(aggregate) | {row["token"] for row in result.values()}:
        rows = sorted(
            (key, row)
            for key, row in result.items()
            if row["token"] == token and row["quantity"] > 0
        )
        quantity, cost = aggregate.get(token, (ZERO, ZERO))
        if sum((row["quantity"] for _, row in rows), ZERO) != quantity:
            raise SessionBlocked("allocation_quantity_does_not_equal_account")
        remaining = cost
        for index, (_, row) in enumerate(rows):
            share = remaining if index == len(rows) - 1 else cost * row["quantity"] / quantity
            row["cost_basis"] = share
            remaining -= share
    return result
