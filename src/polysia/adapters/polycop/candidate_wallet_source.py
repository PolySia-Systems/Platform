from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from polysia.application.ports.candidate_wallets import (
    CandidateSourceReadError,
    CandidateSourceSchemaError,
)
from polysia.domain.wallet_intelligence import (
    CandidateWalletDataset,
    CandidateWalletRecord,
    JsonValue,
)

POLYCOP_BASE_URL = "https://polycop.fun"
POLYCOP_LEADERBOARD_PATH = "/api/leaderboard"
SOURCE_ID = "polycop"
SCHEMA_VERSION = "polycop-leaderboard-v1"

_ENVELOPE_FIELDS = frozenset({"data", "page", "status", "total_pages"})
_ROW_FIELDS = frozenset(
    {
        "actual_pnl",
        "address",
        "all_pnl_json",
        "avg_invest",
        "avg_pnl_m",
        "avg_profit_loss_ratio",
        "buy_price",
        "copy_backtest_pnl",
        "copy_loss_rate",
        "daily_stats_json",
        "hedged",
        "hedged_pct",
        "hold_time",
        "last_2d",
        "last_active",
        "markets_traded",
        "r20_pnl",
        "r20_slip",
        "r20_wr",
        "roi",
        "score",
        "trading_days",
        "trading_volume",
        "win_rate",
    }
)
_DECIMAL_FIELDS = frozenset(
    {
        "actual_pnl",
        "avg_invest",
        "avg_pnl_m",
        "avg_profit_loss_ratio",
        "buy_price",
        "copy_backtest_pnl",
        "copy_loss_rate",
        "hedged_pct",
        "hold_time",
        "last_2d",
        "r20_pnl",
        "r20_slip",
        "r20_wr",
        "roi",
        "score",
        "trading_volume",
        "win_rate",
    }
)
_INTEGER_FIELDS = frozenset({"markets_traded", "trading_days"})
_EMBEDDED_JSON_FIELDS = frozenset({"all_pnl_json", "daily_stats_json"})
_WALLET_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")
_WALLET_SEARCH_PATTERN = re.compile(r"0x[a-fA-F0-9]{40}", re.IGNORECASE)

_MAX_TOTAL_PAGES = 1_000
_MAX_TOTAL_RECORDS = 200_000
_MAX_DATASET_BYTES = 64_000_000

Clock = Callable[[], datetime]
Sleeper = Callable[[float], Awaitable[None]]


class PolyCopSourceError(CandidateSourceReadError):
    """Safe read-only source failure that never includes wallet data."""


class PolyCopSnapshotUnstableError(PolyCopSourceError):
    """The offset-paginated source changed while a complete read was in progress."""

    error_code = "source_snapshot_unstable"


class PolyCopSchemaChangedError(CandidateSourceSchemaError):
    """The external response no longer matches the reviewed schema."""

    def __init__(self, reason_code: str, sample: object, schema_fingerprint: str) -> None:
        super().__init__(reason_code, sample, schema_fingerprint)


class JsonGetTransport(Protocol):
    async def get_json(self, path: str, params: Mapping[str, str | int]) -> Any: ...


class _RejectRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


