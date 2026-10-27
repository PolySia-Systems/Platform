"""Full migration acceptance on protected installed assets, not a development server."""

from __future__ import annotations

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
    os.getenv("POLYSIA_BROWSER_TESTS") != "1",
    reason="explicit synthetic installed-browser job only",
)
OUTPUT = Path("output/playwright")


@pytest.mark.parametrize("width", [1440, 1280, 390])
def test_eight_journeys_visual_accessibility_and_rtl(rich_console, width):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    origin, token, _, _, _, _ = rich_console
    axe = Path("frontend/node_modules/axe-core/axe.min.js")
    assert axe.is_file(), "Install the pinned development-only accessibility engine with npm ci"
    reports = []
    with sync_playwright() as runtime:
        browser, context = browser_context(runtime, origin, token, width=width)
        page = context.new_page()
        response = page.goto(origin)
        assert "unsafe-inline" not in response.headers["content-security-policy"]
        assert "unsafe-eval" not in response.headers["content-security-policy"]
        expect(page.get_by_label("Independent supervision", exact=True)).to_contain_text("STOPPED")
        expect(page.get_by_label("Protective controls", exact=True)).to_contain_text(
            "STOP financial session"
        )
        page.evaluate(axe.read_text(encoding="utf-8"))
        if width == 1440:
            page.keyboard.press("Tab")
            expect(
                page.get_by_role("link", name="Skip to main content", exact=True)
            ).to_be_focused()
            page.keyboard.press("Enter")
            expect(page.locator("#main")).to_be_focused()
        OUTPUT.mkdir(parents=True, exist_ok=True)
        for tab in ("Overview", "Investigate", "Operate", "Evaluate", "System / Setup"):
            page.get_by_role("button", name=tab, exact=True).click()
            expect(page.locator("#main")).to_have_attribute("aria-busy", "false")
            headings = {
                "Operate": "Effective and staged policy",
                "Evaluate": "Same-tape Shadow comparison",
                "System / Setup": "Configured, verified and authorized",
            }
            if tab in headings:
                expect(
                    page.get_by_label("Qualified workspace evidence", exact=True).get_by_role(
                        "heading", name=headings[tab], exact=True
                    )
                ).to_be_visible()
            if tab == "Operate":
                expect(page.locator("#operation")).to_contain_text(
                    "Choose a registered operation and target"
                )
                expect(page.get_by_label("Bounded Shadow Lab", exact=True)).to_contain_text(
                    "ISOLATED_PER_EXPERIMENT"
                )
            if tab == "Investigate":
                page.get_by_label("Search exact identity").fill("order-00000")
                page.get_by_role("button", name="Search", exact=True).click()
                page.get_by_role("button", name="order-00000", exact=True).click()
                expect(page.get_by_label("Evidence detail", exact=True)).to_contain_text(
                    "Risk approved"
                )
            audit = page.evaluate("""async () => {
              const result = await axe.run(document);
              return {violations:result.violations.map(v=>({id:v.id,impact:v.impact,
                nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))})),
                incomplete:result.incomplete.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)})),
                passedRules:result.passes.length};
            }""")
            reports.append({"workspace": tab, **audit})
            assert not any(
                marker in page.locator("body").inner_text() for marker in ("\u00c2", "\u00c3")
            )
            page.locator("h1").click()
            page.evaluate("document.activeElement?.blur(); window.scrollTo(0,0)")
            safe = tab.lower().replace(" / ", "-")
            page.screenshot(path=str(OUTPUT / f"h2-{safe}-{width}.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        # Keyboard/focus and 200%-equivalent CSS reflow remain separate from a native zoom claim.
        if width == 1440:
            page.get_by_role("button", name="Evaluate", exact=True).click()
            expect(page.get_by_role("heading", name="Same-tape Shadow comparison")).to_be_visible()
            page.route("**/workspace?panel=system", lambda route: route.abort(), times=1)
            page.get_by_role("button", name="System / Setup", exact=True).click()
            evidence = page.get_by_role("group", name="Qualified workspace evidence", exact=True)
            expect(evidence.get_by_role("alert")).to_contain_text("Evidence unavailable")
            expect(
                evidence.get_by_role("heading", name="Same-tape Shadow comparison")
            ).to_have_count(0)
            # Retry the failed read explicitly even when the publication generation is unchanged.
            page.get_by_role("button", name="Refresh evidence", exact=False).click()
            expect(
                evidence.get_by_role("heading", name="Configured, verified and authorized")
            ).to_be_visible()
            expect(evidence.get_by_role("alert")).to_have_count(0)
            page.get_by_role("button", name="Operate", exact=True).click()
            page.locator("#operation").select_option("acquisition.stop|acquisition")
            page.get_by_role("button", name="Preview operation", exact=True).focus()
            page.keyboard.press("Enter")
            expect(page.get_by_role("dialog")).to_be_visible()
            expect(page.get_by_role("dialog")).to_contain_text("acquisition.stop")
            page.keyboard.press("Tab")
            assert page.get_by_role("dialog").evaluate(
                "node => node.contains(document.activeElement)"
            )
            page.screenshot(path=str(OUTPUT / "h2-command-critical.png"), full_page=True)
            page.keyboard.press("Escape")
            page.get_by_label("Direction fixture", exact=False).check()
            page.set_viewport_size({"width": 640, "height": 900})
            expect(page.locator("html")).to_have_attribute("dir", "rtl")
            expect(page.locator("[lang=fa]")).to_contain_text("شناسه‌ها")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(OUTPUT / "h2-rtl-zoom-200.png"), full_page=True)
        (OUTPUT / f"h2-accessibility-{width}.json").write_text(
            json.dumps(
                {
                    "engine": "axe-core@4.14.0",
                    "width": width,
                    "reports": reports,
                    "keyboard_focus": "EXERCISED",
                    "screen_reader": "NOT_PERFORMED",
                    "human_acceptance": "NOT_OBSERVED",
                    "wcag_certification": "NOT_CLAIMED",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        assert not [report for report in reports if report["violations"]], reports
        browser.close()


def test_single_presentation_retired_routes_and_readonly_example(console_fixture):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    origin, token, commands, _ = console_fixture
    with sync_playwright() as runtime:
        browser, context = browser_context(runtime, origin, token)
        for route in ("/h1", "/demo", "/api/demo", "/console.js", "/console.css"):
            assert context.request.get(origin + route).status == 404
        page = context.new_page()
        page.goto(origin + "/?example=1")
        expect(
            page.get_by_text("Synthetic example. No financial readiness or commands.", exact=True)
        ).to_be_visible()
        page.get_by_role("button", name="Operate", exact=True).click()
        expect(page.get_by_role("button", name="Preview operation", exact=True)).to_be_disabled()
        assert commands.pending() == []
        assert context.request.get(origin + "/api/report").status == 200
        browser.close()
