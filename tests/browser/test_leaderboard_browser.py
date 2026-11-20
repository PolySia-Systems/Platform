"""Validate the protected workspace, including a refresh failure and focus return."""

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from polysia.domain.copytrading.watchlist_shadow import FILL_REASON, LEGACY_SHADOW_MODEL
from polysia.domain.leaderboard import Board, Observation, ReferenceCapture, Standing
from polysia.storage.leaderboard import LeaderboardStore
from polysia.storage.watchlist_runs import WatchlistRuns
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
        page.get_by_role("button", name="Paper test for Test cohort", exact=True).click()
        form = page.get_by_role("dialog", name="Paper tests")
        expect(form.get_by_role("checkbox", name="Test Trader", exact=False)).to_be_checked()
        page.get_by_label("Duration", exact=True).fill("3")
        page.get_by_role("combobox", name="Duration unit").select_option("days")
        page.get_by_role("button", name="Start paper test", exact=True).click()
        expect(page.get_by_text("Test cohort · Running · 1 wallet")).to_be_visible()
        page.reload()
        page.get_by_role("button", name="Leaderboard", exact=True).click()
        page.get_by_role("button", name="Paper tests", exact=True).click()
        expect(page.get_by_text("Test cohort · Running · 1 wallet")).to_be_visible()
        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="End test and see results").click()
        result = page.get_by_text("Test cohort · Ended early · 1 wallet")
        expect(result).to_be_visible()
        expect(page.get_by_text("The source supplied no verified observations.")).to_be_visible()
        browser.close()


