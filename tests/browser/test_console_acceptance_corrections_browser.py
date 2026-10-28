"""Acceptance corrections against the shipped bundle and actual command owners."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.browser.test_console_browser import console_fixture, rich_console  # noqa: F401
from tests.browser.test_console_h1_browser import (
    PREFIX,
    base_console_fixture,  # noqa: F401
    context_for,
    h1_fixture,  # noqa: F401
    launch,
)

pytestmark = pytest.mark.skipif(
    os.getenv("POLYSIA_BROWSER_TESTS") != "1", reason="explicit installed-browser acceptance only"
)
OUTPUT = Path("output/playwright")


def buffer_actual_receipts(page):
    # Delay a fully buffered genuine gateway reply. This exercises late-result
    # fencing independently of whether transport cancellation wins the race.
    page.add_init_script("""(() => {
      window.delayedKeys=[]; window.bufferedReceipts=[];
      const actual=window.fetch.bind(window);
      window.fetch=async (input,init) => {
        const response=await actual(input,init);
        const url=new URL(String(input),location.href);
        const key=url.searchParams.get('key') || (url.searchParams.has('cursor')?'history-page':'');
        if (!key || !window.delayedKeys.includes(key)) return response;
        const body=await response.text();
        return new Promise(resolve=>window.bufferedReceipts.push({key,
          deliver:()=>resolve(new Response(body,
            {status:response.status,headers:response.headers}))}));
      };
    })()""")


def release_replies(page):
    page.evaluate("window.bufferedReceipts.splice(0).forEach(row=>row.deliver())")
    page.evaluate("() => new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")


def inspect_key(page, key):
    page.get_by_label("Exact request identity", exact=True).fill(key)
    page.get_by_role("button", name="Look up receipt", exact=True).click()


def lost_request(page):
    from playwright.sync_api import expect

    page.get_by_role("button", name="Operate", exact=True).click()
    page.locator("#operation").select_option("session.stop|fixture-run:stop")
    page.get_by_role("button", name="Preview operation", exact=True).click()
    expect(page.get_by_role("dialog")).to_be_visible()
    keys = []

    def lost(route):
        keys.append(route.request.post_data_json["idempotency_key"])
        assert route.fetch().status == 202
        route.abort("failed")

    page.route("**" + PREFIX + "/apply", lost)
    page.get_by_role("button", name="Request exact operation", exact=True).click()
    expect(page.get_by_role("button", name="Recover exact receipt")).to_be_visible()
    return keys


@pytest.mark.parametrize("history_kind", ["known", "absent", "unresolved"])
def test_history_inspection_cannot_release_active_lost_request(h1_fixture, history_kind):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    origin, token, commands, _, owner, custody, _ = h1_fixture
    old_key = "older-acquisition-intent-001"
    commands.submit(
        subject="fixture-owner", action="stop", expected_revision=0, idempotency_key=old_key
    )
    commands.finish(1, status="FAILED" if history_kind == "unresolved" else "APPLIED", result=None)
    with sync_playwright() as runtime:
        browser = launch(runtime)
        context = context_for(browser, origin, token)
        page = context.new_page()
        page.goto(origin)
        keys = lost_request(page)
        lookup = "no-durable-receipt-for-this-key" if history_kind == "absent" else old_key
        page.get_by_label("Exact request identity", exact=True).fill(lookup)
        with page.expect_response("**/receipts?key=" + lookup):
            page.get_by_role("button", name="Look up receipt", exact=True).click()
        expect(page.locator("#operation")).to_be_disabled()
        expect(page.get_by_role("button", name="Recover exact receipt")).to_be_visible()
        expect(page.get_by_text(keys[0], exact=True)).to_be_visible()
        if history_kind == "known":
            # Even a valid, genuine receipt for another key is not recovery of
            # this request if a response is accidentally misrouted.
            other = context.request.get(origin + PREFIX + "/receipts?key=" + old_key).json()
            page.route(
                "**/receipts?key=" + keys[0],
                lambda route: route.fulfill(status=200, json=other),
                times=1,
            )
            page.get_by_role("button", name="Recover exact receipt").click()
            expect(page.get_by_role("alert")).to_contain_text("Incompatible response")
            expect(page.locator("#operation")).to_be_disabled()
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
        expect(page.locator("#operation")).to_be_enabled()
        assert len(keys) == 1
        assert custody.snapshot(owner.authority.fingerprint)["reason"] == "scoped_operator_STOP"
        browser.close()


def test_overlapping_history_and_recovery_cannot_overwrite_new_intent(h1_fixture):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    origin, token, commands, _, owner, _, _ = h1_fixture
    older = "older-acquisition-intent-001"
    newer = "newer-acquisition-intent-002"
    for index, key in enumerate((older, newer)):
        commands.submit(
            subject="fixture-owner", action="stop", expected_revision=index, idempotency_key=key
        )
        commands.finish(index + 1, status="APPLIED", result=None)
    with sync_playwright() as runtime:
        browser = launch(runtime)
        context = context_for(browser, origin, token)
        page = context.new_page()
        buffer_actual_receipts(page)
        page.goto(origin)
        keys = lost_request(page)
        page.evaluate("key=>window.delayedKeys=[key]", older)
        inspect_key(page, older)
        page.wait_for_function("() => window.bufferedReceipts.length===1")
        inspect_key(page, newer)
        inspection = page.get_by_role("region", name="Inspected historical receipt", exact=True)
        expect(inspection).to_contain_text(newer)
        release_replies(page)
        expect(inspection).to_contain_text(newer)
        expect(page.locator("#operation")).to_be_disabled()
        # A buffered REQUESTED result must not overwrite a later observed result.
        page.evaluate("key=>window.delayedKeys=[key]", keys[0])
        page.get_by_role("button", name="Recover exact receipt").click()
        page.wait_for_function("() => window.bufferedReceipts.length===1")
        owner.process_controls()
        page.evaluate("window.delayedKeys=[]")
        page.get_by_role("button", name="Recover exact receipt").click()
        expect(page.locator("#operation")).to_be_enabled()
        release_replies(page)
        operation = page.locator("#operation").locator("..")
        expect(operation).not_to_contain_text("NOT_OBSERVED")
        # A historical reply issued before the next lost action cannot restore
        # the previous inspection or resolve that next action.
        page.evaluate("key=>window.delayedKeys=[key]", older)
        inspect_key(page, older)
        page.wait_for_function("() => window.bufferedReceipts.length===1")
        next_keys = lost_request(page)
        release_replies(page)
        expect(page.locator("#operation")).to_be_disabled()
        expect(page.get_by_role("button", name="Recover exact receipt")).to_be_visible()
        expect(page.get_by_text(next_keys[0], exact=True)).to_be_visible()
        expect(inspection).to_have_count(0)
        assert keys[0] != next_keys[0] and len(keys) == len(next_keys) == 1
        browser.close()


def test_current_key_recovery_survives_csrf_rotation_and_expired_preview(h1_fixture, monkeypatch):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    import polysia.monitoring.console as console_module

    origin, token, _, _, owner, _, _ = h1_fixture
    jwt = token("fixture-owner")
    with sync_playwright() as runtime:
        browser = launch(runtime)
        context = context_for(browser, origin, lambda _subject: jwt)
        page = context.new_page()
        buffer_actual_receipts(page)
        page.goto(origin)
        identity = context.request.get(origin + PREFIX + "/session").json()["identity"]
        keys = lost_request(page)
        page.evaluate("key=>window.delayedKeys=[key]", keys[0])
        page.get_by_role("button", name="Recover exact receipt").click()
        page.wait_for_function("() => window.bufferedReceipts.length===1")
        server_time = console_module.time.time()
        monkeypatch.setattr(console_module.time, "time", lambda: server_time + 3600)
        with page.expect_response("**" + PREFIX + "/session") as renewed:
            page.get_by_role("button", name="Refresh evidence", exact=False).click()
        assert renewed.value.json()["identity"] != identity
        expect(page.get_by_role("button", name="Refresh evidence", exact=False)).to_be_enabled()
        release_replies(page)
        expect(page.locator("#operation")).to_be_disabled()
        expect(page.get_by_role("button", name="Recover exact receipt")).to_be_visible()
        page.clock.install()
        page.route("**" + PREFIX + "/session", lambda route: route.abort("failed"))
        page.clock.fast_forward(121_000)
        page.evaluate("window.delayedKeys=[]")
        owner.process_controls()
        page.get_by_role("button", name="Recover exact receipt").click()
        expect(page.locator("#operation")).to_be_enabled()
        expect(page.get_by_text("OBSERVED", exact=True).first).to_be_visible()
        assert len(keys) == 1
        browser.close()


def test_late_recovery_and_history_page_cannot_restore_data_after_revocation(h1_fixture):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    origin, token, commands, _, owner, _, _ = h1_fixture
    for index in range(51):
        commands.submit(
            subject="fixture-owner",
            action="stop",
            expected_revision=index,
            idempotency_key=f"historical-acquisition-{index:016}",
        )
        commands.finish(index + 1, status="APPLIED", result=None)
    with sync_playwright() as runtime:
        browser = launch(runtime)
        context = context_for(browser, origin, token)
        page = context.new_page()
        buffer_actual_receipts(page)
        page.goto(origin)
        keys = lost_request(page)
        page.evaluate("key=>window.delayedKeys=[key,'history-page']", keys[0])
        page.get_by_role("button", name="Recover exact receipt").click()
        page.get_by_role("button", name="Next 50", exact=True).click()
        page.wait_for_function("() => window.bufferedReceipts.length===2")
        context.set_extra_http_headers({"Cf-Access-Jwt-Assertion": "revoked-fixture-token"})
        page.get_by_role("button", name="Refresh evidence", exact=False).click()
        expect(page.get_by_role("alert").filter(has_text="Authentication changed")).to_be_visible()
        release_replies(page)
        expect(page.get_by_text("APPLIED", exact=True)).to_have_count(0)
        expect(page.get_by_text("REQUESTED", exact=True)).to_have_count(0)
        expect(page.get_by_text(keys[0], exact=True)).to_be_visible()
        context.set_extra_http_headers({"Cf-Access-Jwt-Assertion": token("fixture-owner")})
        page.evaluate("window.delayedKeys=[]")
        page.get_by_role("button", name="Refresh identity", exact=True).click()
        expect(page.get_by_role("button", name="Recover exact receipt")).to_be_enabled()
        owner.process_controls()
        page.get_by_role("button", name="Recover exact receipt").click()
        expect(page.locator("#operation")).to_be_enabled()
        assert len(keys) == 1
        OUTPUT.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(OUTPUT / "hc-r2-authorized-exact-recovery.png"), full_page=True)
        browser.close()


def test_evaluate_expires_at_account_bound_without_successful_refresh(rich_console):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    origin, token, _, _, _, root = rich_console
    path = root / "publication.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    financial = raw["financial_session"]
    financial["account_observed_at"] = datetime.now(UTC).isoformat()
    financial["account_valid_until"] = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
    path.write_text(json.dumps(raw), encoding="utf-8")
    with sync_playwright() as runtime:
        browser = launch(runtime)
        context = context_for(browser, origin, token)
        page = context.new_page()
        page.goto(origin)
        page.get_by_role("button", name="Evaluate", exact=True).click()
        economics = page.get_by_label("Actual trading economics", exact=True)
        badge = economics.locator("div").first.locator("span").first
        expect(badge).to_have_text("AVAILABLE")
        page.route("**" + PREFIX + "/**", lambda route: route.abort("failed"))
        page.clock.install()
        page.clock.fast_forward(31_000)
        expect(badge).to_have_text("STALE")
        expect(economics).to_contain_text("99.49")
        OUTPUT.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(OUTPUT / "hc-r1-account-expired-economics.png"), full_page=True)
        browser.close()
