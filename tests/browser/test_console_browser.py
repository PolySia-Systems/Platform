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


def test_setup_policy_and_scoped_control_tasks(console_fixture: Any) -> None:
    from playwright.sync_api import expect, sync_playwright

    from polysia.control.service import ControlService
    from polysia.domain.financial_session import SessionBlocked

    origin, token, commands, _ = console_fixture
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(**({"channel": "chrome"} if os.name == "nt" else {}))
        context = browser.new_context(ignore_https_errors=True,
            extra_http_headers={"Cf-Access-Jwt-Assertion": token("fixture-owner")})
        retained = context.request.get(origin + "/api/report").json()
        now = datetime.now(UTC)
        retained.update(
            {
                "capabilities": {
                    "catalog": [
                        {
                            "identity": "backup",
                            "obtain": "Enable separate financial recovery",
                            "validate": "Verify isolated restore",
                        }
                    ],
                    "capabilities": [
                        {
                            "capability": "new_entries",
                            "status": "BLOCKED",
                            "required": ["backup"],
                            "requirements": [
                                {
                                    "identity": "backup",
                                    "state": "MISSING",
                                    "evidence": {
                                        "reason": "Financial backup is unprotected",
                                        "next_action": "Verify isolated restore",
                                        "expires_at": now.isoformat(),
                                    },
                                }
                            ],
                        }
                    ],
                },
                "active_account": {"identity": "fixture-account", "status": "UNKNOWN"},
                "copy_policy": {
                    "effective": {
                        "version": "fixture-fixed-v1",
                        "sizing": "FIXED_DEBIT",
                        "exit_preset": "HYBRID",
                        "reentry": False,
                    },
                    "staged": None,
                    "digest": "fixture-policy",
                },
                "capacity": {
                    "allocation": "FIXED",
                    "actual_requests": 12,
                    "measured_response_bytes": 4000,
                    "queue_depth": 1,
                    "queue_limit": 2,
                    "external_shared_egress_utilization": None,
                },
                "backup": {"mode": "UNPROTECTED", "independent_restore": "UNKNOWN"},
            }
        )
        page = context.new_page()
        page.route("**/api/report", lambda route: route.fulfill(json=retained))
        page.goto(origin)
        timings = {}
        start = time.perf_counter()
        page.get_by_role("link", name="Readiness & Setup").click()
        expect(page.locator("#capability-rows")).to_contain_text("Financial backup is unprotected")
        expect(page.locator("#capability-rows")).to_contain_text("Verify isolated restore")
        expect(page.locator("#backup-readiness")).to_contain_text("UNPROTECTED")
        timings["explain_blocker"] = time.perf_counter() - start
        start = time.perf_counter()
        page.get_by_role("link", name="Policy & Shadow Lab").click()
        expect(page.locator("#policy-summary")).to_contain_text("FIXED_DEBIT")
        expect(page.locator("#policy-summary")).to_contain_text("Re-entry disabled")
        expect(page.locator("#capacity-summary")).to_contain_text("1 / 2")
        timings["explain_policy_and_capacity"] = time.perf_counter() - start
        start = time.perf_counter()
        page.locator("#scoped-target").select_option("fixture-lab")
        page.locator("#scoped-operation").select_option("shadow.drain")
        page.locator("#scoped-preview-button").click()
        expect(page.locator("#scoped-preview")).to_contain_text("Effect: not requested")
        page.locator("#scoped-apply-button").focus()
        page.keyboard.press("Enter")
        expect(page.locator("#scoped-preview")).to_contain_text("REQUESTED")
        pending = commands.pending_scoped(targets=frozenset({"fixture-lab"}),
                                          operations=frozenset({"shadow.drain"}))
        assert len(pending) == 1
        def unavailable(_preview):
            raise SessionBlocked("fixture_owner_unavailable")
        ControlService.execute_scoped(commands, idempotency_key=pending[0], now=datetime.now(UTC),
                                      execute=unavailable)
        page.reload()
        expect(page.locator("#scoped-receipts")).to_contain_text("FAILED")
        timings["preview_request_and_explain_failed_receipt"] = time.perf_counter() - start
        expect(page.locator("#capability-rows")).to_contain_text("Financial backup is unprotected")
        expect(page.locator("#policy-summary")).to_contain_text("FIXED_DEBIT")
        output = Path("output/playwright")
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / "e2-operator-controls.png"), full_page=True)
        (output / "e2-operator-task-times.json").write_text(json.dumps({"task_seconds": timings,
            "samples_per_task": 1, "provider_calls": 0, "human_acceptance": "NOT_OBSERVED",
            "proposed_target_seconds": 60}), encoding="utf-8")
        assert all(duration < 60 for duration in timings.values())
        browser.close()


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
            scoped_targets=frozenset({"fixture-lab", "fixture-session:stop", "fixture-run:stop"}),
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
                "element => element.scrollLeft > 0", arg=financial_region.element_handle()
            )
            page.keyboard.press("ArrowLeft")
            page.wait_for_function(
                "element => element.scrollLeft === 0", arg=financial_region.element_handle()
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
        page.on(
            "request",
            lambda request: (
                state.update(posts=state["posts"] + 1) if request.method == "POST" else None
            ),
        )
        page.goto(origin)
        expect(page.locator("#operation")).to_have_text("Observation active")
        expect(page.locator("#main")).to_have_attribute("aria-busy", "false")
        page.locator("#wallet-filter").fill("fixture")
        page.locator("#report-start").fill("2026-10-16T00:00")
        page.get_by_role("button", name="STOP acquisition").click()
        expect(page.locator("#receipts")).to_contain_text("REQUESTED")
        # Receipts render before the report/health reads finish. Advance the
        # mocked clock only after the next refresh has actually been scheduled.
        expect(page.locator("#main")).to_have_attribute("aria-busy", "false")
        commands.finish(1, status="APPLIED")
        page.clock.fast_forward(21000)
        expect(page.locator("#receipts")).to_contain_text("APPLIED")
        expect(page.locator("#main")).to_have_attribute("aria-busy", "false")
        assert state["posts"] == 1
        assert page.locator("#wallet-filter").input_value() == "fixture"
        assert page.locator("#report-start").input_value() == "2026-10-16T00:00"
        state["unavailable"] = True
        page.clock.fast_forward(21000)
        expect(page.locator("#error")).to_be_visible()
        expect(page.locator("#main")).to_have_attribute("aria-busy", "false")
        page.clock.fast_forward(600000)
        expect(page.locator("#operation")).to_have_text("Retained report is out of date")
        # Deterministically exercise the visibility-event contract in Chromium.
        page.evaluate("""() => {
          Object.defineProperty(document, 'hidden', {configurable:true,get:()=>true});
          document.dispatchEvent(new Event('visibilitychange'));
        }""")
        # Hiding cancels future refreshes; an already started read may finish.
        # Measure new hidden-tab reads only after that serialized load settles.
        expect(page.locator("#main")).to_have_attribute("aria-busy", "false")
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
        expect(page.locator("#main")).to_have_attribute("aria-busy", "false")
        retained["last_attempt"] = now
        page.clock.fast_forward(21000)
        expect(page.locator("#operation")).to_have_text("Observation active")
        assert state["posts"] == 1
        browser.close()


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_discovery_pagination_and_four_financial_operator_tasks(
    console_fixture: Any, width: int, height: int
) -> None:
    """Synthetic comprehension automation, not actual human acceptance."""
    from playwright.sync_api import expect, sync_playwright

    origin, token, commands, _digest = console_fixture
    with sync_playwright() as runtime:
        options = {"channel": "chrome"} if os.name == "nt" else {}
        browser = runtime.chromium.launch(**options)
        context = browser.new_context(
            ignore_https_errors=True,
            viewport={"width": width, "height": height},
            extra_http_headers={"Cf-Access-Jwt-Assertion": token("fixture-reader")},
        )
        retained = context.request.get(origin + "/api/report").json()
        now = datetime.now(UTC).isoformat()
        retained["published_at"] = retained["last_attempt"] = now
        retained["selection"] = {
            "monitored_count": 3,
            "records": [
                {
                    "wallet_id": f"fixture-wallet-{index:04d}",
                    "state": "QUALIFIED" if index == 999 else "DISCOVERED",
                    "sources": ["native", "polycop"] if index == 999 else ["native"],
                    "execution_eligibility": "ELIGIBLE" if index == 999 else "UNKNOWN",
                    "reasons": ["sufficient_sample", "exit_depth_verified"] if index == 999 else [],
                    "exclusions": [] if index == 999 else ["unpriced_fees"],
                    "last_qualifying_activity": now,
                }
                for index in range(1000)
            ],
        }
        retained["financial_session"] = {
            "status": "DRAIN",
            "scope": "Synthetic bounded financial-session fixture",
            "activation": "NOT_ACTIVATED",
            "trading_mode": "PAPER",
            "observed_at": now,
            "remaining_authority": {"status": "ENTRY_EXPIRED", "attempts": 2, "requests": 20},
            "exposure": {"cash": "97.9", "reserved": "2.1", "reconciliation": "BLOCKED"},
            "incidents": [
                {
                    "reason": "uncertain_submission",
                    "scope": "account session",
                    "at": now,
                    "next_action": "Reconcile the existing intent before any new entry.",
                }
            ],
            "sources": [
                {
                    "source": "polycop",
                    "status": "FAILED",
                    "phase": "refresh",
                    "age_seconds": 180,
                    "gaps": ["HTTP_429", "incomplete_page"],
                    "next_action": (
                        "Preserve the last complete snapshot; wait within the request budget."
                    ),
                }
            ],
            "orders": [
                {
                    "intent_id": "fixture-intent-9",
                    "order_id": None,
                    "state": "UNCERTAIN_SUBMIT",
                    "side": "BUY",
                    "token": "fixture-token",
                    "updated_at": now,
                    "reason": "Timeout after durable submit claim.",
                }
            ],
            "latency": {
                "bottleneck": "queue/rate wait",
                "sample_count": 20,
                "missing_count": 2,
                "censored_count": 1,
                "clock_quality": "SOURCE_UNVERIFIED",
            },
            "economics": {
                "status": "PARTIAL",
                "realized_pnl": "-0.1",
                "fees": "0.02",
                "unrealized_pnl": None,
                "net_pnl": None,
                "source_value": {"overlap_count": 1, "exclusive_coverage": {"native": 999}},
            },
        }
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/api/report", lambda route: route.fulfill(json=retained))
        page.route("**/api/health", lambda route: route.fulfill(json={"status": "PUBLISHED"}))
        page.goto(origin)
        expect(page.locator("#wallet-page-status")).to_contain_text(
            "1–50 of 1000 matching / 1000 available discovery records"
        )
        expect(page.locator("#wallet-page-status")).to_contain_text("Active bounded monitors: 3")
        assert page.locator("#wallets tr").count() == 50
        expect(page.get_by_role("button", name="Previous discovery page")).to_be_disabled()
        page.get_by_role("button", name="Next discovery page").focus()
        page.keyboard.press("Enter")
        expect(page.locator("#wallet-page-status")).to_contain_text("51–100")
        page.get_by_role("button", name="Previous discovery page").click()
        expect(page.locator("#wallet-page-status")).to_contain_text("Page 1 of 20")

        task_durations: dict[str, float] = {}
        started = time.perf_counter()
        page.get_by_role("link", name="Sources & Wallets").click()
        expect(page.locator("#source-health")).to_contain_text("polycop")
        expect(page.locator("#source-health")).to_contain_text("FAILED")
        expect(page.locator("#source-health")).to_contain_text("incomplete_page")
        expect(page.locator("#source-health")).to_contain_text(
            "Preserve the last complete snapshot"
        )
        task_durations["failed_source"] = time.perf_counter() - started

        started = time.perf_counter()
        page.get_by_label("Wallet identity hash").fill("0999")
        expect(page.locator("#wallets tr")).to_have_count(1)
        page.get_by_role("button", name="fixture-wallet-0999").focus()
        page.keyboard.press("Enter")
        expect(page.locator("#wallet-detail")).to_contain_text("exit_depth_verified")
        expect(page.locator("#wallet-detail")).to_contain_text("native, polycop")
        expect(page.locator("#wallet-detail")).to_contain_text("does not grant execution authority")
        task_durations["selected_wallet_rationale"] = time.perf_counter() - started

        started = time.perf_counter()
        page.get_by_role("link", name="Execution & Health").click()
        expect(page.locator("#session-timing")).to_contain_text("queue/rate wait")
        expect(page.locator("#session-timing")).to_contain_text("Missing / censored: 2 / 1")
        task_durations["timing_bottleneck"] = time.perf_counter() - started

        started = time.perf_counter()
        page.get_by_label("Order or intent identity").fill("fixture-intent-9")
        expect(page.locator("#order-timeline")).to_contain_text("UNCERTAIN_SUBMIT")
        expect(page.locator("#order-timeline")).to_contain_text(
            "Timeout after durable submit claim"
        )
        expect(page.locator("#session-incidents")).to_contain_text("before any new entry")
        task_durations["actual_order_state"] = time.perf_counter() - started

        expect(page.locator("#session-authority")).to_contain_text("ENTRY_EXPIRED")
        expect(page.locator("#session-scope")).to_contain_text("NOT_ACTIVATED")
        expect(page.locator("#session-exposure")).to_contain_text("2.1")
        page.get_by_role("link", name="Economics & Source Value").click()
        expect(page.locator("#actual-economics-state")).to_contain_text("PARTIAL")
        expect(page.locator("#actual-economics")).to_contain_text("UNKNOWN")
        expect(
            page.get_by_text("Source-removal replay is a counterfactual estimate", exact=False)
        ).to_be_visible()
        page.get_by_label("Wallet identity hash").fill("does-not-exist")
        expect(page.locator("#wallets")).to_have_text("No discovery records match this search.")
        assert commands.pending() == []
        assert not errors
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        output = Path("output/playwright")
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / f"financial-console-{width}.png"), full_page=True)
        (output / f"financial-operator-tasks-{width}.json").write_text(
            json.dumps(
                {
                    "dataset": "synthetic 1000 discovery records, 3 monitored, 1 uncertain order",
                    "provider_calls": 0,
                    "task_seconds": task_durations,
                    "human_acceptance": "NOT_OBSERVED",
                    "proposed_human_target_seconds": 60,
                    "automated_tasks_under_target": all(
                        value < 60 for value in task_durations.values()
                    ),
                }
            ),
            encoding="utf-8",
        )
        browser.close()


