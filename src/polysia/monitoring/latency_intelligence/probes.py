"""Out-of-band bounded network probes. Never run on the trading critical path."""

from __future__ import annotations

import socket
import ssl
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime

from polysia.adapters.polymarket.diagnostics import VenueErrorCategory
from polysia.monitoring.latency_intelligence.contract import MeasurementKind
from polysia.monitoring.latency_intelligence.policy import UNKNOWN, LatencyPolicy

MonotonicNs = Callable[[], int]


@dataclass(frozen=True, slots=True)
class ProbeEndpoint:
    endpoint_id: str
    host: str
    port: int = 443
    path: str = "/"
    server_time_path: str | None = None


POLYMARKET_READ_ENDPOINTS: tuple[ProbeEndpoint, ...] = (
    ProbeEndpoint("polymarket:data-api", "data-api.polymarket.com", path="/"),
    ProbeEndpoint("polymarket:gamma-api", "gamma-api.polymarket.com", path="/"),
    ProbeEndpoint(
        "polymarket:clob-time",
        "clob.polymarket.com",
        path="/time",
        server_time_path="/time",
    ),
)


@dataclass(frozen=True, slots=True)
class ProbeSample:
    endpoint_id: str
    status: str
    error_category: str | None
    dns_ns: int | None
    tcp_connect_ns: int | None
    tls_handshake_ns: int | None
    ttfb_ns: int | None
    http_total_ns: int | None
    connection_reused: bool | None
    venue_clock_delta_ns: int | None
    started_at_utc: datetime
    websocket_rtt_ns: int | None = None


def probe_endpoint(
    endpoint: ProbeEndpoint,
    *,
    policy: LatencyPolicy | None = None,
    monotonic_ns: MonotonicNs | None = None,
    reused_socket: ssl.SSLSocket | None = None,
) -> ProbeSample:
    policy = policy or LatencyPolicy()
    clock = monotonic_ns or time.perf_counter_ns
    started = datetime.now(UTC)
    timeout = policy.probe_timeout_seconds
    dns_ns = tcp_ns = tls_ns = ttfb_ns = http_ns = clock_delta = None
    reused = reused_socket is not None
    try:
        if reused_socket is None:
            dns_started = clock()
            infos = socket.getaddrinfo(endpoint.host, endpoint.port, type=socket.SOCK_STREAM)
            dns_ns = _duration(clock(), dns_started)
            if not infos:
                raise OSError("dns_empty")
            tcp_started = clock()
            raw = socket.create_connection((endpoint.host, endpoint.port), timeout=timeout)
            tcp_ns = _duration(clock(), tcp_started)
            tls_started = clock()
            context = ssl.create_default_context()
            sock = context.wrap_socket(raw, server_hostname=endpoint.host)
            tls_ns = _duration(clock(), tls_started)
        else:
            sock = reused_socket
            dns_ns = tcp_ns = tls_ns = None
        request = (
            f"GET {endpoint.path} HTTP/1.1\r\n"
            f"Host: {endpoint.host}\r\n"
            "User-Agent: PolySia/0.1 latency-probe\r\n"
            "Accept: */*\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii")
        http_started = clock()
        sock.settimeout(timeout)
        sock.sendall(request)
        first = sock.recv(1)
        ttfb_ns = _duration(clock(), http_started)
        chunks = [first]
        while True:
            data = sock.recv(4096)
            if not data:
                break
            chunks.append(data)
            if sum(len(item) for item in chunks) > 65_536:
                break
        http_ns = _duration(clock(), http_started)
        payload = b"".join(chunks)
        category = _http_error_category(payload)
        if endpoint.server_time_path == endpoint.path:
            clock_delta = _clock_delta_ns(payload, started)
        with suppress(OSError):
            sock.close()
        return ProbeSample(
            endpoint_id=endpoint.endpoint_id,
            status="ok" if category is None else category.value,
            error_category=None if category is None else category.value,
            dns_ns=dns_ns,
            tcp_connect_ns=tcp_ns,
            tls_handshake_ns=tls_ns,
            ttfb_ns=ttfb_ns,
            http_total_ns=http_ns,
            connection_reused=reused,
            venue_clock_delta_ns=clock_delta,
            started_at_utc=started,
            websocket_rtt_ns=None,
        )
    except TimeoutError:
        return _failed(endpoint.endpoint_id, started, VenueErrorCategory.NETWORK_TIMEOUT)
    except ssl.SSLError:
        return _failed(endpoint.endpoint_id, started, VenueErrorCategory.NETWORK_ERROR)
    except OSError:
        return _failed(endpoint.endpoint_id, started, VenueErrorCategory.NETWORK_ERROR)
    except Exception:
        return _failed(endpoint.endpoint_id, started, VenueErrorCategory.UNKNOWN_VENUE_REJECTION)


