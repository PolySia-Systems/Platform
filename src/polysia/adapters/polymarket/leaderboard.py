"""Bounded public board and wallet reads. No authenticated transport."""

from __future__ import annotations

import json
import random
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from polysia.adapters.polymarket.data_api_v2 import DATA_API_BASE_URL
from polysia.domain.leaderboard import Activity, Board, Observation, Standing

WALLET = re.compile(r"0x[0-9a-fA-F]{40}")
BOARD_PAGE_SIZE = 100
MAX_REQUESTS_PER_RUN = 100
_BODY_CAP = 2 * 1024 * 1024
_ALLOWED = frozenset({"/v2/leaderboard", "/v2/status", "/v2/trades"})


class ReadFailure(ValueError):
    """A sanitized reason suitable for the retained attempt record."""

    def __init__(self, reason: str, retry_at: datetime | None = None) -> None:
        super().__init__(reason)
        self.retry_at = retry_at


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: object, code: int, msg: str, headers: object, newurl: str
    ) -> None:
        return None


class PublicReads:
    """One serial acquisition budget shared across all boards and enrichments."""

    def __init__(
        self,
        *,
        max_requests: int = MAX_REQUESTS_PER_RUN,
        max_bytes: int = 50 * 1024 * 1024,
        seconds: float = 600,
        sleep: Callable[[float], None] = time.sleep,
        on_rate_limit: Callable[[datetime], None] | None = None,
    ) -> None:
        self.requests = 0
        self.bytes = 0
        self._max_requests = max_requests
        self._max_bytes = max_bytes
        self._deadline = time.monotonic() + seconds
        self._open = build_opener(_NoRedirect()).open
        self._sleep = sleep
        self._on_rate_limit = on_rate_limit
        self.deferred_until: datetime | None = None

    def get(self, path: str, params: dict[str, str | int]) -> object:
        if path not in _ALLOWED:
            raise ReadFailure("endpoint_not_allowed")
        if self.deferred_until is not None:
            raise ReadFailure("http_429", self.deferred_until)
        url = DATA_API_BASE_URL + path
        if params:
            url += "?" + urlencode(params)
        request = Request(
            url, headers={"Accept": "application/json", "User-Agent": "PolySia-read-only-research"}
        )
        for attempt in range(3):
            elapsed_left = self._deadline - time.monotonic()
            byte_limit = min(_BODY_CAP, self._max_bytes - self.bytes)
            if self.requests >= self._max_requests or elapsed_left <= 0 or byte_limit <= 0:
                raise ReadFailure("budget_exhausted")
            self.requests += 1
            wait = 2**attempt + random.uniform(0, 0.5)
            retry_at = None
            try:
                with self._open(request, timeout=min(20, elapsed_left)) as response:
                    payload = response.read(byte_limit + 1)
                self.bytes += len(payload)
                if len(payload) > byte_limit:
                    raise ReadFailure("response_size_limit")
                if time.monotonic() >= self._deadline:
                    raise ReadFailure("budget_exhausted")
                try:
                    return json.loads(payload, parse_float=Decimal)
                except (ValueError, UnicodeError) as error:
                    raise ReadFailure("invalid_json") from error
            except HTTPError as error:
                reason = f"http_{error.code}"
                retry_after = error.headers.get("Retry-After")
                error.close()
                if error.code != 429 and not 500 <= error.code <= 599:
                    raise ReadFailure(reason) from None
                if retry_after:
                    observed_at = datetime.now(UTC)
                    retry_at = _retry_deadline(retry_after, observed_at)
                    if retry_at is not None:
                        wait = max(wait, (retry_at - observed_at).total_seconds())
            except OSError, HTTPException:
                reason = "network_unavailable"
            if (
                attempt == 2
                or wait > 20
                or time.monotonic() + wait >= self._deadline
                or self.requests >= self._max_requests
            ):
                if reason == "http_429":
                    minimum = datetime.now(UTC) + timedelta(minutes=15)
                    self.deferred_until = max(minimum, retry_at or minimum)
                    if self._on_rate_limit is not None:
                        self._on_rate_limit(self.deferred_until)
                raise ReadFailure(reason, retry_at)
            self._sleep(wait)
        raise AssertionError("retry loop did not return or raise")


def _retry_deadline(value: str, now: datetime) -> datetime | None:
    try:
        if value.isascii() and value.isdigit():
            # Saturate out-of-range delays without retrying earlier than requested.
            maximum = datetime.max.replace(tzinfo=UTC)
            if len(value.lstrip("0")) > 12:
                return maximum
            seconds = int(value.lstrip("0") or "0")
            if seconds >= (maximum - now).total_seconds():
                return maximum
            return now + timedelta(seconds=seconds)
        stamp = parsedate_to_datetime(value)
        return stamp.astimezone(UTC) if stamp.tzinfo is not None else None
    except ValueError, TypeError, OverflowError:
        return None


def page_payload(payload: object) -> tuple[list[object], str | None]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ReadFailure("invalid_data_envelope")
    pagination = payload.get("pagination")
    if not isinstance(pagination, dict) or type(pagination.get("has_more")) is not bool:
        raise ReadFailure("invalid_pagination")
    cursor = pagination.get("next_cursor")
    if pagination["has_more"]:
        if not isinstance(cursor, str) or not 0 < len(cursor) <= 2048:
            raise ReadFailure("invalid_cursor")
    elif cursor is not None:
        raise ReadFailure("invalid_terminal_cursor")
    rows: list[object] = payload["data"]
    return rows, cursor


