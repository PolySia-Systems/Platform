"""Public GET-only transport with durable pre-request accounting."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import time
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal
from threading import local
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
        self._context: dict[str, str] = {}
        self._request_local = local()
        # The existing read-only RPC receipt owner also calls _retain directly.
        # Such reads have no native poll correlation, rather than an invented one.
        self._request_local.purpose = LeaderReadPurpose.BASELINE.value
        self._request_local.context = {}
        self._counts = {"attempts": 0, "completed": 0, "failed": 0, "response_bytes": 0,
                        "diagnostic_errors": 0}

    def bind_request_context(self, *, poll_run_id: str, experiment_id: str) -> None:
        self._context = {"poll_run_id": poll_run_id, "experiment_id": experiment_id,
                         "source_id": "polymarket:data-api"}

    def request_telemetry(self) -> dict[str, object]:
        return {**self._counts, **self._context,
                "coverage": "bounded transport attempts; rejected admission has no request",
                "provider_publication_latency": "UNKNOWN"}

    async def get_json(
        self, base_url: str, path: str, params: Mapping[str, str | int | bool], *,
        purpose: LeaderReadPurpose = LeaderReadPurpose.BASELINE,
    ) -> Any:
        # Cancellation does not release or refund a running thread's reservation.
        # Its completion retains and settles evidence independently of the waiter.
        return await asyncio.to_thread(self._read_with_purpose, base_url, path, params, purpose)

    def _read_with_purpose(
        self, base_url: str, path: str, params: Mapping[str, str | int | bool],
        purpose: LeaderReadPurpose,
    ) -> Any:
        self._request_local.purpose = purpose.value
        self._request_local.context = dict(self._context)
        return self._read(base_url, path, params)

    def _read(self, base_url: str, path: str, params: Mapping[str, str | int | bool]) -> Any:
        endpoint = base_url + path
        policy = self.authority.policy
        # Reserve disk for the OS, unrelated workloads and recovery staging.
        if shutil.disk_usage(".").free < policy.minimum_free_disk_bytes:
            raise AcquisitionBlockedError("disk_reserve_exhausted")
        request_id = self.authority.reserve(
            endpoint, now=datetime.now(UTC), host=socket.gethostname(), closure=self._closure,
        )
        self._counts["attempts"] += 1
        query = urlencode({key: str(value).lower() if isinstance(value, bool) else value
                           for key, value in params.items()})
        request = Request(endpoint + "?" + query, headers={
            "Accept": "application/json", "User-Agent": "PolySia public research",
        })
        started = time.monotonic_ns()
        try:
            with build_opener(_NoRedirect()).open(request, timeout=policy.timeout_seconds) as reply:
                raw = reply.read(policy.maximum_response_bytes + 1)
                trace_id = reply.headers.get("x-trace-id")
        except HTTPError as error:
            self._retain_failure(request_id, endpoint, f"provider_http_{error.code}", started)
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
            self._retain_failure(request_id, endpoint, "provider_transport_failed", started)
            raise AcquisitionBlockedError("provider_transport_failed") from None
        if len(raw) > policy.maximum_response_bytes:
            self._retain_failure(request_id, endpoint, "response_size_outside_reservation", started)
            raise AcquisitionBlockedError("response_size_outside_reservation")
        try:
            self._retain(request_id, endpoint=endpoint, params=params, raw=raw, trace_id=trace_id,
                         latency_ms=(time.monotonic_ns() - started) // 1_000_000)
        except OSError:
            raise AcquisitionBlockedError("evidence_persistence_failed") from None
        self.authority.settle(request_id, response_bytes=len(raw))
        self._counts["completed"] += 1
        self._counts["response_bytes"] += len(raw)
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
            "request_id": request_id, "purpose": self._request_local.purpose,
            **self._request_local.context,
            "endpoint": endpoint, "params": dict(params),
            "observed_at": datetime.now(UTC).isoformat(), "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(), "trace_id": trace_id,
            "latency_ms": latency_ms,
        }, sort_keys=True), encoding="utf-8")
        if os.name != "nt":
            metadata.chmod(0o600)
        self._observe(request_id, endpoint, latency_ms, len(raw), "COMPLETE")

    def _retain_failure(self, request_id: str, endpoint: str, reason: str, started: int) -> None:
        self._counts["failed"] += 1
        latency_ms = (time.monotonic_ns() - started) // 1_000_000
        self._observe(request_id, endpoint, latency_ms, None, reason)
        root = self.authority.evidence_root
        try:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            target = root / (request_id + ".failure.json")
            target.write_text(json.dumps({
                "request_id": request_id, "purpose": self._request_local.purpose,
                **self._request_local.context,
                "endpoint": endpoint, "reason": reason,
                "observed_at": datetime.now(UTC).isoformat(),
                "latency_ms": (time.monotonic_ns() - started) // 1_000_000,
                "response_bytes": "UNKNOWN_FULL_RESERVATION_CHARGED",
            }, sort_keys=True), encoding="utf-8")
            if os.name != "nt":
                target.chmod(0o600)
        except OSError:
            # Authority still retains the uncertain reservation even if this
            # auxiliary diagnostic fails; preserve the original provider failure.
            return

    def _observe(self, request_id: str, endpoint: str, duration_ms: int,
                 size: int | None, status: str) -> None:
        """Disposable index beside authoritative accounting; never grants I/O."""
        try:
            path = self.authority.evidence_root.parent / "request-diagnostics.sqlite3"
            with closing(sqlite3.connect(path, timeout=0.05)) as connection, connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS requests (request_id TEXT PRIMARY KEY, "
                    "observed_at TEXT NOT NULL, endpoint TEXT NOT NULL,purpose TEXT NOT NULL,"
                    "poll_run_id TEXT,experiment_id TEXT,duration_ms INTEGER,"
                    "response_bytes INTEGER,status TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS request_observed ON requests(observed_at)"
                )
                connection.execute("INSERT OR REPLACE INTO requests VALUES(?,?,?,?,?,?,?,?,?)", (
                    request_id, datetime.now(UTC).isoformat(), endpoint,
                    self._request_local.purpose,
                    self._request_local.context.get("poll_run_id"),
                    self._request_local.context.get("experiment_id"),
                    duration_ms, size, status,
                ))
        except (OSError, sqlite3.Error):
            self._counts["diagnostic_errors"] += 1
