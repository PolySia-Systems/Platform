"""Protected cached Console; no acquisition, shell or financial-store access."""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import re
import sqlite3
import time
from collections.abc import Callable, Iterable
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import jwt

from polysia.application.services.report_integrity import verify_analytical_digest
from polysia.application.services.shadow_reporting import comparison_csv
from polysia.storage.console_commands import ConsoleCommandStore

MAX_PUBLICATION_BYTES = 8_000_000


class AccessVerifier:
    def __init__(self, *, issuer: str, audience: str, roles: dict[str, str]) -> None:
        if re.fullmatch(r"https://[a-z0-9-]+\.cloudflareaccess\.com", issuer) is None:
            raise ValueError("verified Access organization issuer is required")
        if (
            not audience
            or not roles
            or any(role not in {"reader", "operator"} for role in roles.values())
        ):
            raise ValueError("audience and explicit verified roles are required")
        self._issuer, self._audience, self._roles = issuer, audience, dict(roles)
        self._keys = jwt.PyJWKClient(
            issuer + "/cdn-cgi/access/certs", timeout=5, cache_keys=True, lifespan=300
        )

    def __call__(self, token: str) -> tuple[str, str]:
        if (
            not token
            or len(token) > 16_384
            or jwt.get_unverified_header(token).get("alg") != "RS256"
        ):
            raise ValueError("invalid identity token")
        key = self._keys.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            issuer=self._issuer,
            audience=self._audience,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
        subject = str(claims["sub"])
        role = self._roles.get(subject) or self._roles.get(str(claims.get("email", "")))
        if role is None:
            raise ValueError("identity not in verified role map")
        return subject, role


