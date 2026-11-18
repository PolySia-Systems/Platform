"""Project retained paper-run evidence without synthesizing legacy values."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, cast

from polysia.domain.copytrading.watchlist_shadow import FILL_REASON, MAX_MARK_AGE_SECONDS
from polysia.monitoring.console_contract import (
    ShadowEventDetail,
    ShadowPositionDetail,
    ShadowRunDetail,
    WatchlistRun,
    WatchlistRunWallet,
)

DETAIL_PAGE_SIZE = 30


def _position(
    token: str, record: list[str], mark: dict[str, str], as_of: datetime | None,
) -> ShadowPositionDetail:
    if mark and as_of is not None:
        valid = (
            datetime.fromisoformat(mark["received_at"]) <= as_of
            and (
                mark["source"] == "verified-settlement"
                or as_of - datetime.fromisoformat(mark["quote_at"])
                <= timedelta(seconds=MAX_MARK_AGE_SECONDS)
            )
        )
    else:
        valid = False
    mark = mark if valid else {}
    return ShadowPositionDetail(
        outcome=token, quantity=record[0], cost=record[1],
        marked_quantity=mark.get("quantity"), value=mark.get("value"), fee=mark.get("fee"),
        quote_at=mark.get("quote_at"), received_at=mark.get("received_at"),
        source=mark.get("source"),
    )


def _positions(state: dict[str, Any], as_of: datetime | None) -> list[ShadowPositionDetail]:
    marks = state.get("marks", {})
    return [
        _position(token, record, marks.get(token, {}), as_of)
        for token, record in state["positions"].items()
    ]


def _cutoff(status: str, data: dict[str, Any]) -> str | None:
    if status == "RUNNING":
        return None
    return cast(str | None, data.get(
        "cutoff_at", data["ends_at"] if status == "FINISHED" else data["finished_at"],
    ))


def _sum(values: list[str]) -> Decimal:
    return sum(map(Decimal, values), Decimal(0))


def summary(status: str, data: dict[str, Any]) -> WatchlistRun:
    cutoff = _cutoff(status, data)
    cutoff_at = datetime.fromisoformat(cutoff) if cutoff else None
    wallets = []
    for address, value in data["wallets"].items():
        # A running quote is not an ending value.
        positions = _positions(value, cutoff_at)
        marked = [p for p in positions if p.marked_quantity and Decimal(p.marked_quantity) > 0]
        marked_value = _sum([p.value or "0" for p in marked])
        marked_cost = sum(
            (Decimal(p.cost) * Decimal(p.marked_quantity or "0") / Decimal(p.quantity)
             for p in marked),
            Decimal(0),
        )
        events = list(value["events"].values())
        wallets.append(WatchlistRunWallet(
            address=address, observed_through=value["through"],
            observations=value["observations"], read_errors=value["read_errors"],
            fills=events.count(FILL_REASON), skipped=len(events) - events.count(FILL_REASON),
            open_positions=len(positions), realized=value["realized"], cash=value["cash"],
            fees=value["fees"], slippage=value["slippage"], closed_positions=value.get("closed"),
            open_cost=str(_sum([p.cost for p in positions])),
            marked_positions=len(marked),
            valued_positions=sum(
                p.marked_quantity is not None and Decimal(p.marked_quantity) == Decimal(p.quantity)
                for p in marked
            ),
            marked_value=str(marked_value), marked_pnl=str(marked_value - marked_cost),
            gaps=list(value.get("gaps", {})),
        ))
    coverage: Literal["observing", "covered", "incomplete", "none"]
    if status == "RUNNING":
        coverage = "observing"
    elif not any(w.observations for w in wallets):
        coverage = "none"
    elif cutoff_at is None or any(
        not w.observations or datetime.fromisoformat(w.observed_through) < cutoff_at
        or any(key != "valuation_budget" for key in w.gaps)
        for w in wallets
    ):
        coverage = "incomplete"
    else:
        coverage = "covered"
    equity = None
    cash = _sum([w.cash for w in wallets])
    total_marked_value = _sum([w.marked_value for w in wallets])
    marked_pnl = _sum([w.marked_pnl for w in wallets])
    marked_cost = total_marked_value - marked_pnl
    if wallets and all(w.observations and w.open_positions == w.valued_positions for w in wallets):
        equity = cash + total_marked_value
    net_pnl = (
        str(equity - Decimal(data["started_cash_per_wallet"]) * len(wallets))
        if equity is not None and cutoff_at is not None and coverage == "covered" else None
    )
    return WatchlistRun(
        id=data["id"], name=data["name"], model=data["model"], status=cast(Any, status),
        started_at=data["started_at"], ends_at=data["ends_at"], finished_at=data["finished_at"],
        started_cash_per_wallet=data["started_cash_per_wallet"], cutoff_at=cutoff,
        end_reason=data.get("end_reason"), realized=str(_sum([w.realized for w in wallets])),
        equity=str(equity) if equity is not None else None, net_pnl=net_pnl,
        cash=str(cash), marked_pnl=str(marked_pnl),
        unvalued_cost=str(_sum([w.open_cost for w in wallets]) - marked_cost),
        coverage=coverage, wallets=wallets,
    )


def detail(status: str, data: dict[str, Any], wallet: str, offset: int) -> ShadowRunDetail:
    state = data["wallets"].get(wallet)
    if state is None:
        raise LookupError("record_or_route_missing")
    cutoff = _cutoff(status, data)
    positions = _positions(state, datetime.fromisoformat(cutoff) if cutoff else None)
    fills = state.get("fills", {})
    events = list(state["events"].items())
    stop = offset + DETAIL_PAGE_SIZE
    return ShadowRunDetail(
        positions=positions[offset:stop],
        events=[
            ShadowEventDetail(id=key, reason=reason, **fills.get(key, {}))
            for key, reason in events[offset:stop]
        ],
        next_offset=stop if stop < max(len(events), len(positions)) else None,
    )
