"""Read-only RPC for Shadow/research using the existing acquisition budget owner.

No signer, financial journal or account secret is reachable from this transport.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import socket
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from polysia.adapters.polymarket.bounded_transport import BoundedPublicTransport
from polysia.adapters.polymarket.session_chain import ReadOnlyRPC
from polysia.storage.acquisition_authority import AcquisitionAuthority, AcquisitionBlockedError


class BoundedResearchRPC(httpx.AsyncBaseTransport):
    def __init__(
        self,
        authority: AcquisitionAuthority,
        inner: httpx.AsyncBaseTransport | None = None,
        *,
        authenticated_gets: bool = False,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.authority = authority
        self.inner = inner or httpx.AsyncHTTPTransport(retries=0)
        self.authenticated_gets, self.clock = authenticated_gets, clock

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.method == "POST" else {}
        if not (
            (
                request.method == "POST"
                and isinstance(body, dict)
                and body.get("method") in ReadOnlyRPC.METHODS
            )
            or (self.authenticated_gets and request.method == "GET")
        ):
            raise AcquisitionBlockedError("read_only_RPC_method_required")
        if shutil.disk_usage(self.authority.evidence_root.parent).free < (
            self.authority.policy.minimum_free_disk_bytes
            + self.authority.policy.maximum_response_bytes * 2
        ):
            raise AcquisitionBlockedError("evidence_disk_reserve_exhausted")
        endpoint = str(request.url.copy_with(query=None))
        identity = self.authority.reserve(endpoint, now=self.clock(), host=socket.gethostname())
        started = time.monotonic_ns()
        raw = bytearray()
        # Failed/unknown reads keep their full reservation; there is no retry.
        async with asyncio.timeout(self.authority.policy.timeout_seconds):
            request.headers["Accept-Encoding"] = "identity"
            response = await self.inner.handle_async_request(request)
            try:
                if response.headers.get("Content-Encoding", "identity") != "identity":
                    raise AcquisitionBlockedError("compressed_RPC_response_denied")
                if response.is_stream_consumed:
                    raw.extend(response.content)
                else:
                    async for chunk in response.aiter_raw():
                        raw.extend(chunk)
                        if len(raw) > self.authority.policy.maximum_response_bytes:
                            raise AcquisitionBlockedError("RPC_response_exceeds_reserved_bytes")
                if len(raw) > self.authority.policy.maximum_response_bytes:
                    raise AcquisitionBlockedError("RPC_response_exceeds_reserved_bytes")
            finally:
                await response.aclose()
        BoundedPublicTransport(self.authority)._retain(
            identity,
            endpoint=endpoint,
            params={"method": str(body.get("method", "GET"))},
            raw=bytes(raw),
            trace_id=None,
            latency_ms=(time.monotonic_ns() - started) // 1_000_000,
        )
        self.authority.settle(identity, response_bytes=len(raw))
        return httpx.Response(
            response.status_code, content=bytes(raw), headers=response.headers, request=request
        )

    async def aclose(self) -> None:
        await self.inner.aclose()
