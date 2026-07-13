from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

from polymarket import (
    CancelledSigningError,
    InsufficientAllowanceError,
    InsufficientLiquidityError,
    PolymarketError,
    RateLimitError,
    RequestRejectedError,
    SigningError,
    TransactionFailedError,
    TransportError,
    UnexpectedResponseError,
    UserInputError,
)
from polymarket import (
    TimeoutError as PolymarketTimeoutError,
)

T = TypeVar("T")
AsyncSleeper = Callable[[float], Awaitable[None]]


class VenueErrorCategory(StrEnum):
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    SIGNATURE_FAILURE = "SIGNATURE_FAILURE"
    INVALID_AMOUNT_SEMANTICS = "INVALID_AMOUNT_SEMANTICS"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    MINIMUM_SIZE_VIOLATION = "MINIMUM_SIZE_VIOLATION"
    TICK_SIZE_VIOLATION = "TICK_SIZE_VIOLATION"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    INSUFFICIENT_ALLOWANCE = "INSUFFICIENT_ALLOWANCE"
    INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"
    ORDER_TYPE_INCOMPATIBILITY = "ORDER_TYPE_INCOMPATIBILITY"
    ORDER_CONSTRAINT_VIOLATION = "ORDER_CONSTRAINT_VIOLATION"
    MARKET_UNAVAILABLE = "MARKET_UNAVAILABLE"
    GEOBLOCKED = "GEOBLOCKED"
    RATE_LIMIT = "RATE_LIMIT"
    CLOCK_OR_TIMESTAMP = "CLOCK_OR_TIMESTAMP"
    SDK_CONTRACT_MISMATCH = "SDK_CONTRACT_MISMATCH"
    VENUE_SERVER_ERROR = "VENUE_SERVER_ERROR"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    UNKNOWN_VENUE_REJECTION = "UNKNOWN_VENUE_REJECTION"


@dataclass(frozen=True, slots=True)
class PolymarketErrorDiagnostic:
    operation: str
    category: VenueErrorCategory
    retryable_read: bool
    terminal: bool
    error_type: str
    sanitized_message: str | None
    status_code: int | None
    error_code: str | None

    def to_dict(self) -> dict[str, bool | int | str | None]:
        return {
            "category": self.category.value,
            "error_code": self.error_code,
            "error_type": self.error_type,
            "operation": self.operation,
            "retryable_read": self.retryable_read,
            "sanitized_message": self.sanitized_message,
            "status_code": self.status_code,
            "terminal": self.terminal,
        }

    def safe_summary(self) -> str:
        fields = [self.category.value]
        if self.status_code is not None:
            fields.append(f"status={self.status_code}")
        if self.error_code is not None:
            fields.append(f"code={self.error_code}")
        if self.sanitized_message:
            fields.append(self.sanitized_message)
        return "; ".join(fields)


@dataclass(frozen=True, slots=True)
class ReadRetryPolicy:
    """Bounded retry policy for idempotent venue reads only."""

    max_attempts: int = 2
    backoff_seconds: float = 0.25
    sleeper: AsyncSleeper = asyncio.sleep

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 3:
            raise ValueError("read max_attempts must be within [1, 3]")
        if not 0 <= self.backoff_seconds <= 2:
            raise ValueError("read backoff_seconds must be within [0, 2]")

    async def run(self, operation: str, call: Callable[[], Awaitable[T]]) -> T:
        for attempt in range(1, self.max_attempts + 1):
            try:
                return await call()
            except PolymarketError as error:
                diagnostic = classify_polymarket_error(operation, error)
                if not diagnostic.retryable_read or attempt >= self.max_attempts:
                    raise
                await self.sleeper(self.backoff_seconds * attempt)
        raise AssertionError("bounded read retry loop exhausted unexpectedly")


def classify_polymarket_error(
    operation: str,
    error: BaseException,
) -> PolymarketErrorDiagnostic:
    message = str(error)
    normalized = message.casefold()
    status = _optional_int(getattr(error, "status", None))
    code = sanitize_venue_message(getattr(error, "code", None))
    category = _category_from_error(error, normalized, status)
    retryable = category in {
        VenueErrorCategory.NETWORK_ERROR,
        VenueErrorCategory.NETWORK_TIMEOUT,
        VenueErrorCategory.RATE_LIMIT,
        VenueErrorCategory.VENUE_SERVER_ERROR,
    }
    return PolymarketErrorDiagnostic(
        operation=operation,
        category=category,
        retryable_read=retryable,
        terminal=not retryable,
        error_type=type(error).__name__,
        sanitized_message=sanitize_venue_message(message),
        status_code=status,
        error_code=code,
    )


