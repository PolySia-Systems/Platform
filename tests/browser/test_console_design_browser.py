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


@pytest.mark.parametrize("width", [390, 1440])
def test_investigation_distinguishes_unsearched_filters_errors_and_generation(rich_console, width):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    origin, token, *_ = rich_console
    with sync_playwright() as runtime:
        browser, context = browser_context(runtime, origin, token, width=width)
        page = context.new_page()
        page.goto(origin)
        page.get_by_role("button", name="Investigate", exact=True).click()
        prompt = page.get_by_text("Search to load retained evidence for these filters.", exact=True)
        changed = page.get_by_text("This evidence generation changed.", exact=False)
        expect(prompt).to_be_visible()
        expect(changed).to_have_count(0)
        expect(page.get_by_text("No retained financial evidence", exact=True)).to_have_count(0)
        search = page.get_by_label("Search exact identity")
        assert search.evaluate("e => getComputedStyle(e).fontSize") == "14px"
        search.fill("order-00000")
        page.get_by_role("button", name="Search", exact=True).click()
        record = page.get_by_role("button", name="order-00000", exact=True)
        record.click()
        expect(page.get_by_label("Evidence detail", exact=True)).to_be_visible()
        search.fill("no-matching-record")
        expect(record).to_have_count(0)
        expect(page.get_by_label("Evidence detail", exact=True)).to_have_count(0)
        expect(page.get_by_role("button", name="Next 50", exact=True)).to_be_disabled()
        expect(prompt).to_be_visible()
        page.get_by_role("button", name="Search", exact=True).click()
        expect(page.get_by_text("No matching records in this retained generation.")).to_be_visible()
        page.get_by_label("Record type").select_option("wallet")
        expect(changed).to_have_count(0)
        page.get_by_label("Source filter").fill("unused-source")
        page.get_by_label("Record type").select_option("order")
        search.fill("order-00000")
        page.get_by_role("button", name="Search", exact=True).click()
        # The now-hidden source filter must not leak into this query.
        expect(record).to_be_visible()
        page.route("**/api/console/v1/records?*", lambda route: route.abort())
        page.get_by_role("button", name="Refresh list", exact=True).click()
        expect(record).to_have_count(0)
        status = page.get_by_role("status")
        expect(status).to_be_visible()
        error = status.inner_text()
        page.get_by_role("button", name="Overview", exact=True).click()
        page.get_by_role("button", name="Investigate", exact=True).click()
        expect(page.get_by_role("status")).to_have_text(error)
        expect(record).to_have_count(0)
        page.unroute("**/api/console/v1/records?*")
        page.get_by_role("button", name="Search", exact=True).click()
        expect(record).to_be_visible()
        page.get_by_role("button", name="Overview", exact=True).click()

        def next_generation(route):
            response = route.fetch()
            payload = response.json()
            payload["context"]["generation"] = "f" * 64
            route.fulfill(response=response, json=payload)

        page.route("**/api/console/v1/snapshot", next_generation)
        page.get_by_role("button", name="Refresh evidence", exact=False).click()
        expect(page.locator("#main")).to_have_attribute("aria-busy", "false")
        page.get_by_role("button", name="Investigate", exact=True).click()
        expect(changed).to_be_visible()
        expect(record).to_have_count(0)
        expect(search).to_have_value("order-00000")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        browser.close()


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
        page.set_viewport_size({"width": 1024, "height": 1000})
        brand = page.get_by_role("link", name="PolySia CONSOLE", exact=True)
        assert brand.evaluate("""link => {
            const { left, right } = link.getBoundingClientRect();
            return [...link.querySelectorAll('img')].every(image => {
                const bounds = image.getBoundingClientRect();
                return bounds.left >= left && bounds.right <= right;
            });
        }""")
        page.set_viewport_size({"width": 1440, "height": 1000})
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
        compact = next(name for name in manifest["files"] if name.startswith("symbol-light-"))
        symbol = page.locator('img[alt=""]').first
        original = symbol.get_attribute("src")
        symbol.evaluate("(e, url) => { e.src = url; }", origin + "/assets/" + compact)
        expect(symbol).to_have_js_property("complete", True)
        assert symbol.evaluate("e => e.naturalWidth > 0")
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
        page.goto(origin + "?locale=fa-IR")
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
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


def test_auth_loss_clears_evidence_and_recovers_without_replay(rich_console):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    origin, token, *_ = rich_console
    with sync_playwright() as runtime:
        browser, context = browser_context(runtime, origin, token)
        page = context.new_page()
        posts = []
        page.on("request", lambda request: posts.append(request.url)
                if request.method == "POST" else None)
        page.goto(origin)
        expect(page.get_by_label("Exact financial amounts")).to_contain_text("99.49")
        page.route("**/api/console/v1/session", lambda route: route.fulfill(status=403))
        page.get_by_role("button", name="Refresh evidence", exact=False).click()
        expect(page.get_by_role("alert")).to_contain_text("Authentication changed or expired")
        page.unroute("**/api/console/v1/session")
        page.get_by_role("button", name="Refresh identity", exact=False).click()
        expect(page.get_by_role("alert")).to_have_count(0)
        expect(page.get_by_label("Exact financial amounts")).to_contain_text("99.49")
        assert posts == []
        browser.close()

