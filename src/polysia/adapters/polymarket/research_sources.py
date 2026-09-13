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
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.error import HTTPError, URLError

from polysia.adapters.polymarket.copytrading_source import (
    CLOB_API_BASE_URL,
    DATA_API_BASE_URL,
    JsonGetTransport,
    PolymarketCopyTradingSourceError,
    UrllibJsonGetTransport,
)
from polysia.adapters.polymarket.request_scheduling import TradesSourceUnavailableError
from polysia.application.ports.copytrading import LeaderReadPurpose
from polysia.application.ports.research_evidence import SourceCandidate
from polysia.domain.events import MarketDataEvent
from polysia.domain.market import MarketFeeSchedule, MarketOrderBookSnapshot
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
from polysia.orderbook.builder import BookBuilder
from polysia.orderbook.validators import OrderBookValidationError

_WALLET_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")
ACTIVITY_SOURCE_ID = "polymarket:data-api:activity"
TRADES_SOURCE_ID = "polymarket:data-api:trades"
MARKET_STREAM_SOURCE_ID = "polymarket:clob:market-stream"
TERMINAL_SETTLEMENT_SOURCE_ID = "polymarket:gamma:terminal-settlement"
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


@dataclass(frozen=True, slots=True)
class MarketDiscoverySnapshot:
    """Bounded tokens and fee evidence known to the public collector."""

    token_markets: Mapping[str, str]
    fee_schedules: Mapping[str, MarketFeeSchedule]


MarketDiscovery = Callable[[], Awaitable[MarketDiscoverySnapshot]]


@dataclass(frozen=True, slots=True)
class TerminalMarketSnapshot:
    """Fresh public books and fee evidence captured at experiment end."""

    books: Mapping[str, MarketOrderBookSnapshot]
    fee_schedules: Mapping[str, MarketFeeSchedule]


TerminalMarketSnapshotFetcher = Callable[
    [Mapping[str, str]],
    Awaitable[TerminalMarketSnapshot],
]
TerminalSettlementFetcher = Callable[
    [Mapping[str, str]],
    Awaitable[Mapping[str, Decimal]],
]


class MarketStreamRunner(Protocol):
    async def run(self, *, max_events: int | None = None) -> None: ...


