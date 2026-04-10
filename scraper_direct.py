# scraper_direct.py

import json
from pathlib import Path
from typing import Dict, Set

from playwright.sync_api import sync_playwright

from config import SEEK_URL, OUTPUT_HTML, MAX_PAGES_CAP
from filters import passes_title_filters, passes_content_filters
from utils import safe_html, set_page_param, extract_salary, fingerprint_text

from llm_gate import llm_should_consider


SELECTOR_CARDS = 'article[data-automation="normalJob"], article[data-automation="premiumJob"]'
SELECTOR_TITLE = '[data-automation="jobTitle"]'
SELECTOR_COMPANY = '[data-automation="jobCompany"]'
SELECTOR_POSTED = '[data-automation="jobListingDate"]'
SELECTOR_DETAILS = '[data-automation="jobAdDetails"]'

MAX_LLM_CHARS = 3000
LLM_CACHE_PATH = Path("llm_cache.json")


def load_llm_cache() -> Dict[str, str]:
    if not LLM_CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(LLM_CACHE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def save_llm_cache(cache: Dict[str, str]) -> None:
    try:
        LLM_CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def fetch_job_details_text(detail_page, full_url: str) -> str:
    """
    Open each job directly instead of relying on SEEK's right-hand pane.
    """
    try:
        detail_page.goto(full_url, wait_until="domcontentloaded")
    except Exception:
        return ""

    try:
        detail_page.wait_for_selector(SELECTOR_DETAILS, timeout=8000)
        details_text = (detail_page.text_content(SELECTOR_DETAILS) or "").strip()
        if details_text:
            return details_text
    except Exception:
        pass

    try:
        return (detail_page.text_content("body") or "").strip()
    except Exception:
        return ""


def scrape_seek_jobs_direct(max_pages_cap: int = MAX_PAGES_CAP, headless: bool = False) -> str:
    llm_cache: Dict[str, str] = load_llm_cache()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        list_page = browser.new_page(viewport={"width": 1400, "height": 900})
        detail_page = browser.new_page(viewport={"width": 1400, "height": 900})

        output_path = OUTPUT_HTML

        try:
            with open(output_path, "w", encoding="utf-8") as out:
                out.write("<html><head><meta charset='utf-8'></head><body>\n")
                out.write("<h1>SEEK – Filtered Results</h1>\n")
                out.write("<ul>\n")

                kept_count = 0
                seen_urls: Set[str] = set()

                current_page_num = 1
                while current_page_num <= max_pages_cap:
                    page_url = set_page_param(SEEK_URL, current_page_num) if current_page_num > 1 else SEEK_URL

                    print(f"\n=== Page {current_page_num} ===")
                    print("URL:", page_url)

                    list_page.goto(page_url, wait_until="domcontentloaded")
                    list_page.wait_for_selector(SELECTOR_CARDS, timeout=8000)

                    job_cards = list_page.query_selector_all(SELECTOR_CARDS)
                    print(f"Found {len(job_cards)} job cards")

                    if len(job_cards) == 0:
                        print("No cards found. Stopping.")
                        break

                    for card in job_cards:
                        title_el = card.query_selector(SELECTOR_TITLE)
                        company_el = card.query_selector(SELECTOR_COMPANY)
                        posted_el = card.query_selector(SELECTOR_POSTED)

                        title = title_el.inner_text().strip() if title_el else ""
                        ok_title, title_reason = passes_title_filters(title)
                        if not ok_title:
                            print(f"REJECTED (title) [{title_reason}] {title}")
                            continue

                        company = company_el.inner_text().strip() if company_el else "N/A"
                        posted = posted_el.inner_text().strip() if posted_el else "N/A"

                        relative_url = title_el.get_attribute("href") if title_el else None
                        if not relative_url:
                            print(f"REJECTED (card) [NO_URL] {title} @ {company}")
                            continue

                        full_url = f"https://www.seek.com.au{relative_url}"

                        if full_url in seen_urls:
                            print(f"SKIP (duplicate) {title} @ {company}")
                            continue
                        seen_urls.add(full_url)

                        details_text = fetch_job_details_text(detail_page, full_url)
                        if not details_text:
                            print(f"REJECTED (details) [NO_DETAILS] {title} @ {company} | {full_url}")
                            continue

                        ok_desc, desc_reason = passes_content_filters(details_text)
                        if not ok_desc:
                            print(f"REJECTED (content) [{desc_reason}] {title} @ {company}")
                            continue

                        llm_input_text = details_text[:MAX_LLM_CHARS]
                        llm_fp = fingerprint_text(llm_input_text)

                        if llm_fp in llm_cache:
                            llm_decision = llm_cache[llm_fp]
                            print(f"[LLM][CACHE] {llm_decision} {title} @ {company}")
                        else:
                            llm_decision = llm_should_consider(llm_input_text)
                            llm_cache[llm_fp] = llm_decision
                            print(f"[LLM] {llm_decision} {title} @ {company}")

                        if llm_decision == "REJECT":
                            print(f"REJECTED (llm) [LLM_REJECT] {title} @ {company}")
                            continue

                        salary = extract_salary(details_text)

                        kept_count += 1
                        print(f"KEPT: {title} @ {company} | {posted} | {salary}")

                        out.write(
                            "<li>"
                            f"<a href=\"{safe_html(full_url)}\" target=\"_blank\">{safe_html(title)}</a>"
                            f" - {safe_html(company)}"
                            f" (Posted: {safe_html(posted)}"
                            f"{', Salary: ' + safe_html(salary) if salary != 'N/A' else ''})"
                            "</li>\n"
                        )

                    current_page_num += 1

                out.write("</ul>\n")
                out.write(f"<p>Total kept: {kept_count}</p>\n")
                out.write("</body></html>\n")

            save_llm_cache(llm_cache)
            print(f"\nSaved {kept_count} jobs to {output_path}")
            return output_path

        finally:
            browser.close()


if __name__ == "__main__":
    scrape_seek_jobs_direct()
