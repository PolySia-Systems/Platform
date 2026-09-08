"""Public Polymarket observation sources for research collection.

Wallet addresses never leave this adapter except as hashed aliases.
The official market WebSocket is not treated as wallet-attributable.
The authenticated user channel is UNAVAILABLE without credentials.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError

from polysia.adapters.polymarket.copytrading_source import (
    DATA_API_BASE_URL,
    JsonGetTransport,
    PolymarketCopyTradingSourceError,
    UrllibJsonGetTransport,
)
from polysia.adapters.polymarket.request_scheduling import TradesSourceUnavailableError
from polysia.application.ports.copytrading import LeaderReadPurpose
from polysia.application.ports.research_evidence import SourceCandidate
from polysia.domain.events import MarketDataEvent
from polysia.domain.research_evidence.models import (
    RESEARCH_EVIDENCE_SCHEMA_VERSION,
    AttributionStatus,
    CanonicalResearchEvent,
    ConfirmationStatus,
    EvidenceClassification,
    ObservationKind,
    SourceCandidateStatus,
    payload_digest,
    stable_evidence_id,
)

_WALLET_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")
ACTIVITY_SOURCE_ID = "polymarket:data-api:activity"
TRADES_SOURCE_ID = "polymarket:data-api:trades"
MARKET_STREAM_SOURCE_ID = "polymarket:clob:market-stream"
USER_CHANNEL_SOURCE_ID = "polymarket:clob:user-stream"

REST_ACTIVITY_CANDIDATE = SourceCandidate(
    candidate_id="rest_activity",
    display_name="Data API /activity REST poll (current baseline)",
    kind="wallet_event",
    wallet_attributable=True,
    status=SourceCandidateStatus.MEASURED,
)
REST_TRADES_CANDIDATE = SourceCandidate(
    candidate_id="rest_trades",
    display_name="Data API /trades REST poll",
    kind="wallet_event",
    wallet_attributable=True,
    status=SourceCandidateStatus.MEASURED,
)
MARKET_STREAM_CANDIDATE = SourceCandidate(
    candidate_id="clob_market_ws",
    display_name="Official CLOB market WebSocket",
    kind="market_state",
    wallet_attributable=False,
    status=SourceCandidateStatus.MEASURED,
)
USER_CHANNEL_CANDIDATE = SourceCandidate(
    candidate_id="clob_user_ws",
    display_name="Official CLOB user WebSocket",
    kind="wallet_event",
    wallet_attributable=True,
    status=SourceCandidateStatus.UNAVAILABLE,
    unavailable_reason="authenticated_user_channel_requires_credentials",
)

Clock = Callable[[], datetime]
MonotonicNs = Callable[[], int]
Sleeper = Callable[[float], Awaitable[None]]
MarketEventFactory = Callable[[], AsyncIterator[MarketDataEvent]]


def public_wallet_alias(wallet: str) -> str:
    if _WALLET_PATTERN.fullmatch(wallet) is None:
        raise ValueError("wallet is not a valid address")
    digest = hashlib.sha256(wallet.casefold().encode()).hexdigest()[:12]
    return f"pub-{digest}"


class DataApiWalletPollSource:
    """Poll one official public wallet-attributable REST surface."""

    def __init__(
        self,
        candidate: SourceCandidate,
        *,
        path: str,
        source_id: str,
        aliases: Mapping[str, str],
        transport: JsonGetTransport | None = None,
        poll_interval_seconds: float = 2.0,
        page_limit: int = 50,
        clock: Clock | None = None,
        monotonic_ns: MonotonicNs | None = None,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        if not aliases:
            raise ValueError("at least one public wallet alias is required")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self.candidate = candidate
        self._path = path
        self._source_id = source_id
        self._aliases = dict(aliases)
        self._transport = transport or UrllibJsonGetTransport()
        self._poll_interval_seconds = poll_interval_seconds
        self._page_limit = page_limit
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic_ns = monotonic_ns or _perf_ns
        self._sleep = sleep
        self._availability = "not_started"
        self._last_request_outcome = "not_started"
        self._last_successful_request_at: datetime | None = None
        self._last_successful_event_at: datetime | None = None
        self._last_failure_at: datetime | None = None
        self._failure_class: str | None = None
        self._retry_at: datetime | None = None
        self._recovery_required = False
        self._recovery_count = 0

    async def run(
        self,
        *,
        run_id: str,
        deadline: datetime,
    ) -> AsyncIterator[CanonicalResearchEvent]:
        backoff = 1.0
        while self._clock() < deadline:
            window_end = self._clock()
            window_start = window_end - timedelta(minutes=30)
            for alias, wallet in self._aliases.items():
                receive_ns = self._monotonic_ns()
                purpose = (
                    LeaderReadPurpose.RECOVERY
                    if self._recovery_required and self._path == "/trades"
                    else LeaderReadPurpose.DISCOVERY
                )
                try:
                    payload = await self._transport.get_json(
                        DATA_API_BASE_URL,
                        self._path,
                        self._params(wallet, start=window_start, end=window_end),
                        purpose=purpose,
                    )
                    if not isinstance(payload, list) or any(
                        not isinstance(row, dict) for row in payload
                    ):
                        raise TypeError("wallet source response is not a list of objects")
                except (
                    PolymarketCopyTradingSourceError,
                    TradesSourceUnavailableError,
                    HTTPError,
                    URLError,
                    OSError,
                    TimeoutError,
                    ValueError,
                    TypeError,
                ) as error:
                    observed = self._clock()
                    failure_class, retry_at = _sanitized_source_failure(
                        error,
                        observed_at=observed,
                        fallback_seconds=backoff,
                    )
                    self._availability = "unavailable"
                    self._last_request_outcome = "transient_error"
                    self._last_failure_at = observed
                    self._failure_class = failure_class
                    self._retry_at = retry_at
                    if isinstance(error, TradesSourceUnavailableError):
                        self._recovery_required = True
                    yield _error_event(
                        source_id=self._source_id,
                        run_id=run_id,
                        observed_time=observed,
                        receive_ns=receive_ns,
                        normalize_ns=self._monotonic_ns(),
                        reason="transport_error",
                        failure_class=failure_class,
                        retry_at=retry_at,
                        request_purpose=purpose,
                    )
                    remaining = (deadline - self._clock()).total_seconds()
                    if remaining <= 0:
                        return
                    await self._sleep(min(backoff, remaining))
                    backoff = min(backoff * 2, 30.0)
                    continue
                observed = self._clock()
                normalize_ns = self._monotonic_ns()
                recovered = purpose is LeaderReadPurpose.RECOVERY
                if recovered:
                    self._recovery_count += 1
                self._recovery_required = False
                self._availability = "available"
                self._last_successful_request_at = observed
                self._failure_class = None
                self._retry_at = None
                rows = payload
                self._last_request_outcome = (
                    "recovered" if recovered else ("success_events" if rows else "success_empty")
                )
                if rows:
                    self._last_successful_event_at = observed
                rows.sort(key=_row_timestamp)
                for row in rows:
                    yield _normalize_wallet_row(
                        row,
                        source_id=self._source_id,
                        alias=alias,
                        expected_wallet=wallet,
                        run_id=run_id,
                        observed_time=observed,
                        receive_ns=receive_ns,
                        normalize_ns=normalize_ns,
                    )
            remaining = (deadline - self._clock()).total_seconds()
            if remaining <= 0:
                break
            await self._sleep(min(self._poll_interval_seconds, remaining))
            backoff = 1.0

    def health_snapshot(self) -> Mapping[str, object]:
        return {
            "availability": self._availability,
            "last_request_outcome": self._last_request_outcome,
            "last_successful_request_at": _optional_time(self._last_successful_request_at),
            "last_successful_event_at": _optional_time(self._last_successful_event_at),
            "last_failure_at": _optional_time(self._last_failure_at),
            "failure_class": self._failure_class,
            "retry_at": _optional_time(self._retry_at),
            "recovery_count": self._recovery_count,
        }

    def _params(
        self,
        wallet: str,
        *,
        start: datetime,
        end: datetime,
    ) -> dict[str, str | int | bool]:
        params: dict[str, str | int | bool] = {
            "user": wallet,
            "limit": self._page_limit,
            "offset": 0,
            "start": int(start.timestamp()),
            "end": int(end.timestamp()),
        }
        if self._path == "/activity":
            params["type"] = "TRADE"
            params["sortBy"] = "TIMESTAMP"
            params["sortDirection"] = "ASC"
        else:
            params["takerOnly"] = False
        return params


class OfficialMarketStreamSource:
    """Official public market-state stream. Does not supply wallet identity."""

    def __init__(
        self,
        *,
        token_ids: tuple[str, ...],
        event_factory: MarketEventFactory | None = None,
        clock: Clock | None = None,
        monotonic_ns: MonotonicNs | None = None,
        sleep: Sleeper = asyncio.sleep,
        stale_after: timedelta = timedelta(seconds=30),
    ) -> None:
        self.candidate = MARKET_STREAM_CANDIDATE
        if event_factory is None and not token_ids:
            self.candidate = SourceCandidate(
                candidate_id=MARKET_STREAM_CANDIDATE.candidate_id,
                display_name=MARKET_STREAM_CANDIDATE.display_name,
                kind=MARKET_STREAM_CANDIDATE.kind,
                wallet_attributable=False,
                status=SourceCandidateStatus.INSUFFICIENT,
                unavailable_reason="no_public_token_ids_for_stream",
            )
        self._token_ids = token_ids
        self._event_factory = event_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic_ns = monotonic_ns or _perf_ns
        self._sleep = sleep
        self._stale_after = stale_after
        self.reconnect_count = 0
        self._availability = (
            "not_started"
            if self.candidate.status is SourceCandidateStatus.MEASURED
            else self.candidate.status.value.lower()
        )
        self._last_event_at: datetime | None = None
        self._last_failure_at: datetime | None = None
        self._failure_class: str | None = None

    async def run(
        self,
        *,
        run_id: str,
        deadline: datetime,
    ) -> AsyncIterator[CanonicalResearchEvent]:
        if self.candidate.status is not SourceCandidateStatus.MEASURED:
            return
        if self._event_factory is not None:
            async for event in self._event_factory():
                if self._clock() >= deadline:
                    return
                self._availability = "available"
                self._last_event_at = event.received_at
                self._failure_class = None
                yield self._from_market_event(event, run_id=run_id)
            return
        async for item in self._run_official_stream(run_id=run_id, deadline=deadline):
            yield item

    async def _run_official_stream(
        self,
        *,
        run_id: str,
        deadline: datetime,
    ) -> AsyncIterator[CanonicalResearchEvent]:
        from polysia.adapters.polymarket.stream import MarketStream, MarketStreamConfig
        from polysia.bus.in_memory_bus import InMemoryEventBus

        bus = InMemoryEventBus()
        subscription = bus.subscribe()
        stream = MarketStream(
            bus=bus,
            config=MarketStreamConfig(
                token_ids=self._token_ids,
                stale_after=self._stale_after,
            ),
        )
        runner = asyncio.create_task(stream.run())
        try:
            async with subscription:
                while self._clock() < deadline:
                    wait_timeout = min(1.0, max(0.05, (deadline - self._clock()).total_seconds()))
                    next_event = asyncio.create_task(anext(subscription))
                    sleeper: asyncio.Task[None] = asyncio.create_task(
                        asyncio.sleep(wait_timeout)
                    )
                    done, pending = await asyncio.wait(
                        {next_event, sleeper, runner},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in pending:
                        if task is not runner:
                            task.cancel()
                    if next_event in done:
                        market_event = next_event.result()
                        receive_ns = self._monotonic_ns()
                        self._availability = "available"
                        self._last_event_at = market_event.received_at
                        self._failure_class = None
                        yield self._from_market_event(
                            market_event,
                            run_id=run_id,
                            receive_ns=receive_ns,
                            normalize_ns=self._monotonic_ns(),
                        )
                    if runner in done:
                        self.reconnect_count += 1
                        if runner.exception() is not None:
                            self._availability = "unavailable"
                            self._last_failure_at = self._clock()
                            self._failure_class = "stream_disconnected"
                            yield _error_event(
                                source_id=MARKET_STREAM_SOURCE_ID,
                                run_id=run_id,
                                observed_time=self._clock(),
                                receive_ns=self._monotonic_ns(),
                                normalize_ns=self._monotonic_ns(),
                                reason="stream_disconnected",
                            )
                        runner = asyncio.create_task(stream.run())
        finally:
            if not runner.done():
                runner.cancel()
                with suppress(asyncio.CancelledError):
                    await runner
            await subscription.close()

    def health_snapshot(self) -> Mapping[str, object]:
        return {
            "availability": self._availability,
            "last_request_outcome": "stream_event"
            if self._last_event_at is not None
            else "not_started",
            "last_successful_request_at": _optional_time(self._last_event_at),
            "last_successful_event_at": _optional_time(self._last_event_at),
            "last_failure_at": _optional_time(self._last_failure_at),
            "failure_class": self._failure_class,
            "retry_at": None,
            "recovery_count": self.reconnect_count,
        }

    def _from_market_event(
        self,
        event: MarketDataEvent,
        *,
        run_id: str,
        receive_ns: int | None = None,
        normalize_ns: int | None = None,
    ) -> CanonicalResearchEvent:
        receive = receive_ns if receive_ns is not None else self._monotonic_ns()
        normalize = normalize_ns if normalize_ns is not None else receive
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        bid = _optional_decimal(payload.get("best_bid"))
        ask = _optional_decimal(payload.get("best_ask"))
        bid_size = _optional_decimal(payload.get("bid_size") or payload.get("best_bid_size"))
        ask_size = _optional_decimal(payload.get("ask_size") or payload.get("best_ask_size"))
        depth_present = _payload_has_depth(payload)
        executable = _optional_price(payload)
        price = executable
        identity: dict[str, object] = {
            "event_type": event.event_type,
            "received_at": event.received_at.isoformat(),
            "token_id": event.token_id,
        }
        provenance: dict[str, object] = {
            "event_type": event.event_type,
            "wallet_attribution": "not_applicable",
            "source": event.source,
            "best_bid": None if bid is None else format(bid, "f"),
            "best_ask": None if ask is None else format(ask, "f"),
            "bid_size": None if bid_size is None else format(bid_size, "f"),
            "ask_size": None if ask_size is None else format(ask_size, "f"),
            "quote_status": "present" if bid is not None and ask is not None else "UNKNOWN",
            "depth_status": "present" if depth_present else "UNKNOWN",
            "executable_price": None if executable is None else format(executable, "f"),
        }
        return CanonicalResearchEvent(
            evidence_id=stable_evidence_id(
                source_id=MARKET_STREAM_SOURCE_ID,
                identity_fields=identity,
            ),
            schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
            source_id=MARKET_STREAM_SOURCE_ID,
            event_kind=ObservationKind.MARKET_STATE,
            classification=EvidenceClassification.ACCEPTED,
            market_reference=None,
            outcome_reference=event.token_id or None,
            side=None,
            price=price,
            size=None,
            source_time=event.exchange_ts,
            observed_time=event.received_at,
            receive_monotonic_ns=receive,
            normalize_monotonic_ns=normalize,
            attribution_status=AttributionStatus.NOT_APPLICABLE,
            leader_alias=None,
            confirmation=ConfirmationStatus.CONFIRMED
            if price is not None
            else ConfirmationStatus.UNCONFIRMED,
            payload_digest=payload_digest(identity),
            provenance=provenance,
            run_id=run_id,
        )


async def discover_public_follow_set(
    transport: JsonGetTransport,
    *,
    wallet_limit: int = 3,
    page_limit: int = 50,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Discover public wallets and token IDs from unfiltered official trades.

    Wallet addresses stay in the returned in-memory map only.
    """

    payload = await transport.get_json(
        DATA_API_BASE_URL,
        "/trades",
        {"limit": page_limit, "offset": 0, "takerOnly": False},
        purpose=LeaderReadPurpose.DISCOVERY,
    )
    if not isinstance(payload, list):
        return {}, ()
    aliases: dict[str, str] = {}
    tokens: list[str] = []
    seen_tokens: set[str] = set()
    for row in payload:
        if not isinstance(row, dict):
            continue
        wallet = row.get("proxyWallet")
        token = row.get("asset")
        if isinstance(wallet, str) and _WALLET_PATTERN.fullmatch(wallet):
            alias = public_wallet_alias(wallet)
            if alias not in aliases and len(aliases) < wallet_limit:
                aliases[alias] = wallet
        if isinstance(token, str) and token and token not in seen_tokens:
            seen_tokens.add(token)
            tokens.append(token)
            if len(tokens) >= 8:
                break
    return aliases, tuple(tokens)