def test_financial_console_loading_missing_empty_and_unavailable_states(
    console_fixture: Any,
) -> None:
    from playwright.sync_api import expect, sync_playwright

    origin, token, _commands, _digest = console_fixture
    with sync_playwright() as runtime:
        options = {"channel": "chrome"} if os.name == "nt" else {}
        browser = runtime.chromium.launch(**options)
        context = browser.new_context(
            ignore_https_errors=True,
            extra_http_headers={"Cf-Access-Jwt-Assertion": token("fixture-reader")},
        )
        retained = context.request.get(origin + "/api/report").json()
        retained["diagnostic"]["discovery"]["candidates"] = []
        held: list[Any] = []
        page = context.new_page()
        page.route("**/api/report", lambda route: held.append(route))
        page.goto(origin)
        expect(page.locator("#session-status")).to_contain_text("Loading")
        expect(page.locator("#wallet-page-status")).to_contain_text("Loading")
        expect(page.locator("#main")).to_have_attribute("aria-busy", "true")
        page.wait_for_function("document.readyState === 'complete'")
        assert len(held) == 1
        held[0].fulfill(json=retained)
        expect(page.locator("#main")).to_have_attribute("aria-busy", "false")
        expect(page.locator("#session-status")).to_contain_text("No financial-session receipt")
        expect(page.locator("#order-timeline")).to_contain_text("Actual order state is UNKNOWN")
        expect(page.locator("#wallets")).to_have_text(
            "No retained discovery records are available."
        )
        expect(page.locator("#source-health")).to_contain_text("Source health is UNKNOWN")
        expect(page.get_by_role("button", name="Next discovery page")).to_be_disabled()
        unavailable = context.new_page()
        unavailable.route("**/api/report", lambda route: route.fulfill(status=503, json={}))
        unavailable.goto(origin)
        expect(unavailable.locator("#error")).to_contain_text("Publication unavailable (503)")
        expect(unavailable.locator("#session-status")).to_contain_text("UNKNOWN")
        expect(unavailable.locator("#operation")).to_have_text("Publication unavailable")
        browser.close()