class ConsoleApplication:
    def __init__(
        self,
        publication: Path,
        *,
        origin: str,
        verify: Callable[[str], tuple[str, str]],
        commands: ConsoleCommandStore,
        csrf_secret: bytes,
        identity_header: str = "HTTP_CF_ACCESS_JWT_ASSERTION",
    ) -> None:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or re.fullmatch(r"[a-z0-9.-]+", parsed.hostname) is None
            or parsed.port is not None
            and not 1 <= parsed.port <= 65535
            or len(csrf_secret) < 32
        ):
            raise ValueError("HTTPS origin and protected CSRF secret are required")
        self._publication, self._origin, self._verify = publication, origin, verify
        self._commands, self._csrf_secret = commands, csrf_secret
        if identity_header not in {"HTTP_CF_ACCESS_JWT_ASSERTION", "HTTP_X_POLYSIA_USER"}:
            raise ValueError("unsupported identity boundary")
        self._identity_header = identity_header
        self._host = parsed.netloc
        self._cache_key: tuple[int, int] | None = None
        self._cache: dict[str, Any] = {}

    def __call__(self, environ: dict[str, Any], start_response: Any) -> Iterable[bytes]:
        headers = [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
            (
                "Content-Security-Policy",
                "default-src 'none'; style-src 'self'; "
                "script-src 'self'; connect-src 'self'; form-action 'self'; "
                "base-uri 'none'; frame-ancestors 'none'",
            ),
            ("Strict-Transport-Security", "max-age=31536000"),
        ]

        def respond(status: str, payload: object, *, media: str | None = None) -> list[bytes]:
            if media:
                headers[0] = ("Content-Type", media)
            body = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
            start_response(status, [*headers, ("Content-Length", str(len(body)))])
            return [body]

        try:
            subject, role = self._verify(str(environ.get(self._identity_header, "")))
        except jwt.PyJWKClientConnectionError:
            return respond("503 Service Unavailable", {"reason": "identity_service_unavailable"})
        except ValueError, jwt.PyJWTError, OSError:
            return respond("403 Forbidden", {"reason": "identity_required"})
        if environ.get("HTTP_HOST") != self._host:
            return respond("403 Forbidden", {"reason": "host_invalid"})
        if environ.get("HTTP_ORIGIN") not in {None, "", self._origin}:
            return respond("403 Forbidden", {"reason": "origin_invalid"})
        method, path = environ.get("REQUEST_METHOD"), environ.get("PATH_INFO")
        if method not in {"GET", "POST"}:
            return respond("405 Method Not Allowed", {"reason": "unsupported_method"})
        if method == "POST":
            if path != "/api/commands" or role != "operator":
                return respond("403 Forbidden", {"reason": "operator_required"})
            if environ.get("HTTP_ORIGIN") != self._origin:
                return respond("403 Forbidden", {"reason": "origin_invalid"})
            try:
                length = int(environ.get("CONTENT_LENGTH", "0"))
                if not 1 <= length <= 4096:
                    raise ValueError("command_size_invalid")
                if environ.get("CONTENT_TYPE", "").split(";")[0] != "application/json":
                    raise ValueError("command_type_invalid")
                command = json.loads(environ["wsgi.input"].read(length))
                if not isinstance(command, dict):
                    raise ValueError("command_object_required")
                cookie = SimpleCookie()
                cookie.load(environ.get("HTTP_COOKIE", ""))
                csrf = str(command.pop("csrf", ""))
                expected = self._csrf(subject)
                previous = self._csrf(subject, previous=True)
                if (
                    "__Host-polysia-csrf" not in cookie
                    or not hmac.compare_digest(cookie["__Host-polysia-csrf"].value, csrf)
                    or not any(hmac.compare_digest(csrf, item) for item in (expected, previous))
                ):
                    return respond("403 Forbidden", {"reason": "csrf_invalid"})
                receipt = self._commands.submit(subject=subject, **command)
            except sqlite3.DatabaseError:
                return respond(
                    "503 Service Unavailable",
                    {
                        "reason": "command_store_unavailable",
                        "next_action": "inspect durable receipts before retrying",
                    },
                )
            except ValueError, TypeError, KeyError, CookieError, json.JSONDecodeError:
                return respond("409 Conflict", {"reason": "command_invalid_or_revision_changed"})
            return respond("202 Accepted", receipt)
        if path == "/api/commands":
            try:
                return respond("200 OK", self._commands.status())
            except sqlite3.DatabaseError:
                return respond("503 Service Unavailable", {"reason": "command_store_unavailable"})
        if path == "/api/health":
            try:
                status_file = self._publication.parent / "publisher-status.json"
                if status_file.stat().st_size > 4096:
                    raise ValueError("health_receipt_too_large")
                return respond("200 OK", json.loads(status_file.read_text(encoding="utf-8")))
            except OSError, ValueError:
                return respond(
                    "503 Service Unavailable",
                    {"status": "UNKNOWN", "reason": "publisher_receipt_missing"},
                )
        if path in {"/console.css", "/console.js"}:
            asset = Path(__file__).with_name("console_assets") / path.removeprefix("/")
            media = "text/css" if path.endswith("css") else "text/javascript"
            return respond("200 OK", asset.read_text(encoding="utf-8"), media=media)
        if path == "/":
            csrf = self._csrf(subject)
            headers.append(
                (
                    "Set-Cookie",
                    "__Host-polysia-csrf="
                    + csrf
                    + "; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=3600",
                )
            )
            document = (
                (Path(__file__).with_name("console_assets") / "index.html")
                .read_text(
                    encoding="utf-8",
                )
                .replace("{{csrf}}", html.escape(csrf, quote=True))
                .replace("{{role}}", role)
            )
            return respond("200 OK", document, media="text/html; charset=utf-8")
        if isinstance(path, str) and re.fullmatch(r"/reports/[a-f0-9]{64}\.json", path):
            try:
                archive = self._publication.parent / "reports" / path.rsplit("/", 1)[1]
                if archive.is_symlink() or archive.stat().st_size > MAX_PUBLICATION_BYTES:
                    raise ValueError("invalid_archived_report")
                report = json.loads(archive.read_text(encoding="utf-8"))
                verify_analytical_digest(report)
                if report["analytical_digest"] != archive.stem:
                    raise ValueError("archived_report_identity_differs")
                headers.append(
                    ("Content-Disposition", 'attachment; filename="' + archive.name + '"')
                )
                return respond("200 OK", report)
            except OSError, ValueError, KeyError:
                return respond("404 Not Found", {"reason": "archived_report_unavailable"})
        if path not in {"/api/report", "/download/comparison.csv"}:
            return respond("404 Not Found", {"reason": "unknown_route"})
        try:
            publication = self._read_publication()
        except OSError, ValueError, json.JSONDecodeError:
            return respond(
                "503 Service Unavailable",
                {
                    "reason": "publication_unavailable",
                    "next_action": "inspect publisher journal",
                },
            )
        if path == "/api/report":
            return respond("200 OK", publication)
        if path == "/download/comparison.csv":
            headers.append(("Content-Disposition", 'attachment; filename="comparison.csv"'))
            try:
                data = comparison_csv(publication["report"])
            except ValueError, TypeError, KeyError:
                return respond("409 Conflict", {"reason": "comparison_unavailable"})
            return respond("200 OK", data, media="text/csv; charset=utf-8")
        return respond("404 Not Found", {"reason": "unknown_route"})

    def _csrf(self, subject: str, *, previous: bool = False) -> str:
        window = int(time.time()) // 1800 - int(previous)
        return hmac.new(
            self._csrf_secret,
            f"{subject}:{window}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def _read_publication(self) -> dict[str, Any]:
        stat = self._publication.stat()
        if stat.st_size > MAX_PUBLICATION_BYTES:
            raise ValueError("publication_size_limit")
        key = stat.st_mtime_ns, stat.st_size
        if self._cache_key != key:
            with self._publication.open("rb") as stream:
                raw = stream.read(MAX_PUBLICATION_BYTES + 1)
            if len(raw) > MAX_PUBLICATION_BYTES:
                raise ValueError("publication_size_limit")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("invalid_publication")
            if "report" in result:
                verify_analytical_digest(result["report"])
            self._cache, self._cache_key = result, key
        return self._cache