async def discover_followed_token_ids(
    transport: JsonGetTransport,
    aliases: Mapping[str, str],
    *,
    page_limit: int = 50,
    token_limit: int = 32,
) -> tuple[str, ...]:
    """Public tokens traded by followed wallets. Missing overlap stays empty."""

    tokens: list[str] = []
    seen: set[str] = set()
    for wallet in aliases.values():
        payload = await transport.get_json(
            DATA_API_BASE_URL,
            "/trades",
            {"user": wallet, "limit": page_limit, "offset": 0, "takerOnly": False},
            purpose=LeaderReadPurpose.DISCOVERY,
        )
        if not isinstance(payload, list):
            continue
        for row in payload:
            if not isinstance(row, dict):
                continue
            token = row.get("asset")
            if isinstance(token, str) and token and token not in seen:
                seen.add(token)
                tokens.append(token)
                if len(tokens) >= token_limit:
                    return tuple(tokens)
    return tuple(tokens)


def _normalize_wallet_row(
    row: Mapping[str, Any],
    *,
    source_id: str,
    alias: str,
    expected_wallet: str,
    run_id: str,
    observed_time: datetime,
    receive_ns: int,
    normalize_ns: int,
) -> CanonicalResearchEvent:
    wallet = _optional_str(row, "proxyWallet")
    attribution = AttributionStatus.WALLET_ALIASED
    leader_alias: str | None = alias
    if wallet is None or wallet.casefold() != expected_wallet.casefold():
        attribution = AttributionStatus.MISSING
        leader_alias = None
    side = _optional_str(row, "side")
    if side is not None:
        side = side.upper()
        if side not in {"BUY", "SELL"}:
            side = None
    price = _optional_decimal(row.get("price"))
    size = _optional_decimal(row.get("size"))
    source_time = _optional_timestamp(row.get("timestamp"))
    market = _optional_str(row, "conditionId")
    outcome = _optional_str(row, "asset")
    tx_hash = _optional_str(row, "transactionHash")
    identity: dict[str, object] = {
        "asset": outcome,
        "condition_id": None if market is None else market.casefold(),
        "price": None if price is None else format(price, "f"),
        "side": side,
        "size": None if size is None else format(size, "f"),
        "timestamp": None if source_time is None else int(source_time.timestamp()),
        "trade_id": _optional_str(row, "id") or _optional_str(row, "tradeId"),
        "transaction_hash": None if tx_hash is None else tx_hash.casefold(),
    }
    source_event_id = stable_evidence_id(
        source_id="polymarket_public_trade",
        identity_fields=identity,
    )
    observation_identity = {
        "leader_alias": alias,
        "source_event_id": source_event_id,
    }
    provenance: dict[str, object] = {
        "endpoint": source_id,
        "gamma_verified": False,
        "has_transaction": tx_hash is not None,
    }
    return CanonicalResearchEvent(
        evidence_id=stable_evidence_id(
            source_id=source_id,
            identity_fields=observation_identity,
        ),
        schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
        source_id=source_id,
        event_kind=ObservationKind.WALLET_TRADE,
        classification=EvidenceClassification.ACCEPTED,
        market_reference=market,
        outcome_reference=outcome,
        side=side,
        price=price,
        size=size,
        source_time=source_time,
        observed_time=observed_time,
        receive_monotonic_ns=receive_ns,
        normalize_monotonic_ns=normalize_ns,
        attribution_status=attribution,
        leader_alias=leader_alias,
        confirmation=ConfirmationStatus.CONFIRMED,
        payload_digest=payload_digest(
            {
                **identity,
                **observation_identity,
            }
        ),
        provenance=provenance,
        source_event_id=source_event_id,
        run_id=run_id,
    )