def test_console_renders_actual_financial_and_cohort_producer_contracts(
    console_fixture: Any,
) -> None:
    """Exercise real pure projectors, including empty selected exclusion reasons."""
    from decimal import Decimal

    from playwright.sync_api import expect, sync_playwright

    from polysia.application.services.source_cohort import SharedCohortSelection
    from polysia.domain.financial_session import (
        InstrumentScope,
        RuntimeBinding,
        SessionAuthorization,
    )
    from polysia.domain.wallet_intelligence import normalize_evm_wallet
    from polysia.domain.wallet_intelligence.source_cohort import CohortCandidate
    from polysia.monitoring.financial_session import financial_session_view

    now = datetime.now(UTC)
    wallet_id = normalize_evm_wallet("polygon", "0x" + "1" * 40)[0]
    ranking = (
        "Rank 1: comparable follower net, confidence, and exit depth; provider score excluded."
    )
    selection = SharedCohortSelection(
        policy_version="fixture-selection-v1",
        selected_at=now,
        candidates=(
            CohortCandidate(
                wallet_id=wallet_id,
                sources=("native", "polycop"),
                current_sources=("native", "polycop"),
                state="SELECTED",
                reasons=(),
                rank=1,
                evidence_id="fictional-comparable-evidence",
                evaluation_start=now + timedelta(minutes=1),
                ranking_explanation=ranking,
            ),
        ),
        sources=(),
        qualification_evidence=(),
        digest=hashlib.sha256(b"fictional-projection-fixture").hexdigest(),
    )
    authority = SessionAuthorization(
        version=1,
        run_id="fictional-projection-run",
        owner_receipt="fixture-no-authority-granted",
        granted=False,
        binding=RuntimeBinding(
            "fixture-release", "fixture-config", "fixture-policy", "private-fixture-account", "host"
        ),
        starts_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=10),
        protective_until=now + timedelta(minutes=20),
        wallets=frozenset({wallet_id}),
        instruments=(InstrumentScope("market", "token", "collateral", "route"),),
        strategy="fixture-strategy",
        exit_policy="leader-reduction-v1",
        max_order_all_in=Decimal("1"),
        max_open_exposure=Decimal("2"),
        max_turnover=Decimal("2"),
        max_total_loss=Decimal("2"),
        max_daily_loss=Decimal("2"),
        max_market_exposure=Decimal("2"),
        max_wallet_exposure=Decimal("2"),
        max_positions=1,
        max_concurrent_orders=1,
        max_attempts=1,
        fee_rate=Decimal("0.01"),
        max_evidence_age_seconds=30,
        supervision_timeout_seconds=10,
        max_holding_seconds=30,
        dust_shares=Decimal("0.001"),
        max_requests=10,
        protective_request_reserve=1,
        max_response_bytes=10000,
        max_storage_bytes=1000000,
        max_source_cost=Decimal("0"),
        restart_policy="DENY",
        protective_actions=frozenset(),
    )
    state = {
        "opening": {"cash": "100"},
        "fills": [],
        "orders": {},
        "decisions": {},
        "equity": [],
        "mode": "STOP",
        "attempts": 0,
        "turnover": "0",
        "requests": 0,
        "source_cost": "0",
        "reconciliation_ok": False,
        "incidents": [],
    }
    origin, token, commands, _digest = console_fixture
    with sync_playwright() as runtime:
        options = {"channel": "chrome"} if os.name == "nt" else {}
        browser = runtime.chromium.launch(**options)
        context = browser.new_context(
            ignore_https_errors=True,
            extra_http_headers={"Cf-Access-Jwt-Assertion": token("fixture-reader")},
        )
        retained = context.request.get(origin + "/api/report").json()
        retained["published_at"] = retained["last_attempt"] = now.isoformat()
        retained["financial_session"] = financial_session_view(state, authority, now=now)
        retained["selection"] = selection.to_console_dict()
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/api/report", lambda route: route.fulfill(json=retained))
        page.route("**/api/health", lambda route: route.fulfill(json={"status": "PUBLISHED"}))
        page.goto(origin)
        expect(page.locator("#session-status")).to_contain_text(now.isoformat())
        expect(page.locator("#session-status")).to_contain_text("Recorded mode: DATA_ONLY")
        expect(page.locator("#session-scope")).to_contain_text("bounded session library")
        expect(page.locator("#session-scope")).to_contain_text("NOT_COMMISSIONED")
        expect(page.locator("#session-authority")).to_contain_text("DENIED")
        expect(page.locator("#actual-economics-state")).to_contain_text("NO_FINANCIAL_OBSERVATIONS")
        expect(
            page.locator("#actual-economics tr").filter(has_text="Net trading result")
        ).to_contain_text("UNKNOWN")
        expect(page.locator("#source-value")).to_have_text(
            retained["financial_session"]["economics"]["source_value"]
        )
        page.get_by_label("Wallet identity hash").fill("provider score excluded")
        expect(page.locator("#wallets tr")).to_have_count(1)
        page.get_by_role("button", name=wallet_id).click()
        expect(page.locator("#wallet-detail")).to_contain_text(ranking)
        expect(page.locator("#wallet-detail")).to_contain_text("Exclusions: None recorded")
        expect(page.locator("#wallet-detail")).to_contain_text(
            "NOT_AUTHORIZED_BY_DISCOVERY_OR_SELECTION"
        )
        assert "private-fixture-account" not in page.locator("body").inner_text()
        assert commands.pending() == []
        assert not errors
        browser.close()
