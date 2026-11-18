"""Validate the protected workspace, including a refresh failure and focus return."""

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from polysia.domain.leaderboard import Board, Observation, ReferenceCapture, Standing
from polysia.storage.leaderboard import LeaderboardStore
from tests.browser.test_console_browser import browser_context, console_fixture  # noqa: F401

pytestmark = pytest.mark.skipif(
    os.getenv("POLYSIA_BROWSER_TESTS") != "1", reason="opt-in synthetic browser"
)


def test_watchlist_is_restored_in_a_new_browser_context(console_fixture, tmp_path):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    store = LeaderboardStore(tmp_path / "leaderboard.sqlite3")
    store.initialize()
    now = datetime.now(UTC)
    token = store.acquire(now)
    assert token
    rows = (Standing("0x" + "1" * 40, "Test Trader", 1, Decimal("42"), Decimal("200")),)
    store.publish(
        Observation(
            Board("polymarket", "month", "PNL"), rows, now, now, "complete", None, False, 1, 100,
        ),
        token,
    )
    store.release(token)
    origin, impersonate, *_ = console_fixture
    with sync_playwright() as runtime:
        browser, context = browser_context(runtime, origin, impersonate)
        page = context.new_page()
        page.goto(origin)
        page.get_by_role("button", name="Leaderboard", exact=True).click()
        page.get_by_role("checkbox", name="Select Test Trader").check()
        page.get_by_role("button", name="Save selection").click()
        page.get_by_label("Watchlist name").fill("Test cohort")
        page.get_by_role("button", name="Save watchlist").click()
        expect(page.get_by_text("Watchlist saved.")).to_be_visible()
        browser.close()
        browser, context = browser_context(runtime, origin, impersonate)
        page = context.new_page()
        page.goto(origin)
        page.get_by_role("button", name="Leaderboard", exact=True).click()
        page.get_by_role("button", name="Watchlists", exact=True).click()
        expect(page.get_by_text("Test cohort", exact=True)).to_be_visible()
        page.get_by_role("button", name="Shadow Test cohort", exact=True).click()
        page.get_by_label("Duration", exact=True).fill("3")
        page.get_by_role("combobox", name="Duration unit").select_option("days")
        page.get_by_role("button", name="Start Shadow", exact=True).click()
        expect(page.get_by_text("Test cohort · RUNNING · 1 wallets")).to_be_visible()
        browser.close()