def test_console_read_failure_recovers_without_losing_retained_amounts(rich_console):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    origin, token, *_ = rich_console
    output = Path("output/playwright")
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as runtime:
        browser, context = browser_context(runtime, origin, token, role="fixture-reader")
        page = context.new_page()
        snapshot = "**/api/console/v1/snapshot"
        page.route(snapshot, lambda route: route.fulfill(status=503))
        page.goto(origin)
        attention = page.get_by_role("region", name="Needs attention")
        expect(attention).to_contain_text("Use Refresh evidence to retry")
        expect(attention).not_to_contain_text("Loading protected evidence")
        expect(attention.get_by_role("button", name="Operate")).to_have_count(0)
        page.screenshot(path=str(output / "overview-read-failure.png"))

        refresh = page.get_by_role("button", name="Refresh evidence")
        page.unroute(snapshot)
        refresh.click()
        amounts = page.get_by_label("Exact financial amounts")
        expect(amounts).to_contain_text("1.010")
        expect(page.get_by_role("alert")).to_have_count(0)
        page.route(snapshot, lambda route: route.fulfill(status=503))
        refresh.click()
        expect(attention).to_contain_text("last successful read")
        expect(amounts).to_contain_text("1.010")
        expect(amounts.get_by_text("STALE", exact=True).first).to_be_visible()
        page.get_by_role("button", name="System / Setup").click()
        expect(page.get_by_role("region", name="Installation settings")).to_have_count(0)
        browser.close()


def test_installation_settings_retries_its_own_read_and_labels_update_policy(rich_console):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    origin, token, _, _, _, root = rich_console
    (root / "connection-status.json").write_text(
        json.dumps({"state": "OBSERVED", "checked_at": "2026-11-20T18:20:00+03:30"}),
        encoding="utf-8",
    )
    output = Path("output/playwright")
    output.mkdir(parents=True, exist_ok=True)
    endpoint = "**/api/console/v1/installation-settings"
    with sync_playwright() as runtime:
        browser, context = browser_context(runtime, origin, token, width=390)
        page = context.new_page()
        page.route(endpoint, lambda route: route.fulfill(status=503))
        page.goto(origin)
        page.get_by_role("button", name="System / Setup").click()
        panel = page.get_by_role("region", name="Installation settings")
        expect(panel.get_by_role("status")).to_contain_text("Use Refresh evidence to retry")
        page.unroute(endpoint)
        refresh = page.get_by_role("button", name="Refresh evidence")
        with page.expect_response(lambda response: response.url.endswith("/installation-settings")):
            refresh.press("Enter")
        expect(panel).to_contain_text("Update policy unknown")
        expect(panel).to_contain_text("14:50:00 UTC")
        for policy, label in [(True, "Automatic"), (False, "Manual")]:
            (root / "update-status.json").write_text(
                json.dumps({"automatic": policy, "state": "UNKNOWN"}), encoding="utf-8",
            )
            refresh.click()
            expect(panel).to_contain_text(label)
            expect(panel).to_contain_text("Last check: UNKNOWN")
        page.route(endpoint, lambda route: route.fulfill(status=503))
        refresh.click()
        expect(panel.get_by_role("status")).to_contain_text("last successful read")
        expect(panel).to_contain_text("Manual")
        expect(page.locator("#main")).to_have_attribute("aria-busy", "false")
        panel.screenshot(path=str(output / "setup-retained-status.png"))
        browser.close()


def test_protected_favicon_has_opaque_background_and_manifest_digest(rich_console):  # noqa: F811
    import hashlib

    from playwright.sync_api import sync_playwright

    origin, token, *_ = rich_console
    manifest = json.loads(
        Path("src/polysia/monitoring/human_console_assets/manifest.json").read_text()
    )
    output = Path("output/playwright")
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as runtime:
        browser, context = browser_context(runtime, origin, token)
        page = context.new_page()
        index = page.goto(origin)
        assert "img-src 'self'" in index.headers["content-security-policy"]
        href = page.locator('link[rel="icon"]').get_attribute("href")
        name = href.rsplit("/", 1)[-1]
        assert name.startswith("favicon-") and name.endswith(".png")
        response = context.request.get(origin + href)
        assert response.ok and response.headers["content-type"] == "image/png"
        assert hashlib.sha256(response.body()).hexdigest() == manifest["files"][name]
        assert page.evaluate(
            """async href => {
                const icon = new Image();
                icon.src = href;
                await icon.decode();
                const canvas = document.createElement('canvas');
                canvas.width = canvas.height = 32;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(icon, 0, 0);
                const data = ctx.getImageData(0, 0, 32, 32).data;
                return icon.width === 32 && icon.height === 32
                    && data[0] === 8 && data[1] === 11 && data[2] === 18
                    && data.every((value, i) => i % 4 !== 3 || value === 255);
            }""",
            href,
        )
        brand = page.get_by_role("link", name="PolySia CONSOLE")
        for width in (320, 390, 760, 761, 1024, 1100, 1101, 1440):
            page.set_viewport_size({"width": width, "height": 1000})
            assert brand.evaluate("""link => {
                const { left, right } = link.getBoundingClientRect();
                return [...link.querySelectorAll('img')].every(image => {
                    const bounds = image.getBoundingClientRect();
                    return bounds.left >= left && bounds.right <= right;
                });
            }"""), width
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
            if width <= 760:
                navigation = page.get_by_role("navigation")
                assert navigation.evaluate("nav => nav.scrollWidth <= nav.clientWidth"), width
        brand.focus()
        assert brand.evaluate("link => link.matches(':focus-visible')")
        page.screenshot(path=str(output / "header-keyboard-focus.png"))
        browser.close()