MarketStreamFactory = Callable[
    [Any, tuple[str, ...], timedelta],
    MarketStreamRunner,
]


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
        initial_delay_seconds: float = 0.0,
        page_limit: int = 50,
        clock: Clock | None = None,
        monotonic_ns: MonotonicNs | None = None,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        if not aliases:
            raise ValueError("at least one public wallet alias is required")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if initial_delay_seconds < 0:
            raise ValueError("initial_delay_seconds must not be negative")
        self.candidate = candidate
        self._path = path
        self._source_id = source_id
        self._aliases = dict(aliases)
        self._transport = transport or UrllibJsonGetTransport()
        self._poll_interval_seconds = poll_interval_seconds
        self._initial_delay_seconds = initial_delay_seconds
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
        if self._initial_delay_seconds:
            remaining = (deadline - self._clock()).total_seconds()
            if remaining <= 0:
                return
            await self._sleep(min(self._initial_delay_seconds, remaining))
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
        fee_schedules: Mapping[str, MarketFeeSchedule] | None = None,
        market_discovery: MarketDiscovery | None = None,
        discovery_interval_seconds: float = 2.0,
        market_stream_factory: MarketStreamFactory | None = None,
        token_markets: Mapping[str, str] | None = None,
        terminal_snapshot_fetcher: TerminalMarketSnapshotFetcher | None = None,
        terminal_settlement_fetcher: TerminalSettlementFetcher | None = None,
        terminal_snapshot_limit: int = 500,
        snapshot_refresh_interval_seconds: float = 20.0,
    ) -> None:
        if discovery_interval_seconds <= 0:
            raise ValueError("discovery_interval_seconds must be positive")
        if len(token_ids) > 500:
            raise ValueError("token_ids must contain at most 500 items")
        if terminal_snapshot_limit <= 0 or terminal_snapshot_limit > 500:
            raise ValueError("terminal_snapshot_limit must be within [1, 500]")
        if snapshot_refresh_interval_seconds <= 0:
            raise ValueError("snapshot_refresh_interval_seconds must be positive")
        self.candidate = MARKET_STREAM_CANDIDATE
        if event_factory is None and not token_ids and market_discovery is None:
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
        self._fee_schedules = dict(fee_schedules or {})
        self._market_discovery = market_discovery
        self._discovery_interval_seconds = discovery_interval_seconds
        self._market_stream_factory = market_stream_factory
        self._token_markets = dict(token_markets or {})
        self._terminal_snapshot_fetcher = terminal_snapshot_fetcher
        self._terminal_settlement_fetcher = terminal_settlement_fetcher
        self._terminal_snapshot_limit = terminal_snapshot_limit
        self._snapshot_refresh_interval_seconds = snapshot_refresh_interval_seconds
        self._books = BookBuilder()
        self._invalid_book_tokens: set[str] = set()
        self._last_book_failure_at: datetime | None = None
        self._last_book_failure_class: str | None = None
        self._book_recovery_requested = False
        self._book_recovery_not_before: datetime | None = None
        self._usable_book_tokens: set[str] = set()
        self.reconnect_count = 0
        self.subscription_update_count = 0
        self.discovery_failure_count = 0
        self.book_validation_failure_count = 0
        self.book_recovery_count = 0
        self.snapshot_refresh_count = 0
        self.snapshot_refresh_failure_count = 0
        self.snapshot_refresh_missing = 0
        self.terminal_snapshot_requested = 0
        self.terminal_snapshot_captured = 0
        self.terminal_snapshot_missing = 0
        self.terminal_snapshot_limit_reached = False
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
                for item in self._from_market_event(event, run_id=run_id):
                    yield item
            return
        async for item in self._run_official_stream(run_id=run_id, deadline=deadline):
            yield item

    async def _run_official_stream(
        self,
        *,
        run_id: str,
        deadline: datetime,
    ) -> AsyncIterator[CanonicalResearchEvent]:
        from polysia.bus.in_memory_bus import InMemoryEventBus

        bus = InMemoryEventBus()
        subscription = bus.subscribe()
        stream = self._new_market_stream(bus)
        runner = asyncio.create_task(stream.run())
        next_discovery_at = self._clock() + timedelta(
            seconds=self._discovery_interval_seconds
        )
        next_snapshot_at = self._clock()
        try:
            async with subscription:
                while self._clock() < deadline:
                    wait_timeout = min(1.0, max(0.05, (deadline - self._clock()).total_seconds()))
                    next_event = asyncio.create_task(anext(subscription))
                    sleeper = asyncio.ensure_future(self._sleep(wait_timeout))
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
                        normalized = self._from_market_event(
                            market_event,
                            run_id=run_id,
                            receive_ns=receive_ns,
                            normalize_ns=self._monotonic_ns(),
                        )
                        for item in normalized:
                            yield item
                        if self._book_recovery_requested and self._book_recovery_due():
                            if not runner.done():
                                runner.cancel()
                                with suppress(asyncio.CancelledError):
                                    await runner
                            stream = self._new_market_stream(bus)
                            runner = asyncio.create_task(stream.run())
                            self._book_recovery_requested = False
                            self._book_recovery_not_before = self._clock() + timedelta(seconds=5)
                            self.book_recovery_count += 1
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
                        stream = self._new_market_stream(bus)
                        runner = asyncio.create_task(stream.run())
                    if self._clock() >= next_discovery_at:
                        changed = await self._refresh_market_discovery()
                        next_discovery_at = self._clock() + timedelta(
                            seconds=self._discovery_interval_seconds
                        )
                        if changed:
                            if not runner.done():
                                runner.cancel()
                                with suppress(asyncio.CancelledError):
                                    await runner
                            stream = self._new_market_stream(bus)
                            runner = asyncio.create_task(stream.run())
                            self.subscription_update_count += 1
                            # Newly discovered wallet tokens need executable evidence
                            # immediately; waiting for the periodic cadence creates a
                            # deterministic first-observation coverage gap.
                            next_snapshot_at = self._clock()
                    if self._clock() >= next_snapshot_at:
                        refreshed = await self._capture_snapshot_evidence(
                            run_id=run_id,
                            token_markets=self._token_markets,
                            reason="periodic_refresh",
                        )
                        if refreshed is None:
                            self.snapshot_refresh_failure_count += 1
                        else:
                            events, _requested, _captured, missing, _capped = refreshed
                            self.snapshot_refresh_count += 1
                            self.snapshot_refresh_missing = missing
                            for item in events:
                                yield item
                        next_snapshot_at = self._clock() + timedelta(
                            seconds=self._snapshot_refresh_interval_seconds
                        )
        finally:
            if not runner.done():
                runner.cancel()
                with suppress(asyncio.CancelledError):
                    await runner
            await subscription.close()

    def _new_market_stream(self, bus: Any) -> MarketStreamRunner:
        if self._market_stream_factory is not None:
            return self._market_stream_factory(bus, self._token_ids, self._stale_after)
        from polysia.adapters.polymarket.stream import MarketStream, MarketStreamConfig

        return MarketStream(
            bus=bus,
            config=MarketStreamConfig(
                token_ids=self._token_ids,
                stale_after=self._stale_after,
            ),
        )

    async def _refresh_market_discovery(self) -> bool:
        if self._market_discovery is None:
            return False
        try:
            snapshot = await self._market_discovery()
        except (
            PolymarketCopyTradingSourceError,
            TradesSourceUnavailableError,
            HTTPError,
            URLError,
            OSError,
            TimeoutError,
            ValueError,
            TypeError,
        ):
            self.discovery_failure_count += 1
            return False
        current = set(self._token_ids)
        desired = {token for token in snapshot.token_markets if token}
        changed = desired != current
        if changed:
            retained = tuple(token for token in self._token_ids if token in desired)
            added = tuple(
                token
                for token in snapshot.token_markets
                if token and token not in current
            )
            self._token_ids = (*retained, *added)[:500]
        self._token_markets = {
            token: market
            for token, market in snapshot.token_markets.items()
            if token in set(self._token_ids)
        }
        known = set(self._token_ids)
        self._fee_schedules = {
            token: schedule
            for token, schedule in self._fee_schedules.items()
            if token in known
        }
        self._fee_schedules.update(
            {
                token: schedule
                for token, schedule in snapshot.fee_schedules.items()
                if token in known
            }
        )
        return changed

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
            "subscription_update_count": self.subscription_update_count,
            "discovery_failure_count": self.discovery_failure_count,
            "book_validation_failure_count": self.book_validation_failure_count,
            "book_recovery_count": self.book_recovery_count,
            "snapshot_refresh_count": self.snapshot_refresh_count,
            "snapshot_refresh_failure_count": self.snapshot_refresh_failure_count,
            "snapshot_refresh_missing": self.snapshot_refresh_missing,
            "last_book_failure_at": _optional_time(self._last_book_failure_at),
            "last_book_failure_class": self._last_book_failure_class,
            "invalid_book_token_count": len(self._invalid_book_tokens),
            "usable_book_token_count": len(self._usable_book_tokens),
            "terminal_snapshot_requested": self.terminal_snapshot_requested,
            "terminal_snapshot_captured": self.terminal_snapshot_captured,
            "terminal_snapshot_missing": self.terminal_snapshot_missing,
            "terminal_snapshot_limit_reached": self.terminal_snapshot_limit_reached,
        }

    async def capture_terminal_evidence(
        self,
        *,
        run_id: str,
        token_markets: Mapping[str, str],
    ) -> tuple[CanonicalResearchEvent, ...]:
        """Capture bounded fresh books needed for terminal valuation."""

        captured = await self._capture_snapshot_evidence(
            run_id=run_id,
            token_markets=token_markets,
            reason="terminal_valuation",
        )
        if captured is None:
            self.terminal_snapshot_requested = len(token_markets)
            self.terminal_snapshot_captured = 0
            self.terminal_snapshot_missing = min(
                len(token_markets),
                self._terminal_snapshot_limit,
            )
            self.terminal_snapshot_limit_reached = (
                len(token_markets) > self._terminal_snapshot_limit
            )
            self._last_failure_at = self._clock()
            self._failure_class = "terminal_snapshot_failed"
            return ()
        events, requested, books, missing, capped = captured
        selected = dict(list(token_markets.items())[: self._terminal_snapshot_limit])
        captured_tokens = {
            item.outcome_reference
            for item in events
            if item.outcome_reference is not None
        }
        settlement_events: tuple[CanonicalResearchEvent, ...] = ()
        if self._terminal_settlement_fetcher is not None and missing:
            unresolved = {
                token: market
                for token, market in selected.items()
                if token not in captured_tokens
            }
            try:
                settlements = await self._terminal_settlement_fetcher(unresolved)
            except (OSError, RuntimeError, TimeoutError, TypeError, ValueError):
                settlements = {}
            settlement_events = tuple(
                self._settlement_event(
                    run_id=run_id,
                    token=token,
                    market=unresolved[token],
                    price=price,
                )
                for token, price in settlements.items()
                if token in unresolved and price in {Decimal("0"), Decimal("1")}
            )
            self._invalid_book_tokens.difference_update(
                item.outcome_reference
                for item in settlement_events
                if item.outcome_reference is not None
            )
            books += len(settlement_events)
            missing = max(0, len(selected) - books)
        self.terminal_snapshot_requested = requested
        self.terminal_snapshot_captured = books
        self.terminal_snapshot_missing = missing
        self.terminal_snapshot_limit_reached = capped
        return (*events, *settlement_events)

    def _settlement_event(
        self,
        *,
        run_id: str,
        token: str,
        market: str,
        price: Decimal,
    ) -> CanonicalResearchEvent:
        observed = self._clock()
        receive = self._monotonic_ns()
        identity = {
            "event_type": "settlement",
            "market": market,
            "received_at": observed.isoformat(),
            "settlement_price": format(price, "f"),
            "token_id": token,
        }
        return CanonicalResearchEvent(
            evidence_id=stable_evidence_id(
                source_id=TERMINAL_SETTLEMENT_SOURCE_ID,
                identity_fields=identity,
            ),
            schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
            source_id=TERMINAL_SETTLEMENT_SOURCE_ID,
            event_kind=ObservationKind.MARKET_STATE,
            classification=EvidenceClassification.ACCEPTED,
            market_reference=market,
            outcome_reference=token,
            side=None,
            price=price if price > 0 else None,
            size=None,
            source_time=None,
            observed_time=observed,
            receive_monotonic_ns=receive,
            normalize_monotonic_ns=receive,
            attribution_status=AttributionStatus.NOT_APPLICABLE,
            leader_alias=None,
            confirmation=ConfirmationStatus.CONFIRMED,
            payload_digest=payload_digest(identity),
            provenance={
                "event_type": "settlement",
                "settlement_evidence_version": "official-terminal-settlement-v1",
                "settlement_price": format(price, "f"),
                "settlement_status": "resolved",
                "source": "polymarket-public-market",
                "valuation_basis": "official-settlement",
                "wallet_attribution": "not_applicable",
            },
            run_id=run_id,
        )

    async def _capture_snapshot_evidence(
        self,
        *,
        run_id: str,
        token_markets: Mapping[str, str],
        reason: str,
    ) -> tuple[tuple[CanonicalResearchEvent, ...], int, int, int, bool] | None:
        if self._terminal_snapshot_fetcher is None or not token_markets:
            return ((), len(token_markets), 0, len(token_markets), False)
        selected = dict(list(token_markets.items())[: self._terminal_snapshot_limit])
        try:
            snapshot = await self._terminal_snapshot_fetcher(selected)
        except (OSError, RuntimeError, TimeoutError, TypeError, ValueError):
            return None
        self._fee_schedules.update(snapshot.fee_schedules)
        self._token_markets.update(selected)
        observed = self._clock()
        events: list[CanonicalResearchEvent] = []
        for token, book in snapshot.books.items():
            if token not in selected:
                continue
            event = MarketDataEvent(
                source="polymarket",
                event_type="book",
                token_id=token,
                received_at=observed,
                exchange_ts=book.timestamp,
                payload={
                    "asks": [
                        {"price": format(level.price, "f"), "size": format(level.size, "f")}
                        for level in book.asks
                    ],
                    "bids": [
                        {"price": format(level.price, "f"), "size": format(level.size, "f")}
                        for level in book.bids
                    ],
                    "hash": book.book_hash,
                    "market": selected[token],
                    "snapshot_reason": reason,
                },
                raw_payload={},
            )
            events.extend(self._from_market_event(event, run_id=run_id))
        return (
            tuple(events),
            len(token_markets),
            len(snapshot.books),
            len(selected) - len(snapshot.books),
            len(token_markets) > len(selected),
        )

    def _from_market_event(
        self,
        event: MarketDataEvent,
        *,
        run_id: str,
        receive_ns: int | None = None,
        normalize_ns: int | None = None,
    ) -> tuple[CanonicalResearchEvent, ...]:
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
        market_reference = _optional_mapping_text(payload, "market")
        identity = _base_identity(event, market_reference=market_reference)
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
        base = CanonicalResearchEvent(
            evidence_id=stable_evidence_id(
                source_id=MARKET_STREAM_SOURCE_ID,
                identity_fields=identity,
            ),
            schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
            source_id=MARKET_STREAM_SOURCE_ID,
            event_kind=ObservationKind.MARKET_STATE,
            classification=EvidenceClassification.ACCEPTED,
            market_reference=market_reference,
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
        if event.event_type not in {"book", "price_change"}:
            return (base,)
        if event.token_id in self._invalid_book_tokens and event.event_type != "book":
            return (self._invalid_book_base(base, "awaiting_fresh_snapshot"),)
        try:
            book = self._books.apply(event)
        except (KeyError, TypeError, ValueError, OrderBookValidationError) as error:
            self._books.invalidate(event.token_id)
            self._usable_book_tokens.discard(event.token_id)
            self._invalid_book_tokens.add(event.token_id)
            self._book_recovery_requested = True
            self.book_validation_failure_count += 1
            self._last_book_failure_at = self._clock()
            self._last_book_failure_class = type(error).__name__
            return (self._invalid_book_base(base, type(error).__name__),)
        if event.event_type == "book":
            self._invalid_book_tokens.discard(event.token_id)
        if book.best_bid is not None and book.best_ask is not None:
            self._usable_book_tokens.add(event.token_id)
        book_bid = book.best_bid
        book_ask = book.best_ask
        if book_bid is not None:
            base = replace(
                base,
                price=book_bid,
                confirmation=ConfirmationStatus.CONFIRMED,
                provenance={
                    **base.provenance,
                    "best_bid": format(book_bid, "f"),
                    "best_ask": None if book_ask is None else format(book_ask, "f"),
                    "quote_status": "present" if book_ask is not None else "UNKNOWN",
                    "depth_status": "present",
                    "valuation_basis": "executable_bid",
                },
            )
        executions = tuple(
            self._execution_event(
                event,
                run_id=run_id,
                side=side,
                levels=levels,
                market_reference=base.market_reference,
                receive_ns=receive,
                normalize_ns=normalize,
            )
            for side, levels in (("BUY", book.asks), ("SELL", book.bids))
        )
        return (base, *executions)

    def _book_recovery_due(self) -> bool:
        return (
            self._book_recovery_not_before is None
            or self._clock() >= self._book_recovery_not_before
        )

    @staticmethod
    def _invalid_book_base(
        base: CanonicalResearchEvent,
        failure_class: str,
    ) -> CanonicalResearchEvent:
        return replace(
            base,
            price=None,
            confirmation=ConfirmationStatus.UNCONFIRMED,
            provenance={
                **base.provenance,
                "book_state": "invalid",
                "book_validation_failure": failure_class,
                "depth_status": "UNKNOWN",
                "executable_price": None,
                "quote_status": "UNKNOWN",
            },
        )

    def _execution_event(
        self,
        event: MarketDataEvent,
        *,
        run_id: str,
        side: str,
        levels: object,
        market_reference: str | None,
        receive_ns: int,
        normalize_ns: int,
    ) -> CanonicalResearchEvent:
        normalized_levels = tuple(levels) if isinstance(levels, tuple | list) else ()
        schedule = self._fee_schedules.get(event.token_id)
        rate = None if schedule is None else schedule.rate
        exponent = None if schedule is None else schedule.exponent
        taker_only = None if schedule is None else schedule.taker_only
        fees_enabled = None if schedule is None else schedule.enabled
        available = sum((item.size for item in normalized_levels), Decimal("0"))
        best = normalized_levels[0].price if normalized_levels else None
        fee_complete = fees_enabled is False or (
            rate is not None and exponent is not None and taker_only is True
        )
        complete = best is not None and available > 0 and fee_complete
        if not normalized_levels:
            failure = "missing_depth"
        elif not fee_complete:
            failure = "missing_fee"
        else:
            failure = None
        identity = {
            "event_type": event.event_type,
            "market": market_reference,
            "received_at": event.received_at.isoformat(),
            "side": side,
            "token_id": event.token_id,
        }
        evidence_id = stable_evidence_id(
            source_id=MARKET_STREAM_SOURCE_ID,
            identity_fields=identity,
        )
        provenance: dict[str, object] = {
            "book_levels": [
                {"price": format(item.price, "f"), "size": format(item.size, "f")}
                for item in normalized_levels
            ],
            "decision_clock": "wallet-observed-time",
            "execution_evidence": complete,
            "execution_evidence_version": "order-book-depth-v1",
            "execution_failure": failure,
            "fee_calculation_version": "polymarket-taker-fee-v1",
            "fee_exponent": None if exponent is None else format(exponent, "f"),
            "fee_rate": None if rate is None else format(rate, "f"),
            "fee_source": "official-public-market-fee-schedule",
            "fee_taker_only": taker_only,
            "fee_valid_at": event.received_at.isoformat(),
            "fees_enabled": fees_enabled,
            "markout_eligible": False,
            "book_state_digest": payload_digest(
                {
                    "levels": [
                        (format(item.price, "f"), format(item.size, "f"))
                        for item in normalized_levels
                    ],
                    "side": side,
                }
            ),
            "source_sequence": event.payload.get("hash")
            or event.payload.get("timestamp"),
            "source_event_type": event.event_type,
        }
        return CanonicalResearchEvent(
            evidence_id=evidence_id,
            schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
            source_id=MARKET_STREAM_SOURCE_ID,
            event_kind=ObservationKind.MARKET_STATE,
            classification=EvidenceClassification.ACCEPTED,
            market_reference=market_reference,
            outcome_reference=event.token_id or None,
            side=side,
            price=best,
            size=available if available > 0 else None,
            source_time=event.exchange_ts,
            observed_time=event.received_at,
            receive_monotonic_ns=receive_ns,
            normalize_monotonic_ns=normalize_ns,
            attribution_status=AttributionStatus.NOT_APPLICABLE,
            leader_alias=None,
            confirmation=(
                ConfirmationStatus.CONFIRMED
                if complete
                else ConfirmationStatus.UNCONFIRMED
            ),
            payload_digest=payload_digest(identity),
            provenance=provenance,
            related_evidence_id=base_evidence_id(event),
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
    page_limit: int = 500,
    token_limit: int = 500,
    lookback: timedelta = timedelta(minutes=30),
    clock: Clock | None = None,
) -> tuple[str, ...]:
    """Public tokens recently traded by followed wallets."""

    markets = await discover_followed_markets(
        transport,
        aliases,
        page_limit=page_limit,
        token_limit=token_limit,
        lookback=lookback,
        clock=clock,
    )
    return tuple(markets)


async def discover_followed_markets(
    transport: JsonGetTransport,
    aliases: Mapping[str, str],
    *,
    page_limit: int = 500,
    token_limit: int = 500,
    lookback: timedelta = timedelta(minutes=30),
    clock: Clock | None = None,
) -> dict[str, str]:
    """Map recent public outcome tokens to their condition IDs.

    The lookback matches the persistent wallet source. This keeps the market
    stream bounded while covering the observations eligible for the next
    window instead of an arbitrary prefix of historical tokens.
    """

    if page_limit <= 0 or page_limit > 10_000:
        raise ValueError("page_limit must be within [1, 10000]")
    if token_limit <= 0 or token_limit > 500:
        raise ValueError("token_limit must be within [1, 500]")
    if lookback.total_seconds() <= 0:
        raise ValueError("lookback must be positive")

    now = (clock or (lambda: datetime.now(UTC)))()
    start = now - lookback
    candidates: dict[str, tuple[int, str]] = {}
    for wallet in aliases.values():
        payload = await transport.get_json(
            DATA_API_BASE_URL,
            "/trades",
            {
                "user": wallet,
                "limit": page_limit,
                "offset": 0,
                "start": int(start.timestamp()),
                "end": int(now.timestamp()),
                "takerOnly": False,
            },
            purpose=LeaderReadPurpose.DISCOVERY,
        )
        if not isinstance(payload, list):
            continue
        for row in payload:
            if not isinstance(row, dict):
                continue
            token = row.get("asset")
            condition = row.get("conditionId")
            if (
                isinstance(token, str)
                and token
                and isinstance(condition, str)
                and condition
            ):
                observed = _row_timestamp(row)
                current = candidates.get(token)
                if current is None or observed > current[0]:
                    candidates[token] = (observed, condition)
    ranked = sorted(
        candidates.items(),
        key=lambda item: (-item[1][0], item[0]),
    )
    return {
        token: timestamp_and_condition[1]
        for token, timestamp_and_condition in ranked[:token_limit]
    }


async def discover_clob_market_fee_schedules(
    transport: JsonGetTransport,
    token_markets: Mapping[str, str],
    *,
    batch_size: int = 20,
) -> dict[str, MarketFeeSchedule]:
    """Resolve fee curves from the official CLOB market-info endpoint."""

    if batch_size <= 0 or batch_size > 50:
        raise ValueError("batch_size must be within [1, 50]")
    requested = set(token_markets)
    conditions = tuple(dict.fromkeys(token_markets.values()))

    async def fetch(condition: str) -> object:
        return await transport.get_json(
            CLOB_API_BASE_URL,
            f"/clob-markets/{condition}",
            {},
            purpose=LeaderReadPurpose.DISCOVERY,
        )

    schedules: dict[str, MarketFeeSchedule] = {}
    for offset in range(0, len(conditions), batch_size):
        results = await asyncio.gather(
            *(fetch(condition) for condition in conditions[offset : offset + batch_size]),
            return_exceptions=True,
        )
        for payload in results:
            if not isinstance(payload, Mapping):
                continue
            fee = payload.get("fd")
            tokens = payload.get("t")
            if not isinstance(fee, Mapping) or not isinstance(tokens, list):
                continue
            rate = _optional_decimal(fee.get("r"))
            exponent = _optional_decimal(fee.get("e"))
            taker_only = fee.get("to")
            if rate is None or exponent is None or taker_only is not True:
                continue
            schedule = MarketFeeSchedule(
                enabled=rate > 0,
                rate=rate,
                exponent=exponent,
                taker_only=True,
            )
            for item in tokens:
                if not isinstance(item, Mapping):
                    continue
                token = item.get("t")
                if token is not None and str(token) in requested:
                    schedules[str(token)] = schedule
    return schedules


class FollowedMarketDiscovery:
    """Refresh a bounded followed-token set without repeating fee lookups."""

    def __init__(
        self,
        transport: JsonGetTransport,
        aliases: Mapping[str, str],
        *,
        token_limit: int = 500,
        lookback: timedelta = timedelta(minutes=30),
        clock: Clock | None = None,
    ) -> None:
        if not aliases:
            raise ValueError("at least one public wallet alias is required")
        if token_limit <= 0 or token_limit > 500:
            raise ValueError("token_limit must be within [1, 500]")
        self._transport = transport
        self._aliases = dict(aliases)
        self._token_limit = token_limit
        self._lookback = lookback
        self._clock = clock or (lambda: datetime.now(UTC))
        self._token_markets: dict[str, str] = {}
        self._fee_schedules: dict[str, MarketFeeSchedule] = {}
        self._fee_retry_at: dict[str, datetime] = {}

    async def refresh(self) -> MarketDiscoverySnapshot:
        discovered = await discover_followed_markets(
            self._transport,
            self._aliases,
            token_limit=self._token_limit,
            lookback=self._lookback,
            clock=self._clock,
        )
        self._token_markets = dict(discovered)
        active_tokens = set(self._token_markets)
        self._fee_schedules = {
            token: schedule
            for token, schedule in self._fee_schedules.items()
            if token in active_tokens
        }
        self._fee_retry_at = {
            token: retry_at
            for token, retry_at in self._fee_retry_at.items()
            if token in active_tokens
        }

        now = self._clock()
        pending = {
            token: condition
            for token, condition in self._token_markets.items()
            if token not in self._fee_schedules
            and self._fee_retry_at.get(token, now) <= now
        }
        resolved = await discover_clob_market_fee_schedules(self._transport, pending)
        self._fee_schedules.update(resolved)
        retry_at = now + timedelta(minutes=1)
        self._fee_retry_at.update(
            {token: retry_at for token in pending if token not in resolved}
        )
        return MarketDiscoverySnapshot(
            token_markets=dict(self._token_markets),
            fee_schedules=dict(self._fee_schedules),
        )


async def discover_market_fee_schedules(
    token_ids: tuple[str, ...],
) -> dict[str, MarketFeeSchedule]:
    """Resolve authoritative public Gamma fee schedules for followed tokens."""

    if not token_ids:
        return {}
    from polymarket import AsyncPublicClient

    schedules: dict[str, MarketFeeSchedule] = {}
    async with AsyncPublicClient() as client:
        paginator = client.list_markets(
            clob_token_ids=token_ids,
            include_tag=False,
            page_size=max(20, len(token_ids)),
        )
        page = await paginator.first_page()
        for market in page.items:
            trading = getattr(market, "trading", None)
            enabled = getattr(trading, "fees_enabled", None)
            schedule = getattr(trading, "fee_schedule", None)
            if not isinstance(enabled, bool):
                continue
            normalized = MarketFeeSchedule(
                enabled=enabled,
                rate=(Decimal("0") if enabled is False else getattr(schedule, "rate", None)),
                exponent=(
                    Decimal("0") if enabled is False else getattr(schedule, "exponent", None)
                ),
                taker_only=(True if enabled is False else getattr(schedule, "taker_only", None)),
                rebate_rate=getattr(schedule, "rebate_rate", None),
            )
            outcomes = getattr(market, "outcomes", None)
            for name in ("yes", "no"):
                outcome = getattr(outcomes, name, None)
                token = getattr(outcome, "token_id", None)
                if token is not None and str(token) in token_ids:
                    schedules[str(token)] = normalized
    return schedules


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


def base_evidence_id(event: MarketDataEvent) -> str:
    return stable_evidence_id(
        source_id=MARKET_STREAM_SOURCE_ID,
        identity_fields=_base_identity(
            event,
            market_reference=_optional_mapping_text(event.payload, "market"),
        ),
    )


def _base_identity(
    event: MarketDataEvent,
    *,
    market_reference: str | None,
) -> dict[str, object]:
    return {
        "event_type": event.event_type,
        "market": market_reference,
        "received_at": event.received_at.isoformat(),
        "token_id": event.token_id,
    }


def _optional_mapping_text(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        price_change = payload.get("price_change")
        if isinstance(price_change, Mapping):
            value = price_change.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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
