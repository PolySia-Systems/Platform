from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from polysia.application.ports.copytrading import (
    LeaderInventorySnapshot,
    LeaderMarketMetadata,
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
SOURCE_ID = "polymarket:data-api"

Clock = Callable[[], datetime]


class PolymarketCopyTradingSourceError(RuntimeError):
    """Safe Stage 1 source failure with no raw wallet or response content."""


class JsonGetTransport(Protocol):
    async def get_json(
        self,
        base_url: str,
        path: str,
        params: Mapping[str, str | int | bool],
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
class _VerifiedBtc15Market:
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
        rate_limit_requests: int = 140,
        rate_limit_window_seconds: float = 10,
    ) -> None:
        if not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts must be within [1, 3]")
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be within [1, 30]")
        if not 0 <= backoff_seconds <= 2:
            raise ValueError("backoff_seconds must be within [0, 2]")
        if not 1024 <= max_response_bytes <= 10_000_000:
            raise ValueError("max_response_bytes must be within [1024, 10000000]")
        if not 1 <= rate_limit_requests <= 140:
            raise ValueError("rate_limit_requests must be within [1, 140]")
        if not 1 <= rate_limit_window_seconds <= 60:
            raise ValueError("rate_limit_window_seconds must be within [1, 60]")
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._max_response_bytes = max_response_bytes
        self._rate_limit_requests = rate_limit_requests
        self._rate_limit_window_seconds = rate_limit_window_seconds
        self._rate_lock = asyncio.Lock()
        self._request_times: deque[float] = deque()

    async def get_json(
        self,
        base_url: str,
        path: str,
        params: Mapping[str, str | int | bool],
    ) -> Any:
        if base_url not in {DATA_API_BASE_URL, GAMMA_API_BASE_URL}:
            raise PolymarketCopyTradingSourceError("Unapproved public API base URL.")
        if not path.startswith("/") or "://" in path:
            raise PolymarketCopyTradingSourceError("Invalid public API path.")

        url = f"{base_url}{path}?{urlencode(_stringify_params(params))}"
        for attempt in range(1, self._max_attempts + 1):
            await self._wait_for_rate_slot()
            try:
                return await asyncio.to_thread(self._read_json, url)
            except HTTPError as error:
                retryable = error.code == 429 or error.code >= 500
                if not retryable or attempt >= self._max_attempts:
                    raise PolymarketCopyTradingSourceError(
                        f"Public API returned HTTP {error.code}."
                    ) from error
            except (TimeoutError, URLError) as error:
                if attempt >= self._max_attempts:
                    raise PolymarketCopyTradingSourceError(
                        "Public API read failed after bounded retry."
                    ) from error
            await asyncio.sleep(self._backoff_seconds * attempt)

        raise AssertionError("bounded public read retry loop exhausted unexpectedly")

    async def _wait_for_rate_slot(self) -> None:
        async with self._rate_lock:
            loop = asyncio.get_running_loop()
            while True:
                now = loop.time()
                cutoff = now - self._rate_limit_window_seconds
                while self._request_times and self._request_times[0] <= cutoff:
                    self._request_times.popleft()
                if len(self._request_times) < self._rate_limit_requests:
                    self._request_times.append(now)
                    return
                await asyncio.sleep(
                    max(
                        0,
                        self._request_times[0]
                        + self._rate_limit_window_seconds
                        - now,
                    )
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
            raise PolymarketCopyTradingSourceError(
                "Public API returned invalid JSON."
            ) from error


class PolymarketCopyTradingSource:
    """Read-only Stage 1 adapter for confirmed public leader executions."""

    def __init__(
        self,
        leaders: Mapping[str, str],
        *,
        transport: JsonGetTransport | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._leaders = _validated_leaders(leaders)
        self._transport = transport or UrllibJsonGetTransport()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._market_cache: dict[str, _VerifiedBtc15Market] = {}
        self._market_by_condition: dict[str, _VerifiedBtc15Market] = {}

    async def read_page(
        self,
        leader_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        page_size: int = 100,
        checkpoint: LeaderTradeCheckpoint | None = None,
    ) -> LeaderTradeReadPage:
        wallet = self._leader_wallet(leader_id)
        _require_utc_window(start_at, end_at)
        if not 1 <= page_size <= 500:
            raise ValueError("page_size must be within [1, 500]")

        offset = 0
        frozen_start = int(start_at.timestamp())
        frozen_end = int(end_at.timestamp())
        if checkpoint is not None:
            frozen_start, frozen_end, offset = _decode_checkpoint(
                checkpoint,
                leader_id=leader_id,
            )

        payload = await self._transport.get_json(
            DATA_API_BASE_URL,
            "/trades",
            {
                "user": wallet,
                "takerOnly": False,
                "start": frozen_start,
                "end": frozen_end,
                "limit": page_size,
                "offset": offset,
            },
        )
        rows = _require_object_list(payload, source="/trades")
        observed_at = self._utc_now()
        normalized: list[LeaderTradeEvent] = []
        filtered_count = 0
        rejected_count = 0
        target_rows: list[tuple[dict[str, Any], str]] = []

        for row in rows:
            try:
                slug = _required_string(row, "eventSlug")
                if _BTC_15M_SLUG_PATTERN.fullmatch(slug) is None:
                    filtered_count += 1
                    continue
                target_rows.append((row, slug))
            except (TypeError, ValueError):
                rejected_count += 1

        verified_markets = await self._verified_markets(
            {slug for _, slug in target_rows}
        )
        for row, slug in target_rows:
            try:
                market = verified_markets[slug]
                normalized.append(
                    _normalize_trade(
                        row,
                        expected_wallet=wallet,
                        leader_id=leader_id,
                        observed_at=observed_at,
                        market=market,
                    )
                )
            except (KeyError, TypeError, ValueError, PolymarketCopyTradingSourceError):
                rejected_count += 1

        events, duplicate_count = deduplicate_leader_trade_events(normalized)
        next_checkpoint = None
        if len(rows) == page_size:
            next_checkpoint = _encode_checkpoint(
                leader_id=leader_id,
                start_epoch=frozen_start,
                end_epoch=frozen_end,
                offset=offset + page_size,
            )

        return LeaderTradeReadPage(
            events=events,
            next_checkpoint=next_checkpoint,
            raw_count=len(rows),
            filtered_count=filtered_count,
            rejected_count=rejected_count,
            duplicate_count=duplicate_count,
        )

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
            "offset": 0,
        }
        all_trades, taker_trades, activity, positions, closed = await asyncio.gather(
            self._transport.get_json(
                DATA_API_BASE_URL,
                "/trades",
                {**common, "takerOnly": False},
            ),
            self._transport.get_json(
                DATA_API_BASE_URL,
                "/trades",
                {**common, "takerOnly": True},
            ),
            self._transport.get_json(
                DATA_API_BASE_URL,
                "/activity",
                {
                    **common,
                    "type": "TRADE",
                    "sortBy": "TIMESTAMP",
                    "sortDirection": "ASC",
                },
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
            ),
        )
        all_rows = _require_object_list(all_trades, source="/trades")
        taker_rows = _require_object_list(taker_trades, source="/trades")
        activity_rows = _require_object_list(activity, source="/activity")
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
        page_size = 500
        for page_number in range(5):
            payload = await self._transport.get_json(
                DATA_API_BASE_URL,
                "/positions",
                {
                    "user": wallet,
                    "sizeThreshold": 0,
                    "limit": page_size,
                    "offset": page_number * page_size,
                },
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
        digest = hashlib.sha256(
            json.dumps(evidence, separators=(",", ":")).encode()
        ).hexdigest()
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

    async def _verified_btc_15m_market(self, slug: str) -> _VerifiedBtc15Market:
        cached = self._market_cache.get(slug)
        if cached is not None:
            return cached
        match = _BTC_15M_SLUG_PATTERN.fullmatch(slug)
        if match is None:
            raise ValueError("trade is not a strict BTC Up/Down 15-minute market")
        payload = await self._transport.get_json(
            GAMMA_API_BASE_URL,
            "/events",
            {"slug": slug},
        )
        events = _require_object_list(payload, source="/events")
        if len(events) != 1 or events[0].get("slug") != slug:
            raise PolymarketCopyTradingSourceError(
                "BTC 15-minute market metadata was not unique."
            )
        markets = _require_object_list(events[0].get("markets"), source="event markets")
        if len(markets) != 1:
            raise PolymarketCopyTradingSourceError(
                "BTC 15-minute event did not contain exactly one market."
            )
        raw_market = markets[0]
        condition_id = _required_string(raw_market, "conditionId")
        if _CONDITION_PATTERN.fullmatch(condition_id) is None:
            raise ValueError("invalid condition ID")
        outcomes = _string_list(raw_market.get("outcomes"), name="outcomes")
        token_ids = _string_list(raw_market.get("clobTokenIds"), name="clobTokenIds")
        if outcomes != ["Up", "Down"] or len(token_ids) != len(outcomes):
            raise ValueError("unexpected BTC 15-minute outcomes")
        starts_at = datetime.fromtimestamp(int(match.group("start")), tz=UTC)
        ends_at = _parse_utc_datetime(raw_market.get("endDate"), name="endDate")
        if abs((ends_at - (starts_at + timedelta(minutes=15))).total_seconds()) > 1:
            raise ValueError("BTC 15-minute metadata end time does not match its slug")
        verified = _VerifiedBtc15Market(
            slug=slug,
            condition_id=condition_id,
            outcomes_by_token=dict(zip(token_ids, outcomes, strict=True)),
            starts_at=starts_at,
            ends_at=ends_at,
        )
        self._market_cache[slug] = verified
        self._market_by_condition[condition_id] = verified
        return verified

    async def _verified_markets(
        self,
        slugs: set[str],
    ) -> dict[str, _VerifiedBtc15Market]:
        semaphore = asyncio.Semaphore(5)

        async def load(slug: str) -> tuple[str, _VerifiedBtc15Market | None]:
            try:
                async with semaphore:
                    return slug, await self._verified_btc_15m_market(slug)
            except (TypeError, ValueError, PolymarketCopyTradingSourceError):
                return slug, None

        results = await asyncio.gather(*(load(slug) for slug in sorted(slugs)))
        return {slug: market for slug, market in results if market is not None}


def _normalize_trade(
    row: Mapping[str, Any],
    *,
    expected_wallet: str,
    leader_id: str,
    observed_at: datetime,
    market: _VerifiedBtc15Market,
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
    event_id = hashlib.sha256(
        json.dumps(event_components, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    evidence_reference = "sha256:" + hashlib.sha256(
        transaction_hash.casefold().encode()
    ).hexdigest()

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


def _encode_checkpoint(
    *,
    leader_id: str,
    start_epoch: int,
    end_epoch: int,
    offset: int,
) -> LeaderTradeCheckpoint:
    alias_digest = hashlib.sha256(leader_id.encode()).hexdigest()[:16]
    return LeaderTradeCheckpoint(
        value=f"v1:{alias_digest}:{start_epoch}:{end_epoch}:{offset}"
    )


def _decode_checkpoint(
    checkpoint: LeaderTradeCheckpoint,
    *,
    leader_id: str,
) -> tuple[int, int, int]:
    parts = checkpoint.value.split(":")
    expected_alias_digest = hashlib.sha256(leader_id.encode()).hexdigest()[:16]
    if len(parts) != 5 or parts[0] != "v1" or parts[1] != expected_alias_digest:
        raise ValueError("checkpoint does not match the leader alias")
    try:
        start_epoch, end_epoch, offset = (int(value) for value in parts[2:])
    except ValueError as error:
        raise ValueError("checkpoint contains invalid numeric fields") from error
    if start_epoch < 0 or end_epoch <= start_epoch or not 0 <= offset <= 10_000:
        raise ValueError("checkpoint is outside supported bounds")
    return start_epoch, end_epoch, offset


def _stringify_params(
    params: Mapping[str, str | int | bool],
) -> dict[str, str | int]:
    return {
        key: ("true" if value else "false") if isinstance(value, bool) else value
        for key, value in params.items()
    }