def _error_event(
    *,
    source_id: str,
    run_id: str,
    observed_time: datetime,
    receive_ns: int,
    normalize_ns: int,
    reason: str,
    failure_class: str | None = None,
    retry_at: datetime | None = None,
    request_purpose: LeaderReadPurpose | None = None,
) -> CanonicalResearchEvent:
    identity: dict[str, object] = {
        "reason": reason,
        "observed_time": observed_time.isoformat(),
        "run_id": run_id,
    }
    provenance: dict[str, object] = {
        "reason": reason,
        "diagnostic": True,
        "failure_class": failure_class or reason,
        "retry_at": _optional_time(retry_at),
        "request_purpose": None if request_purpose is None else request_purpose.value,
    }
    return CanonicalResearchEvent(
        evidence_id=stable_evidence_id(source_id=source_id, identity_fields=identity),
        schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
        source_id=source_id,
        event_kind=ObservationKind.CONTROL,
        classification=EvidenceClassification.INCOMPLETE,
        market_reference=None,
        outcome_reference=None,
        side=None,
        price=None,
        size=None,
        source_time=None,
        observed_time=observed_time,
        receive_monotonic_ns=receive_ns,
        normalize_monotonic_ns=normalize_ns,
        attribution_status=AttributionStatus.NOT_APPLICABLE,
        leader_alias=None,
        confirmation=ConfirmationStatus.UNCONFIRMED,
        payload_digest=payload_digest(provenance),
        provenance=provenance,
        run_id=run_id,
    )


