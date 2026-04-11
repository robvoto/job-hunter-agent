# scraper.py

import json
import time
from pathlib import Path
from typing import Dict, Set

from playwright.sync_api import sync_playwright

from config import (
    SEEK_URL,
    OUTPUT_HTML,
    MAX_PAGES_CAP,
    DETAILS_MIN_LEN,
    PANE_UPDATE_TIMEOUT_MS,
    PANE_TEXT_TIMEOUT_SECONDS,
)
from filters import passes_title_filters, passes_content_filters
from utils import (
    safe_html,
    set_page_param,
    extract_job_id_from_relative_url,
    fingerprint_text,
    extract_salary,
)

# LLM (import once, not inside the loop)
from llm_gate import llm_should_consider


SELECTOR_CARDS = 'article[data-automation="normalJob"], article[data-automation="premiumJob"]'
SELECTOR_TITLE = '[data-automation="jobTitle"]'
SELECTOR_COMPANY = '[data-automation="jobCompany"]'
SELECTOR_POSTED = '[data-automation="jobListingDate"]'
SELECTOR_OVERLAY = '[data-automation="job-list-item-link-overlay"]'

SELECTOR_DETAILS = '[data-automation="jobAdDetails"]'
SELECTOR_APPLY = '[data-automation="jobAdApply"]'


# ---- LLM COST CONTROLS ----
MAX_LLM_CHARS = 3000  # truncate job description sent to LLM (big cost saver)
LLM_CACHE_PATH = Path("llm_cache.json")  # persistent cache across runs


def load_llm_cache() -> Dict[str, str]:
    if not LLM_CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(LLM_CACHE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            # ensure values are strings
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
        # cache save failure should never break scraping
        pass


def wait_for_job_details_loaded(page, job_id: str, timeout_ms: int) -> bool:
    """
    Confirm right-hand pane is showing the job we clicked.
    Proof: Apply button/link href contains this job_id.
    """
    try:
        page.wait_for_selector(SELECTOR_APPLY, timeout=timeout_ms)
        page.wait_for_function(
            """(jobId, sel) => {
                const a = document.querySelector(sel);
                if (!a) return false;
                const href = a.getAttribute('href') || '';
                return href.includes(jobId);
            }""",
            job_id,
            SELECTOR_APPLY,
            timeout=timeout_ms
        )
        return True
    except Exception:
        return False


def wait_for_details_text_change(
    page,
    previous_fingerprint: str,
    minimum_length: int,
    timeout_seconds: float,
) -> str:
    """
    Small/fast poll for details text change (no hard sleep like wait_for_timeout(3000)).
    """
    start = time.time()
    last_text = ""

    while (time.time() - start) < timeout_seconds:
        try:
            page.wait_for_selector(SELECTOR_DETAILS, timeout=500)
            current = (page.text_content(SELECTOR_DETAILS) or "").strip()
            last_text = current

            if len(current) >= minimum_length and fingerprint_text(current) != previous_fingerprint:
                return current
        except Exception:
            pass

        time.sleep(0.12)

    return last_text.strip()


def scrape_seek_jobs(max_pages_cap: int = MAX_PAGES_CAP, headless: bool = False) -> str:
    """
    - Paginates via page=1..N (keeps your existing URL filters)
    - Reads cards: normalJob + premiumJob
    - Clicks each card to load the right-hand details pane (no new tabs)
    - Filters by title + content
    - LLM gate (KEEP/REJECT/MAYBE) with truncation + caching
    - Outputs a fresh HTML file each run
    Returns output path.
    """
    llm_cache: Dict[str, str] = load_llm_cache()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page()

        output_path = OUTPUT_HTML

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

                page.goto(page_url, wait_until="domcontentloaded")
                page.wait_for_selector(SELECTOR_CARDS, timeout=8000)

                job_cards = page.query_selector_all(SELECTOR_CARDS)
                print(f"Found {len(job_cards)} job cards")

                if len(job_cards) == 0:
                    print("No cards found. Stopping.")
                    break

                # baseline fingerprint from whatever is currently in the pane
                try:
                    details_before = (page.text_content(SELECTOR_DETAILS) or "").strip()
                except Exception:
                    details_before = ""
                prev_fp = fingerprint_text(details_before)

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

                    # click (overlay is most reliable)
                    try:
                        overlay = card.query_selector(SELECTOR_OVERLAY)
                        (overlay or title_el).click()
                    except Exception as e:
                        print(f"REJECTED (click) [CLICK_FAIL] {title} @ {company} ({e})")
                        continue

                    # quick confirm pane updated (keep short)
                    job_id = extract_job_id_from_relative_url(relative_url)
                    if job_id:
                        loaded = wait_for_job_details_loaded(page, job_id, timeout_ms=PANE_UPDATE_TIMEOUT_MS)
                        if not loaded:
                            # fallback: if seek changed apply link logic, accept a text-change proof
                            details_text = wait_for_details_text_change(
                                page=page,
                                previous_fingerprint=prev_fp,
                                minimum_length=DETAILS_MIN_LEN,
                                timeout_seconds=PANE_TEXT_TIMEOUT_SECONDS,
                            )
                            if not details_text or len(details_text) < DETAILS_MIN_LEN:
                                print(f"REJECTED (details) [PANE_NOT_UPDATED] {title} @ {company} | {full_url}")
                                continue
                        else:
                            details_text = (page.text_content(SELECTOR_DETAILS) or "").strip()
                    else:
                        # no job id? fallback to text change
                        details_text = wait_for_details_text_change(
                            page=page,
                            previous_fingerprint=prev_fp,
                            minimum_length=DETAILS_MIN_LEN,
                            timeout_seconds=PANE_TEXT_TIMEOUT_SECONDS,
                        )

                    # update fingerprint for next click
                    prev_fp = fingerprint_text(details_text)

                    if not details_text or len(details_text) < DETAILS_MIN_LEN:
                        print(f"REJECTED (details) [NO_DETAILS] {title} @ {company} | {full_url}")
                        continue

                    ok_desc, desc_reason = passes_content_filters(details_text)
                    if not ok_desc:
                        print(f"REJECTED (content) [{desc_reason}] {title} @ {company}")
                        continue

                    # ---- LLM gate with truncation + caching ----
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
                    # KEEP or MAYBE continues
                    # ------------------------------------------

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

        # persist cache even if something went wrong mid-run
        save_llm_cache(llm_cache)

        print(f"\nSaved {kept_count} jobs to {output_path}")
        browser.close()
        return output_path
