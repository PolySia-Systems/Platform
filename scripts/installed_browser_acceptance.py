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
                    expect(page.locator("#setup-state")).to_contain_text("Installed release:")
                    expect(page.locator("#control")).to_have_text("NO MEASURABLE RESULT")
                    page.locator("#report-start").fill("2026-10-01T00:00")
                    page.locator("#report-end").fill("2026-10-02T00:00")
                    page.locator("#wallet-filter").fill("retained-input-fixture")
                    page.wait_for_timeout(21000)
                    expect(page.locator("#report-start")).to_have_value("2026-10-01T00:00")
                    expect(page.locator("#report-end")).to_have_value("2026-10-02T00:00")
                    expect(page.locator("#wallet-filter")).to_have_value("retained-input-fixture")
                    page.locator('button[data-action="stop"]').focus()
                    page.keyboard.press("Enter")
                    expect(page.locator("#receipt")).to_contain_text("Command")
                    expect(page.locator("#receipts")).to_contain_text("stop")
                    page.goto("https://localhost:8443/demo", wait_until="networkidle")
                    expect(page.locator("#operation")).to_have_text("Offline demonstration")
                    expect(page.locator('button[data-action="stop"]')).to_be_disabled()
                    expect(page.locator("#scope")).to_contain_text("OFFLINE_DEMO")
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