def _sanitized_source_failure(
    error: BaseException,
    *,
    observed_at: datetime,
    fallback_seconds: float,
) -> tuple[str, datetime]:
    if isinstance(error, TradesSourceUnavailableError):
        return "trades_circuit_open", error.retry_at
    if isinstance(error, HTTPError):
        return f"http_{error.code}", observed_at + timedelta(seconds=fallback_seconds)
    if isinstance(error, (TimeoutError, URLError, OSError)):
        return "network_transport", observed_at + timedelta(seconds=fallback_seconds)
    if isinstance(error, (ValueError, TypeError)):
        return "invalid_response", observed_at + timedelta(seconds=fallback_seconds)
    return "source_transport", observed_at + timedelta(seconds=fallback_seconds)


def _optional_time(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


def _row_timestamp(row: Mapping[str, Any]) -> int:
    value = row.get("timestamp")
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _payload_has_depth(payload: Mapping[str, Any]) -> bool:
    for key in ("bids", "asks", "depth", "levels"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return True
    return False


def _optional_str(row: Mapping[str, Any], name: str) -> str | None:
    value = row.get(name)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _optional_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite() or result <= Decimal("0"):
        return None
    return result


def _optional_price(payload: Mapping[str, Any] | object) -> Decimal | None:
    if not isinstance(payload, Mapping):
        return None
    for key in ("price", "best_bid", "best_ask"):
        price = _optional_decimal(payload.get(key))
        if price is not None:
            return price
    change = payload.get("price_change")
    if isinstance(change, Mapping):
        return _optional_decimal(change.get("price"))
    return None


def _optional_timestamp(value: Any) -> datetime | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        if value > 10_000_000_000:
            value = value / 1000
        return datetime.fromtimestamp(int(value), tz=UTC)
    return None


def _perf_ns() -> int:
    import time

    return time.perf_counter_ns()
