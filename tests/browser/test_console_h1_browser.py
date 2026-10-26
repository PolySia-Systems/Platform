"""Installed protected H1 slice with real producers/command owner and synthetic custody."""

from __future__ import annotations

import json
import os
import platform
import statistics
import time
from pathlib import Path
from typing import Any

import pytest

from tests.browser.test_console_browser import console_fixture as base_console_fixture  # noqa: F401
from tests.fixtures.console_h1 import protective_owner, write_publication

pytestmark = pytest.mark.skipif(
    os.getenv("POLYSIA_BROWSER_TESTS") != "1",
    reason="explicit synthetic installed-browser job only",
)
PREFIX = "/api/console/v1"
OUTPUT = Path("output/playwright")


@pytest.fixture
def h1_fixture(base_console_fixture: Any, tmp_path: Path) -> Any:  # noqa: F811
    origin, token, commands, _ = base_console_fixture
    publication = write_publication(tmp_path, wallets=10_000, orders=200)
    owner, custody = protective_owner(tmp_path, commands)
    return origin, token, commands, publication, owner, custody, tmp_path


def launch(runtime):
    return runtime.chromium.launch(**({"channel": "chrome"} if os.name == "nt" else {}))


def context_for(browser, origin, token, *, width=1440):
    return browser.new_context(
        ignore_https_errors=True,
        viewport={"width": width, "height": 1000},
        extra_http_headers={"Cf-Access-Jwt-Assertion": token("fixture-owner")},
    )


@pytest.mark.parametrize("width", [1440, 390])
def test_h1_production_csp_visual_detail_and_real_supervisor_receipt(h1_fixture, width):
    from playwright.sync_api import expect, sync_playwright

    origin, token, commands, publication, owner, custody, _ = h1_fixture
    with sync_playwright() as runtime:
        browser = launch(runtime)
        context = context_for(browser, origin, token, width=width)
        context.add_init_script(
            "window.cspViolations=[];document.addEventListener('securitypolicyviolation',e=>window.cspViolations.push(e.violatedDirective+':'+e.blockedURI))"
        )
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        response = page.goto(origin + "/h1")
        assert "unsafe-inline" not in response.headers["content-security-policy"]
        assert "unsafe-eval" not in response.headers["content-security-policy"]
        expect(page.get_by_role("heading", name="A clear view of the session.")).to_be_visible()
        expect(page.get_by_label("Session context")).to_contain_text("PAPER")
        expect(page.get_by_label("Exact financial amounts")).to_contain_text(
            publication["financial_session"]["exposure"]["reserved"]
        )
        expect(page.get_by_label("Independent supervision")).to_contain_text("STOPPED")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        OUTPUT.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(OUTPUT / f"h1-overview-{width}.png"), full_page=True)
        page.get_by_role("button", name="Investigate", exact=True).click()
        page.get_by_role("button", name="Search", exact=True).click()
        expect(page.get_by_role("button", name="order-00000", exact=True)).to_be_visible()
        page.get_by_role("button", name="Next 50", exact=True).click()
        expect(page.get_by_role("button", name="order-00050", exact=True)).to_be_visible()
        page.get_by_label("Search exact identity").fill("00199")
        page.get_by_role("button", name="Search", exact=True).click()
        page.get_by_role("button", name="order-00199", exact=True).click()
        expect(page.get_by_label("Evidence detail")).to_contain_text("Only retained producer links")
        page.screenshot(path=str(OUTPUT / f"h1-investigate-{width}.png"), full_page=True)
        page.get_by_role("button", name="Operate", exact=True).first.click()
        page.locator("#operation").select_option("session.stop|fixture-run:stop")
        page.get_by_role("button", name="Preview operation", exact=True).click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text("fixture-run:stop")
        # Focus is trapped in the actual Mantine portal under shipped CSP.
        page.keyboard.press("Tab")
        assert dialog.evaluate("element => element.contains(document.activeElement)")
        page.screenshot(path=str(OUTPUT / f"h1-preview-{width}.png"), full_page=True)
        page.get_by_role("button", name="Request exact operation", exact=True).focus()
        page.keyboard.press("Enter")
        expect(dialog).not_to_be_visible()
        expect(page.get_by_text("REQUESTED", exact=True).first).to_be_visible()
        pending = commands.pending_scoped(
            targets=frozenset({"fixture-run:stop"}), operations=frozenset({"session.stop"})
        )
        assert len(pending) == 1
        owner.process_controls()
        assert custody.snapshot(owner.authority.fingerprint)["reason"] == "scoped_operator_STOP"
        page.reload()
        page.get_by_role("button", name="Operate", exact=True).first.click()
        expect(page.get_by_text("APPLIED", exact=True)).to_be_visible()
        expect(page.get_by_text("OBSERVED", exact=True)).to_be_visible()
        assert not errors, errors
        assert page.evaluate("window.cspViolations") == []
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        browser.close()


