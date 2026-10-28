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
            scoped_targets=frozenset(
                {
                    "fixture-lab",
                    "fixture-lab-two",
                    "fixture-session:stop",
                    "fixture-run:stop",
                    "fixture-run:drain",
                }
            ),
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


@pytest.fixture
def rich_console(console_fixture, tmp_path):
    import asyncio

    from tests.fixtures.console_h2 import lab, write

    owner = lab(tmp_path / "lab")
    try:
        retained = write(tmp_path, lab_view=owner.console_view())
        yield (*console_fixture, retained, tmp_path)
    finally:
        asyncio.run(owner.close())


def browser_context(runtime, origin, token, *, width=1440, role="fixture-owner"):
    browser = runtime.chromium.launch(**({"channel": "chrome"} if os.name == "nt" else {}))
    context = browser.new_context(
        ignore_https_errors=True,
        viewport={"width": width, "height": 1000},
        extra_http_headers={"Cf-Access-Jwt-Assertion": token(role)},
    )
    return browser, context


def request_action(page, operation="acquisition.stop|acquisition"):
    from playwright.sync_api import expect

    page.get_by_role("button", name="Operate", exact=True).click()
    page.locator("#operation").select_option(operation)
    page.get_by_role("button", name="Preview operation", exact=True).click()
    expect(page.get_by_role("dialog")).to_be_visible()
    page.get_by_role("button", name="Request exact operation", exact=True).focus()
    page.keyboard.press("Enter")
    expect(page.get_by_role("dialog")).not_to_be_visible()
    expect(page.get_by_text("REQUESTED", exact=True).first).to_be_visible()


def test_setup_policy_and_scoped_control_tasks(console_fixture, tmp_path):
    import asyncio

    from playwright.sync_api import expect, sync_playwright

    from polysia.control.service import ControlService
    from tests.fixtures.console_h2 import lab, write

    owner = lab(tmp_path / "lab")
    write(tmp_path, wallets=4, orders=2, lab_view=owner.console_view())
    origin, token, commands, _ = console_fixture
    try:
        with sync_playwright() as runtime:
            browser, context = browser_context(runtime, origin, token)
            page = context.new_page()
            page.goto(origin)
            page.get_by_role("button", name="System / Setup", exact=True).click()
            expect(page.get_by_label("Configured, verified and authorized")).to_contain_text(
                "Verify isolated restore"
            )
            expect(page.get_by_label("Financial backup and independent restore")).to_contain_text(
                "UNPROTECTED"
            )
            page.get_by_role("button", name="Operate", exact=True).click()
            expect(page.get_by_label("Effective and staged policy")).to_contain_text("FIXED_DEBIT")
            page.locator("#operation").select_option("shadow.create|fixture-lab")
            page.get_by_label("Registered policy digest").select_option(next(iter(owner.templates)))
            page.get_by_role("button", name="Preview operation", exact=True).click()
            expect(page.get_by_role("dialog")).to_contain_text(next(iter(owner.templates)))
            page.get_by_role("button", name="Request exact operation", exact=True).click()
            expect(page.get_by_text("REQUESTED", exact=True).first).to_be_visible()
            pending = commands.pending_scoped(
                targets=owner.targets, operations=frozenset({"shadow.create"})
            )
            assert len(pending) == 1
            ControlService.execute_scoped(
                commands, idempotency_key=pending[0], now=datetime.now(UTC), execute=owner.execute
            )
            assert owner.slot("fixture-lab")["phase"] == "CREATED"
            page.get_by_role("button", name="Refresh evidence", exact=False).click()
            expect(page.get_by_text("OBSERVED", exact=True).first).to_be_visible()
            browser.close()
    finally:
        asyncio.run(owner.close())


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_console_operator_tasks_and_protected_downloads(rich_console, width, height):
    from playwright.sync_api import expect, sync_playwright

    origin, token, commands, digest, _, _ = rich_console
    with sync_playwright() as runtime:
        browser, context = browser_context(runtime, origin, token, width=width)
        page = context.new_page()
        page.goto(origin)
        page.get_by_role("button", name="Evaluate", exact=True).click()
        expect(page.get_by_label("Same-tape Shadow comparison")).to_contain_text("-1")
        page.get_by_role("link", name="Download same-tape comparison CSV", exact=True).focus()
        with page.expect_download() as download:
            page.keyboard.press("Enter")
        assert digest in Path(download.value.path()).read_text()
        page.get_by_role("button", name="Investigate", exact=True).click()
        page.get_by_label("Record type").select_option("wallet")
        page.get_by_label("Search exact identity").fill("wallet-00123")
        page.get_by_role("button", name="Search", exact=True).click()
        page.get_by_role("button", name="wallet-00123", exact=True).click()
        expect(page.get_by_label("Evidence detail", exact=True)).to_contain_text("unpriced_fees")
        request_action(page)
        assert commands.pending() == [(1, "stop")]
        page.goto(origin + "/?example=1")
        expect(
            page.get_by_text("Synthetic example. No financial readiness or commands.", exact=True)
        ).to_be_visible()
        page.get_by_role("button", name="Operate", exact=True).click()
        expect(page.get_by_role("button", name="Preview operation", exact=True)).to_be_disabled()
        assert commands.pending() == [(1, "stop")]
        browser.close()