def monetary(value: object) -> Decimal:
    if type(value) not in (int, Decimal, str) or len(str(value)) > 128:
        raise ReadFailure("invalid_amount")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ReadFailure("invalid_amount") from None
    if not number.is_finite() or abs(number.adjusted()) > 100:
        raise ReadFailure("invalid_amount")
    return number if number else Decimal(0)


def standing(row: object) -> Standing:
    if not isinstance(row, dict):
        raise ReadFailure("invalid_row")
    wallet, rank = row.get("user_id"), row.get("rank")
    if not isinstance(wallet, str) or not WALLET.fullmatch(wallet):
        raise ReadFailure("invalid_wallet")
    if type(rank) is not int or not 1 <= rank <= 1_000_000_000:
        raise ReadFailure("invalid_rank")
    name = row.get("user_name")
    volume = monetary(row.get("volume"))
    if volume < 0:
        raise ReadFailure("invalid_volume")
    return Standing(
        wallet.lower(),
        name[:160] if isinstance(name, str) and name.strip() else None,
        rank,
        monetary(row.get("pnl")),
        volume,
    )


def board_observation(
    board: Board, reads: PublicReads, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
) -> Observation:
    started, requests, byte_count = clock(), reads.requests, reads.bytes
    params: dict[str, str | int] = {
        "time_period": board.period,
        "sort_by": board.ranking,
        "category": board.category,
        "limit": BOARD_PAGE_SIZE,
    }
    rows: list[Standing] = []
    wallets: set[str] = set()
    seen_cursors: set[str] = set()
    cursor: str | None = None
    try:
        while True:
            payload = reads.get(
                "/v2/leaderboard", params if not cursor else {**params, "cursor": cursor}
            )
            page, cursor = page_payload(payload)
            if len(page) > BOARD_PAGE_SIZE or cursor and (not page or cursor in seen_cursors):
                raise ReadFailure("invalid_page_or_repeated_cursor")
            mapped = [standing(row) for row in page]
            ids = {row.wallet for row in mapped}
            if len(ids) != len(mapped) or ids & wallets:
                raise ReadFailure("duplicate_wallet")
            ranks = [row.rank for row in mapped]
            if ranks != sorted(ranks) or (rows and ranks and ranks[0] < rows[-1].rank):
                raise ReadFailure("rank_order_changed")
            wallets.update(ids)
            rows.extend(mapped)
            if not cursor or len(rows) >= board.depth:
                break
            seen_cursors.add(cursor)
            if len(seen_cursors) >= (board.depth // BOARD_PAGE_SIZE) + 2:
                raise ReadFailure("page_budget_exhausted")
    except ReadFailure as error:
        return Observation(
            board,
            tuple(rows),
            started,
            clock(),
            "partial" if rows else "failed",
            str(error),
            None,
            reads.requests - requests,
            reads.bytes - byte_count,
            error.retry_at,
        )
    ordered = tuple(sorted(rows, key=lambda row: (row.rank, row.wallet))[: board.depth])
    return Observation(
        board,
        ordered,
        started,
        clock(),
        "complete",
        None,
        bool(cursor) or len(rows) > board.depth,
        reads.requests - requests,
        reads.bytes - byte_count,
    )


def source_health(reads: PublicReads) -> datetime | None:
    try:
        payload = reads.get("/v2/status", {})
        data = payload.get("data") if isinstance(payload, dict) else None
        value = data.get("computed_at") if isinstance(data, dict) else None
        if isinstance(value, str):
            timestamp = datetime.fromisoformat(value)
            if timestamp.tzinfo is not None and timestamp <= datetime.now(UTC):
                return timestamp.astimezone(UTC)
    except ReadFailure, ValueError:
        pass
    return None


def wallet_activity(wallet: str, reads: PublicReads, since: int, through: int) -> Activity:
    """Count official returned trade records in a frozen window."""
    if not WALLET.fullmatch(wallet):
        raise ReadFailure("invalid_wallet")
    params: dict[str, str | int] = {"user": wallet, "start": since, "end": through, "limit": 100}
    count = 0
    markets: set[str] = set()
    latest: int | None = None
    cursors: set[str] = set()
    for _ in range(3):
        try:
            page, cursor = page_payload(reads.get("/v2/trades", params))
            if len(page) > 100 or cursor and (not page or cursor in cursors):
                raise ReadFailure("invalid_activity_page")
            validated: list[tuple[int, str]] = []
            for item in page:
                if not isinstance(item, dict):
                    raise ReadFailure("invalid_trade")
                timestamp, market = item.get("timestamp"), item.get("condition_id")
                if (
                    type(timestamp) is not int
                    or not since <= timestamp <= through
                    or not isinstance(market, str)
                    or not 0 < len(market) <= 128
                    or str(item.get("proxy_wallet", "")).lower() != wallet
                ):
                    raise ReadFailure("invalid_trade_scope")
                validated.append((timestamp, market))
        except ReadFailure:
            break
        count += len(validated)
        for timestamp, market in validated:
            latest = max(timestamp, latest or 0)
            markets.add(market)
        if cursor is None:
            return Activity(wallet, since, through, latest, count, len(markets), True)
        cursors.add(cursor)
        params["cursor"] = cursor
    return Activity(wallet, since, through, latest, count, len(markets), False)
