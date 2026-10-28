"""Desktop/mobile/keyboard journeys with an isolated Firefox CA trust store.

No global trust changes and no certificate-error bypass. The handoff contains
only a generated disposable fixture identity and its public test CA.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    value = json.loads(args.handoff.read_text())
    if value.get("fixture_only") is not True:
        raise ValueError("disposable fixture handoff required")
    counts = []
    with tempfile.TemporaryDirectory(prefix="polysia-browser-trust-") as directory:
        root = Path(directory)
        ca = root / "root.crt"
        ca.write_text(value["ca_certificate"])
        profile = root / "firefox"
        profile.mkdir()
        subprocess.run(
            ["certutil", "-N", "--empty-password", "-d", "sql:" + str(profile)], check=True
        )
        subprocess.run(
            [
                "certutil",
                "-A",
                "-n",
                "PolySia disposable fixture CA",
                "-t",
                "C,,",
                "-d",
                "sql:" + str(profile),
                "-i",
                str(ca),
            ],
            check=True,
        )
        with sync_playwright() as playwright:
            for width, height in ((1280, 800), (390, 844)):
                context = playwright.firefox.launch_persistent_context(
                    user_data_dir=str(profile),
                    headless=True,
                    ignore_https_errors=False,
                    viewport={"width": width, "height": height},
                    http_credentials={
                        "username": value["username"],
                        "password": value["password"],
                        "origin": "https://localhost:8443",
                    },
                )
                try:
                    page = context.new_page()
                    page.goto("https://localhost:8443", wait_until="networkidle")
                    page.get_by_role("button", name="System / Setup", exact=True).click()
                    expect(
                        page.get_by_label("Installed release and compatibility", exact=True)
                    ).to_contain_text("0.4.0")
                    page.get_by_role("button", name="Evaluate", exact=True).click()
                    expect(
                        page.get_by_label("Same-tape Shadow comparison", exact=True)
                    ).to_contain_text("NO_MEASURABLE_RESULT")
                    page.get_by_role("button", name="Operate", exact=True).click()
                    page.locator("#operation").select_option("acquisition.export|acquisition")
                    page.get_by_label("Optional start (UTC)").fill("2026-10-01T00:00")
                    page.get_by_label("Optional end (UTC)").fill("2026-10-02T00:00")
                    # Await an observed automatic refresh, not a fixed sleep.
                    with page.expect_response(
                        lambda response: response.url.endswith("/session"), timeout=25000
                    ):
                        pass
                    expect(page.get_by_label("Optional start (UTC)")).to_have_value(
                        "2026-10-01T00:00"
                    )
                    expect(page.get_by_label("Optional end (UTC)")).to_have_value(
                        "2026-10-02T00:00"
                    )
                    page.locator("#operation").select_option("acquisition.stop|acquisition")
                    page.get_by_role("button", name="Preview operation", exact=True).focus()
                    page.keyboard.press("Enter")
                    expect(page.get_by_role("dialog")).to_be_visible()
                    page.get_by_role("button", name="Request exact operation", exact=True).focus()
                    page.keyboard.press("Enter")
                    expect(page.get_by_text("acquisition.stop", exact=True).first).to_be_visible()
                    page.goto("https://localhost:8443/?example=1", wait_until="networkidle")
                    expect(
                        page.get_by_text(
                            "Synthetic example. No financial readiness or commands.", exact=True
                        )
                    ).to_be_visible()
                    page.get_by_role("button", name="Operate", exact=True).click()
                    expect(
                        page.get_by_role("button", name="Preview operation", exact=True)
                    ).to_be_disabled()
                    expect(page.get_by_label("Session context", exact=True)).to_contain_text(
                        "SYNTHETIC"
                    )
                    counts.append({"width": width, "height": height, "journey": "PASS"})
                finally:
                    context.close()
    args.output.write_text(
        json.dumps(
            {
                "status": "PASS",
                "trust": "ISOLATED_FIREFOX_CA",
                "certificate_validation": "ENABLED",
                "viewports": counts,
                "human_acceptance": "NOT_CLAIMED",
            },
            indent=2,
        )
        + "\n"
    )
    args.handoff.unlink()


if __name__ == "__main__":
    main()