def test_console_ages_recovers_refreshes_and_observes_async_receipts(rich_console):
    from playwright.sync_api import expect, sync_playwright

    origin, token, commands, _, _, _ = rich_console
    with sync_playwright() as runtime:
        browser, context = browser_context(runtime, origin, token)
        page = context.new_page()
        page.clock.install()
        calls = []
        page.on("request", lambda request: calls.append((request.method, request.url)))
        page.goto(origin)
        request_action(page)
        expect(page.locator("#main")).to_have_attribute("aria-busy", "false")
        commands.finish(1, status="APPLIED")
        page.clock.fast_forward(15001)
        expect(page.get_by_text("OBSERVED", exact=True).first).to_be_visible()
        assert len([method for method, _ in calls if method == "POST"]) == 2
        page.locator("#operation").select_option("acquisition.export|acquisition")
        page.get_by_label("Optional start (UTC)").fill("2026-10-01T00:00")
        page.get_by_label("Optional end (UTC)").fill("2026-10-02T00:00")
        page.clock.fast_forward(15001)
        expect(page.locator("#main")).to_have_attribute("aria-busy", "false")
        expect(page.get_by_label("Optional start (UTC)")).to_have_value("2026-10-01T00:00")
        page.evaluate(
            "Object.defineProperty(document,'hidden',{configurable:true,get:()=>tru"
            "e});document.dispatchEvent(new Event('visibilitychange'))"
        )
        reads = len([method for method, _ in calls if method == "GET"])
        page.clock.fast_forward(60000)
        assert len([method for method, _ in calls if method == "GET"]) == reads
        page.evaluate(
            "Object.defineProperty(document,'hidden',{configurable:true,get:()=>fal"
            "se});document.dispatchEvent(new Event('visibilitychange'))"
        )
        expect(page.locator("#main")).to_have_attribute("aria-busy", "false")
        assert len([method for method, _ in calls if method == "POST"]) == 2
        browser.close()


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_discovery_pagination_and_four_financial_operator_tasks(rich_console, width, height):
    from playwright.sync_api import expect, sync_playwright

    origin, token, _, _, retained, _ = rich_console
    with sync_playwright() as runtime:
        browser, context = browser_context(
            runtime, origin, token, width=width, role="fixture-reader"
        )
        page = context.new_page()
        page.goto(origin)
        expect(page.get_by_label("Session context", exact=True)).to_contain_text("PAPER")
        expect(page.get_by_label("Independent supervision", exact=True)).to_contain_text("STOPPED")
        page.get_by_role("button", name="Investigate", exact=True).click()
        page.get_by_label("Record type").select_option("wallet")
        page.get_by_role("button", name="Search", exact=True).click()
        expect(page.get_by_text("50 / 10000 observations", exact=True)).to_be_visible()
        page.get_by_role("button", name="Next 50", exact=True).click()
        expect(page.get_by_role("button", name="wallet-00050", exact=True)).to_be_visible()
        page.get_by_label("Search exact identity").fill("wallet-09999")
        page.get_by_role("button", name="Search", exact=True).click()
        page.get_by_role("button", name="wallet-09999", exact=True).click()
        expect(page.get_by_label("Evidence detail", exact=True)).to_contain_text(
            "provider score excluded"
        )
        page.get_by_label("Record type").select_option("position")
        page.get_by_role("button", name="Search", exact=True).click()
        page.get_by_role("button", name="token", exact=True).click()
        expect(page.get_by_label("Evidence detail", exact=True)).to_contain_text("OPEN")
        expect(page.get_by_label("Evidence detail", exact=True)).to_contain_text("redeemable")
        page.get_by_role("button", name="Retained order · order-00000", exact=True).click()
        expect(page.get_by_label("Evidence detail", exact=True)).to_contain_text("Fill fill-")
        expect(page.get_by_label("Evidence detail", exact=True)).to_contain_text(
            retained["financial_session"]["orders"][0]["trigger_id"]
        )
        page.get_by_role("button", name="System / Setup", exact=True).click()
        expect(
            page.get_by_label("Incidents and notification delivery", exact=True)
        ).to_contain_text("NOT_CONFIGURED")
        expect(page.get_by_label("Source capacity and timing", exact=True)).to_contain_text(
            "UNKNOWN"
        )
        browser.close()


