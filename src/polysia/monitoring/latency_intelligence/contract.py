"""Versioned venue-neutral performance contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from polysia.monitoring.latency_intelligence.policy import (
    PERFORMANCE_CONTRACT_VERSION,
    UNKNOWN,
)


class SpanStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    UNKNOWN = "UNKNOWN"


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class MeasurementKind(StrEnum):
    SOURCE_TO_OBSERVATION = "source_to_observation_ms"
    POLL_WAIT_COMPONENT = "poll_wait_component_ms"
    REQUEST_DURATION = "request_duration_ms"
    POST_RESPONSE_PROCESSING = "post_response_processing_ms"
    DNS = "dns_duration_ms"
    TCP_CONNECT = "tcp_connect_duration_ms"
    TLS_HANDSHAKE = "tls_handshake_duration_ms"
    TTFB = "ttfb_ms"
    HTTP_TOTAL = "http_total_duration_ms"
    WEBSOCKET_RTT = "websocket_rtt_ms"
    VENUE_CLOCK_DELTA = "venue_clock_delta_ms"
    CONNECTION_REUSE = "connection_reuse"


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    host_id: str = UNKNOWN
    provider: str = UNKNOWN
    region: str = UNKNOWN
    deploy_sha: str = UNKNOWN
    runtime_version: str = UNKNOWN
    image_digest: str = UNKNOWN
    configuration_version: str = UNKNOWN
    policy_version: str = UNKNOWN
    venue_id: str = UNKNOWN

    def sanitized(self) -> RuntimeIdentity:
        return RuntimeIdentity(
            host_id=_token(self.host_id),
            provider=_token(self.provider),
            region=_token(self.region),
            deploy_sha=_token(self.deploy_sha),
            runtime_version=_token(self.runtime_version),
            image_digest=_token(self.image_digest),
            configuration_version=_token(self.configuration_version),
            policy_version=_token(self.policy_version),
            venue_id=_token(self.venue_id),
        )


@dataclass(frozen=True, slots=True)
class PerformanceSpan:
    performance_contract_version: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    component: str
    operation: str
    status: str
    duration_ns: int | None
    started_at_utc: datetime
    venue_id: str
    endpoint_id: str | None
    host_id: str
    provider: str
    region: str
    deploy_sha: str
    runtime_version: str
    image_digest: str
    configuration_version: str
    policy_version: str
    poll_run_id: str | None = None
    experiment_id: str | None = None

    def __post_init__(self) -> None:
        if self.duration_ns is not None and self.duration_ns < 0:
            raise ValueError("duration_ns must be null or non-negative")
        if self.performance_contract_version != PERFORMANCE_CONTRACT_VERSION:
            raise ValueError("unsupported performance_contract_version")
        if not self.trace_id or not self.span_id:
            raise ValueError("trace_id and span_id are required")
        if self.parent_span_id == self.span_id:
            raise ValueError("parent_span_id must not equal span_id")


@dataclass(frozen=True, slots=True)
class PerformanceMeasurement:
    measurement_id: str
    kind: str
    status: str
    value_ns: int | None
    started_at_utc: datetime
    identity: RuntimeIdentity
    endpoint_id: str | None = None
    poll_run_id: str | None = None
    experiment_id: str | None = None

    def __post_init__(self) -> None:
        if self.value_ns is not None and self.value_ns < 0:
            raise ValueError("value_ns must be null or non-negative")


def duration_ns_or_unknown(value: int | None) -> int | None:
    """Reject negative or impossible durations. Missing stays None, never 0."""

    if value is None:
        return None
    if value < 0:
        raise ValueError("impossible negative duration")
    return value


def ms_to_ns(value_ms: int | float | None) -> int | None:
    if value_ms is None:
        return None
    if value_ms < 0:
        raise ValueError("impossible negative duration")
    return int(value_ms * 1_000_000)


def ns_to_ms(value_ns: int | None) -> int | None:
    if value_ns is None:
        return None
    return int(value_ns // 1_000_000)


def _token(value: str | None) -> str:
    text = "" if value is None else value.strip()
    return text if text else UNKNOWN
