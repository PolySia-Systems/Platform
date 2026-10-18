"""Synthetic HTTPS browser acceptance; opt in with POLYSIA_BROWSER_TESTS=1."""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, make_server

import jwt
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("POLYSIA_BROWSER_TESTS") != "1",
    reason="explicit browser acceptance job only",
)


@pytest.fixture
def console_fixture(tmp_path: Path) -> Any:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    import polysia
    from polysia.monitoring.console import AccessVerifier, ConsoleApplication
    from polysia.storage.console_commands import ConsoleCommandStore

    if os.getenv("POLYSIA_REQUIRE_WHEEL") == "1":
        assert "site-packages" in str(Path(polysia.__file__).resolve())
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    certificate, private = tmp_path / "fixture.pem", tmp_path / "fixture-key.pem"
    certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    private.chmod(0o600)
    state = {
        "opening_cash": "100",
        "closing_cash": "99",
        "net_result": "-1",
        "recorded_fees": "0.1",
        "closing_positions": [],
        "operating_costs": "UNALLOCATED",
    }
    analytical = {
        "report": {
            "evaluated_observations": 1,
            "total_observations": 1,
            "unknown_observations": 0,
            "control": {"net_pnl": "-1"},
            "target": {"net_pnl": "-1"},
            "control_target_net_delta": "0",
        },
        "financial_state": {"control": state, "target": state},
    }
    digest = hashlib.sha256(
        json.dumps(analytical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    publication = tmp_path / "publication.json"
    publication.write_text(
        json.dumps(
            {
                "status": "SYNTHETIC TEST FIXTURE",
                "published_at": now.isoformat(),
                "last_attempt": now.isoformat(),
                "next_action": "Fixture only; no acquisition",
                "authority_window": {
                    "expires_at": "2026-10-16T12:00:00+00:00",
                    "maximum_requests": 40,
                    "maximum_bytes": 33554432,
                },
                "authority": {"requests_charged": 11, "bytes_charged": 2371503},
                "report": {
                    "analytical": analytical,
                    "analytical_digest": digest,
                    "scope": "TEST FIXTURE",
                },
                "diagnostic": {
                    "discovery": {
                        "source_rows": 500,
                        "unique_wallets": 1,
                        "excluded": {"before_activity_window": 499},
                        "candidates": [
                            {
                                "wallet_id": "fixture-wallet-123",
                                "state": "ACTIVITY_CONFIRMED",
                                "execution_eligibility": "UNKNOWN",
                                "exclusions": ["book_stale"],
                                "last_qualifying_activity": now.isoformat(),
                            }
                        ],
                    }
                },
            }
        )
    )
    commands = ConsoleCommandStore(tmp_path / "commands.sqlite3")
    commands.initialize()
    verifier = AccessVerifier(
        issuer="https://fixture.cloudflareaccess.com",
        audience="fixture",
        roles={"fixture-owner": "operator", "fixture-reader": "reader"},
    )
    verifier._keys = SimpleNamespace(
        get_signing_key_from_jwt=lambda _: SimpleNamespace(key=key.public_key())
    )

    class Quiet(WSGIRequestHandler):
        def log_message(self, *_args: Any) -> None:
            pass

    server = make_server("127.0.0.1", 0, lambda _e, _s: [], handler_class=Quiet)
    origin = f"https://localhost:{server.server_port}"
    server.set_app(
        ConsoleApplication(
            publication,
            origin=origin,
            verify=verifier,
            commands=commands,
            csrf_secret=b"test-fixture-only" * 3,
        )
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, private)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def token(subject: str) -> str:
        return jwt.encode(
            {
                "sub": subject,
                "iss": "https://fixture.cloudflareaccess.com",
                "aud": "fixture",
                "iat": int(time.time()),
                "exp": int(time.time()) + 600,
            },
            key,
            algorithm="RS256",
            headers={"kid": "fixture"},
        )

    try:
        yield origin, token, commands, digest
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_console_operator_tasks_and_protected_downloads(
    console_fixture: Any, width: int, height: int
) -> None:
    from playwright.sync_api import expect, sync_playwright

    origin, token, commands, digest = console_fixture
    with sync_playwright() as runtime:
        options = {"channel": "chrome"} if os.name == "nt" else {}
        browser = runtime.chromium.launch(**options)
        # This generated localhost fixture is the only certificate exception.
        context = browser.new_context(
            ignore_https_errors=True,
            viewport={"width": width, "height": height},
            extra_http_headers={"Cf-Access-Jwt-Assertion": token("fixture-owner")},
        )
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(origin)
        expect(page.get_by_role("heading", name="SYNTHETIC TEST FIXTURE")).to_be_visible()
        expect(page.locator("#control")).to_have_text("-1")
        expect(page.locator("#authority-window")).to_contain_text("11 / 40 requests")
        expect(page.locator("#reasons")).to_contain_text("499 excluded: before activity window")
        if width < 480:
            financial_region = page.get_by_role("region", name="Control and Target financial state")
            financial_region.focus()
            page.keyboard.press("ArrowRight")
            page.wait_for_function(
                "() => document.querySelector('#report-section .scroll').scrollLeft > 0"
            )
            page.keyboard.press("ArrowLeft")
            page.wait_for_function(
                "() => document.querySelector('#report-section .scroll').scrollLeft === 0"
            )
        page.get_by_label("Wallet identity hash").fill("123")
        page.get_by_role("button", name="fixture-wallet-123").click()
        expect(page.locator("#wallet-detail")).to_contain_text("book_stale")
        page.get_by_role("link", name="Export comparison CSV").focus()
        with page.expect_download() as download:
            page.keyboard.press("Enter")
        assert digest in Path(download.value.path()).read_text()
        page.get_by_role("button", name="STOP acquisition").click()
        expect(page.locator("#receipt")).to_contain_text("REQUESTED")
        assert commands.pending() == [(1, "stop")]
        assert not errors
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        output = Path("output/playwright")
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / f"console-{width}.png"), full_page=True)
        assert (
            context.request.get(origin + "/api/report").json()["report"]["analytical_digest"]
            == digest
        )
        durations = []
        for _ in range(25):
            started = time.perf_counter()
            assert context.request.get(origin + "/api/report").status == 200
            durations.append((time.perf_counter() - started) * 1000)
        p95 = sorted(durations)[23]
        (output / f"cache-latency-{width}.json").write_text(
            json.dumps(
                {
                    "dataset": "synthetic one observation and one wallet",
                    "samples": 25,
                    "p95_ms": p95,
                    "target_ms": 2000,
                    "provider_calls": 0,
                }
            ),
            encoding="utf-8",
        )
        assert p95 < 2000
        denied = browser.new_context(ignore_https_errors=True)
        assert denied.request.get(origin + "/api/report").status == 403
        reader = browser.new_context(
            ignore_https_errors=True,
            extra_http_headers={"Cf-Access-Jwt-Assertion": token("fixture-reader")},
        )
        read_page = reader.new_page()
        read_page.goto(origin)
        expect(read_page.get_by_role("button", name="STOP acquisition")).to_be_disabled()
        browser.close()