def test_h1_lost_apply_response_exact_recovery_and_no_duplicate_effect(h1_fixture):
    from playwright.sync_api import expect, sync_playwright

    origin, token, commands, _, owner, custody, _ = h1_fixture
    with sync_playwright() as runtime:
        browser = launch(runtime)
        context = context_for(browser, origin, token)
        page = context.new_page()
        page.goto(origin + "/h1")
        page.get_by_role("button", name="Operate", exact=True).first.click()
        page.locator("#operation").select_option("session.stop|fixture-run:stop")
        page.get_by_role("button", name="Preview operation", exact=True).click()
        expect(page.get_by_role("dialog")).to_be_visible()
        keys = []

        def lost(route):
            payload = route.request.post_data_json
            keys.append(payload["idempotency_key"])
            response = route.fetch()
            assert response.status == 202
            route.abort("failed")

        page.route("**" + PREFIX + "/apply", lost)
        page.get_by_role("button", name="Request exact operation").click()
        expect(page.get_by_text("Response lost.", exact=False)).to_be_visible()
        assert (
            len(
                commands.pending_scoped(
                    targets=frozenset({"fixture-run:stop"}), operations=frozenset({"session.stop"})
                )
            )
            == 1
        )
        owner.process_controls()
        page.get_by_role("button", name="Recover exact receipt").click()
        expect(page.get_by_text("APPLIED", exact=True)).to_be_visible()
        assert len(keys) == 1
        assert custody.snapshot(owner.authority.fingerprint)["reason"] == "scoped_operator_STOP"
        page.reload()
        page.get_by_role("button", name="Operate", exact=True).first.click()
        expect(page.get_by_text(keys[0], exact=True)).to_be_visible()
        browser.close()


def test_h1_absent_receipt_stays_pinned_across_context_and_visibility_change(h1_fixture):
    from playwright.sync_api import expect, sync_playwright

    origin, token, commands, _, _, _, _ = h1_fixture
    with sync_playwright() as runtime:
        browser = launch(runtime)
        context = context_for(browser, origin, token)
        page = context.new_page()
        page.goto(origin + "/h1")
        page.get_by_role("button", name="Operate", exact=True).first.click()
        page.locator("#operation").select_option("session.stop|fixture-run:stop")
        page.get_by_role("button", name="Preview operation").click()
        expect(page.get_by_role("dialog")).to_be_visible()
        keys = []

        def no_dispatch(route):
            keys.append(route.request.post_data_json["idempotency_key"])
            route.abort("timedout")

        page.route("**" + PREFIX + "/apply", no_dispatch)
        page.get_by_role("button", name="Request exact operation").click()
        page.get_by_role("button", name="Recover exact receipt").click()
        expect(page.get_by_role("button", name="Resend identical request")).to_be_visible()
        page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow'))")
        expect(page.get_by_role("button", name="Preview operation")).to_be_disabled()
        expect(page.locator("#operation")).to_be_disabled()
        expect(page.get_by_role("button", name="Recover exact receipt")).to_be_visible()
        expect(page.get_by_role("button", name="Resend identical request")).not_to_be_visible()
        expect(page.get_by_text(keys[0], exact=True)).to_be_visible()
        assert len(keys) == 1
        assert (
            commands.pending_scoped(
                targets=frozenset({"fixture-run:stop"}), operations=frozenset({"session.stop"})
            )
            == []
        )
        browser.close()


