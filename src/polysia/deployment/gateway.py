"""Configuration for the optional authenticated HTTPS gateway, never a TCP identity port."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

GATEWAY_IDENTITY_HEADER = "HTTP_X_POLYSIA_USER"


class GatewayVerifier:
    """Trust only the gateway's socket boundary and an explicit local role map."""

    def __init__(self, roles: dict[str, str]) -> None:
        if (
            not roles
            or len(roles) > 16
            or any(
                re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", name) is None
                or role not in {"reader", "operator"}
                for name, role in roles.items()
            )
        ):
            raise ValueError("explicit gateway usernames and reader/operator roles required")
        self._roles = dict(roles)

    def __call__(self, username: str) -> tuple[str, str]:
        if username not in self._roles:
            raise ValueError("gateway identity not configured")
        return username, self._roles[username]


def gateway_config(
    *,
    profile: str,
    origin: str,
    socket_path: str,
    passwords: dict[str, str],
) -> str:
    """Render stock Caddy configuration. Passwords must already be bcrypt hashes."""
    url = urlsplit(origin)
    if (
        profile not in {"private", "own-domain"}
        or url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.path
        or url.query
        or url.fragment
        or re.fullmatch(r"[a-z0-9.-]+", url.hostname) is None
    ):
        raise ValueError("valid HTTPS gateway profile/origin required")
    if profile == "private" and url.hostname != "localhost":
        raise ValueError("private access uses localhost through authenticated SSH")
    if profile == "own-domain" and (
        url.port not in {None, 443} or "." not in url.hostname or url.hostname == "localhost"
    ):
        raise ValueError("own-domain access requires an explicit public hostname on 443")
    socket = Path(socket_path)
    if (
        not PurePosixPath(socket_path).is_absolute()
        or re.fullmatch(r"/[a-zA-Z0-9/_.-]+", socket_path) is None
        or ".." in PurePosixPath(socket_path).parts
        or socket.is_symlink()
    ):
        raise ValueError("absolute protected backend socket required")
    GatewayVerifier(dict.fromkeys(passwords, "reader"))
    if any(
        re.fullmatch(r"\$2[aby]\$1[0-4]\$[./A-Za-z0-9]{53}", value) is None
        for value in passwords.values()
    ):
        raise ValueError("bounded bcrypt password hashes required")
    accounts = "\n".join(f"            {name} {value}" for name, value in passwords.items())
    private = "    bind 127.0.0.1\n    tls internal\n" if profile == "private" else ""
    return (
        "{\n    admin off\n    skip_install_trust\n"
        + ("    auto_https disable_redirects\n" if profile == "private" else "")
        + "    servers {\n        protocols h1 h2\n        strict_sni_host on\n"
        "        max_header_size 16KB\n"
        "        timeouts {\n            read_header 5s\n            read_body 5s\n"
        "            write 15s\n            idle 15s\n        }\n    }\n}\n"
        + origin
        + " {\n"
        + private
        + "    route {\n        request_header -X-Polysia-User\n"
        "        request_header -X_Polysia_User\n"
        "        request_header -Cf-Access-Jwt-Assertion\n"
        "        request_header -Cf_Access_Jwt_Assertion\n"
        "        request_header -X-Forwarded-User\n"
        "        request_header -X_Forwarded_User\n"
        "        basic_auth bcrypt {\n" + accounts + "\n        }\n"
        "        request_body {\n            max_size 4096\n        }\n"
        "        reverse_proxy unix/" + socket_path + " {\n"
        "            header_up X-Polysia-User {http.auth.user.id}\n"
        "            header_up -Authorization\n            header_up -Cf-Access-Jwt-Assertion\n"
        "            transport http {\n                dial_timeout 2s\n"
        "                response_header_timeout 10s\n                max_conns_per_host 8\n"
        "            }\n        }\n    }\n}\n"
    )


def console_identity(value: dict[str, Any]) -> tuple[Any, str, dict[str, Any]]:
    """One exclusive identity mechanism; invalid Cloudflare never falls back."""
    from polysia.monitoring.console import AccessVerifier

    profile = value.get("profile", "cloudflare")
    if profile == "cloudflare":
        if "unix_socket" in value:
            raise ValueError("Cloudflare profile requires the existing loopback boundary")
        return (
            AccessVerifier(
                issuer=value["issuer"], audience=value["audience"], roles=value["roles"]
            ),
            "HTTP_CF_ACCESS_JWT_ASSERTION",
            {"host": "127.0.0.1", "port": int(value.get("port", 8765))},
        )
    if profile not in {"private", "own-domain"} or "port" in value:
        raise ValueError("gateway requires an exclusive Unix-socket backend")
    if sys.platform == "win32":
        raise ValueError("gateway backend requires the supported Linux server profile")
    socket = Path(value["unix_socket"])
    if (
        not socket.is_absolute()
        or ".." in socket.parts
        or socket.is_symlink()
        or socket.parent.is_symlink()
    ):
        raise ValueError("protected backend socket required")
    parent = socket.parent.stat()
    if (
        parent.st_mode & 0o007
        or parent.st_uid not in {0, os.geteuid()}
        or parent.st_gid != os.getegid()
    ):
        raise ValueError(
            "backend socket directory is not protected: "
            f"uid={parent.st_uid} gid={parent.st_gid} mode={parent.st_mode & 0o777:o}; "
            f"expected uid=0/{os.geteuid()} gid={os.getegid()} other=0",
        )
    return (
        GatewayVerifier(value["roles"]),
        GATEWAY_IDENTITY_HEADER,
        {"unix_socket": str(socket), "unix_socket_perms": "660", "url_scheme": "https"},
    )