def test_console_ages_recovers_refreshes_and_observes_async_receipts(console_fixture: Any) -> None:
    from playwright.sync_api import expect, sync_playwright

    origin, token, commands, _digest = console_fixture
    with sync_playwright() as runtime:
        options = {"channel": "chrome"} if os.name == "nt" else {}
        browser = runtime.chromium.launch(**options)
        context = browser.new_context(
            ignore_https_errors=True,
            extra_http_headers={"Cf-Access-Jwt-Assertion": token("fixture-owner")},
        )
        retained = context.request.get(origin + "/api/report").json()
        retained["status"] = "OBSERVING"
        state = {"unavailable": False, "reads": 0, "posts": 0}
        page = context.new_page()
        page.clock.install(time=datetime.now(UTC))

        def report(route: Any) -> None:
            state["reads"] += 1
            route.fulfill(status=503 if state["unavailable"] else 200, json=retained)

        page.route("**/api/report", report)
        page.route("**/api/health", lambda route: route.fulfill(json={"status": "PUBLISHED"}))
        page.on("request", lambda request: state.update(posts=state["posts"] + 1)
                if request.method == "POST" else None)
        page.goto(origin)
        expect(page.locator("#operation")).to_have_text("Observation active")
        page.locator("#wallet-filter").fill("fixture")
        page.locator("#report-start").fill("2026-10-16T00:00")
        page.get_by_role("button", name="STOP acquisition").click()
        expect(page.locator("#receipts")).to_contain_text("REQUESTED")
        commands.finish(1, status="APPLIED")
        page.clock.fast_forward(21000)
        expect(page.locator("#receipts")).to_contain_text("APPLIED")
        assert state["posts"] == 1
        assert page.locator("#wallet-filter").input_value() == "fixture"
        assert page.locator("#report-start").input_value() == "2026-10-16T00:00"
        state["unavailable"] = True
        page.clock.fast_forward(21000)
        expect(page.locator("#error")).to_be_visible()
        page.clock.fast_forward(600000)
        expect(page.locator("#operation")).to_have_text("Retained report is out of date")
        # Deterministically exercise the visibility-event contract in Chromium.
        page.evaluate("""() => {
          Object.defineProperty(document, 'hidden', {configurable:true,get:()=>true});
          document.dispatchEvent(new Event('visibilitychange'));
        }""")
        # Hiding cancels future refreshes; an already started read may finish.
        # Measure new hidden-tab reads only after that serialized load settles.
        page.wait_for_function("inFlight === null")
        reads = state["reads"]
        page.clock.fast_forward(60000)
        assert state["reads"] == reads
        state["unavailable"] = False
        now = page.evaluate("new Date().toISOString()")
        retained["published_at"] = now
        page.evaluate("""() => {
          Object.defineProperty(document, 'hidden', {configurable:true,get:()=>false});
          document.dispatchEvent(new Event('visibilitychange'));
        }""")
        expect(page.locator("#operation")).to_have_text("Worker status is out of date")
        expect(page.locator("#error")).to_be_hidden()
        retained["last_attempt"] = now
        page.clock.fast_forward(21000)
        expect(page.locator("#operation")).to_have_text("Observation active")
        assert state["posts"] == 1
        browser.close()
