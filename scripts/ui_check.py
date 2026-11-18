"""Check the web app end to end, in a real (headless) browser, against the answer key.

What it does, exactly as a person would:
  1. Presses "Reset demo data" in the header and confirms.
  2. For each of the 13 samples: opens "New run", clicks the sample, waits for the decision
     banner, and reads the decision off the screen.
  3. Compares each decision with data/invoices/expected.json.
  4. Opens the dashboard and checks that all 13 runs are listed.

It calls the live AI model 13 times (about US $0.22). Both servers must be running first
(`make dev`). Run it with `make ui-check`.
"""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = "http://localhost:5173"


def main() -> int:
    expected = json.loads(
        (REPO_ROOT / "data" / "invoices" / "expected.json").read_text(encoding="utf-8"))["invoices"]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        # 1. Reset, using the button and its confirmation dialog.
        page.goto(BASE + "/")
        page.get_by_role("button", name="Reset demo data").click()
        page.get_by_role("alertdialog").get_by_role("button", name="Reset demo data").click()
        page.wait_for_selector("text=No invoices have been run yet")

        # 2 and 3. Run every sample and compare what the screen says with the answer key.
        all_match = True
        for entry in expected:
            number = f"{entry['case']:02d}"
            page.goto(BASE + "/new")
            card = page.locator("section", has=page.locator(f"span.num:text-is('{number}')")).first
            card.locator("button").click()
            page.wait_for_url("**/runs/*")
            page.wait_for_selector("text=Next step", timeout=90_000)
            banner = page.locator("section", has=page.locator("text=Next step")).first
            shown = banner.locator("span.uppercase").first.inner_text().strip().upper()
            headline = banner.locator("h2").inner_text()
            wanted = entry["expected"]["decision"]
            verdict = "OK" if shown == wanted else "MISMATCH"
            all_match &= shown == wanted
            print(f"{number} {entry['file']:<34} expected {wanted:<8} on screen {shown:<8} "
                  f"{verdict}  {headline}")

        # 4. The dashboard lists every run.
        page.goto(BASE + "/")
        page.wait_for_selector("text=Seeded history")
        runs_table = page.locator("section", has=page.locator("h2:text-is('Runs')"))
        rows = runs_table.locator("tbody tr").count()
        print(f"Dashboard lists {rows} runs (expected {len(expected)}).")
        browser.close()

    if page_errors:
        print("Errors raised in the page:", page_errors)
    passed = all_match and rows == len(expected) and not page_errors
    print("UI CHECK PASSED" if passed else "UI CHECK FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
