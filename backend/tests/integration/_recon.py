"""Reconnaissance: inspect the frontend page."""

import contextlib

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    page.goto("http://localhost:5173")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    # Take screenshot
    page.screenshot(
        path="c:/Users/15116/Desktop/aiplatform/backend/tests/integration/_recon_initial.png",
        full_page=True,
    )

    # Get all buttons and links
    title = page.title()
    print(f"Page title: {title}")

    buttons = page.locator("button").all()
    print(f"\nButtons ({len(buttons)}):")
    for i, b in enumerate(buttons[:20]):
        with contextlib.suppress(Exception):
            print(f"  [{i}] text='{b.inner_text()[:50]}' visible={b.is_visible()}")

    links = page.locator("a").all()
    print(f"\nLinks ({len(links)}):")
    for i, line in enumerate(links[:20]):
        with contextlib.suppress(Exception):
            print(f"  [{i}] text='{line.inner_text()[:50]}' href='{line.get_attribute('href')}'")

    inputs = page.locator("input").all()
    print(f"\nInputs ({len(inputs)}):")
    for i, inp in enumerate(inputs[:20]):
        with contextlib.suppress(Exception):
            print(
                f"  [{i}] type='{inp.get_attribute('type')}' placeholder='{inp.get_attribute('placeholder')}' name='{inp.get_attribute('name')}'"
            )

    # Get page text content (first 500 chars)
    text = page.locator("body").inner_text()
    print(f"\nBody text (first 500 chars):\n{text[:500]}")

    browser.close()
    print("\nRecon complete.")
