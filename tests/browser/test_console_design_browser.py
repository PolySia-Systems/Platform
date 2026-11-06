"""Design acceptance on the real protected bundle and bounded synthetic producer."""

import json
import os
from pathlib import Path

import pytest

from tests.browser.test_console_browser import (
    browser_context,
    console_fixture,  # noqa: F401
    rich_console,  # noqa: F401
)

pytestmark = pytest.mark.skipif(
    os.getenv("POLYSIA_BROWSER_TESTS") != "1", reason="opt-in synthetic browser"
)


def test_design_themes_assets_filters_and_preview(rich_console):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    origin, token, *_ = rich_console
    with sync_playwright() as runtime:
        browser, context = browser_context(runtime, origin, token)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(origin)
        expect(page.get_by_role("heading", name="A clear view of the session.")).to_be_visible()
        page.evaluate("document.fonts.ready")
        assert page.locator('img[alt="PolySia"]').evaluate("e => e.complete && e.naturalWidth > 0")
        output = Path("output/playwright")
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / "design-light.png"), full_page=True)
        page.get_by_role("button", name="Investigate", exact=True).click()
        page.get_by_label("Search exact identity").fill("order-00000")
        page.get_by_role("button", name="Search", exact=True).click()
        expect(page.get_by_role("button", name="order-00000", exact=True)).to_be_visible()
        page.get_by_role("button", name="order-00000", exact=True).click()
        page.get_by_role("button", name="Overview", exact=True).click()
        page.get_by_role("button", name="Investigate", exact=True).click()
        expect(page.get_by_role("button", name="order-00000", exact=True)).to_be_visible()
        expect(page.get_by_label("Evidence detail", exact=True)).to_be_visible()
        expect(page.get_by_label("Search exact identity")).to_have_value("order-00000")
        page.get_by_role("button", name="Operate", exact=True).click()
        page.locator("#operation").select_option("acquisition.stop|acquisition")
        page.get_by_role("button", name="Preview operation", exact=True).click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.keyboard.press("Escape")
        page.get_by_role("button", name="Switch to dark theme").click()
        expect(page.locator("html")).to_have_attribute("data-mantine-color-scheme", "dark")
        page.get_by_role("button", name="Overview", exact=True).click()
        page.screenshot(path=str(output / "design-dark.png"), full_page=True)
        page.evaluate(Path("frontend/node_modules/axe-core/axe.min.js").read_text(encoding="utf-8"))
        violations = page.evaluate(
            "async () => (await axe.run(document)).violations.map(v=>({id:v.id,"
            "nodes:v.nodes.map(n=>n.target)}))"
        )
        assert violations == []
        # Shared-value substitution changes presentation without touching financial meaning.
        before = page.get_by_label("Exact financial amounts", exact=True).inner_text()
        page.evaluate("""() => {
          document.documentElement.style.setProperty('--console-space', '10px');
          document.documentElement.style.setProperty('--console-accent', '#ffffff');
          document.documentElement.style.setProperty('--mantine-font-family', 'system-ui');
        }""")
        assert page.get_by_label("Exact financial amounts", exact=True).inner_text() == before
        assert (
            page.locator("html").evaluate(
                "e => getComputedStyle(e).getPropertyValue('--console-danger').trim()"
            )
            == "#ffa1ad"
        )
        page.evaluate("""() => {
          document.documentElement.style.removeProperty('--console-space');
          document.documentElement.style.removeProperty('--console-accent');
          document.documentElement.style.removeProperty('--mantine-font-family');
        }""")
        manifest = json.loads(
            Path("src/polysia/monitoring/human_console_assets/manifest.json").read_text()
        )
        compact = next(name for name in manifest["files"] if name.startswith("compact-"))
        symbol = page.locator('img[alt=""]').first
        original = symbol.get_attribute("src")
        symbol.evaluate("(e, url) => { e.src = url; }", origin + "/assets/" + compact)
        expect(symbol).to_have_js_property("naturalWidth", 459)
        assert symbol.evaluate("e => getComputedStyle(e).objectFit") == "contain"
        symbol.evaluate("(e, url) => { e.src = url; }", original)
        for workspace in ("Investigate", "Operate", "Evaluate", "System / Setup"):
            page.get_by_role("button", name=workspace, exact=True).click()
            expect(page.locator("#main")).to_have_attribute("aria-busy", "false")
            audit = page.evaluate(
                "async () => (await axe.run(document)).violations.map(v=>({id:v.id,"
                "nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))"
            )
            (output / "design-audit-failure.txt").write_text(str(audit), encoding="utf-8")
            assert audit == [], (workspace, audit)
        page.get_by_role("button", name="Overview", exact=True).click()
        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_label("Direction fixture", exact=False).check()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(output / "design-mobile-rtl.png"), full_page=True)
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        assert not errors
        browser.close()


def test_failed_font_keeps_navigation_usable(rich_console):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    origin, token, *_ = rich_console
    with sync_playwright() as runtime:
        browser, context = browser_context(runtime, origin, token, width=390)
        context.route("**/*.woff2", lambda route: route.abort())
        page = context.new_page()
        page.goto(origin)
        expect(page.get_by_role("button", name="Investigate", exact=True)).to_be_visible()
        page.get_by_role("button", name="Investigate", exact=True).click()
        expect(page.get_by_label("Search exact identity")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        browser.close()


def test_open_tab_bundle_change_preserves_uncertain_request(rich_console):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    origin, token, *_ = rich_console
    with sync_playwright() as runtime:
        browser, context = browser_context(runtime, origin, token)
        page = context.new_page()
        page.goto(origin)
        page.get_by_role("button", name="Operate", exact=True).click()
        page.locator("#operation").select_option("acquisition.stop|acquisition")
        page.get_by_role("button", name="Preview operation", exact=True).click()
        expect(page.get_by_role("dialog")).to_be_visible()
        sends = []

        def lost(route):
            sends.append(route.request.post_data)
            route.fetch()
            route.abort()

        page.route("**/api/console/v1/apply", lost)
        page.get_by_role("button", name="Request exact operation", exact=True).click()
        expect(page.get_by_text("Response lost.", exact=False)).to_be_visible()
        request_identity = page.locator("p").filter(has_text="Request identity").locator("bdi")
        key = request_identity.inner_text()
        source = page.locator('meta[name="bundle-source"]').get_attribute("content")

        def upgraded(route):
            response = route.fetch()
            payload = response.json()
            payload["bundle"] = "f" * 64
            route.fulfill(response=response, json=payload)

        page.route("**/api/console/v1/session", upgraded)
        page.get_by_role("button", name="Refresh evidence", exact=False).click()
        expect(page.get_by_text("Incompatible response.", exact=False)).to_be_visible()
        expect(request_identity).to_be_visible()
        expect(request_identity).to_have_text(key)
        expect(page.get_by_role("button", name="Preview operation", exact=True)).to_be_disabled()
        assert page.locator('meta[name="bundle-source"]').get_attribute("content") == source
        assert len(sends) == 1
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        browser.close()
