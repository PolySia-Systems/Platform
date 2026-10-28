"""One fixed budget owner at the actual HTTP boundary, including SDK paging.

Port bounds remain conservatively charged after errors/restarts. Measured wire
requests/bytes are separate evidence. No retry or redirect is implicit here.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from polysia.adapters.polymarket.request_scheduling import EndpointRequestScheduler
from polysia.application.ports.copytrading import LeaderReadPurpose
from polysia.application.ports.financial_session import RequestCharge
from polysia.domain.financial_session import SessionBlocked, digest
from polysia.storage.financial_session import FinancialSessionJournal


class SessionNetwork:
    def __init__(
        self,
        journal: FinancialSessionJournal,
        *,
        allowed_origins: frozenset[str],
        maximum_response_bytes: int,
        maximum_queued: int,
        timeout_seconds: int,
        guard: Callable[[], None],
        clock: Callable[[], datetime],
        scheduler: EndpointRequestScheduler | None = None,
        rpc_url: str | None = None,
        minimum_free_disk_bytes: int = 0,
    ) -> None:
        if not allowed_origins or not 0 < maximum_queued <= 16 or not 0 < timeout_seconds <= 30:
            raise SessionBlocked("bounded_network_configuration_required")
        if maximum_response_bytes <= 0:
            raise SessionBlocked("response_bound_required")
        self.journal, self.origins = journal, allowed_origins
        self.maximum_bytes, self.maximum_queued = maximum_response_bytes, maximum_queued
        self.timeout, self.guard, self.clock = timeout_seconds, guard, clock
        self.scheduler = scheduler or EndpointRequestScheduler()
        self._allowance: dict[str, RequestCharge] = {}
        self._used: dict[str, tuple[int, int]] = {}
        self._action: ContextVar[str] = ContextVar("session_network_action", default="UNBOUND")
        self._financial_action: ContextVar[str] = ContextVar(
            "session_financial_action", default="READ"
        )
        self._evidence_deadline: ContextVar[datetime | None] = ContextVar(
            "session_financial_evidence_deadline", default=None
        )
        self._queued = 0
        self.rpc_url = rpc_url
        self.minimum_free_disk_bytes = minimum_free_disk_bytes
        self._registered_requests = int(journal.read()["requests"])

    def register_bound(self, action: str, charge: RequestCharge) -> None:
        if self._queued:
            raise SessionBlocked("cannot_replace_inflight_network_reservation")
        charged = int(self.journal.read()["requests"])
        if charged < self._registered_requests + charge.requests:
            raise SessionBlocked("network_bound_without_new_durable_charge")
        self._registered_requests = charged
        self._allowance[action] = charge
        self._used[action] = (0, 0)

    @contextmanager
    def action(
        self,
        action: str,
        financial_action: str = "READ",
        *,
        evidence_deadline: datetime | None = None,
    ) -> Iterator[None]:
        token = self._action.set(action)
        financial_token = self._financial_action.set(financial_action)
        deadline_token = self._evidence_deadline.set(evidence_deadline)
        try:
            yield
        finally:
            self._action.reset(token)
            self._financial_action.reset(financial_token)
            self._evidence_deadline.reset(deadline_token)

    def transport(self, inner: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncBaseTransport:
        return _MeteredHTTP(self, inner or httpx.AsyncHTTPTransport(retries=0))

    async def request(
        self, request: httpx.Request, inner: httpx.AsyncBaseTransport
    ) -> httpx.Response:
        self.guard()
        deadline = self._evidence_deadline.get()
        if deadline is not None and self.clock() >= deadline:
            raise SessionBlocked("financial_evidence_expired_before_wire")
        if shutil.disk_usage(self.journal.path.parent).free < (
            self.minimum_free_disk_bytes + self.maximum_bytes * 2
        ):
            raise SessionBlocked("network_evidence_disk_headroom_exhausted")
        financial_action = (
            "ENTRY" if self._action.get() == "SOURCE" else self._financial_action.get()
        )
        authority = self.journal.authority
        if financial_action != "READ":
            authority.assert_action(authority.binding, self.clock(), financial_action)
        elif self.clock() >= authority.protective_until:
            raise SessionBlocked("account_read_budget_window_expired")
        origin = str(request.url.copy_with(path="/", query=None)).rstrip("/")
        if origin not in self.origins:
            raise SessionBlocked("network_origin_outside_authorized_config")
        if request.method not in {"GET", "POST", "DELETE"}:
            raise SessionBlocked("unreviewed_network_method")
        if request.method != "GET":
            if request.url.host == "clob.polymarket.com":
                if request.url.path != "/order" or financial_action not in {
                    "ENTRY",
                    "REDUCE",
                    "CANCEL",
                }:
                    raise SessionBlocked("unreviewed_or_unbound_financial_endpoint")
            else:
                from polysia.adapters.polymarket.session_chain import ReadOnlyRPC

                body = json.loads(request.content)
                if (
                    self.rpc_url is None
                    or str(request.url) != self.rpc_url
                    or request.method != "POST"
                    or not isinstance(body, dict)
                    or body.get("method") not in ReadOnlyRPC.METHODS
                ):
                    raise SessionBlocked("RPC_mutation_denied")
        action = self._action.get()
        if action not in self._allowance:
            raise SessionBlocked("network_request_without_durable_reservation")
        count, size = self._used[action]
        bound = self._allowance[action]
        if count + 1 > bound.requests or size + self.maximum_bytes > bound.response_bytes:
            raise SessionBlocked("underlying_request_exceeds_reserved_bound")
        if self._queued >= self.maximum_queued:
            raise SessionBlocked("bounded_network_queue_full")
        self._queued += 1
        self._used[action] = (count + 1, size + self.maximum_bytes)
        identity = digest(
            (self.journal.checkpoint().sequence, action, count, str(request.url.path))
        )

        def attempted(state: dict[str, Any]) -> None:
            state.setdefault("wire", {})[identity] = {
                "action": action,
                "path": request.url.path,
                "method": request.method,
                "at": self.clock(),
                "reserved_bytes": self.maximum_bytes,
                "actual_bytes": None,
                "result": "IN_FLIGHT",
            }

        self.journal.mutate("WIRE_REQUEST", {"request": identity, "action": action}, attempted)
        invoked = False
        try:
            purpose = (
                LeaderReadPurpose.DISCOVERY if action == "SOURCE" else LeaderReadPurpose.RECOVERY
            )
            async with asyncio.timeout(self.timeout):
                async with self.scheduler.request(request.url.path, purpose=purpose):
                    self.guard()  # queued responses do not preserve stale permission
                    if deadline is not None and self.clock() >= deadline:
                        raise SessionBlocked("financial_evidence_expired_in_queue")
                    if financial_action != "READ":
                        authority.assert_action(authority.binding, self.clock(), financial_action)
                    request.headers["Accept-Encoding"] = "identity"
                    invoked = True
                    response = await inner.handle_async_request(request)
                    raw = bytearray()
                    try:
                        if response.headers.get("Content-Encoding", "identity") != "identity":
                            raise SessionBlocked("compressed_response_outside_memory_bound")
                        if response.is_stream_consumed:
                            raw.extend(response.content)
                        else:
                            async for chunk in response.aiter_raw():
                                raw.extend(chunk)
                                if len(raw) > self.maximum_bytes:
                                    raise SessionBlocked("response_overrun_no_retry")
                        if len(raw) > self.maximum_bytes:
                            raise SessionBlocked("response_overrun_no_retry")
                    finally:
                        await response.aclose()
            self.journal.retain_response(identity, bytes(raw))
            self._finish(
                identity,
                len(raw),
                f"HTTP_{response.status_code}",
                digest(bytes(raw).hex()),
                invoked=True,
            )
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=bytes(raw),
                request=request,
                extensions=response.extensions,
            )
        except BaseException as error:
            self._finish(identity, None, type(error).__name__, None, invoked=invoked)
            raise
        finally:
            self._queued -= 1

    def _finish(
        self,
        identity: str,
        size: int | None,
        result: str,
        response_digest: str | None,
        *,
        invoked: bool,
    ) -> None:
        def update(state: dict[str, Any]) -> None:
            state["wire"][identity].update(
                actual_bytes=size,
                result=result,
                response_digest=response_digest,
                completed_at=self.clock(),
                transport_invoked=invoked,
            )

        self.journal.mutate("WIRE_RESULT", {"request": identity, "result": result}, update)

    def observation(self) -> dict[str, object]:
        rows = list(self.journal.read().get("wire", {}).values())
        return {
            "allocation": "FIXED",
            "reserved_port_bounds": {key: asdict(value) for key, value in self._allowance.items()},
            "actual_requests": sum(str(row["result"]).startswith("HTTP_") for row in rows),
            "attempt_records": len(rows),
            "confirmed_transport_invocations": sum(
                row.get("transport_invoked") is True for row in rows
            ),
            "unknown_transport_invocations": sum(
                row.get("transport_invoked") is None for row in rows
            ),
            "measured_response_bytes": sum(row["actual_bytes"] or 0 for row in rows),
            "unknown_response_count": sum(
                row["actual_bytes"] is None and row.get("transport_invoked") is not False
                for row in rows
            ),
            "queue_depth": self._queued,
            "queue_limit": self.maximum_queued,
            "external_shared_egress_utilization": None,
            "scheduler": self.scheduler.telemetry_snapshot(),
        }


class _MeteredHTTP(httpx.AsyncBaseTransport):
    def __init__(self, budget: SessionNetwork, inner: httpx.AsyncBaseTransport) -> None:
        self.budget, self.inner = budget, inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.budget.request(request, self.inner)

    async def aclose(self) -> None:
        await self.inner.aclose()


class SessionPublicJSON:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def get_json(
        self,
        base_url: str,
        path: str,
        params: Mapping[str, str | int | bool],
        *,
        purpose: LeaderReadPurpose = LeaderReadPurpose.BASELINE,
    ) -> Any:
        response = await self.client.get(base_url + path, params=dict(params))
        response.raise_for_status()
        import json

        return json.loads(response.content, parse_float=Decimal)
