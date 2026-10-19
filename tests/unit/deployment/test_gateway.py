from __future__ import annotations

import io
from pathlib import Path

import pytest

from polysia.deployment.gateway import GatewayVerifier, console_identity, gateway_config
from polysia.monitoring.console import ConsoleApplication
from polysia.storage.console_commands import ConsoleCommandStore

HASH = "$2a$10$" + "a" * 53


def test_gateway_config_has_one_protected_socket_and_no_admin_or_identity_fallback():
    for profile, origin in (
        ("private", "https://localhost:8443"),
        ("own-domain", "https://console.example.com"),
    ):
        result = gateway_config(
            profile=profile,
            origin=origin,
            socket_path="/run/app/web.sock",
            passwords={"owner": HASH},
        )
        assert "admin off" in result and "skip_install_trust" in result
        assert "strict_sni_host on" in result
        assert "reverse_proxy unix//run/app/web.sock" in result
        assert "request_header -X-Polysia-User" in result
        assert "header_up X-Polysia-User {http.auth.user.id}" in result
        assert "header_up -Authorization" in result
        assert ("bind 127.0.0.1" in result) is (profile == "private")
        assert ("tls internal" in result) is (profile == "private")


@pytest.mark.parametrize(
    "change",
    [
        {"profile": "anonymous"},
        {"origin": "http://localhost"},
        {"origin": "https://unapproved.example.com"},
        {"socket_path": "/tmp/../web.sock"},
        {"passwords": {"owner": "plaintext"}},
        {"passwords": {"bad\nuser": HASH}},
    ],
)
def test_gateway_configuration_rejects_unsafe_input(change):
    args = dict(
        profile="private",
        origin="https://localhost:8443",
        socket_path="/run/app/web.sock",
        passwords={"owner": HASH},
    )
    with pytest.raises(ValueError):
        gateway_config(**{**args, **change})


def test_gateway_cannot_enable_tcp_and_cloudflare_never_falls_back():
    with pytest.raises(ValueError, match="exclusive"):
        console_identity({"profile": "private", "port": 8765})
    with pytest.raises(ValueError):
        console_identity(
            {
                "profile": "cloudflare",
                "issuer": "invalid",
                "audience": "x",
                "roles": {"owner": "operator"},
            }
        )
    with pytest.raises(ValueError):
        GatewayVerifier({"owner": "root"})


def test_gateway_identity_requires_known_user_and_exact_host(tmp_path: Path):
    store = ConsoleCommandStore(tmp_path / "commands.sqlite3")
    store.initialize()
    app = ConsoleApplication(
        tmp_path / "missing.json",
        origin="https://localhost:8443",
        verify=GatewayVerifier({"owner": "operator", "guest": "reader"}),
        identity_header="HTTP_X_POLYSIA_USER",
        commands=store,
        csrf_secret=b"x" * 32,
    )
    for user, host, expected in (
        ("", "localhost:8443", "403"),
        ("unknown", "localhost:8443", "403"),
        ("owner", "foreign.example", "403"),
        ("owner", "localhost:8443", "200"),
    ):
        state = []
        app(
            {
                "HTTP_HOST": host,
                "HTTP_X_POLYSIA_USER": user,
                "HTTP_CF_ACCESS_JWT_ASSERTION": "irrelevant",
                "REQUEST_METHOD": "GET",
                "PATH_INFO": "/",
                "wsgi.input": io.BytesIO(),
            },
            lambda status, _headers, state=state: state.append(status),
        )
        assert state[0].startswith(expected)