class UrllibPolyCopTransport:
    """Bounded unauthenticated GET transport for the owner-approved PolyCop source."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 20,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        max_response_bytes: int = 12_000_000,
        sleeper: Sleeper = asyncio.sleep,
    ) -> None:
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be within [1, 30]")
        if not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts must be within [1, 3]")
        if not 0 <= backoff_seconds <= 2:
            raise ValueError("backoff_seconds must be within [0, 2]")
        if not 1_024 <= max_response_bytes <= 20_000_000:
            raise ValueError("max_response_bytes must be within [1024, 20000000]")
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._max_response_bytes = max_response_bytes
        self._sleeper = sleeper
        self._opener = build_opener(_RejectRedirectHandler())

    async def get_json(self, path: str, params: Mapping[str, str | int]) -> Any:
        if path != POLYCOP_LEADERBOARD_PATH:
            raise PolyCopSourceError("Unapproved PolyCop API path.")
        url = f"{POLYCOP_BASE_URL}{path}?{urlencode(params)}"
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await asyncio.to_thread(self._read_json, url)
            except HTTPError as error:
                retryable = error.code == 429 or error.code >= 500
                if not retryable or attempt == self._max_attempts:
                    raise PolyCopSourceError(
                        f"PolyCop returned HTTP {error.code} after a bounded read."
                    ) from error
                delay = _retry_delay(error, default=self._backoff_seconds * attempt)
            except (TimeoutError, URLError) as error:
                if attempt == self._max_attempts:
                    raise PolyCopSourceError(
                        "PolyCop read failed after bounded retries."
                    ) from error
                delay = self._backoff_seconds * attempt
            await self._sleeper(delay)
        raise AssertionError("bounded PolyCop retry loop exhausted unexpectedly")

    def _read_json(self, url: str) -> Any:
        request = Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "User-Agent": "PolySia/0.1 authorized read-only candidate ingestion",
            },
        )
        with self._opener.open(request, timeout=self._timeout_seconds) as response:
            payload = response.read(self._max_response_bytes + 1)
        if len(payload) > self._max_response_bytes:
            raise PolyCopSourceError("PolyCop response exceeded the configured size cap.")
        try:
            return json.loads(payload, parse_float=Decimal)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PolyCopSourceError("PolyCop returned invalid JSON.") from error


class PolyCopCandidateWalletSource:
    """Complete, read-only PolyCop leaderboard source with consistency checks."""

    def __init__(
        self,
        *,
        transport: JsonGetTransport | None = None,
        clock: Clock | None = None,
        page_delay_seconds: float = 0.1,
        consistency_attempts: int = 2,
        sleeper: Sleeper = asyncio.sleep,
    ) -> None:
        if not 0 <= page_delay_seconds <= 2:
            raise ValueError("page_delay_seconds must be within [0, 2]")
        if not 1 <= consistency_attempts <= 2:
            raise ValueError("consistency_attempts must be within [1, 2]")
        self._transport = transport or UrllibPolyCopTransport()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._page_delay_seconds = page_delay_seconds
        self._consistency_attempts = consistency_attempts
        self._sleeper = sleeper

    @property
    def source_id(self) -> str:
        return SOURCE_ID

    async def fetch_snapshot(self) -> CandidateWalletDataset:
        last_error: PolyCopSnapshotUnstableError | None = None
        for attempt in range(1, self._consistency_attempts + 1):
            try:
                return await self._fetch_once()
            except PolyCopSnapshotUnstableError as error:
                last_error = error
                if attempt < self._consistency_attempts:
                    await self._sleeper(self._page_delay_seconds)
        assert last_error is not None
        raise last_error

    async def _fetch_once(self) -> CandidateWalletDataset:
        first_payload = await self._read_page(1)
        total_pages, first_rows = _validate_page(first_payload, expected_page=1)
        if total_pages > _MAX_TOTAL_PAGES:
            raise PolyCopSourceError("PolyCop total_pages exceeded the safety cap.")
        if not first_rows:
            raise PolyCopSourceError("PolyCop returned an empty complete leaderboard.")

        first_digest = _digest_json(first_payload)
        records: list[CandidateWalletRecord] = []
        normalized_ids: set[str] = set()
        aggregate_bytes = _append_page(
            records,
            normalized_ids,
            first_rows,
            source_page=1,
            aggregate_bytes=0,
        )
        for page_number in range(2, total_pages + 1):
            if self._page_delay_seconds:
                await self._sleeper(self._page_delay_seconds)
            payload = await self._read_page(page_number)
            observed_total_pages, rows = _validate_page(payload, expected_page=page_number)
            if observed_total_pages != total_pages:
                raise PolyCopSnapshotUnstableError(
                    "PolyCop total_pages changed during the paginated read."
                )
            if not rows:
                raise PolyCopSnapshotUnstableError(
                    "PolyCop returned an empty page inside the advertised range."
                )
            aggregate_bytes = _append_page(
                records,
                normalized_ids,
                rows,
                source_page=page_number,
                aggregate_bytes=aggregate_bytes,
            )

        if self._page_delay_seconds:
            await self._sleeper(self._page_delay_seconds)
        guard_payload = await self._read_page(1)
        guard_total_pages, _ = _validate_page(guard_payload, expected_page=1)
        if guard_total_pages != total_pages or _digest_json(guard_payload) != first_digest:
            raise PolyCopSnapshotUnstableError(
                "PolyCop page 1 changed during the paginated read."
            )

        dataset_digest = hashlib.sha256(
            "\n".join(record.row_digest for record in records).encode("ascii")
        ).hexdigest()
        clock_value = self._clock()
        if clock_value.tzinfo is None or clock_value.utcoffset() is None:
            raise PolyCopSourceError("PolyCop adapter clock must be timezone-aware.")
        fetched_at = clock_value.astimezone(UTC)
        return CandidateWalletDataset(
            source_id=SOURCE_ID,
            schema_version=SCHEMA_VERSION,
            fetched_at=fetched_at,
            source_total_pages=total_pages,
            records=tuple(records),
            dataset_digest=dataset_digest,
        )

    async def _read_page(self, page_number: int) -> Any:
        return await self._transport.get_json(
            POLYCOP_LEADERBOARD_PATH,
            {
                "page": page_number,
                "sort_by": "score",
                "sort_order": "DESC",
                "min_score": 50,
                "full": 1,
            },
        )


def _append_page(
    records: list[CandidateWalletRecord],
    normalized_ids: set[str],
    rows: list[dict[str, Any]],
    *,
    source_page: int,
    aggregate_bytes: int,
) -> int:
    for row in rows:
        source_rank = len(records) + 1
        if source_rank > _MAX_TOTAL_RECORDS:
            raise PolyCopSourceError("PolyCop record count exceeded the safety cap.")
        aggregate_bytes += len(_canonical_json(row).encode("utf-8"))
        if aggregate_bytes > _MAX_DATASET_BYTES:
            raise PolyCopSourceError("PolyCop dataset exceeded the aggregate size cap.")
        record = _normalize_row(
            row,
            source_page=source_page,
            source_rank=source_rank,
        )
        if record.external_wallet_id in normalized_ids:
            raise PolyCopSnapshotUnstableError(
                "PolyCop pagination produced duplicate wallet identities."
            )
        normalized_ids.add(record.external_wallet_id)
        records.append(record)
    return aggregate_bytes


def _validate_page(payload: Any, *, expected_page: int) -> tuple[int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise _schema_error("envelope_not_object", payload)
    actual_fields = frozenset(str(key) for key in payload)
    if actual_fields != _ENVELOPE_FIELDS:
        raise _schema_error("envelope_fields_changed", payload)
    if payload.get("status") != "success":
        raise PolyCopSourceError("PolyCop response status was not successful.")
    page = payload.get("page")
    total_pages = payload.get("total_pages")
    rows = payload.get("data")
    if isinstance(page, bool) or not isinstance(page, int) or page != expected_page:
        raise _schema_error("page_value_changed", payload)
    if isinstance(total_pages, bool) or not isinstance(total_pages, int) or total_pages < 1:
        raise _schema_error("total_pages_value_changed", payload)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise _schema_error("data_value_changed", payload)
    return total_pages, rows


def _normalize_row(
    row: dict[str, Any],
    *,
    source_page: int,
    source_rank: int,
) -> CandidateWalletRecord:
    actual_fields = frozenset(str(key) for key in row)
    if actual_fields != _ROW_FIELDS:
        raise _schema_error("row_fields_changed", row)
    raw_address = row.get("address")
    if not isinstance(raw_address, str) or _WALLET_PATTERN.fullmatch(raw_address) is None:
        raise _schema_error("wallet_value_changed", row)
    address = raw_address.lower()

    metrics: dict[str, JsonValue] = {}
    for field_name in sorted(_ROW_FIELDS - {"address"}):
        value = row[field_name]
        if field_name in _DECIMAL_FIELDS:
            metrics[field_name] = _decimal_text(value, field_name=field_name)
        elif field_name in _INTEGER_FIELDS:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise _schema_error(f"{field_name}_value_changed", row)
            metrics[field_name] = value
        elif field_name == "hedged":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise _schema_error("hedged_value_changed", row)
            metrics[field_name] = value
        elif field_name in _EMBEDDED_JSON_FIELDS:
            if not isinstance(value, str):
                raise _schema_error(f"{field_name}_value_changed", row)
            try:
                json.loads(value, parse_float=Decimal)
            except json.JSONDecodeError as error:
                raise _schema_error(f"{field_name}_invalid_json", row) from error
            metrics[field_name] = value
        elif field_name == "last_active":
            if not isinstance(value, str) or not value:
                raise _schema_error("last_active_value_changed", row)
            metrics[field_name] = value
        else:
            raise AssertionError(f"unhandled reviewed PolyCop field: {field_name}")

    if _WALLET_SEARCH_PATTERN.search(_canonical_json(metrics)) is not None:
        raise _schema_error("wallet_value_outside_identity_field", row)
    digest_payload = {"address": address, "metrics": metrics}
    row_digest = hashlib.sha256(_canonical_json(digest_payload).encode("utf-8")).hexdigest()
    return CandidateWalletRecord(
        external_wallet_id=address,
        source_rank=source_rank,
        source_page=source_page,
        metrics=metrics,
        row_digest=row_digest,
    )


def _decimal_text(value: Any, *, field_name: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise _schema_error(f"{field_name}_value_changed", {field_name: value})
    decimal_value = Decimal(value)
    if not decimal_value.is_finite():
        raise _schema_error(f"{field_name}_value_changed", {field_name: value})
    rendered = format(decimal_value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


def _schema_error(reason_code: str, sample: object) -> PolyCopSchemaChangedError:
    if isinstance(sample, dict):
        fields = sorted(str(key) for key in sample)
    else:
        fields = [type(sample).__name__]
    fingerprint = hashlib.sha256("\n".join(fields).encode("utf-8")).hexdigest()
    return PolyCopSchemaChangedError(reason_code, sample, fingerprint)


def _digest_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        default=_json_default,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return _decimal_text(value, field_name="json_number")
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _retry_delay(error: HTTPError, *, default: float) -> float:
    retry_after = None if error.headers is None else error.headers.get("Retry-After")
    if retry_after is None:
        return default
    try:
        return min(5.0, max(0.0, float(retry_after)))
    except ValueError:
        return default
