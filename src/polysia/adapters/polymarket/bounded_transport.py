"""Public GET-only transport with durable pre-request accounting."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import socket
import time
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
        started = time.monotonic_ns()
        try:
            with build_opener(_NoRedirect()).open(request, timeout=policy.timeout_seconds) as reply:
                raw = reply.read(policy.maximum_response_bytes + 1)
                trace_id = reply.headers.get("x-trace-id")
        except HTTPError as error:
            # Failure bodies/in-flight costs remain fully reserved. Do not
            # retry geographic/auth/rate-limit failures or print provider URLs.
            retry = error.headers.get("Retry-After", "") if error.headers else ""
            if retry and (not retry.isdigit() or len(retry) > 5 or int(retry) > 86_400):
                raise AcquisitionBlockedError("provider_retry_after_unsupported") from None
            retry_seconds = int(retry) if retry else None
            raise AcquisitionBlockedError(
                f"provider_http_{error.code}", retry_after_seconds=retry_seconds,
            ) from None
        except (URLError, TimeoutError, OSError):
            raise AcquisitionBlockedError("provider_transport_failed") from None
        if len(raw) > policy.maximum_response_bytes:
            raise AcquisitionBlockedError("response_size_outside_reservation")
        try:
            self._retain(request_id, endpoint=endpoint, params=params, raw=raw, trace_id=trace_id,
                         latency_ms=(time.monotonic_ns() - started) // 1_000_000)
        except OSError:
            raise AcquisitionBlockedError("evidence_persistence_failed") from None
        self.authority.settle(request_id, response_bytes=len(raw))
        try:
            return json.loads(raw, parse_float=Decimal)
        except (ValueError, UnicodeDecodeError):
            raise AcquisitionBlockedError("provider_invalid_json") from None

    def _retain(
        self, request_id: str, *, endpoint: str, params: Mapping[str, str | int | bool],
        raw: bytes, trace_id: str | None,
        latency_ms: int,
    ) -> None:
        root = self.authority.evidence_root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = root / (request_id + ".json")
        temporary = target.with_suffix(".partial")
        temporary.write_bytes(raw)
        if os.name != "nt":
            temporary.chmod(0o600)
        temporary.replace(target)
        metadata = root / (request_id + ".metadata.json")
        metadata.write_text(json.dumps({
            "endpoint": endpoint, "params": dict(params),
            "observed_at": datetime.now(UTC).isoformat(), "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(), "trace_id": trace_id,
            "latency_ms": latency_ms,
        }, sort_keys=True), encoding="utf-8")
        if os.name != "nt":
            metadata.chmod(0o600)
