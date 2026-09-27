from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from polysia.adapters.polymarket.data_api_v2 import (
    DATA_API_V2_ACTIVITY_PATH,
    DATA_API_V2_TRADES_PATH,
    IncompleteWalletWindowError,
    fetch_data_api_v2_window,
)
from polysia.adapters.polymarket.request_scheduling import (
    EndpointRequestScheduler,
)
from polysia.application.ports.copytrading import (
    LeaderInventorySnapshot,
    LeaderMarketMetadata,
    LeaderReadPurpose,
    LeaderTradeCheckpoint,
    LeaderTradeReadPage,
)
from polysia.domain.copytrading import (
    LeaderPositionEffect,
    LeaderTradeAction,
    LeaderTradeEvent,
    deduplicate_leader_trade_events,
)

_WALLET_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")
_CONDITION_PATTERN = re.compile(r"^0x[a-fA-F0-9]{64}$")
_TRANSACTION_PATTERN = re.compile(r"^0x[a-fA-F0-9]{64}$")
_BTC_15M_SLUG_PATTERN = re.compile(r"^btc-updown-15m-(?P<start>[0-9]{10})$")
_SAFE_ALIAS_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")

DATA_API_BASE_URL = "https://data-api.polymarket.com"
GAMMA_API_BASE_URL = "https://gamma-api.polymarket.com"
CLOB_API_BASE_URL = "https://clob.polymarket.com"
POSITION_PAGE_SIZE = 500
POSITION_MAX_OFFSET = 10_000
SOURCE_ID = "polymarket:data-api"

Clock = Callable[[], datetime]
_PUBLIC_READ_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="polysia-public-read")
_PUBLIC_READ_SLOTS = threading.BoundedSemaphore(8)


class PolymarketCopyTradingSourceError(RuntimeError):
    """Safe Stage 1 source failure with no raw wallet or response content."""


class PolymarketMarketScope(StrEnum):
    """Explicit market scope; legacy execution remains BTC-15m by default."""

    BTC_15M = "BTC_15M"
    ALL_VERIFIED = "ALL_VERIFIED"


