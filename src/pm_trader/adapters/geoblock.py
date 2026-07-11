from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

GEOBLOCK_URL = "https://polymarket.com/api/geoblock"
GeoblockResult = Literal["allowed", "blocked", "error", "not_checked"]


def utc_now() -> datetime:
    return datetime.now(UTC)


class GeoblockClientError(RuntimeError):
    """Raised when the official Polymarket geoblock endpoint cannot be trusted."""


class PreLiveOrderGeoblockError(RuntimeError):
    """Raised when a live order must be blocked by geoblock policy."""


@dataclass(frozen=True, slots=True)
class GeoblockStatus:
    """Sanitized geoblock check status with no sensitive location details."""

    status: GeoblockResult
    checked_at: datetime
    blocked: bool | None
    endpoint: str = GEOBLOCK_URL
    error_type: str | None = None

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "blocked": self.blocked,
            "checked_at": self.checked_at.isoformat(),
            "endpoint": self.endpoint,
            "error_type": self.error_type,
            "status": self.status,
        }


class GeoblockClient:
    """Client for the official Polymarket geoblock endpoint."""

    def __init__(self, *, url: str = GEOBLOCK_URL, timeout_seconds: float = 5.0) -> None:
        self._url = url
        self._timeout_seconds = timeout_seconds

    async def check(self) -> GeoblockStatus:
        return await asyncio.to_thread(self.check_sync)

    def check_sync(self) -> GeoblockStatus:
        checked_at = utc_now()
        request = Request(
            self._url,
            headers={"Accept": "application/json", "User-Agent": "pm-trader-geoblock/1.0"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw_payload = response.read()
            payload = json.loads(raw_payload.decode("utf-8"))
        except (HTTPError, URLError, OSError, TimeoutError, json.JSONDecodeError) as error:
            raise GeoblockClientError(
                "Could not verify Polymarket geoblock eligibility."
            ) from error

        blocked = _extract_blocked(payload)
        return GeoblockStatus(
            status="blocked" if blocked else "allowed",
            checked_at=checked_at,
            blocked=blocked,
            endpoint=self._url,
        )


class PreLiveOrderGeoblockCheck:
    """Mandatory fail-closed geoblock check for every live order placement."""

    def __init__(self, client: GeoblockClient | None = None) -> None:
        self._client = client or GeoblockClient()

    async def check(self) -> GeoblockStatus:
        try:
            return await self._client.check()
        except GeoblockClientError as error:
            return GeoblockStatus(
                status="error",
                checked_at=utc_now(),
                blocked=None,
                error_type=type(error.__cause__ or error).__name__,
            )

    async def assert_allowed(self) -> GeoblockStatus:
        status = await self.check()
        if status.status == "allowed" and status.blocked is False:
            return status
        if status.status == "blocked" or status.blocked is True:
            raise PreLiveOrderGeoblockError(
                "Polymarket geoblock check blocked live order placement."
            )
        raise PreLiveOrderGeoblockError(
            "Polymarket geoblock check failed closed; live order placement is blocked."
        )


def not_checked_geoblock_status() -> GeoblockStatus:
    return GeoblockStatus(
        status="not_checked",
        checked_at=utc_now(),
        blocked=None,
    )


def _extract_blocked(payload: Any) -> bool:
    if not isinstance(payload, dict):
        raise GeoblockClientError("Polymarket geoblock response was not a JSON object.")
    blocked = payload.get("blocked")
    if not isinstance(blocked, bool):
        raise GeoblockClientError(
            "Polymarket geoblock response did not include blocked=true/false."
        )
    return blocked
