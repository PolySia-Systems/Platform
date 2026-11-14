"""Polymarket evidence limited to an owner-operated order lifecycle."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from polymarket.errors import RequestRejectedError

from polysia.adapters.polymarket.session_account import ClobSessionReads, ExactAccountMapping, field
from polysia.domain.financial_session import (
    AccountObservation,
    ConfirmedSessionFill,
    InstrumentScope,
    SessionBlocked,
    digest,
    utc,
)
from polysia.storage.financial_session import FinancialSessionJournal

TERMINAL_TRADE = frozenset({"CONFIRMED", "FAILED"})


class APISettlementPending(SessionBlocked):
    """Read again within the same budget; no account or mutation clearance."""
PENDING_TRADE = frozenset({"MATCHED", "MATCHED_NOT_BROADCASTED", "MINED", "RETRYING"})
UNIT = Decimal(1_000_000)


def explicit_zero_fee_market(
    market: Any, token: str, *, gamma: Any = None, fee_rate: Any = None,
) -> bool:
    # Explicit curves come from CLOB. A missing curve needs the independent
    # exact Gamma feesEnabled flag and the authenticated route's public fee rate.
    if not isinstance(market, dict) or not isinstance(tokens := market.get("t"), list):
        return False
    if not any(isinstance(item, dict) and str(item.get("t")) == token for item in tokens):
        return False
    fee = market.get("fd")
    if isinstance(fee, dict) and type(fee.get("r")) in (Decimal, int, str):
        try:
            return Decimal(fee["r"]) == 0 and fee.get("to") is True
        except InvalidOperation:
            return False
    if fee is not None or not isinstance(gamma, list) or len(gamma) != 1:
        return False
    row = gamma[0]
    if (
        not isinstance(row, dict)
        or row.get("conditionId") != market.get("c")
        or row.get("feesEnabled") is not False
        or row.get("negRisk") is not False
        or not isinstance(fee_rate, dict)
        or type(fee_rate.get("base_fee")) is not int
        or fee_rate["base_fee"] != 0
    ):
        return False
    try:
        gamma_tokens = json.loads(row["clobTokenIds"])
    except (KeyError, TypeError, ValueError):
        return False
    return isinstance(gamma_tokens, list) and token in gamma_tokens


def _atomic(value: object) -> Decimal:
    if type(value) is not int or value < 0:
        raise SessionBlocked("invalid_CLOB_atomic_amount")
    return Decimal(value) / UNIT


def _amount(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal | str | int):
        raise SessionBlocked("invalid_CLOB_fill_amount")
    result = Decimal(value)
    if not result.is_finite() or result <= 0:
        raise SessionBlocked("invalid_CLOB_fill_amount")
    return result


class OrderLifecycleAccountReader(ClobSessionReads):
    """No full-account observation or venue mutation can originate here."""

    def __init__(
        self, client: Any, mapping: ExactAccountMapping, *, maximum_pages: int,
        clock: Callable[[], datetime], maximum_age_seconds: int = 30,
        trades_after: datetime | None = None,
    ) -> None:
        super().__init__(client, mapping, maximum_pages=maximum_pages)
        if mapping.signature_type != 3 or not 0 < maximum_age_seconds <= 30:
            raise SessionBlocked("owner_deposit_wallet_and_bounded_freshness_required")
        self.clock, self.maximum_age_seconds = clock, maximum_age_seconds
        self.trades_after = None if trades_after is None else utc(trades_after)

    async def _current_trades(self) -> list[Any]:
        if self.trades_after is None:
            return await self._walk(self.client.list_account_trades())
        if self.trades_after > self.clock():
            raise SessionBlocked("API_trade_baseline_in_future")
        return await self._walk(self.client.list_account_trades(
            after=str(int(self.trades_after.timestamp())),
        ))

    async def observe(
        self, instrument: InstrumentScope, *, exchange: str,
        tracked: Mapping[str, str], explicit_zero_fee: bool,
    ) -> dict[str, Any]:
        self.require_identity()
        if instrument.collateral.lower() != self.mapping.collateral.lower() or (
            instrument.settlement_route != self.mapping.settlement_route
        ):
            raise SessionBlocked("lifecycle_instrument_binding_mismatch")
        started = self.clock()
        before = await self._matching_open_orders()
        trades = await self._current_trades()
        collateral = await self.client.get_balance_allowance(asset_type="COLLATERAL")
        position = await self.client.get_balance_allowance(
            asset_type="CONDITIONAL", asset_id=instrument.token,
        )
        details = {}
        for identity in tracked:
            try:
                details[identity] = await self.client.get_order(order_id=identity)
            except RequestRejectedError as error:
                if error.status != 404:
                    raise
                details[identity] = None
        after = await self._matching_open_orders()
        repeated_trades = await self._current_trades() if tracked else trades
        finished = self.clock()

        def open_facts(rows: list[Any]) -> dict[str, tuple[str, ...]]:
            facts: dict[str, tuple[str, ...]] = {}
            for row in rows:
                identity = field(row, "id")
                if not isinstance(identity, str) or not identity or identity in facts:
                    raise SessionBlocked("invalid_or_duplicate_CLOB_order")
                facts[identity] = tuple(str(field(row, name)) for name in (
                    "maker_address", "market", "asset_id", "side", "status", "size_matched",
                ))
            return facts

        open_orders = open_facts(after)
        if open_facts(before) != open_orders or not (
            0 <= (finished - started).total_seconds() <= self.maximum_age_seconds
        ):
            raise SessionBlocked("lifecycle_order_or_freshness_changed")
        foreign_open = set(open_orders) - set(tracked)
        for identity in set(open_orders) & set(tracked):
            maker, market, token, side = open_orders[identity][:4]
            if (maker.lower(), market.lower(), token, side) != (
                self.mapping.funder.lower(), instrument.market.lower(), instrument.token,
                tracked[identity],
            ):
                raise SessionBlocked("tracked_order_identity_mismatch")

        allowances = field(collateral, "allowances")
        if not isinstance(allowances, dict):
            raise SessionBlocked("CLOB_exchange_allowance_missing")
        matching = [quantity for spender, quantity in allowances.items()
                    if str(spender).lower() == exchange.lower()]
        allowance = _atomic(matching[0]) if len(matching) == 1 else None
        cash = _atomic(field(collateral, "balance"))
        conditional = _atomic(field(position, "balance"))
        fills, pending = self._trade_facts(trades, instrument, tracked, explicit_zero_fee)
        if tracked:
            later = self._trade_facts(repeated_trades, instrument, tracked, explicit_zero_fee)
            if later != (fills, pending):
                raise SessionBlocked("lifecycle_trade_observation_changed")
        order_evidence = {}
        for identity, detail in details.items():
            if detail is None:
                order_evidence[identity] = {"status": "UNKNOWN", "terminal_evidence": False}
                continue
            if (
                field(detail, "id") != identity
                or str(field(detail, "maker_address")).lower() != self.mapping.funder.lower()
                or str(field(detail, "market")).lower() != instrument.market.lower()
                or field(detail, "asset_id") != instrument.token
                or field(detail, "side") != tracked[identity]
            ):
                raise SessionBlocked("tracked_order_detail_identity_mismatch")
            confirmed = [fill for fill in fills if fill["order_id"] == identity]
            settled = sum((fill["shares"] for fill in confirmed), Decimal(0))
            original = _amount(field(detail, "original_size"))
            matched = Decimal(str(field(detail, "size_matched")))
            if not matched.is_finite() or not 0 <= settled <= matched <= original:
                raise SessionBlocked("tracked_order_quantity_disagrees")
            status = str(field(detail, "status")).upper()
            order_evidence[identity] = {
                "status": status,
                "confirmed_shares": settled,
                "matched_shares": matched,
                "terminal_evidence": (
                    not pending and identity not in open_orders and settled == matched
                    and (
                        status in {"CANCELED", "CANCELLED"}
                        or status in {"MATCHED", "FILLED"} and settled == original
                    )
                ),
            }
        inventory = sum(
            (fill["shares"] if fill["side"] == "BUY" else -fill["shares"] for fill in fills),
            Decimal(0),
        )
        complete_run = bool(order_evidence) and all(
            item["terminal_evidence"] for item in order_evidence.values()
        )
        realized = None
        if complete_run and fills and explicit_zero_fee and not inventory:
            # A tied or reversed buy/sell sequence cannot establish run ownership.
            buys = [fill["matched_at"] for fill in fills if fill["side"] == "BUY"]
            sells = [fill["matched_at"] for fill in fills if fill["side"] == "SELL"]
            if not buys or not sells or max(buys) >= min(sells):
                raise SessionBlocked("tracked_round_trip_fill_order_unverified")
            realized = sum(
                (fill["notional"] if fill["side"] == "SELL" else -fill["notional"]
                 for fill in fills),
                Decimal(0),
            )
        return {
            "evidence_scope": "OWNER_ORDER_LIFECYCLE_API",
            "full_account_reconciled": False,
            "wallet_inventory": "UNASSESSED",
            "pending_trade_visibility": "AUTHENTICATED_CREDENTIAL",
            "trade_window_start": self.trades_after,
            "observed_at": finished,
            "collateral_balance": cash,
            "collateral_allowance": allowance,
            "usable_collateral": (
                min(cash, allowance) if allowance is not None and not open_orders and not pending
                else None
            ),
            "tested_token_balance": conditional,
            "open_order_ids": sorted(open_orders),
            "untracked_open_order_ids": sorted(foreign_open),
            "pending_trade_ids": sorted(pending),
            "order_evidence": order_evidence,
            "confirmed_fills": fills,
            "confirmed_run_inventory_delta": inventory,
            "confirmed_run_fees": Decimal(0) if explicit_zero_fee or not fills else None,
            "realized_pnl": realized,
        }

    def _trade_facts(
        self, trades: list[Any], instrument: InstrumentScope, tracked: Mapping[str, str],
        explicit_zero_fee: bool,
    ) -> tuple[list[dict[str, Any]], set[str]]:
        fills: list[dict[str, Any]] = []
        pending: set[str] = set()
        seen: set[str] = set()
        for row in trades:
            trade_id, status = field(row, "id"), field(row, "status")
            if not isinstance(trade_id, str) or not trade_id or trade_id in seen:
                raise SessionBlocked("invalid_or_duplicate_CLOB_trade")
            seen.add(trade_id)
            if status in PENDING_TRADE:
                pending.add(trade_id)
                continue
            if status not in TERMINAL_TRADE:
                raise SessionBlocked("unrecognized_CLOB_trade_status")
            if status != "CONFIRMED" or not tracked:
                continue
            role = field(row, "trader_side")
            legs: tuple[tuple[Any, Any, str], ...]
            if role == "TAKER":
                legs = ((field(row, "taker_order_id"), row, "size"),)
            elif role == "MAKER":
                legs = tuple((field(leg, "order_id"), leg, "matched_amount")
                             for leg in field(row, "maker_orders") or ())
            else:
                raise SessionBlocked("unrecognized_CLOB_trade_role")
            for identity, leg, size_field in legs:
                if identity not in tracked:
                    continue
                side = field(leg, "side")
                transaction = field(row, "transaction_hash")
                if (
                    str(field(leg, "maker_address")).lower() != self.mapping.funder.lower()
                    or str(field(row, "market")).lower() != instrument.market.lower()
                    or field(leg, "asset_id") != instrument.token
                    or side != tracked[identity]
                    or side not in {"BUY", "SELL"}
                    or not transaction
                    or any(item["trade_id"] == trade_id and item["order_id"] == identity
                           for item in fills)
                ):
                    raise SessionBlocked("tracked_fill_ownership_or_identity_unverified")
                size = _amount(field(leg, size_field))
                price = _amount(field(leg, "price"))
                if price > 1:
                    raise SessionBlocked("invalid_CLOB_fill_price")
                rate = field(leg, "fee_rate_bps")
                if explicit_zero_fee and rate is not None and Decimal(str(rate)) != 0:
                    raise SessionBlocked("zero_fee_evidence_disagrees_with_fill")
                matched_at = field(row, "matched_at")
                if not isinstance(matched_at, datetime) or matched_at.utcoffset() is None:
                    raise SessionBlocked("tracked_fill_timestamp_missing")
                fills.append({
                    "matched_at": matched_at,
                    "trade_id": trade_id, "order_id": identity, "transaction_hash": transaction,
                    "side": side, "shares": size, "price": price, "notional": size * price,
                    "fee": Decimal(0) if explicit_zero_fee else None,
                })
        return fills, pending


def scoped_opening(
    evidence: dict[str, Any], *, account: str, explicit_zero_fee: bool,
) -> AccountObservation | None:
    """Fresh flat-token baseline, explicitly not full-wallet reconciliation."""
    if (
        not explicit_zero_fee or evidence["usable_collateral"] is None
        or evidence["tested_token_balance"] != 0 or evidence["open_order_ids"]
        or evidence["pending_trade_ids"] or evidence["confirmed_fills"]
    ):
        return None
    return AccountObservation(
        account, evidence["observed_at"], evidence["usable_collateral"], (),
        frozenset(), Decimal(0), True, digest(evidence), scope="ORDER_LIFECYCLE_API",
    )


class OrderLifecycleSessionAccount:
    """Project only the frozen instrument and run-owned orders into session accounting."""

    def __init__(
        self, reader: OrderLifecycleAccountReader, journal: FinancialSessionJournal,
        instrument: InstrumentScope, *, exchange: str, http: Any,
    ) -> None:
        self.reader, self.journal, self.instrument = reader, journal, instrument
        self.exchange, self.http = exchange, http
        self.last_observation: AccountObservation | None = None
        self.last_redemptions: tuple[Any, ...] = ()
        self.last_evidence: dict[str, Any] = {}
        self.mapping, self.clock = reader.mapping, reader.clock

    def require_identity(self) -> None:
        self.reader.require_identity()

    async def observe(self, instrument: InstrumentScope) -> AccountObservation:
        if instrument != self.instrument:
            raise SessionBlocked("API_lifecycle_instrument_changed")
        state = self.journal.read()
        if state["opening"].get("scope") != "ORDER_LIFECYCLE_API":
            raise SessionBlocked("API_lifecycle_requires_signed_scoped_opening")
        rows = state["orders"]
        tracked = {row["order_id"]: row["side"] for row in rows.values() if row["order_id"]}
        market = await self.http.get(
            "https://clob.polymarket.com/clob-markets/" + instrument.market,
        )
        gamma = await self.http.get(
            "https://gamma-api.polymarket.com/markets", params={"condition_ids": instrument.market},
        )
        rate = await self.http.get(
            "https://clob.polymarket.com/fee-rate", params={"token_id": instrument.token},
        )
        for response in (market, gamma, rate):
            response.raise_for_status()
        market_body = json.loads(market.content, parse_float=Decimal)
        if market_body.get("c") != instrument.market or not explicit_zero_fee_market(
            market_body, instrument.token, gamma=gamma.json(), fee_rate=rate.json(),
        ):
            raise SessionBlocked("API_lifecycle_requires_fresh_explicit_zero_fee_market")
        evidence = await self.reader.observe(
            instrument, exchange=self.exchange, tracked=tracked, explicit_zero_fee=True,
        )
        if evidence["untracked_open_order_ids"]:
            raise SessionBlocked("API_lifecycle_unowned_order")
        if evidence["pending_trade_ids"]:
            raise APISettlementPending("API_lifecycle_pending_trade")
        fees = evidence["confirmed_run_fees"]
        allowance = evidence["collateral_allowance"]
        if allowance is None:
            raise SessionBlocked("API_lifecycle_exchange_allowance_unknown")
        if fees is None:
            raise SessionBlocked("API_lifecycle_charged_fees_unknown")
        # Cash remains a spending observation only. Run P&L is reconstructed from
        # the journal's owned fills and is never inferred from this cash balance.
        positions = ((instrument.token, evidence["tested_token_balance"]),) if (
            evidence["tested_token_balance"]
        ) else ()
        self.last_evidence = evidence
        observation = AccountObservation(
            self.mapping.account_id, evidence["observed_at"],
            min(evidence["collateral_balance"], allowance), positions,
            frozenset(evidence["open_order_ids"]), fees, True, digest(evidence),
            scope="ORDER_LIFECYCLE_API",
        )
        self.last_observation = observation
        return observation

    def confirmed(self, identity: str, row: dict[str, Any]) -> tuple[ConfirmedSessionFill, ...]:
        return tuple(
            ConfirmedSessionFill(
                digest((fill["trade_id"], fill["order_id"])), identity, fill["order_id"],
                self.instrument.token, fill["side"], fill["price"], fill["shares"], fill["fee"],
                fill["matched_at"], fill["notional"],
            )
            for fill in self.last_evidence.get("confirmed_fills", ())
            if fill["order_id"] == row["order_id"]
        )