def sanitize_venue_message(value: object) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    text = re.sub(
        r"(?i)\b(private[_ -]?key|api[_ -]?(?:key|secret|passphrase)|"
        r"authorization|bearer|signature|token)\b\s*[:=]\s*[^\s,;]+",
        r"\1=<redacted>",
        text,
    )
    text = re.sub(
        r"(?i)\b(signed payload|credentials?)\b.*",
        r"\1 <redacted>",
        text,
    )
    text = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <redacted>", text)
    text = re.sub(r"(?i)0x[a-f0-9]{32,}", "<redacted-hex>", text)
    text = re.sub(
        r"(?<![A-Za-z0-9._-])[A-Za-z0-9_-]{40,}(?![A-Za-z0-9._-])",
        "<redacted-value>",
        text,
    )
    return text[:240]


def _category_from_error(
    error: BaseException,
    message: str,
    status: int | None,
) -> VenueErrorCategory:
    if isinstance(error, (SigningError, CancelledSigningError)):
        return VenueErrorCategory.SIGNATURE_FAILURE
    if isinstance(error, InsufficientAllowanceError):
        return VenueErrorCategory.INSUFFICIENT_ALLOWANCE
    if isinstance(error, InsufficientLiquidityError):
        return VenueErrorCategory.INSUFFICIENT_LIQUIDITY
    if isinstance(error, RateLimitError) or status == 429:
        return VenueErrorCategory.RATE_LIMIT
    if isinstance(error, PolymarketTimeoutError):
        return VenueErrorCategory.NETWORK_TIMEOUT
    if isinstance(error, TransportError):
        return (
            VenueErrorCategory.NETWORK_TIMEOUT
            if "timeout" in message or "timed out" in message
            else VenueErrorCategory.NETWORK_ERROR
        )
    if isinstance(error, UnexpectedResponseError):
        return VenueErrorCategory.SDK_CONTRACT_MISMATCH
    if status is not None and status >= 500:
        return VenueErrorCategory.VENUE_SERVER_ERROR

    keyword_categories = (
        (
            ("geoblock", "geo-block", "restricted region", "restricted country"),
            VenueErrorCategory.GEOBLOCKED,
        ),
        (("signature", "signing"), VenueErrorCategory.SIGNATURE_FAILURE),
        (("allowance",), VenueErrorCategory.INSUFFICIENT_ALLOWANCE),
        (("insufficient balance", "not enough balance"), VenueErrorCategory.INSUFFICIENT_BALANCE),
        (
            ("minimum size", "min order size", "minimum order"),
            VenueErrorCategory.MINIMUM_SIZE_VIOLATION,
        ),
        (("tick size", "min tick", "price increment"), VenueErrorCategory.TICK_SIZE_VIOLATION),
        (
            ("invalid quantity", "invalid size", "size must", "quantity must"),
            VenueErrorCategory.INVALID_QUANTITY,
        ),
        (
            ("invalid amount", "amount must", "amount semantics"),
            VenueErrorCategory.INVALID_AMOUNT_SEMANTICS,
        ),
        (
            ("fok", "fak", "gtc", "fill-or-kill", "fill-and-kill"),
            VenueErrorCategory.ORDER_CONSTRAINT_VIOLATION,
        ),
        (("order type", "post only", "post-only"), VenueErrorCategory.ORDER_TYPE_INCOMPATIBILITY),
        (
            ("market closed", "market inactive", "not accepting orders"),
            VenueErrorCategory.MARKET_UNAVAILABLE,
        ),
        (
            ("timestamp", "clock", "expired request", "request time"),
            VenueErrorCategory.CLOCK_OR_TIMESTAMP,
        ),
        (
            ("schema", "response shape", "contract mismatch"),
            VenueErrorCategory.SDK_CONTRACT_MISMATCH,
        ),
        (("rate limit", "too many requests"), VenueErrorCategory.RATE_LIMIT),
        (("timeout", "timed out"), VenueErrorCategory.NETWORK_TIMEOUT),
    )
    for keywords, category in keyword_categories:
        if any(keyword in message for keyword in keywords):
            return category
    if status in {401, 403} or "authentication" in message or "unauthorized" in message:
        return VenueErrorCategory.AUTHENTICATION_FAILURE
    if isinstance(error, UserInputError):
        return VenueErrorCategory.INVALID_AMOUNT_SEMANTICS
    if isinstance(error, (RequestRejectedError, TransactionFailedError, PolymarketError)):
        return VenueErrorCategory.UNKNOWN_VENUE_REJECTION
    return VenueErrorCategory.UNKNOWN_VENUE_REJECTION


def _optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if not isinstance(value, (str, bytes, bytearray)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "PolymarketErrorDiagnostic",
    "ReadRetryPolicy",
    "VenueErrorCategory",
    "classify_polymarket_error",
    "sanitize_venue_message",
]
