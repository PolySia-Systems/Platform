"""Exact, bounded account evidence. Public V2 inventory is never the authority.

Finalized chain cash/CTF balances and actual fee events are bracketed by stable
authenticated CLOB order/trade walks. Any incomplete, in-flight, changed or
unmapped evidence denies financial readiness rather than inventing a snapshot.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from polysia.adapters.polymarket.session_chain import ChainFill, CTFChainReader, address
from polysia.domain.financial_session import (
    AccountObservation,
    InstrumentScope,
    SessionBlocked,
    digest,
)


@dataclass(frozen=True, slots=True)
class ExactAccountMapping:
    account_id: str
    signer: str
    funder: str
    signature_type: int
    venue: str
    collateral: str
    settlement_route: str

    def __post_init__(self) -> None:
        address(self.signer)
        address(self.funder)
        address(self.collateral)
        # Deliberately bounded first composition: no implicit proxy/deposit-wallet
        # creation, approvals or signer/funder substitution in SDK bootstrap.
        if (
            self.signature_type != 0
            or self.signer.lower() != self.funder.lower()
            or self.venue != "polymarket"
            or not self.account_id
            or self.settlement_route != "ctf-exchange-v2-standard"
        ):
            raise SessionBlocked("unsupported_exact_account_mapping")


class ExactSessionAccountReader:
    def __init__(
        self,
        client: Any,
        chain: CTFChainReader,
        mapping: ExactAccountMapping,
        *,
        maximum_pages: int,
        maximum_age_seconds: int,
        clock: Callable[[], datetime],
        collateral_adapter: str | None = None,
        recognition_since: datetime | None = None,
    ) -> None:
        if not 0 < maximum_pages <= 100 or maximum_age_seconds <= 0:
            raise SessionBlocked("bounded_account_read_required")
        self.client, self.chain, self.mapping = client, chain, mapping
        self.maximum_pages, self.maximum_age, self.clock = maximum_pages, maximum_age_seconds, clock
        self.last_fills: tuple[ChainFill, ...] = ()
        self.last_orders: dict[str, dict[str, Any]] = {}
        self.last_evidence: dict[str, Any] = {}
        self.collateral_adapter, self.recognition_since = collateral_adapter, recognition_since
        self.last_redemptions: tuple[Any, ...] = ()
        self.last_observation: AccountObservation | None = None

    def require_identity(self) -> None:
        if (
            address(str(self.client.signer)) != address(self.mapping.signer)
            or address(str(self.client.wallet)) != address(self.mapping.funder)
            or str(self.client.wallet_type) != "EOA"
            or self.chain.collateral != address(self.mapping.collateral)
        ):
            raise SessionBlocked("authenticated_account_identity_changed")

    async def observe(self, instrument: InstrumentScope) -> AccountObservation:
        self.require_identity()
        if self.chain.instruments.get(instrument.token) != instrument:
            raise SessionBlocked("account_instrument_mapping_mismatch")
        start = self.clock()
        before = await self._clob_view()
        block = await self.chain.finalized()
        fills = await self.chain.fills(self.mapping.funder, block=block, observed_at=self.clock())
        cash = await self.chain.cash(self.mapping.funder, block=block)
        positions = await self.chain.holdings(self.mapping.funder, block=block)
        redemptions: tuple[Any, ...] = ()
        if self.collateral_adapter is not None and self.recognition_since is not None:
            redemptions = await self.chain.redemptions(
                self.mapping.funder,
                account_id=self.mapping.account_id,
                adapter=self.collateral_adapter,
                since=self.recognition_since,
                block=block,
            )
        balance = await self.client.get_balance_allowance(asset_type="COLLATERAL")
        after = await self._clob_view()
        canonical = await self.chain.rpc.call("eth_getBlockByNumber", [block["number"], False])
        now = self.clock()
        if (
            before != after
            or canonical.get("hash") != block["hash"]
            or not 0 <= (now - start).total_seconds() <= self.maximum_age
            or Decimal(str(field(balance, "balance"))) / Decimal("1000000") != cash
        ):
            raise SessionBlocked("account_snapshot_changed_or_temporally_incoherent")
        block_time = datetime.fromtimestamp(int(block["timestamp"], 16), now.tzinfo)
        if not 0 <= (now - block_time).total_seconds() <= self.maximum_age:
            raise SessionBlocked("account_finality_or_clock_stale")
        known_transactions = {fill.occurrence.transaction for fill in fills}
        for trade in before["trades"]:
            if (
                trade["status"] != "CONFIRMED"
                or trade["transaction_hash"].lower() not in known_transactions
                or datetime.fromisoformat(trade["updated_at"]) > block_time
            ):
                raise SessionBlocked("account_trade_finality_not_coherent")
        chain_trades: dict[tuple[str, str, str, str], tuple[Decimal, Decimal]] = {}
        for fill in fills:
            key = (
                fill.occurrence.transaction.lower(),
                fill.order_hash.lower(),
                fill.occurrence.instrument.token,
                fill.occurrence.side,
            )
            size, notional = chain_trades.get(key, (Decimal(0), Decimal(0)))
            chain_trades[key] = (size + fill.shares, notional + fill.collateral)
        clob_trades: dict[tuple[str, str, str, str], tuple[Decimal, Decimal]] = {}
        for trade in before["trades"]:
            for leg in trade["contributions"]:
                key = (
                    trade["transaction_hash"].lower(),
                    leg["order_id"].lower(),
                    leg["token"],
                    leg["side"],
                )
                size, notional = clob_trades.get(key, (Decimal(0), Decimal(0)))
                quantity, price = Decimal(leg["size"]), Decimal(leg["price"])
                clob_trades[key] = size + quantity, notional + quantity * price
        if set(chain_trades) != set(clob_trades) or any(
            chain_trades[key][0] != size
            or abs(chain_trades[key][1] - notional) > Decimal("0.000001") * (size + 1)
            for key, (size, notional) in clob_trades.items()
        ):
            raise SessionBlocked("account_chain_and_CLOB_trade_inventory_disagree")
        self.last_fills = fills
        self.last_redemptions = redemptions
        self.last_orders = {row["id"]: row for row in before["orders"]}
        self.last_evidence = {
            "block": block,
            "clob": before,
            "positions": positions,
            "cash": cash,
            "mapping": self.mapping.account_id,
            "started_at": start,
            "completed_at": now,
            "fee_occurrences": [fill.occurrence.identity for fill in fills],
        }
        observation = AccountObservation(
            self.mapping.account_id,
            now,
            cash,
            positions,
            frozenset(self.last_orders),
            sum((fill.fee for fill in fills), Decimal("0")),
            True,
            digest(self.last_evidence),
        )
        self.last_observation = observation
        return observation

    async def _clob_view(self) -> dict[str, Any]:
        orders = await self._walk(self.client.list_open_orders())
        trades = await self._walk(self.client.list_account_trades())
        order_rows = [
            extract(
                row,
                (
                    "id",
                    "asset_id",
                    "side",
                    "status",
                    "original_size",
                    "size_matched",
                    "price",
                    "maker_address",
                    "market",
                ),
            )
            for row in orders
        ]
        trade_rows = [
            extract(
                row,
                (
                    "id",
                    "asset_id",
                    "side",
                    "status",
                    "transaction_hash",
                    "updated_at",
                    "size",
                    "price",
                ),
            )
            for row in trades
        ]
        for raw, row in zip(trades, trade_rows, strict=True):
            if field(raw, "trader_side") == "TAKER":
                legs = [
                    {
                        "order_id": str(field(raw, "taker_order_id")),
                        "token": row["asset_id"],
                        "side": row["side"],
                        "size": row["size"],
                        "price": row["price"],
                    }
                ]
            elif field(raw, "trader_side") == "MAKER":
                legs = [
                    {
                        "order_id": str(field(item, "order_id")),
                        "token": str(field(item, "asset_id")),
                        "side": str(field(item, "side")),
                        "size": str(field(item, "matched_amount")),
                        "price": str(field(item, "price")),
                    }
                    for item in field(raw, "maker_orders")
                    if address(str(field(item, "maker_address"))) == address(self.mapping.funder)
                ]
            else:
                raise SessionBlocked("account_trade_role_unknown")
            if not legs or any(
                leg["order_id"] in {"None", ""}
                or leg["token"] not in self.chain.instruments
                or leg["side"] not in {"BUY", "SELL"}
                or not 0 < Decimal(leg["price"]) <= 1
                or Decimal(leg["size"]) <= 0
                for leg in legs
            ):
                raise SessionBlocked("account_trade_ownership_or_contribution_unknown")
            row["contributions"] = legs
        for row in order_rows:
            if (
                address(row["maker_address"]) != address(self.mapping.funder)
                or row["market"] != self.chain.instruments[row["asset_id"]].market
                or row["side"] not in {"BUY", "SELL"}
                or not 0 <= Decimal(row["size_matched"]) <= Decimal(row["original_size"])
                or not 0 < Decimal(row["price"]) < 1
            ):
                raise SessionBlocked("account_open_order_mapping_unknown")
        for row in order_rows + trade_rows:
            if row["asset_id"] not in self.chain.instruments:
                raise SessionBlocked("unmapped_account_order_or_trade")
        return {"orders": sorted_unique(order_rows), "trades": sorted_unique(trade_rows)}

    async def _walk(self, pages: Any) -> list[Any]:
        rows, cursors = [], set()
        count = 0
        async for page in pages:
            count += 1
            if count > self.maximum_pages or page.limit_reached:
                raise SessionBlocked("account_page_budget_exhausted")
            rows.extend(page.items)
            if not page.has_more:
                return rows
            if not page.next_cursor or page.next_cursor in cursors:
                raise SessionBlocked("account_cursor_repeated_or_missing")
            cursors.add(page.next_cursor)
        raise SessionBlocked("account_terminal_page_missing")


def field(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def extract(value: Any, names: tuple[str, ...]) -> dict[str, Any]:
    result = {}
    for name in names:
        item = field(value, name)
        if item is None:
            raise SessionBlocked("account_row_field_missing")
        result[name] = item.isoformat() if isinstance(item, datetime) else str(item)
    return result


def sorted_unique(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["id"] in unique and unique[row["id"]] != row:
            raise SessionBlocked("conflicting_account_row")
        unique[row["id"]] = row
    return [unique[key] for key in sorted(unique)]