def test_financial_console_loading_missing_empty_and_unavailable_states(console_fixture, tmp_path):
    from playwright.sync_api import expect, sync_playwright

    origin, token, _, _ = console_fixture
    (tmp_path / "publication.json").write_text("{malformed", encoding="utf-8")
    with sync_playwright() as runtime:
        browser, context = browser_context(runtime, origin, token)
        page = context.new_page()
        page.goto(origin)
        expect(page.get_by_label("Exact financial amounts", exact=True)).to_contain_text("UNKNOWN")
        page.get_by_role("button", name="Operate", exact=True).click()
        page.locator("#operation").select_option("acquisition.stop|acquisition")
        page.get_by_role("button", name="Preview operation", exact=True).click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.keyboard.press("Escape")
        page.goto(origin + "/?example=1")
        expect(page.get_by_label("Session context", exact=True)).to_contain_text("SYNTHETIC")
        page.get_by_role("button", name="Investigate", exact=True).click()
        page.get_by_role("button", name="Search", exact=True).click()
        expect(
            page.get_by_text("No matching records in this retained generation.", exact=True)
        ).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        browser.close()


def test_console_renders_actual_financial_and_cohort_producer_contracts(
    console_fixture: Any,
    tmp_path: Path,
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
    retained = json.loads((tmp_path / "publication.json").read_text())
    retained["published_at"] = now.isoformat()
    retained["financial_session"] = financial_session_view(state, authority, now=now)
    retained["selection"] = selection.to_console_dict()
    (tmp_path / "publication.json").write_text(json.dumps(retained), encoding="utf-8")
    with sync_playwright() as runtime:
        browser, context = browser_context(runtime, origin, token, role="fixture-reader")
        page = context.new_page()
        page.goto(origin)
        expect(page.get_by_label("Session context", exact=True)).to_contain_text("DATA_ONLY")
        # The retained denial remains exact, while absent account evidence and
        # blocked reconciliation cannot become a current financial-ready badge.
        snapshot = context.request.get(origin + "/api/console/v1/snapshot").json()
        assert snapshot["financial"]["authority"] == "DENIED"
        assert snapshot["financial"]["cash"]["value"] is None
        expect(
            page.get_by_role("heading", name="Financial authority").locator("..")
        ).to_contain_text("UNKNOWN")
        expect(page.get_by_text("UNKNOWN_RECONCILIATION_BLOCKED", exact=True)).to_be_visible()
        page.get_by_role("button", name="Investigate", exact=True).click()
        page.get_by_label("Record type").select_option("wallet")
        page.get_by_label("Search exact identity").fill("provider score excluded")
        page.get_by_role("button", name="Search", exact=True).click()
        page.get_by_role("button", name=wallet_id, exact=True).click()
        expect(page.get_by_label("Evidence detail", exact=True)).to_contain_text(ranking)
        expect(page.get_by_label("Evidence detail", exact=True)).to_contain_text(
            "NOT_AUTHORIZED_BY_DISCOVERY_OR_SELECTION"
        )
        assert "private-fixture-account" not in page.locator("body").inner_text()
        assert commands.pending() == []
        browser.close()