def test_h1_rtl_zoom_keyboard_error_expiry_and_late_preview(h1_fixture):
    from playwright.sync_api import expect, sync_playwright

    origin, token, _, _, _, _, root = h1_fixture
    with sync_playwright() as runtime:
        browser = launch(runtime)
        context = context_for(browser, origin, token, width=1280)
        page = context.new_page()
        page.goto(origin + "/h1?locale=fa-IR")
        expect(page.get_by_label("Session context")).to_contain_text("PAPER")
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        page.screenshot(path=str(OUTPUT / "h1-rtl.png"), full_page=True)
        # A 200% browser layout zoom: CSS viewport equals 640px at 1280 device pixels.
        page.set_viewport_size({"width": 640, "height": 500})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.tagName") != "BODY"
        page.screenshot(path=str(OUTPUT / "h1-zoom-200.png"), full_page=True)
        page.get_by_role("button", name="Operate", exact=True).first.click()
        page.locator("#operation").select_option("session.stop|fixture-run:stop")

        def late(route):
            response = route.fetch()
            page.locator("#operation").select_option("shadow.drain|fixture-lab")
            route.fulfill(response=response)

        page.route("**" + PREFIX + "/preview", late, times=1)
        with page.expect_response("**" + PREFIX + "/preview") as delivered:
            page.get_by_role("button", name="Preview operation").click()
        delivered.value.finished()
        expect(page.locator("#operation")).to_have_value("shadow.drain|fixture-lab")
        expect(page.get_by_role("dialog")).not_to_be_visible()
        (root / "publication.json").unlink()
        page.get_by_role("button", name="Refresh evidence").click()
        page.locator("#operation").select_option("session.stop|fixture-run:stop")
        page.get_by_role("button", name="Preview operation").click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.clock.install()
        page.clock.fast_forward(121_000)
        expect(page.get_by_role("dialog")).not_to_be_visible()
        # Real gateway denial; no authenticated read can resurrect an expired identity.
        context.set_extra_http_headers({"Cf-Access-Jwt-Assertion": "expired-fixture-token"})
        page.get_by_role("button", name="Refresh evidence").click()
        expect(page.get_by_role("alert")).to_contain_text("Authentication changed")
        expect(page.get_by_role("button", name="Preview operation")).to_be_disabled()
        page.screenshot(path=str(OUTPUT / "h1-auth-error.png"), full_page=True)
        browser.close()


def test_h1_optional_requests_cannot_block_protective_stop(h1_fixture):
    from playwright.sync_api import expect, sync_playwright

    origin, token, _, _, owner, custody, _ = h1_fixture
    with sync_playwright() as runtime:
        browser = launch(runtime)
        context = context_for(browser, origin, token)
        page = context.new_page()
        page.route("**" + PREFIX + "/snapshot", lambda route: route.abort("timedout"))
        page.route("**" + PREFIX + "/receipts", lambda route: route.abort("timedout"))
        page.goto(origin + "/h1")
        page.get_by_role("button", name="Operate", exact=True).first.click()
        page.locator("#operation").select_option("session.stop|fixture-run:stop")
        page.get_by_role("button", name="Preview operation").click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.get_by_role("button", name="Request exact operation").click()
        expect(page.get_by_text("REQUESTED", exact=True)).to_be_visible()
        owner.process_controls()
        assert custody.snapshot(owner.authority.fingerprint)["reason"] == "scoped_operator_STOP"
        browser.close()


