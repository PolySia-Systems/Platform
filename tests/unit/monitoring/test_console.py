from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import jwt
import pytest

from polysia.monitoring.console import AccessVerifier, ConsoleApplication
from polysia.storage.console_commands import ConsoleCommandStore


def application(tmp_path: Path, *, role: str = "operator") -> ConsoleApplication:
    tmp_path.mkdir(parents=True, exist_ok=True)
    publication = tmp_path / "publication.json"
    publication.write_text(json.dumps({"status": "STOPPED", "published_at": "2026-10-16"}))
    commands = ConsoleCommandStore(tmp_path / "commands.sqlite3")
    commands.initialize()

    def verify(token: str) -> tuple[str, str]:
        if token != "verified":
            raise ValueError("denied")
        return "owner-subject", role

    return ConsoleApplication(
        publication,
        origin="https://platform.example.com",
        verify=verify,
        commands=commands,
        csrf_secret=b"x" * 32,
    )


def request(
    app: ConsoleApplication,
    *,
    path: str = "/",
    token: str = "verified",
    method: str = "GET",
    body: Any = None,
    origin: str = "https://platform.example.com",
    cookie: str = "",
) -> tuple[str, dict[str, str], bytes]:
    raw = json.dumps(body).encode() if body is not None else b""
    state: list[Any] = []
    result = app(
        {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "HTTP_CF_ACCESS_JWT_ASSERTION": token,
            "HTTP_ORIGIN": origin,
            "HTTP_COOKIE": cookie,
            "CONTENT_LENGTH": str(len(raw)),
            "CONTENT_TYPE": "application/json",
            "wsgi.input": io.BytesIO(raw),
        },
        lambda status, headers: state.extend((status, dict(headers))),
    )
    return state[0], state[1], b"".join(result)


def test_unauthenticated_downloads_assets_and_origin_are_denied(tmp_path: Path) -> None:
    app = application(tmp_path)
    for path in (
        "/",
        "/api/report",
        "/console.js",
        "/download/comparison.csv",
        "/api/health",
        "/reports/" + "a" * 64 + ".json",
    ):
        status, _, body = request(app, path=path, token="spoofed-email")
        assert status == "403 Forbidden"
        assert json.loads(body) == {"reason": "identity_required"}
    status, headers, body = request(app)
    assert status == "200 OK" and b"PolySia Console" in body
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "HttpOnly; SameSite=Strict" in headers["Set-Cookie"]
    assert "Secure" in headers["Set-Cookie"]
    assert request(app, path="/../../secret")[0] == "404 Not Found"


def test_stop_path_survives_missing_report_publication(tmp_path: Path) -> None:
    app = application(tmp_path)
    (tmp_path / "publication.json").unlink()
    status, headers, _ = request(app)
    assert status == "200 OK"
    assert request(app, path="/console.js")[0] == "200 OK"
    assert request(app, path="/api/report")[0] == "503 Service Unavailable"
    cookie = headers["Set-Cookie"].split(";")[0]
    body = {
        "action": "stop",
        "expected_revision": 0,
        "idempotency_key": "stop-without-publication",
        "csrf": cookie.split("=", 1)[1],
    }
    assert request(app, path="/api/commands", method="POST", body=body, cookie=cookie)[0] == (
        "202 Accepted"
    )


def test_csrf_roles_revision_and_idempotency_fail_closed(tmp_path: Path) -> None:
    app = application(tmp_path)
    _, headers, _ = request(app)
    cookie = headers["Set-Cookie"].split(";")[0]
    csrf = cookie.split("=", 1)[1]
    body = {
        "action": "stop",
        "expected_revision": 0,
        "idempotency_key": "same-command-identity",
        "csrf": csrf,
    }
    assert request(app, path="/api/commands", method="POST", body=body)[0] == "403 Forbidden"
    assert (
        request(
            app,
            path="/api/commands",
            method="POST",
            body=body,
            cookie=cookie,
            origin="https://foreign.example",
        )[0]
        == "403 Forbidden"
    )
    status, _, receipt = request(app, path="/api/commands", method="POST", body=body, cookie=cookie)
    assert status == "202 Accepted"
    assert json.loads(receipt) == {"revision": 1, "status": "REQUESTED"}
    assert request(app, path="/api/commands", method="POST", body=body, cookie=cookie)[2] == receipt
    body["action"] = "resume"
    assert request(app, path="/api/commands", method="POST", body=body, cookie=cookie)[0] == (
        "409 Conflict"
    )
    reader = application(tmp_path / "reader", role="reader")
    assert request(reader, path="/api/commands", method="POST", body=body)[0] == "403 Forbidden"


def test_signed_tokens_require_correct_issuer_audience_expiry_and_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verify = AccessVerifier(
        issuer="https://test.cloudflareaccess.com", audience="aud", roles={"owner": "operator"}
    )
    monkeypatch.setattr(
        verify._keys,
        "get_signing_key_from_jwt",
        lambda _token: SimpleNamespace(key=key.public_key()),
    )
    now = datetime.now(UTC)
    claims = {
        "iss": "https://test.cloudflareaccess.com",
        "aud": "aud",
        "sub": "owner",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    assert verify(jwt.encode(claims, key, algorithm="RS256")) == ("owner", "operator")
    for changed in (
        {"aud": "foreign"},
        {"iss": "https://foreign.example"},
        {"exp": now - timedelta(seconds=1)},
        {"sub": "stranger"},
    ):
        with pytest.raises((ValueError, jwt.PyJWTError)):
            verify(jwt.encode({**claims, **changed}, key, algorithm="RS256"))
    with pytest.raises(ValueError):
        AccessVerifier(issuer="https://unapproved.example", audience="aud", roles={"a": "operator"})


def test_identity_provider_failure_is_distinct_from_invalid_identity(tmp_path: Path) -> None:
    app = application(tmp_path)

    def unavailable(_token: str) -> tuple[str, str]:
        raise jwt.PyJWKClientConnectionError("fixture key service unavailable")

    app._verify = unavailable
    status, _, body = request(app)
    assert status == "503 Service Unavailable"
    assert json.loads(body)["reason"] == "identity_service_unavailable"


def test_legacy_retained_metadata_does_not_invent_latency_or_break_reports(tmp_path: Path) -> None:
    from polysia.monitoring.platform_diagnostics import retained_diagnostics

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "legacy.metadata.json").write_text(
        json.dumps(
            {
                "endpoint": "https://data-api.polymarket.com/v2/trades",
                "bytes": 128,
                "observed_at": "2026-10-16T00:00:00+00:00",
            }
        )
    )
    diagnostics = retained_diagnostics(tmp_path / "authority.sqlite3", {})
    endpoint = diagnostics["endpoint_receipts"]["https://data-api.polymarket.com/v2/trades"]
    assert endpoint["latency_p95_ms"] is None
    assert endpoint["latency_sample_count"] == 0
    assert endpoint["unknown_latency_count"] == 1
    assert endpoint["known_bytes"] == 128
