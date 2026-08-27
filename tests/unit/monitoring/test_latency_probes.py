from __future__ import annotations

from polysia.adapters.polymarket.diagnostics import VenueErrorCategory
from polysia.monitoring.latency_intelligence.policy import UNKNOWN
from polysia.monitoring.latency_intelligence.probes import (
    ProbeEndpoint,
    ProbeSample,
    _http_error_category,
    sanitize_endpoint_id,
)


def test_probe_reuses_polymarket_error_taxonomy() -> None:
    assert _http_error_category(b"HTTP/1.1 429 Too Many Requests\r\n\r\n") is (
        VenueErrorCategory.RATE_LIMIT
    )
    assert _http_error_category(b"HTTP/1.1 503 Unavailable\r\n\r\n") is (
        VenueErrorCategory.VENUE_SERVER_ERROR
    )
    assert _http_error_category(b"HTTP/1.1 200 OK\r\n\r\n") is None


def test_probe_endpoint_id_is_stable_and_redacted() -> None:
    assert sanitize_endpoint_id("polymarket:data-api") == "polymarket:data-api"
    assert sanitize_endpoint_id("https://clob.polymarket.com/auth?key=secret") == UNKNOWN
    endpoint = ProbeEndpoint("polymarket:data-api", "data-api.polymarket.com")
    assert "?" not in endpoint.endpoint_id
    assert "http" not in endpoint.endpoint_id


def test_websocket_rtt_stays_unknown_when_unused() -> None:
    from datetime import UTC, datetime

    sample = ProbeSample(
        endpoint_id="polymarket:data-api",
        status="ok",
        error_category=None,
        dns_ns=1,
        tcp_connect_ns=1,
        tls_handshake_ns=1,
        ttfb_ns=1,
        http_total_ns=1,
        connection_reused=False,
        venue_clock_delta_ns=None,
        started_at_utc=datetime.now(UTC),
        websocket_rtt_ns=None,
    )
    assert sample.websocket_rtt_ns is None