def test_h1_reference_footprint_100_interactions_and_1000_refresh_cycles(h1_fixture, monkeypatch):
    from playwright.sync_api import expect, sync_playwright

    import polysia.monitoring.console as console_module
    from polysia.control.service import ControlService

    origin, token, commands, _, owner, _, _ = h1_fixture
    from datetime import UTC, datetime

    plan = ControlService.preview_scoped(
        commands,
        operation="session.stop",
        target="fixture-run:stop",
        actor="fixture-owner",
        role="operator",
        allowed_targets=frozenset({"fixture-run:stop"}),
        now=datetime.now(UTC),
    )
    commands.submit_scoped(
        subject="fixture-owner",
        role="operator",
        preview_id=plan.fingerprint,
        expected_revision=0,
        idempotency_key="footprint-fixture-intent",
        now=datetime.now(UTC),
        allowed_targets=frozenset({"fixture-run:stop"}),
    )
    owner.process_controls()
    server_time = [time.time()]
    monkeypatch.setattr(console_module.time, "time", lambda: server_time[0])
    with sync_playwright() as runtime:
        browser = launch(runtime)
        context = context_for(browser, origin, token)
        page = context.new_page()
        cdp = context.new_cdp_session(page)
        start = time.perf_counter()
        page.goto(origin + "/h1")
        expect(page.get_by_label("Exact financial amounts")).to_contain_text("100")
        cold = time.perf_counter() - start
        snapshot_cold_ms = page.evaluate("""() => performance.getEntriesByType('resource')
            .find(entry => entry.name.endsWith('/snapshot'))?.duration ?? null""")
        start = time.perf_counter()
        snapshot_response = context.request.get(origin + PREFIX + "/snapshot")
        snapshot_warm_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        records_response = context.request.get(origin + PREFIX + "/records?kind=wallet")
        records_cold_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        assert context.request.get(origin + PREFIX + "/records?kind=wallet").status == 200
        records_warm_ms = (time.perf_counter() - start) * 1000
        assert snapshot_response.status == records_response.status == 200
        start = time.perf_counter()
        page.reload()
        expect(page.get_by_label("Exact financial amounts")).to_contain_text("100")
        warm = time.perf_counter() - start
        timings = []
        for index in range(100):
            tab = "Operate" if index % 2 == 0 else "Overview"
            start = time.perf_counter()
            page.get_by_role("button", name=tab, exact=True).first.click()
            page.evaluate(
                "() => new Promise(resolve => requestAnimationFrame("
                "() => requestAnimationFrame(resolve)))"
            )
            timings.append((time.perf_counter() - start) * 1000)
        cdp.send("HeapProfiler.collectGarbage")
        baseline = cdp.send("Runtime.getHeapUsage")["usedSize"]
        baseline_nodes = cdp.send("Memory.getDOMCounters")["nodes"]
        requests, failures, posts = [], [], []

        def intermittent_history(route):
            requests.append(route.request.url)
            if len(requests) % 10 == 0:
                failures.append(route.request.url)
                route.abort("timedout")
            else:
                route.continue_()

        page.route("**" + PREFIX + "/receipts", intermittent_history)
        page.on(
            "request",
            lambda request: posts.append(request.url) if request.method == "POST" else None,
        )
        # Ten accelerated 2.5h gaps plus 1,000 fully settled protected refreshes.
        # This is a lab clock jump, never an operational soak or server lifetime claim.
        page.clock.install()
        cycle_start = time.perf_counter()
        refresh_button = page.get_by_role("button", name="Refresh evidence")
        for _ in range(10):
            server_time[0] += 9000  # Actual server CSRF windows rotate alongside browser gaps.
            page.clock.fast_forward(9_000_000)
            expect(refresh_button).to_be_enabled()
            page.evaluate("""async () => {
                const button = [...document.querySelectorAll('button')]
                    .find(b => b.textContent.startsWith('Refresh evidence'));
                for (let i=0;i<100;i++) {
                    const complete = new Promise(resolve => {
                        let started = false;
                        const observer = new MutationObserver(() => {
                            if (button.disabled) started = true;
                            if (started && !button.disabled) {observer.disconnect();resolve();}
                        });
                        observer.observe(button, {attributes:true,attributeFilter:['disabled']});
                    });
                    button.click(); await complete;
                }
            }""")
        cycle_seconds = time.perf_counter() - cycle_start
        cdp.send("HeapProfiler.collectGarbage")
        final = cdp.send("Runtime.getHeapUsage")["usedSize"]
        final_nodes = cdp.send("Memory.getDOMCounters")["nodes"]
        assert page.locator("article").count() < 20
        assert final - baseline < 5 * 1024 * 1024
        assert final_nodes - baseline_nodes < 100
        assert len(requests) >= 1000 and len(failures) >= 100 and posts == []
        p95 = sorted(timings)[94]
        record = {
            "environment": platform.platform(),
            "python": platform.python_version(),
            "browser": browser.version,
            "wallets": 10_000,
            "orders": 200,
            "cold_overview_seconds": cold,
            "warm_overview_seconds": warm,
            "api_snapshot_cold_ms": snapshot_cold_ms,
            "api_snapshot_warm_ms": snapshot_warm_ms,
            "api_records_cold_ms": records_cold_ms,
            "api_records_warm_ms": records_warm_ms,
            "snapshot_bytes": len(snapshot_response.body()),
            "page_50_bytes": len(records_response.body()),
            "interaction_samples": 100,
            "interaction_p95_ms": p95,
            "interaction_mean_ms": statistics.mean(timings),
            "refresh_cycles": 1000,
            "cycle_wall_seconds": cycle_seconds,
            "accelerated_browser_hours": 25,
            "server_csrf_rotations": 10,
            "receipt_requests": len(requests),
            "receipt_failures": len(failures),
            "retained_durable_receipts": 1,
            "automatic_mutation_retries": len(posts),
            "heap_before": baseline,
            "heap_after": final,
            "dom_nodes_before": baseline_nodes,
            "dom_nodes_after": final_nodes,
            "human_acceptance": "NOT_OBSERVED",
            "provider_calls": 0,
        }
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / "h1-footprint.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        assert cold < 2
        assert p95 < 200
        browser.close()
