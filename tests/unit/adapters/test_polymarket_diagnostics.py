from __future__ import annotations

from typing import Any

import pytest
from polymarket import (
    InsufficientAllowanceError,
    RateLimitError,
    RequestRejectedError,
    SigningError,
    TransportError,
    UnexpectedResponseError,
    UserInputError,
)
from polymarket import (
    TimeoutError as PolymarketTimeoutError,
)

from polysia.adapters.polymarket.diagnostics import (
    ReadRetryPolicy,
    VenueErrorCategory,
    classify_polymarket_error,
    sanitize_venue_message,
)


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (
            RequestRejectedError("unauthorized", status=401),
            VenueErrorCategory.AUTHENTICATION_FAILURE,
        ),
        (SigningError("signature failed"), VenueErrorCategory.SIGNATURE_FAILURE),
        (
            UserInputError("invalid amount semantics"),
            VenueErrorCategory.INVALID_AMOUNT_SEMANTICS,
        ),
        (
            RequestRejectedError("invalid quantity", status=400),
            VenueErrorCategory.INVALID_QUANTITY,
        ),
        (
            RequestRejectedError("minimum order size", status=400),
            VenueErrorCategory.MINIMUM_SIZE_VIOLATION,
        ),
        (
            RequestRejectedError("invalid tick size", status=400),
            VenueErrorCategory.TICK_SIZE_VIOLATION,
        ),
        (
            RequestRejectedError("insufficient balance", status=400),
            VenueErrorCategory.INSUFFICIENT_BALANCE,
        ),
        (
            InsufficientAllowanceError("allowance too low"),
            VenueErrorCategory.INSUFFICIENT_ALLOWANCE,
        ),
        (
            RequestRejectedError("order type incompatible", status=400),
            VenueErrorCategory.ORDER_TYPE_INCOMPATIBILITY,
        ),
        (
            RequestRejectedError(
                "invalid post-only order: order crosses book",
                status=400,
            ),
            VenueErrorCategory.POST_ONLY_WOULD_CROSS,
        ),
        (
            RequestRejectedError("FOK constraint", status=400),
            VenueErrorCategory.ORDER_CONSTRAINT_VIOLATION,
        ),
        (
            RequestRejectedError("market closed", status=400),
            VenueErrorCategory.MARKET_UNAVAILABLE,
        ),
        (
            RequestRejectedError("geoblock restriction", status=403),
            VenueErrorCategory.GEOBLOCKED,
        ),
        (RateLimitError("rate limited"), VenueErrorCategory.RATE_LIMIT),
        (
            RequestRejectedError("request timestamp invalid", status=400),
            VenueErrorCategory.CLOCK_OR_TIMESTAMP,
        ),
        (
            UnexpectedResponseError("response shape changed"),
            VenueErrorCategory.SDK_CONTRACT_MISMATCH,
        ),
        (
            RequestRejectedError("server unavailable", status=503),
            VenueErrorCategory.VENUE_SERVER_ERROR,
        ),
        (
            PolymarketTimeoutError("read timeout"),
            VenueErrorCategory.NETWORK_TIMEOUT,
        ),
        (TransportError("connection reset"), VenueErrorCategory.NETWORK_ERROR),
        (
            RequestRejectedError("venue said no", status=400),
            VenueErrorCategory.UNKNOWN_VENUE_REJECTION,
        ),
    ],
)
def test_classifies_actionable_venue_failures(
    error: BaseException,
    category: VenueErrorCategory,
) -> None:
    diagnostic = classify_polymarket_error("operation", error)

    assert diagnostic.category == category
    assert diagnostic.operation == "operation"


def test_sanitized_message_preserves_context_without_sensitive_values() -> None:
    message = (
        "signature=very-secret private_key=another-secret "
        "wallet 0x1111111111111111111111111111111111111111 tick size invalid"
    )

    sanitized = sanitize_venue_message(message)

    assert sanitized is not None
    assert "tick size invalid" in sanitized
    assert "very-secret" not in sanitized
    assert "another-secret" not in sanitized
    assert "0x1111111111111111111111111111111111111111" not in sanitized


@pytest.mark.asyncio
async def test_read_retry_is_bounded_and_only_for_transient_failures() -> None:
    calls = 0
    sleeps: list[float] = []

    async def sleeper(delay: float) -> None:
        sleeps.append(delay)

    async def transient_read() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TransportError("connection reset")
        return {"status": "ok"}

    result = await ReadRetryPolicy(
        max_attempts=2,
        backoff_seconds=0.25,
        sleeper=sleeper,
    ).run("read", transient_read)

    assert result == {"status": "ok"}
    assert calls == 2
    assert sleeps == [0.25]


@pytest.mark.asyncio
async def test_read_retry_does_not_retry_authentication_failure() -> None:
    calls = 0

    async def rejected_read() -> None:
        nonlocal calls
        calls += 1
        raise RequestRejectedError("unauthorized", status=401)

    with pytest.raises(RequestRejectedError):
        await ReadRetryPolicy(max_attempts=3, backoff_seconds=0).run(
            "read",
            rejected_read,
        )

    assert calls == 1