@pytest.mark.parametrize("width", [360, 1280])
def test_direct_paper_selection_recovers_from_two_errors(console_fixture, tmp_path, width):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    store = LeaderboardStore(tmp_path / "leaderboard.sqlite3")
    store.initialize()
    now = datetime.now(UTC)
    token = store.acquire(now)
    assert token
    rows = tuple(
        Standing(f"0x{i:040x}", f"Trader {i}" if i < 8 else "Shared name" if i < 10 else None,
                 i, Decimal(200 - i), Decimal(300))
        for i in range(1, 11)
    )
    store.publish(
        Observation(
            Board("polymarket", "month", "PNL"), rows, now, now, "complete", None, False, 1, 100,
        ),
        token,
    )
    store.release(token)
    origin, impersonate, *_ = console_fixture
    with sync_playwright() as runtime:
        browser, context = browser_context(runtime, origin, impersonate, width=width)
        page = context.new_page()
        page.goto(origin)
        page.get_by_role("button", name="Leaderboard", exact=True).click()
        for row in rows:
            label = row.name or row.wallet
            checkboxes = page.get_by_role("checkbox", name=f"Select {label}", exact=True)
            checkboxes.nth(1 if row.rank == 9 else 0).press("Space")
        run_name = "Leaderboard selection"
        if width == 1280:
            run_name = "Ten traders"
            page.get_by_role("button", name="Save selection").press("Enter")
            page.get_by_label("Watchlist name").fill(run_name)
            page.get_by_role("button", name="Save watchlist").press("Enter")
            page.get_by_role("button", name="Paper test for Ten traders").press("Enter")
        else:
            page.get_by_role("button", name="Test selected wallets", exact=True).press("Enter")
        form = page.get_by_role("dialog", name="Paper tests")
        back = "Back to watchlists" if width == 1280 else "Back to leaderboard"
        form.get_by_role("button", name=back).press("Enter")
        if width == 1280:
            entry = page.get_by_role("button", name="Paper test for Ten traders", exact=True)
        else:
            entry = page.get_by_role("button", name="Test selected wallets", exact=True)
        expect(entry).to_be_focused()
        entry.press("Enter")
        form.get_by_label("Duration", exact=True).fill("15")
        expect(form.get_by_text("Choose 1–6 wallets for this test.")).to_be_visible()
        expect(form.get_by_label("Duration", exact=True)).to_have_attribute("aria-invalid", "true")
        expect(form.get_by_role("button", name="Start paper test")).to_be_disabled()
        output = Path("output/playwright")
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / f"paper-test-validation-{width}.png"))
        expect(form.get_by_role("checkbox", name="Trader 1 0x00000000…000001")).to_be_checked()
        expect(form.get_by_role("checkbox", name="Shared name 0x00000000…000008")).to_be_checked()
        expect(form.get_by_role("checkbox", name="Shared name 0x00000000…000009")).to_be_checked()
        expect(form.get_by_role("checkbox", name="0x00000000…00000a")).to_be_checked()
        for item in form.get_by_role("checkbox").all()[6:]:
            item.press("Space")
        form.get_by_role("button", name="15 minutes", exact=True).press("Enter")
        expect(form.get_by_role("button", name="Start paper test")).to_be_enabled()
        form.get_by_role("button", name="Start paper test").press("Enter")
        expect(form.get_by_text(f"{run_name} · Running · 6 wallets")).to_be_visible()
        expect(form.get_by_text("Paper test · virtual funds")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        expect(form.get_by_text("lack a full ending price", exact=False)).to_have_count(0)
        runs = WatchlistRuns(tmp_path / "watchlists.sqlite3")
        active = runs.active()
        assert active is not None
        owner, run_id, revision, data = active
        _record_paper_result(runs, owner, run_id, revision, data)
        for label, key in (("Known total", "a"), ("Older run", "b")):
            runs.start(owner, key * 32, None, None, 900, now, selection=[rows[0].wallet])
            stored = runs.active()
            assert stored is not None
            _, _, test_revision, test_data = stored
            test_data["name"] = label
            test_data["finished_at"] = test_data["ends_at"]
            state = next(iter(test_data["wallets"].values()))
            if label == "Known total":
                state.update(through=test_data["ends_at"], observations=1)
            else:
                test_data["model"] = LEGACY_SHADOW_MODEL
                state.pop("closed")
            assert runs.apply(owner, key * 32, test_revision, "FINISHED", test_data)
        page.keyboard.press("Escape")
        if width == 1280:
            expect(entry).to_be_focused()
            page.keyboard.press("Escape")
        paper_tests = page.get_by_role("button", name="Paper tests", exact=True)
        paper_tests.press("Enter")
        result = form.get_by_text(f"{run_name} · Finished · 6 wallets", exact=True)
        card = result.locator("..")
        result.press("Enter")
        expect(card.get_by_text("Total gain or loss is unknown")).to_be_visible()
        expect(card.get_by_text("66 simulated trades · 204 skipped · 46 open", exact=False)
               ).to_be_visible()
        expect(card.get_by_text("1 of 46 open positions lack a full ending price.", exact=False)
               ).to_contain_text("10.2 USDC")
        expect(card.get_by_text("Estimated gain or loss on priced shares:", exact=False)
               ).to_contain_text("-35.3853 USDC")
        expect(card.get_by_text("Insufficient virtual cash: 191", exact=True)).to_be_visible()
        expect(card.get_by_text("Signal arrived too late to simulate: 9", exact=True)
               ).to_be_visible()
        expect(card.get_by_text("Not enough liquidity at the observed price: 4", exact=True)
               ).to_be_visible()
        page.screenshot(path=str(output / f"paper-test-result-{width}.png"))
        card.get_by_text("Wallets and exact evidence", exact=True).press("Enter")
        expect(card.get_by_text("-35.3853389653836416246313455 USDC", exact=True)).to_be_visible()
        form.get_by_text("Known total · Finished · 1 wallet", exact=True).press("Enter")
        expect(form.get_by_text("Estimated total gain or loss: 0 USDC", exact=True)).to_be_visible()
        legacy = form.get_by_text("Older run · Finished · 1 wallet", exact=True)
        legacy.press("Enter")
        expect(legacy.locator("..").get_by_text("The source supplied no verified observations.")
               ).to_be_visible()
        page.keyboard.press("Escape")
        expect(paper_tests).to_be_focused()
        browser.close()


def _record_paper_result(runs, owner, run_id, revision, data):
    """Replay the result shape of the six-wallet acceptance run with synthetic identities."""
    cutoff = data["ends_at"]
    data.update(finished_at=cutoff, cutoff_at=cutoff, end_reason="time")
    for state in data["wallets"].values():
        state.update(through=cutoff, observations=1)
    states = list(data["wallets"].values())
    for reason, count in (
        (FILL_REASON, 66), ("virtual_cash_exhausted", 191), ("observed_after_cutoff", 9),
        ("insufficient_executable_liquidity", 4),
    ):
        for index in range(count):
            states[index % len(states)]["events"][f"{reason}-{index}"] = reason
    for index in range(46):
        state = states[index % len(states)]
        state["positions"][str(index)] = ["20", "10.20"]
        state["cash"] = str(Decimal(state["cash"]) - Decimal("10.20"))
        if index < 45:
            marked_value = (
                "10.20" if index < 41 else "0" if index < 44 else "5.4146610346163583753686545"
            )
            state["marks"][str(index)] = {
                "quantity": "20", "value": marked_value,
                "source": "book", "received_at": cutoff, "quote_at": cutoff, "fee": "0",
            }
    assert runs.apply(owner, run_id, revision, "FINISHED", data)


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