@pytest.mark.parametrize("width", [360, 768, 1280, 1920])
def test_leaderboard_journey(console_fixture, tmp_path, width):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    store = LeaderboardStore(tmp_path / "leaderboard.sqlite3")
    store.initialize()
    now = datetime.now(UTC)
    token = store.acquire(now)
    assert token
    rows = tuple(
        Standing(
            f"0x{i:040x}",
            "A much longer trader name than the column can show" if i == 1 else f"Trader {i:02}",
            i,
            Decimal("8000.1234567890123456") - i,
            Decimal(80000 - i),
        )
        for i in range(1, 54)
    )
    board = Board("polymarket", "month", "PNL")
    earlier = now - timedelta(hours=15)
    store.publish(
        Observation(board, rows, earlier, earlier, "complete", None, False, 1, 400), token
    )
    store.publish(Observation(board, (), now, now, "failed", "http_429", None, 3, 0), token)
    store.publish(
        Observation(
            Board("polymarket", "week", "PNL"), (), now, now, "complete", None, False, 1, 40
        ),
        token,
    )
    store.release(token)
    store.import_reference(
        ReferenceCapture(
            "Rivo",
            now,
            "Visible rows from the sample",
            "Read-only fixture",
            (rows[0].wallet, f"0x{333:040x}"),
            True,
        ),
        now=now,
    )
    origin, impersonate, *_ = console_fixture
    with sync_playwright() as runtime:
        browser, context = browser_context(
            runtime, origin, impersonate, width=width, role="fixture-reader"
        )
        page = context.new_page()
        page.goto(origin)
        page.get_by_role("button", name="Leaderboard", exact=True).click()
        table = page.get_by_role("region", name="Trader rankings table")
        expect(table.get_by_text("7999.1234567890123456", exact=True)).to_be_visible()
        expect(page.get_by_text("Showing the last complete board.", exact=False)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        output = Path("output/playwright")
        output.mkdir(parents=True, exist_ok=True)
        if width in {360, 1280}:
            page.screenshot(path=str(output / f"leaderboard-{width}-light.png"))
        if width == 360:
            toggle = page.get_by_role("button", name="Search and filters", exact=False)
            expect(toggle).to_have_attribute("aria-expanded", "false")
            expect(page.get_by_label("Search wallet bank")).to_be_hidden()
            toggle.click()
            expect(toggle).to_have_attribute("aria-expanded", "true")
        wallet = table.get_by_role("button", name="Wallet details for Trader 02", exact=True)
        wallet.click()
        dialog = page.get_by_role("dialog", name="Wallet detail")
        expect(dialog.get_by_text("Rank history on this board")).to_be_visible()
        expect(dialog.get_by_role("link", name="Polymarket profile ↗")).to_have_attribute(
            "href", "https://polymarket.com/profile/" + rows[1].wallet
        )
        page.keyboard.press("Escape")
        expect(wallet).to_be_focused()
        page.get_by_role("button", name="Next", exact=True).click()
        expect(
            table.get_by_role("button", name="Wallet details for Trader 53", exact=True)
        ).to_be_visible()
        page.get_by_label("Search wallet bank").fill("Trader 25")
        page.get_by_role("button", name="Search", exact=True).click()
        expect(
            table.get_by_role("button", name="Wallet details for Trader 25", exact=True)
        ).to_be_visible()
        page.route("**/api/console/v1/leaderboard?*", lambda route: route.abort())
        page.get_by_role("button", name="Reload data").click()
        expect(page.get_by_text("Showing the last loaded view.", exact=False)).to_be_visible()
        expect(
            table.get_by_role("button", name="Wallet details for Trader 25", exact=True)
        ).to_be_visible()
        page.get_by_label("Period").select_option("week")
        expect(table).to_have_count(0)
        page.unroute("**/api/console/v1/leaderboard?*")
        page.get_by_role("button", name="Reload data").click()
        expect(page.get_by_text("Outside this board", exact=False)).to_be_visible()
        page.get_by_label("Search wallet bank").fill("")
        expect(page.get_by_text("The provider returned an empty board.")).to_be_visible()
        page.get_by_role("button", name="Compare Rivo").click()
        benchmark = page.get_by_role("dialog", name="Rivo coverage")
        expect(benchmark.get_by_text("Outside captured bank", exact=True)).to_be_visible()
        expect(benchmark.get_by_text("Shared", exact=True)).to_be_visible()
        page.keyboard.press("Escape")
        page.get_by_role("button", name="Switch to dark theme").click()
        page.get_by_label("Period").select_option("month")
        expect(table).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        if width in {360, 1280}:
            page.evaluate("window.scrollTo(0, 0)")
            page.screenshot(path=str(output / f"leaderboard-{width}-dark.png"))
        if width == 1280:
            page.evaluate(
                Path("frontend/node_modules/axe-core/axe.min.js").read_text(encoding="utf-8")
            )
            audit = page.evaluate(
                "async () => (await axe.run({ runOnly: ['wcag2a', 'wcag2aa'] })).violations"
            )
            assert audit == []
            route = "**/api/console/v1/leaderboard?*"
            page.route(route, lambda request: request.fulfill(json={"incompatible": True}))
            page.get_by_role("button", name="Reload data").click()
            mismatch = page.get_by_text("Leaderboard data is incompatible", exact=False)
            expect(mismatch).to_be_visible()
            expect(table).to_have_count(0)
            page.unroute(route)
            page.get_by_role("button", name="Reload data").click()
            expect(table).to_be_visible()
            page.route(route, lambda request: request.fulfill(status=401))
            page.get_by_role("button", name="Reload data").click()
            expect(page.get_by_role("region", name="Polymarket leaderboard")).to_have_count(0)
        browser.close()
