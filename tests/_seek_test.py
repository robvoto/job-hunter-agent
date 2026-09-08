"""Tests for seek."""

from playwright.sync_api import sync_playwright

from job_hunter_agent.paths import SEEK_PLAYWRIGHT_USER_DATA_DIR
from job_hunter_agent.scrapers.seek import SELECTOR_CARDS

url = "https://www.seek.com.au/jobs?keywords=senior+business+analyst&where=Sydney&daterange=3&sortMode=ListedDate"
SEEK_PLAYWRIGHT_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(SEEK_PLAYWRIGHT_USER_DATA_DIR),
        headless=True,
        viewport={"width": 1400, "height": 900},
    )
    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector(SELECTOR_CARDS, timeout=10000)
        cards = page.query_selector_all(SELECTOR_CARDS)
        print(f"Cards found: {len(cards)}")
        if cards:
            title_el = cards[0].query_selector('[data-automation="jobTitle"]')
            print("First title:", title_el.inner_text() if title_el else "N/A")
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        body = page.text_content("body") or ""
        print("Body snippet:", body[:500])
    context.close()