def record_probe(recorder: object, sample: ProbeSample) -> None:
    record = getattr(recorder, "record_measurement", None)
    if record is None:
        return
    started = sample.started_at_utc
    endpoint = sample.endpoint_id
    status = sample.status
    pairs = (
        (MeasurementKind.DNS.value, sample.dns_ns),
        (MeasurementKind.TCP_CONNECT.value, sample.tcp_connect_ns),
        (MeasurementKind.TLS_HANDSHAKE.value, sample.tls_handshake_ns),
        (MeasurementKind.TTFB.value, sample.ttfb_ns),
        (MeasurementKind.HTTP_TOTAL.value, sample.http_total_ns),
        (MeasurementKind.VENUE_CLOCK_DELTA.value, sample.venue_clock_delta_ns),
        (MeasurementKind.WEBSOCKET_RTT.value, sample.websocket_rtt_ns),
    )
    for kind, value in pairs:
        record(
            kind=kind,
            value_ns=value,
            started_at_utc=started,
            endpoint_id=endpoint,
            status=status,
        )
    record(
        kind=MeasurementKind.CONNECTION_REUSE.value,
        value_ns=None if sample.connection_reused is None else int(sample.connection_reused),
        started_at_utc=started,
        endpoint_id=endpoint,
        status=status,
    )
    outcome = getattr(recorder, "record_probe_outcome", None)
    if outcome is not None:
        outcome(success=sample.error_category is None)


def _duration(ended: int, started: int) -> int | None:
    value = ended - started
    if value < 0:
        return None
    return value


def _failed(endpoint_id: str, started: datetime, category: VenueErrorCategory) -> ProbeSample:
    return ProbeSample(
        endpoint_id=endpoint_id,
        status=category.value,
        error_category=category.value,
        dns_ns=None,
        tcp_connect_ns=None,
        tls_handshake_ns=None,
        ttfb_ns=None,
        http_total_ns=None,
        connection_reused=None,
        venue_clock_delta_ns=None,
        started_at_utc=started,
        websocket_rtt_ns=None,
    )


def _http_error_category(payload: bytes) -> VenueErrorCategory | None:
    try:
        header = payload.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    except Exception:
        return VenueErrorCategory.UNKNOWN_VENUE_REJECTION
    parts = header.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return None
    code = int(parts[1])
    if code == 429:
        return VenueErrorCategory.RATE_LIMIT
    if 500 <= code <= 599:
        return VenueErrorCategory.VENUE_SERVER_ERROR
    if code >= 400:
        return VenueErrorCategory.UNKNOWN_VENUE_REJECTION
    return None


def _clock_delta_ns(payload: bytes, local_started: datetime) -> int | None:
    try:
        _, body = payload.split(b"\r\n\r\n", 1)
        text = body.decode("utf-8").strip().strip('"')
        venue = int(text)
    except (ValueError, UnicodeError):
        return None
    local = int(local_started.timestamp())
    delta_seconds = venue - local
    return abs(delta_seconds) * 1_000_000_000


def sanitize_endpoint_id(value: str) -> str:
    text = value.strip()
    lowered = text.lower()
    if any(token in lowered for token in ("http://", "https://", "?", "authorization", "0x")):
        return UNKNOWN
    return text