class JsonGetTransport(Protocol):
    async def get_json(
        self,
        base_url: str,
        path: str,
        params: Mapping[str, str | int | bool],
        *,
        purpose: LeaderReadPurpose = LeaderReadPurpose.BASELINE,
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class PolymarketSourceCoverage:
    all_trade_count: int
    taker_trade_count: int
    activity_trade_count: int
    current_position_count: int
    closed_position_count: int
    smallest_visible_position: Decimal | None
    page_limit: int

    @property
    def maker_coverage_delta(self) -> int:
        return max(0, self.all_trade_count - self.taker_trade_count)


@dataclass(frozen=True, slots=True)
class _VerifiedMarket:
    slug: str
    condition_id: str
    outcomes_by_token: Mapping[str, str]
    starts_at: datetime
    ends_at: datetime


class UrllibJsonGetTransport:
    """Bounded unauthenticated JSON GET transport for official public APIs."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 10,
        max_attempts: int = 2,
        backoff_seconds: float = 0.25,
        max_response_bytes: int = 5_000_000,
        scheduler: EndpointRequestScheduler | None = None,
    ) -> None:
        if not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts must be within [1, 3]")
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be within [1, 30]")
        if not 0 <= backoff_seconds <= 2:
            raise ValueError("backoff_seconds must be within [0, 2]")
        if not 1024 <= max_response_bytes <= 10_000_000:
            raise ValueError("max_response_bytes must be within [1024, 10000000]")
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._max_response_bytes = max_response_bytes
        self._scheduler = scheduler or EndpointRequestScheduler()

    async def get_json(
        self,
        base_url: str,
        path: str,
        params: Mapping[str, str | int | bool],
        *,
        purpose: LeaderReadPurpose = LeaderReadPurpose.BASELINE,
    ) -> Any:
        if base_url not in {CLOB_API_BASE_URL, DATA_API_BASE_URL, GAMMA_API_BASE_URL}:
            raise PolymarketCopyTradingSourceError("Unapproved public API base URL.")
        if not path.startswith("/") or "://" in path:
            raise PolymarketCopyTradingSourceError("Invalid public API path.")

        url = f"{base_url}{path}?{urlencode(_stringify_params(params))}"
        api = (
            "gamma"
            if base_url == GAMMA_API_BASE_URL
            else ("clob" if base_url == CLOB_API_BASE_URL else "data")
        )
        route = f"{api}:{path}"
        for attempt in range(1, self._max_attempts + 1):
            try:
                async with self._scheduler.request(
                    route,
                    purpose=purpose,
                    retry=attempt > 1,
                ):
                    if not _PUBLIC_READ_SLOTS.acquire(blocking=False):
                        raise PolymarketCopyTradingSourceError(
                            "Public API blocking-read capacity exhausted."
                        )
                    try:
                        future = _PUBLIC_READ_POOL.submit(self._read_json, url)
                    except Exception:
                        _PUBLIC_READ_SLOTS.release()
                        raise
                    future.add_done_callback(lambda _: _PUBLIC_READ_SLOTS.release())
                    payload = await asyncio.wrap_future(future)
                await self._scheduler.record_success(route, purpose=purpose)
                return payload
            except HTTPError as error:
                if error.code == 429 and _is_trades_path(path):
                    retry_after = (
                        None if error.headers is None else error.headers.get("Retry-After")
                    )
                    await self._scheduler.record_rate_limit(
                        retry_after,
                        purpose=purpose,
                    )
                    raise await self._scheduler.unavailable_error(
                        reason="Public /trades source returned HTTP 429."
                    ) from error
                retryable = error.code >= 500
                if not retryable or attempt >= self._max_attempts:
                    if _is_trades_path(path):
                        await self._scheduler.record_trades_failure(purpose=purpose)
                        raise await self._scheduler.unavailable_error(
                            reason="Public /trades source remained unavailable."
                        ) from error
                    raise PolymarketCopyTradingSourceError(
                        f"Public API returned HTTP {error.code}."
                    ) from error
            except (TimeoutError, URLError) as error:
                if attempt >= self._max_attempts:
                    if _is_trades_path(path):
                        await self._scheduler.record_trades_failure(purpose=purpose)
                        raise await self._scheduler.unavailable_error(
                            reason="Public /trades read failed after bounded retry."
                        ) from error
                    raise PolymarketCopyTradingSourceError(
                        "Public API read failed after bounded retry."
                    ) from error
            await asyncio.sleep(self._backoff_seconds * attempt)

        raise AssertionError("bounded public read retry loop exhausted unexpectedly")

    def request_telemetry(self) -> dict[str, object]:
        return self._scheduler.telemetry_snapshot()

    def trades_circuit(self) -> dict[str, object]:
        return self._scheduler.circuit_snapshot()

    async def restore_trades_circuit(
        self,
        *,
        outage_started_at: datetime,
        retry_at: datetime,
        cooldown_attempt: int,
    ) -> None:
        await self._scheduler.restore_circuit(
            outage_started_at=outage_started_at,
            retry_at=retry_at,
            cooldown_attempt=cooldown_attempt,
        )

    def _read_json(self, url: str) -> Any:
        request = Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "User-Agent": "PolySia/0.1 read-only research",
            },
        )
        with urlopen(request, timeout=self._timeout_seconds) as response:
            payload = response.read(self._max_response_bytes + 1)
        if len(payload) > self._max_response_bytes:
            raise PolymarketCopyTradingSourceError("Public API response exceeded size cap.")
        try:
            return json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PolymarketCopyTradingSourceError("Public API returned invalid JSON.") from error


class PolymarketCopyTradingSource:
    """Read-only Stage 1 adapter for confirmed public leader executions."""

    def __init__(
        self,
        leaders: Mapping[str, str],
        *,
        transport: JsonGetTransport | None = None,
        clock: Clock | None = None,
        market_scope: PolymarketMarketScope = PolymarketMarketScope.BTC_15M,
        max_pages: int = 20,
        max_requests: int = 20,
        max_elapsed_seconds: int = 30,
    ) -> None:
        if not 1 <= max_pages <= max_requests <= 100:
            raise ValueError("Data API cursor page/request budgets are invalid")
        if not 1 <= max_elapsed_seconds <= 60:
            raise ValueError("Data API cursor time budget is invalid")
        self._leaders = _validated_leaders(leaders)
        self._transport = transport or UrllibJsonGetTransport()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._market_scope = market_scope
        self._max_pages = max_pages
        self._max_requests = max_requests
        self._max_elapsed_seconds = max_elapsed_seconds
        self._market_cache: dict[str, dict[str, _VerifiedMarket]] = {}
        self._market_by_condition: dict[str, _VerifiedMarket] = {}
        self._pending_observer: Callable[[tuple[str, ...], datetime], None] | None = None

    def set_pending_observer(
        self, observer: Callable[[tuple[str, ...], datetime], None]
    ) -> None:
        """Capture page identities before a complete walk permits admission."""

        self._pending_observer = observer

    async def read_page(
        self,
        leader_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        page_size: int = 100,
        checkpoint: LeaderTradeCheckpoint | None = None,
        purpose: LeaderReadPurpose = LeaderReadPurpose.DISCOVERY,
    ) -> LeaderTradeReadPage:
        wallet = self._leader_wallet(leader_id)
        _require_utc_window(start_at, end_at)
        if not 1 <= page_size <= 500:
            raise ValueError("page_size must be within [1, 500]")

        frozen_start = int(start_at.timestamp())
        frozen_end = int(end_at.timestamp())
        if checkpoint is not None:
            raise PolymarketCopyTradingSourceError(
                "Legacy offset checkpoint cannot resume a v2 cursor window."
            )

        deadline_monotonic = time.monotonic() + self._max_elapsed_seconds
        rows = await fetch_data_api_v2_window(
            self._transport,
            DATA_API_V2_TRADES_PATH,
            {
                "user": wallet,
                "taker_only": False,
                "start": frozen_start,
                "end": frozen_end,
                "limit": page_size,
            },
            purpose=purpose,
            max_pages=self._max_pages,
            max_requests=self._max_requests,
            max_elapsed_seconds=self._max_elapsed_seconds,
            deadline_monotonic=deadline_monotonic,
            on_page=lambda page_rows: self._capture_pending_page(
                page_rows, expected_wallet=wallet
            ),
        )
        observed_at = self._utc_now()
        normalized: list[LeaderTradeEvent] = []
        filtered_count = 0
        rejected_count = 0
        target_rows: list[tuple[dict[str, Any], str, str]] = []

        for row in rows:
            try:
                timestamp = row.get("timestamp")
                if isinstance(timestamp, bool) or not isinstance(timestamp, int):
                    raise ValueError("timestamp must be epoch seconds")
                executed_at = datetime.fromtimestamp(timestamp, tz=UTC)
                if not start_at <= executed_at <= end_at:
                    # The endpoint uses whole seconds; enforce the precise caller window
                    # before metadata reads. Pagination still uses the raw row count.
                    filtered_count += 1
                    continue
                slug = _required_string(row, "eventSlug")
                if (
                    self._market_scope is PolymarketMarketScope.BTC_15M
                    and _BTC_15M_SLUG_PATTERN.fullmatch(slug) is None
                ):
                    filtered_count += 1
                    continue
                condition_id = _required_string(row, "conditionId")
                if _CONDITION_PATTERN.fullmatch(condition_id) is None:
                    raise ValueError("invalid condition ID")
                target_rows.append((row, slug, condition_id))
            except (TypeError, ValueError):
                rejected_count += 1

        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise IncompleteWalletWindowError("time_budget_exhausted")
        try:
            verified_markets = await asyncio.wait_for(
                self._verified_markets(
                    {(slug, condition_id) for _, slug, condition_id in target_rows},
                    purpose=purpose,
                ),
                timeout=remaining,
            )
        except TimeoutError as error:
            raise IncompleteWalletWindowError("time_budget_exhausted") from error
        for row, slug, condition_id in target_rows:
            try:
                market = verified_markets[(slug, condition_id)]
                normalized.append(
                    _normalize_trade(
                        row,
                        expected_wallet=wallet,
                        leader_id=leader_id,
                        observed_at=observed_at,
                        market=market,
                    )
                )
            except (
                KeyError, TypeError, ValueError, PolymarketCopyTradingSourceError
            ):
                rejected_count += 1

        events, duplicate_count = deduplicate_leader_trade_events(normalized)
        if time.monotonic() >= deadline_monotonic:
            raise IncompleteWalletWindowError("time_budget_exhausted")
        return LeaderTradeReadPage(
            events=events,
            next_checkpoint=None,
            raw_count=len(rows),
            filtered_count=filtered_count,
            rejected_count=rejected_count,
            duplicate_count=duplicate_count,
        )

    def _capture_pending_page(
        self, rows: list[dict[str, Any]], *, expected_wallet: str
    ) -> None:
        if self._pending_observer is None:
            return
        identities: list[str] = []
        for row in rows:
            try:
                if _required_string(row, "proxyWallet").casefold() != expected_wallet.casefold():
                    continue
                identities.append(_trade_event_id(row))
            except (TypeError, ValueError):
                continue
        if identities:
            self._pending_observer(tuple(identities), self._utc_now())

    async def probe_source_coverage(
        self,
        leader_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        page_limit: int = 500,
    ) -> PolymarketSourceCoverage:
        """Compare bounded official read surfaces without exposing source identity."""

        wallet = self._leader_wallet(leader_id)
        _require_utc_window(start_at, end_at)
        if not 1 <= page_limit <= 500:
            raise ValueError("page_limit must be within [1, 500]")
        common: dict[str, str | int | bool] = {
            "user": wallet,
            "start": int(start_at.timestamp()),
            "end": int(end_at.timestamp()),
            "limit": page_limit,
        }
        all_trades, taker_trades, activity, positions, closed = await asyncio.gather(
            fetch_data_api_v2_window(
                self._transport,
                DATA_API_V2_TRADES_PATH,
                {**common, "taker_only": False},
                purpose=LeaderReadPurpose.BASELINE,
            ),
            fetch_data_api_v2_window(
                self._transport,
                DATA_API_V2_TRADES_PATH,
                {**common, "taker_only": True},
                purpose=LeaderReadPurpose.BASELINE,
            ),
            fetch_data_api_v2_window(
                self._transport,
                DATA_API_V2_ACTIVITY_PATH,
                {
                    **common,
                    "type": "TRADE",
                    "sort_by": "TIMESTAMP",
                    "sort_direction": "ASC",
                },
                purpose=LeaderReadPurpose.BASELINE,
            ),
            self._transport.get_json(
                DATA_API_BASE_URL,
                "/positions",
                {
                    "user": wallet,
                    "sizeThreshold": 0,
                    "limit": page_limit,
                    "offset": 0,
                },
                purpose=LeaderReadPurpose.BASELINE,
            ),
            self._transport.get_json(
                DATA_API_BASE_URL,
                "/closed-positions",
                {
                    "user": wallet,
                    "limit": min(page_limit, 50),
                    "offset": 0,
                    "sortBy": "TIMESTAMP",
                    "sortDirection": "DESC",
                },
                purpose=LeaderReadPurpose.BASELINE,
            ),
        )
        all_rows = all_trades
        taker_rows = taker_trades
        activity_rows = activity
        position_rows = _require_object_list(positions, source="/positions")
        closed_rows = _require_object_list(closed, source="/closed-positions")
        visible_sizes = [
            _positive_decimal(row.get("size"), name="position size")
            for row in position_rows
            if row.get("size") is not None
        ]
        return PolymarketSourceCoverage(
            all_trade_count=len(all_rows),
            taker_trade_count=len(taker_rows),
            activity_trade_count=len(activity_rows),
            current_position_count=len(position_rows),
            closed_position_count=len(closed_rows),
            smallest_visible_position=min(visible_sizes, default=None),
            page_limit=page_limit,
        )

    async def read_inventory(self, leader_id: str) -> LeaderInventorySnapshot:
        """Read a complete sizeThreshold=0 public position baseline."""

        wallet = self._leader_wallet(leader_id)
        positions: dict[tuple[str, str], Decimal] = {}
        page_size = POSITION_PAGE_SIZE
        maximum_pages = POSITION_MAX_OFFSET // page_size + 1
        for page_number in range(maximum_pages):
            payload = await self._transport.get_json(
                DATA_API_BASE_URL,
                "/positions",
                {
                    "user": wallet,
                    "sizeThreshold": 0,
                    "limit": page_size,
                    "offset": page_number * page_size,
                },
                purpose=LeaderReadPurpose.BASELINE,
            )
            rows = _require_object_list(payload, source="/positions")
            for row in rows:
                condition_id = _required_string(row, "conditionId")
                token_id = _required_string(row, "asset")
                if _CONDITION_PATTERN.fullmatch(condition_id) is None:
                    raise PolymarketCopyTradingSourceError(
                        "Position baseline contained an invalid market reference."
                    )
                size = _non_negative_decimal(row.get("size"), name="position size")
                positions[(condition_id, token_id)] = size
            if len(rows) < page_size:
                break
        else:
            raise PolymarketCopyTradingSourceError(
                "Position baseline exceeded the bounded pagination limit."
            )

        observed_at = self._utc_now()
        evidence = [
            [market_reference, outcome_reference, str(size)]
            for (market_reference, outcome_reference), size in sorted(positions.items())
        ]
        digest = hashlib.sha256(json.dumps(evidence, separators=(",", ":")).encode()).hexdigest()
        return LeaderInventorySnapshot(
            leader_id=leader_id,
            positions=positions,
            observed_at=observed_at,
            evidence_digest=f"sha256:{digest}",
        )

    def market_metadata(
        self,
        market_reference: str,
        outcome_reference: str,
    ) -> LeaderMarketMetadata:
        try:
            market = self._market_by_condition[market_reference]
            outcome = market.outcomes_by_token[outcome_reference]
        except KeyError as error:
            raise PolymarketCopyTradingSourceError(
                "Verified market metadata is unavailable for the event."
            ) from error
        return LeaderMarketMetadata(
            market_reference=market.condition_id,
            outcome_reference=outcome_reference,
            external_slug=market.slug,
            outcome_label=outcome,
            starts_at=market.starts_at,
            ends_at=market.ends_at,
        )

    def request_telemetry(self) -> dict[str, object]:
        reader = getattr(self._transport, "request_telemetry", None)
        if callable(reader):
            return dict(reader())
        return {}

    def trades_circuit(self) -> dict[str, object]:
        reader = getattr(self._transport, "trades_circuit", None)
        if callable(reader):
            return dict(reader())
        return {"open": False}

    async def restore_trades_circuit(
        self,
        *,
        outage_started_at: datetime,
        retry_at: datetime,
        cooldown_attempt: int,
    ) -> None:
        restorer = getattr(self._transport, "restore_trades_circuit", None)
        if callable(restorer):
            await restorer(
                outage_started_at=outage_started_at,
                retry_at=retry_at,
                cooldown_attempt=cooldown_attempt,
            )

    def _leader_wallet(self, leader_id: str) -> str:
        try:
            return self._leaders[leader_id]
        except KeyError as error:
            raise ValueError("Unknown approved leader alias.") from error

    def _utc_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("clock must return timezone-aware UTC")
        return value

    async def _verified_event_markets(
        self,
        slug: str,
        *,
        purpose: LeaderReadPurpose,
    ) -> dict[str, _VerifiedMarket]:
        cached = self._market_cache.get(slug)
        if cached is not None:
            return cached
        payload = await self._transport.get_json(
            GAMMA_API_BASE_URL,
            "/events",
            {"slug": slug},
            purpose=purpose,
        )
        events = _require_object_list(payload, source="/events")
        if len(events) != 1 or events[0].get("slug") != slug:
            raise PolymarketCopyTradingSourceError("Market event metadata was not unique.")
        markets = _require_object_list(events[0].get("markets"), source="event markets")
        if not markets:
            raise PolymarketCopyTradingSourceError("Market event contained no markets.")
        verified_by_condition: dict[str, _VerifiedMarket] = {}
        for raw_market in markets:
            condition_id = _required_string(raw_market, "conditionId")
            if _CONDITION_PATTERN.fullmatch(condition_id) is None:
                raise ValueError("invalid condition ID")
            outcomes = _string_list(raw_market.get("outcomes"), name="outcomes")
            token_ids = _string_list(raw_market.get("clobTokenIds"), name="clobTokenIds")
            if not outcomes or len(token_ids) != len(outcomes):
                raise ValueError("market outcomes and token IDs are inconsistent")
            starts_at = _parse_utc_datetime(
                raw_market.get("eventStartTime") or raw_market.get("startDate"),
                name="market start time",
            )
            ends_at = _parse_utc_datetime(raw_market.get("endDate"), name="endDate")
            if ends_at <= starts_at:
                raise ValueError("market end time must follow its start time")
            btc_match = _BTC_15M_SLUG_PATTERN.fullmatch(slug)
            if btc_match is not None:
                slug_start = datetime.fromtimestamp(int(btc_match.group("start")), tz=UTC)
                if outcomes != ["Up", "Down"]:
                    raise ValueError("unexpected BTC 15-minute outcomes")
                if abs((starts_at - slug_start).total_seconds()) > 1:
                    raise ValueError("BTC 15-minute event start time does not match its slug")
                expected_end = slug_start + timedelta(minutes=15)
                if abs((ends_at - expected_end).total_seconds()) > 1:
                    raise ValueError("BTC 15-minute metadata end time does not match its slug")
            if condition_id in verified_by_condition:
                raise ValueError("duplicate condition ID in event metadata")
            verified = _VerifiedMarket(
                slug=slug,
                condition_id=condition_id,
                outcomes_by_token=dict(zip(token_ids, outcomes, strict=True)),
                starts_at=starts_at,
                ends_at=ends_at,
            )
            verified_by_condition[condition_id] = verified
            self._market_by_condition[condition_id] = verified
        self._market_cache[slug] = verified_by_condition
        return verified_by_condition

    async def _verified_markets(
        self,
        market_keys: set[tuple[str, str]],
        *,
        purpose: LeaderReadPurpose,
    ) -> dict[tuple[str, str], _VerifiedMarket]:
        semaphore = asyncio.Semaphore(5)

        async def load(slug: str) -> tuple[str, dict[str, _VerifiedMarket] | None]:
            try:
                async with semaphore:
                    return slug, await self._verified_event_markets(
                        slug,
                        purpose=purpose,
                    )
            except (TypeError, ValueError, PolymarketCopyTradingSourceError):
                return slug, None

        slugs = {slug for slug, _ in market_keys}
        results = await asyncio.gather(*(load(slug) for slug in sorted(slugs)))
        by_slug = {slug: markets for slug, markets in results if markets is not None}
        return {
            (slug, condition_id): by_slug[slug][condition_id]
            for slug, condition_id in market_keys
            if slug in by_slug and condition_id in by_slug[slug]
        }


def _normalize_trade(
    row: Mapping[str, Any],
    *,
    expected_wallet: str,
    leader_id: str,
    observed_at: datetime,
    market: _VerifiedMarket,
) -> LeaderTradeEvent:
    wallet = _required_string(row, "proxyWallet")
    if wallet.casefold() != expected_wallet.casefold():
        raise ValueError("trade wallet does not match configured leader")
    condition_id = _required_string(row, "conditionId")
    token_id = _required_string(row, "asset")
    outcome = _required_string(row, "outcome")
    slug = _required_string(row, "eventSlug")
    transaction_hash = _required_string(row, "transactionHash")
    if condition_id != market.condition_id or slug != market.slug:
        raise ValueError("trade market identifiers do not match verified metadata")
    if market.outcomes_by_token.get(token_id) != outcome:
        raise ValueError("trade token does not match verified outcome metadata")
    if _TRANSACTION_PATTERN.fullmatch(transaction_hash) is None:
        raise ValueError("invalid transaction hash")

    action = LeaderTradeAction(_required_string(row, "side"))
    price = _positive_decimal(row.get("price"), name="price")
    size = _positive_decimal(row.get("size"), name="size")
    timestamp = row.get("timestamp")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        raise ValueError("timestamp must be epoch seconds")
    executed_at = datetime.fromtimestamp(timestamp, tz=UTC)

    event_id = _trade_event_id(row)
    evidence_reference = (
        "sha256:" + hashlib.sha256(transaction_hash.casefold().encode()).hexdigest()
    )

    return LeaderTradeEvent(
        event_id=event_id,
        source_id=SOURCE_ID,
        leader_id=leader_id,
        market_reference=condition_id,
        outcome_reference=token_id,
        trade_action=action,
        position_effect=LeaderPositionEffect.UNKNOWN,
        executed_price=price,
        executed_size=size,
        executed_at=executed_at,
        observed_at=observed_at,
        external_evidence_reference=evidence_reference,
    )


def _trade_event_id(row: Mapping[str, Any]) -> str:
    wallet = _required_string(row, "proxyWallet")
    condition_id = _required_string(row, "conditionId")
    token_id = _required_string(row, "asset")
    transaction_hash = _required_string(row, "transactionHash")
    if _TRANSACTION_PATTERN.fullmatch(transaction_hash) is None:
        raise ValueError("invalid transaction hash")
    action = LeaderTradeAction(_required_string(row, "side"))
    price = _positive_decimal(row.get("price"), name="price")
    size = _positive_decimal(row.get("size"), name="size")
    timestamp = row.get("timestamp")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        raise ValueError("timestamp must be epoch seconds")
    event_components = {
        "asset": token_id,
        "condition_id": condition_id.casefold(),
        "price": str(price),
        "side": action.value,
        "size": str(size),
        "timestamp": timestamp,
        "transaction_hash": transaction_hash.casefold(),
        "wallet": wallet.casefold(),
    }
    return hashlib.sha256(
        json.dumps(event_components, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _validated_leaders(leaders: Mapping[str, str]) -> dict[str, str]:
    if not leaders:
        raise ValueError("at least one approved leader alias is required")
    validated: dict[str, str] = {}
    for alias, wallet in leaders.items():
        if _SAFE_ALIAS_PATTERN.fullmatch(alias) is None:
            raise ValueError("leader alias contains unsupported characters")
        if _WALLET_PATTERN.fullmatch(wallet) is None:
            raise ValueError("leader source reference is not a valid wallet address")
        validated[alias] = wallet
    return validated


def _require_object_list(value: Any, *, source: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise PolymarketCopyTradingSourceError(f"{source} returned an invalid payload.")
    return value


def _required_string(row: Mapping[str, Any], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _positive_decimal(value: Any, *, name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{name} must be numeric") from error
    if not result.is_finite() or result <= Decimal("0"):
        raise ValueError(f"{name} must be positive")
    return result


def _non_negative_decimal(value: Any, *, name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{name} must be numeric") from error
    if not result.is_finite() or result < Decimal("0"):
        raise ValueError(f"{name} must not be negative")
    return result


def _string_list(value: Any, *, name: str) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"{name} must contain a JSON string list") from error
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a string list")
    return value


def _parse_utc_datetime(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{name} must be an ISO timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _require_utc_window(start_at: datetime, end_at: datetime) -> None:
    for name, value in (("start_at", start_at), ("end_at", end_at)):
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError(f"{name} must be timezone-aware UTC")
    if start_at >= end_at:
        raise ValueError("start_at must precede end_at")


def _stringify_params(
    params: Mapping[str, str | int | bool],
) -> dict[str, str | int]:
    return {
        key: ("true" if value else "false") if isinstance(value, bool) else value
        for key, value in params.items()
    }


def _is_trades_path(path: str) -> bool:
    return path == "/trades" or path == "/v2/trades"
