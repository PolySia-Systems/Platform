"""Read-only finalized CTF Exchange V2 occurrence/account corroboration.

This narrowly supports the standard legacy CTF route and six-decimal pUSD/CTF
units. V3 PositionManager, negative-risk conversions and other contracts are
outside this slice and must not be silently interpreted with this ABI.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

import httpx

from polysia.domain.financial_session import (
    InstrumentScope,
    ObservedRedemption,
    SessionBlocked,
    SourceOccurrence,
    digest,
)

# Public ABI event topics, not secret key material.
ORDER_FILLED = "0x" + "d543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"
TRANSFER_SINGLE = "0x" + "c3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62"
TRANSFER_BATCH = "0x" + "4a39dc06d4c0dbc64b70af90fd698a233a518aa5d07e595d983b8c0526c8f7fb"
ERC20_TRANSFER = "0x" + "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
UNIT = Decimal("1000000")


def address(value: str) -> str:
    if len(value) != 42 or not value.startswith("0x"):
        raise SessionBlocked("invalid_exact_account_address")
    try:
        int(value[2:], 16)
    except ValueError as error:
        raise SessionBlocked("invalid_exact_account_address") from error
    return value.lower()


def topic_address(value: str) -> str:
    return "0x" + "0" * 24 + address(value)[2:]


def words(value: str) -> tuple[int, ...]:
    if not isinstance(value, str) or not value.startswith("0x") or (len(value) - 2) % 64:
        raise SessionBlocked("invalid_event_ABI")
    try:
        return tuple(int(value[index : index + 64], 16) for index in range(2, len(value), 64))
    except ValueError as error:
        raise SessionBlocked("invalid_event_ABI") from error


@dataclass(frozen=True, slots=True)
class ChainFill:
    occurrence: SourceOccurrence
    order_hash: str
    shares: Decimal
    collateral: Decimal
    fee: Decimal
    block_hash: str
    raw_digest: str
    leader_position_before: Decimal | None = None
    chain_order: tuple[int, int] | None = None


class ReadOnlyRPC:
    METHODS = frozenset(
        {
            "eth_chainId",
            "eth_getBlockByNumber",
            "eth_getBlockByHash",
            "eth_getTransactionReceipt",
            "eth_getTransactionByHash",
            "eth_getLogs",
            "eth_call",
            "eth_getCode",
        }
    )

    def __init__(self, client: httpx.AsyncClient, url: str) -> None:
        self.client, self.url = client, url
        self._sequence = 0

    async def call(self, method: str, params: list[object]) -> Any:
        if method not in self.METHODS:
            raise SessionBlocked("RPC_mutation_or_unreviewed_method_denied")
        self._sequence += 1
        request_id = self._sequence
        response = await self.client.post(
            self.url,
            json={
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            },
        )
        response.raise_for_status()
        payload = json.loads(response.content, parse_float=Decimal)
        if (
            not isinstance(payload, dict)
            or payload.get("id") != request_id
            or "error" in payload
            or "result" not in payload
        ):
            raise SessionBlocked("RPC_read_incomplete")
        return payload["result"]


class CTFChainReader:
    def __init__(
        self,
        rpc: ReadOnlyRPC,
        *,
        exchange: str,
        ctf: str,
        collateral: str,
        instruments: tuple[InstrumentScope, ...],
    ) -> None:
        self.rpc = rpc
        self.exchange, self.ctf, self.collateral = map(address, (exchange, ctf, collateral))
        self.instruments = {item.token: item for item in instruments}
        if any(
            item.collateral.lower() != self.collateral
            or item.settlement_route != "ctf-exchange-v2-standard"
            for item in instruments
        ):
            raise SessionBlocked("unsupported_chain_collateral_route")

    async def finalized(self) -> dict[str, Any]:
        if await self.rpc.call("eth_chainId", []) != "0x89":
            raise SessionBlocked("chain_identity_mismatch")
        block = await self.rpc.call("eth_getBlockByNumber", ["finalized", False])
        if not isinstance(block, dict) or not all(
            block.get(key) for key in ("hash", "number", "timestamp")
        ):
            raise SessionBlocked("finalized_block_unavailable")
        return block

    async def fills(
        self,
        wallet: str,
        *,
        block: Mapping[str, Any],
        observed_at: datetime,
        transaction: str | None = None,
    ) -> tuple[ChainFill, ...]:
        wallet = address(wallet)
        if transaction is None:
            logs = await self.rpc.call(
                "eth_getLogs",
                [
                    {
                        "address": self.exchange,
                        "fromBlock": "0x0",
                        "toBlock": block["number"],
                        "topics": [ORDER_FILLED, None, topic_address(wallet)],
                    }
                ],
            )
        else:
            receipt = await self.rpc.call("eth_getTransactionReceipt", [transaction])
            if (
                not isinstance(receipt, dict)
                or receipt.get("status") != "0x1"
                or receipt.get("transactionHash", "").lower() != transaction.lower()
                or int(receipt.get("blockNumber", "0x0"), 16) > int(block["number"], 16)
            ):
                raise SessionBlocked("transaction_not_finalized")
            canonical = await self.rpc.call("eth_getBlockByNumber", [receipt["blockNumber"], False])
            if canonical.get("hash") != receipt.get("blockHash"):
                raise SessionBlocked("transaction_reorg_or_block_mismatch")
            logs = canonical_receipt_logs(receipt, transaction)
        if not isinstance(logs, list):
            raise SessionBlocked("chain_log_inventory_incomplete")
        result: dict[str, ChainFill] = {}
        blocks: dict[str, Mapping[str, Any]] = {}
        for log in logs:
            topics = log.get("topics", [])
            if (
                log.get("address", "").lower() != self.exchange
                or len(topics) != 4
                or topics[0] != ORDER_FILLED
                or topics[2].lower() != topic_address(wallet)
            ):
                continue
            if log.get("removed") is not False or int(log["blockNumber"], 16) > int(
                block["number"], 16
            ):
                raise SessionBlocked("chain_log_not_final")
            block_hash = log["blockHash"]
            if block_hash not in blocks:
                blocks[block_hash] = await self.rpc.call(
                    "eth_getBlockByNumber", [log["blockNumber"], False]
                )
            header = blocks[block_hash]
            if header.get("hash") != block_hash:
                raise SessionBlocked("chain_log_reorg")
            values = words(log["data"])
            if len(values) != 7 or values[0] not in (0, 1) or not values[2] or not values[3]:
                raise SessionBlocked("unsupported_order_filled_ABI")
            side: Literal["BUY", "SELL"] = "BUY" if values[0] == 0 else "SELL"
            token = str(values[1])
            if token not in self.instruments:
                raise SessionBlocked("account_or_source_traded_outside_mapped_instruments")
            collateral, shares = (values[2], values[3]) if side == "BUY" else (values[3], values[2])
            quantity, debit = Decimal(shares) / UNIT, Decimal(collateral) / UNIT
            occurred = datetime.fromtimestamp(int(header["timestamp"], 16), UTC)
            event = SourceOccurrence(
                "137",
                log["transactionHash"].lower(),
                str(int(log["logIndex"], 16)),
                wallet,
                self.instruments[token],
                side,
                occurred,
                observed_at,
                observed_at,
                "polygon-finalized-rpc",
                digest(log),
                "ctf-exchange-v2/OrderFilled",
                True,
                True,
                debit / quantity,
            )
            fill = ChainFill(
                event,
                topics[1].lower(),
                quantity,
                debit,
                Decimal(values[4]) / UNIT,
                block_hash,
                digest(log),
                chain_order=(int(log["blockNumber"], 16), int(log["logIndex"], 16)),
            )
            previous = result.get(event.identity)
            if previous is not None and previous != fill:
                raise SessionBlocked("conflicting_chain_occurrence")
            result[event.identity] = fill
        return tuple(result.values())

    async def cash(self, wallet: str, *, block: Mapping[str, Any]) -> Decimal:
        payload = "0x70a08231" + topic_address(wallet)[2:]
        value = await self.rpc.call(
            "eth_call",
            [
                {"to": self.collateral, "data": payload},
                {"blockHash": block["hash"], "requireCanonical": True},
            ],
        )
        return Decimal(int(value, 16)) / UNIT

    async def position_before(self, fill: ChainFill, wallet: str) -> Decimal:
        """Exact prior-block balance plus preceding transfers in the fill block.

        The OrderFilled event follows its own transfers. Reverse that order's
        proven quantity to recover the pre-action economic baseline.
        """
        block = await self.rpc.call("eth_getBlockByHash", [fill.block_hash, False])
        previous = await self.rpc.call(
            "eth_getBlockByNumber", [hex(int(block["number"], 16) - 1), False]
        )
        token = fill.occurrence.instrument.token
        balance = await self.token_balance(wallet, token, block=previous)
        logs = await self.rpc.call(
            "eth_getLogs", [{"address": self.ctf, "blockHash": fill.block_hash}]
        )
        if not isinstance(logs, list):
            raise SessionBlocked("leader_baseline_transfer_inventory_incomplete")
        unique: dict[int, dict[str, Any]] = {}
        for log in logs:
            index = int(log["logIndex"], 16)
            if index in unique and unique[index] != log:
                raise SessionBlocked("leader_baseline_conflicting_transfer_occurrence")
            unique[index] = log
        for log in sorted(unique.values(), key=lambda row: int(row["logIndex"], 16)):
            if (
                log.get("address", "").lower() != self.ctf
                or log.get("blockHash") != fill.block_hash
            ):
                raise SessionBlocked("leader_baseline_transfer_scope_mismatch")
            if int(log["logIndex"], 16) >= int(fill.occurrence.occurrence or "-1"):
                break
            for changed_token, delta in transfer_deltas(log, wallet):
                if changed_token == token:
                    balance += delta
        before = balance + fill.shares * (1 if fill.occurrence.side == "SELL" else -1)
        if before < 0 or fill.occurrence.side == "SELL" and fill.shares > before:
            raise SessionBlocked("leader_baseline_conflicts_with_fill")
        return before

    async def redemptions(
        self,
        wallet: str,
        *,
        account_id: str,
        adapter: str,
        since: datetime,
        block: Mapping[str, Any],
    ) -> tuple[ObservedRedemption, ...]:
        adapter = address(adapter)
        logs = await self.rpc.call(
            "eth_getLogs",
            [
                {
                    "address": self.ctf,
                    "fromBlock": "0x0",
                    "toBlock": block["number"],
                    "topics": [
                        [TRANSFER_SINGLE, TRANSFER_BATCH],
                        None,
                        topic_address(wallet),
                        topic_address(adapter),
                    ],
                }
            ],
        )
        if not isinstance(logs, list):
            raise SessionBlocked("redemption_inventory_incomplete")
        results = []
        for tx_id in sorted({row["transactionHash"] for row in logs}):
            receipt = await self.rpc.call("eth_getTransactionReceipt", [tx_id])
            if (
                not isinstance(receipt, dict)
                or receipt.get("status") != "0x1"
                or receipt.get("transactionHash", "").lower() != tx_id.lower()
                or int(receipt["blockNumber"], 16) > int(block["number"], 16)
            ):
                raise SessionBlocked("redemption_finality_incomplete")
            header = await self.rpc.call("eth_getBlockByNumber", [receipt["blockNumber"], False])
            occurred = datetime.fromtimestamp(int(header["timestamp"], 16), UTC)
            if occurred < since:
                continue
            if header["hash"] != receipt["blockHash"]:
                raise SessionBlocked("redemption_reorg")
            transaction = await self.rpc.call("eth_getTransactionByHash", [tx_id])
            data = transaction.get("input", "")
            if (
                transaction.get("from", "").lower() != address(wallet)
                or transaction.get("to", "").lower() != adapter
                or not data.startswith("0x01b7037c")
            ):
                # Manual transfers and merges remain unexplained account changes.
                continue
            values = words("0x" + data[10:])
            if (
                len(values) < 5
                or values[3] != 128
                or values[4] != len(values) - 5
                or values[0] >= 2**160
            ):
                raise SessionBlocked("redemption_call_shape_unknown")
            condition = "0x" + f"{values[2]:064x}"
            removed: dict[str, Decimal] = {}
            cash = Decimal("0")
            for log in canonical_receipt_logs(receipt, tx_id):
                if log.get("address", "").lower() == self.ctf:
                    for token, delta in transfer_deltas(log, wallet):
                        if delta < 0:
                            if log["topics"][3].lower() != topic_address(adapter):
                                raise SessionBlocked("redemption_inventory_recipient_unknown")
                            scope = self.instruments.get(token)
                            if scope is None or scope.market.lower() != condition:
                                raise SessionBlocked("redemption_token_condition_mismatch")
                            removed[token] = removed.get(token, Decimal(0)) - delta
                topics = log.get("topics", [])
                if (
                    log.get("address", "").lower() == self.collateral
                    and len(topics) == 3
                    and topics[0] == ERC20_TRANSFER
                    and topic_address(wallet) in {topics[1].lower(), topics[2].lower()}
                ):
                    amount = words(log["data"])
                    if len(amount) != 1 or log.get("removed") is not False:
                        raise SessionBlocked("redemption_cash_transfer_unknown")
                    sign = int(topics[2].lower() == topic_address(wallet)) - int(
                        topics[1].lower() == topic_address(wallet)
                    )
                    cash += Decimal(amount[0]) / UNIT * sign
            if not removed or cash < 0:
                raise SessionBlocked("redemption_without_confirmed_inventory_movement")
            results.append(
                ObservedRedemption(
                    digest(("137", tx_id, account_id)),
                    account_id,
                    self.collateral,
                    tuple(sorted(removed.items())),
                    cash,
                    occurred,
                    digest(receipt),
                )
            )
        return tuple(results)

    async def token_balance(self, wallet: str, token: str, *, block: Mapping[str, Any]) -> Decimal:
        data = "0x00fdd58e" + topic_address(wallet)[2:] + f"{int(token):064x}"
        raw = await self.rpc.call(
            "eth_call",
            [
                {"to": self.ctf, "data": data},
                {"blockHash": block["hash"], "requireCanonical": True},
            ],
        )
        return Decimal(int(raw, 16)) / UNIT

    async def holdings(
        self, wallet: str, *, block: Mapping[str, Any]
    ) -> tuple[tuple[str, Decimal], ...]:
        """Enumerate all account CTF transfers, then pin every balance to one block.

        RPC providers must implement all-or-error log responses. Provider silent
        truncation is an explicit qualification dependency, never inferred away.
        """
        tokens = set(self.instruments)
        for position in (2, 3):
            topics: list[object] = [[TRANSFER_SINGLE, TRANSFER_BATCH], None, None, None]
            topics[position] = topic_address(wallet)
            logs = await self.rpc.call(
                "eth_getLogs",
                [
                    {
                        "address": self.ctf,
                        "fromBlock": "0x0",
                        "toBlock": block["number"],
                        "topics": topics,
                    }
                ],
            )
            if not isinstance(logs, list):
                raise SessionBlocked("account_token_inventory_incomplete")
            for log in logs:
                if (
                    log.get("removed") is not False
                    or log.get("address", "").lower() != self.ctf
                    or int(log["blockNumber"], 16) > int(block["number"], 16)
                ):
                    raise SessionBlocked("account_token_transfer_not_final")
                tokens.update(token for token, _ in transfer_deltas(log, wallet))
        result = []
        for token in sorted(tokens):
            data = "0x00fdd58e" + topic_address(wallet)[2:] + f"{int(token):064x}"
            raw = await self.rpc.call(
                "eth_call",
                [
                    {"to": self.ctf, "data": data},
                    {"blockHash": block["hash"], "requireCanonical": True},
                ],
            )
            quantity = Decimal(int(raw, 16)) / UNIT
            if quantity:
                if token not in self.instruments:
                    raise SessionBlocked("unmapped_external_account_inventory")
                result.append((token, quantity))
        return tuple(result)


def transfer_deltas(log: Mapping[str, Any], wallet: str) -> tuple[tuple[str, Decimal], ...]:
    topics = log.get("topics", [])
    if not topics or topics[0] not in {TRANSFER_SINGLE, TRANSFER_BATCH}:
        return ()
    if len(topics) != 4 or log.get("removed") is not False:
        raise SessionBlocked("incomplete_token_transfer_evidence")
    who = topic_address(wallet)
    sign = int(topics[3].lower() == who) - int(topics[2].lower() == who)
    if not sign:
        return ()
    values = words(log["data"])
    if topics[0] == TRANSFER_SINGLE:
        if len(values) != 2:
            raise SessionBlocked("invalid_transfer_single")
        return ((str(values[0]), Decimal(values[1]) / UNIT * sign),)
    if len(values) < 4 or values[0] % 32 or values[1] % 32:
        raise SessionBlocked("invalid_transfer_batch")
    left, right = values[0] // 32, values[1] // 32
    if left >= len(values) or right >= len(values):
        raise SessionBlocked("invalid_transfer_batch_offsets")
    count = values[left]
    if (
        count != values[right]
        or left != 2
        or right != left + 1 + count
        or right + 1 + count != len(values)
    ):
        raise SessionBlocked("invalid_transfer_batch_lengths")
    return tuple(
        (str(token), Decimal(amount) / UNIT * sign)
        for token, amount in zip(
            values[left + 1 : left + 1 + count], values[right + 1 : right + 1 + count], strict=True
        )
    )


def canonical_receipt_logs(receipt: Mapping[str, Any], transaction: str) -> list[dict[str, Any]]:
    logs = receipt.get("logs")
    if not isinstance(logs, list):
        raise SessionBlocked("transaction_logs_incomplete")
    unique: dict[int, dict[str, Any]] = {}
    for log in logs:
        if (
            not isinstance(log, dict)
            or log.get("removed") is not False
            or log.get("transactionHash", "").lower() != transaction.lower()
            or log.get("blockHash") != receipt.get("blockHash")
            or log.get("blockNumber") != receipt.get("blockNumber")
        ):
            raise SessionBlocked("receipt_occurrence_scope_mismatch")
        index = int(log["logIndex"], 16)
        if index in unique and unique[index] != log:
            raise SessionBlocked("receipt_occurrence_conflict")
        unique[index] = log
    return [unique[index] for index in sorted(unique)]
