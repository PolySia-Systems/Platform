"""Public GET-only transport with durable pre-request accounting."""

from __future__ import annotations

import asyncio
import json
import shutil
import socket
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from polysia.application.ports.copytrading import LeaderReadPurpose
from polysia.storage.acquisition_authority import AcquisitionAuthority, AcquisitionBlockedError


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str,
        headers: Any, newurl: str,
    ) -> None:
        return None


class BoundedPublicTransport:
    """No hidden retries, redirects, credentials or external mutation methods."""

    def __init__(self, authority: AcquisitionAuthority, *, closure: bool = False) -> None:
        self.authority = authority
        self._closure = closure

    async def get_json(
        self, base_url: str, path: str, params: Mapping[str, str | int | bool], *,
        purpose: LeaderReadPurpose = LeaderReadPurpose.BASELINE,
    ) -> Any:
        del purpose
        return await asyncio.to_thread(self._read, base_url, path, params)

    def _read(self, base_url: str, path: str, params: Mapping[str, str | int | bool]) -> Any:
        endpoint = base_url + path
        policy = self.authority.policy
        # Reserve disk for the OS, unrelated workloads and recovery staging.
        if shutil.disk_usage(".").free < policy.minimum_free_disk_bytes:
            raise AcquisitionBlockedError("disk_reserve_exhausted")
        request_id = self.authority.reserve(
            endpoint, now=datetime.now(UTC), host=socket.gethostname(), closure=self._closure,
        )
        query = urlencode({key: str(value).lower() if isinstance(value, bool) else value
                           for key, value in params.items()})
        request = Request(endpoint + "?" + query, headers={
            "Accept": "application/json", "User-Agent": "PolySia/0.1 public research",
        })
        try:
            with build_opener(_NoRedirect()).open(request, timeout=policy.timeout_seconds) as reply:
                raw = reply.read(policy.maximum_response_bytes + 1)
            if len(raw) > policy.maximum_response_bytes:
                raise AcquisitionBlockedError("response_size_outside_reservation")
            self.authority.settle(request_id, response_bytes=len(raw))
            return json.loads(raw, parse_float=Decimal)
        except HTTPError as error:
            # Failure bodies/in-flight costs remain fully reserved. Do not
            # retry geographic/auth/rate-limit failures or print provider URLs.
            raise AcquisitionBlockedError(f"provider_http_{error.code}") from None
        except (URLError, TimeoutError, OSError):
            raise AcquisitionBlockedError("provider_transport_failed") from None
