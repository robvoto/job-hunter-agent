from playwright.sync_api import sync_playwright
import time
import re
from html import escape
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from typing import Optional, Tuple

# Your exact filtered search URL - Sydney NSW 3 days top
SEEK_URL = "https://www.seek.com.au/business-analyst-jobs/in-All-Sydney-NSW?classification=6076%2C1209%2C6123%2C6281%2C1223%2C1210&daterange=3"

# ---------- FILTERS ----------

def passes_title_filters(title: str) -> Tuple[bool, str]:
    """
    Title-based gatekeeping.
    Returns (True, "OK") if title is acceptable, else (False, "REASON").
    """
    if not title:
        return False, "TITLE_EMPTY"

    title_lower = title.strip().lower()

    # Step 1: Must look like a BA role (tight)
    allowed_ba_title_patterns = [
        r"\bbusiness analyst\b",
        r"\btechnical business analyst\b",
        r"\bsenior business analyst\b",
        r"\blead business analyst\b",
        r"\bprincipal business analyst\b",
        r"\bdigital business analyst\b",
        r"\bpayments business analyst\b",
        r"\bgovernment business analyst\b",
    ]
    if not any(re.search(pattern, title_lower) for pattern in allowed_ba_title_patterns):
        return False, "TITLE_NOT_BA"

    # Step 2: Reject roles that aren't BA even if they contain BA-ish wording
    bad_role_patterns = [
        r"\bproject manager\b",
        r"\bprogram manager\b",
        r"\bproduct manager\b",
        r"\bproduct owner\b",
        r"\bproduct owner\b",
        r"\bscrum master\b",
        r"\bchange analyst\b",
        r"\bservice transition\b",
        r"\bapplication support\b",
        r"\bsupport analyst\b",
        r"\bdata governance\b",
        r"\bdeveloper\b",
        r"\bengineer\b",
        r"\btester\b|\btest analyst\b|\bqa\b",
        r"\bconsultant\b",
        r"\bintern\b",
        r"\bofficer\b",
        r"\bcoordinator\b",
    ]
    for pattern in bad_role_patterns:
        if re.search(pattern, title_lower):
            return False, f"TITLE_BAD_ROLE:{pattern}"

    # Step 3: Reject titles that are basically tool/platform specialists (not you)
    bad_title_patterns = [
        r"\bservicenow\b",
        r"\bdynamics\s*365\b",
        r"\bms\s*dynamics\b",
        r"\bzoho\b",
        r"\bsalesforce\b",
        r"\bworkday\b",
        r"\bsap\b",
        r"\boracle\b",
        r"\bnetsuite\b",
        r"\bunderwriting\b",
    ]
    for pattern in bad_title_patterns:
        if re.search(pattern, title_lower):
            return False, f"TITLE_BAD_KEYWORD:{pattern}"

    return True, "OK"


def passes_content_filters(details_text: str) -> Tuple[bool, str]:
    """
    Description-based filtering.
    Returns (True, "OK") if description fits, else (False, "REASON").
    """
    if not details_text:
        return False, "DESC_EMPTY"

    description_lower = details_text.lower()

    # --- Wealth / banking style roles (not you)
    finance_bad_phrases = [
        "wealth management",
        "private banking",
        "private wealth",
        "funds management",
        "portfolio management",
    ]
    for phrase in finance_bad_phrases:
        if phrase in description_lower:
            return False, f"DESC_FINANCE:{phrase}"

    # --- Treasury / loan systems (not you)
    treasury_bad_phrases = [
        "treasury",
        "loan systems",
        "loan system",
        "core banking",
        "derivatives",
        "market data feed",
        "debt instruments",
        "amortization",
    ]
    for phrase in treasury_bad_phrases:
        if phrase in description_lower:
            return False, f"DESC_TREASURY:{phrase}"

    # --- Underwriting domain (not you)
    underwriting_patterns = [
        r"\bunderwriting\b",
        r"\bunderwriter\b",
    ]
    for pattern in underwriting_patterns:
        if re.search(pattern, description_lower):
            return False, f"DESC_UNDERWRITING:{pattern}"

    # --- ERP / Finance Systems / GL / AP AR roles (not you)
    # IMPORTANT: we do NOT reject "superannuation" because it may just be pay text.
    erp_finance_systems_patterns = [
        r"\berp\b",
        r"\bfinance systems?\b",
        r"\bfinancial systems?\b",
        r"\bfinance function\b",
        r"\bgeneral ledger\b|\bgl\b",
        r"\baccounts payable\b|\baccounts receivable\b",
        r"\bpayable\b|\breceivable\b",
        r"\bmonth[- ]end\b|\byear[- ]end\b",
        r"\breconciliation\b",
        r"\bchart of accounts\b",
    ]
    for pattern in erp_finance_systems_patterns:
        if re.search(pattern, description_lower):
            return False, f"DESC_ERP_FIN:{pattern}"

    return True, "OK"


# ---------- HELPERS ----------

def extract_salary(details_text: str) -> str:
    """
    Pull a salary-ish line from the details pane text.
    (Best-effort: SEEK formats vary)
    """
    if not details_text:
        return "N/A"

    lines = [line.strip() for line in details_text.splitlines() if line.strip()]
    for line in lines[:20]:
        line_lower = line.lower()
        if (
            "salary" in line_lower
            or "package" in line_lower
            or "$" in line
            or "k p.a." in line_lower
            or "per day" in line_lower
            or "daily rate" in line_lower
            or "incl super" in line_lower
        ):
            return line
    return "N/A"


def set_page_param(url: str, page_num: int) -> str:
    """
    Updates/sets page= in the URL while keeping all other filters intact.
    """
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query, keep_blank_values=True)
    query_params["page"] = [str(page_num)]
    new_query = urlencode(query_params, doseq=True)
    return urlunparse(
        (parsed_url.scheme, parsed_url.netloc, parsed_url.path, parsed_url.params, new_query, parsed_url.fragment)
    )


def safe_html(text: str) -> str:
    return escape(text or "", quote=True)


def fingerprint_text(text: str) -> str:
    """
    A simple fingerprint so we can detect when the right-side details pane changes.
    """
    if not text:
        return ""
    snippet_start = text[:120]
    snippet_end = text[-120:] if len(text) > 120 else text
    return f"{len(text)}::{snippet_start}::{snippet_end}"


def wait_for_details_text_change(
    page,
    previous_fingerprint: str,
    minimum_length: int = 200,
    timeout_seconds: float = 8.0,
) -> str:
    """
    Wait until the details pane text changes (not just "exists").
    This is the main fix for your 'only 2 descriptions' issue.
    """
    start_time = time.time()
    last_seen_text = ""

    while time.time() - start_time < timeout_seconds:
        try:
            page.wait_for_selector('[data-automation="jobAdDetails"]', timeout=2000)
            current_text = (page.text_content('[data-automation="jobAdDetails"]') or "").strip()
            last_seen_text = current_text

            current_fp = fingerprint_text(current_text)
            changed = current_fp != previous_fingerprint

            if changed and len(current_text) >= minimum_length:
                return current_text
        except Exception:
            pass

        time.sleep(0.2)

    return last_seen_text.strip()


def extract_job_id_from_relative_url(relative_url: str) -> Optional[str]:
    match = re.search(r"/job/(\d+)", relative_url or "")
    return match.group(1) if match else None


def try_click_job_card(page, card) -> bool:
    """
    Clicking on Seek can be flaky (overlays, intercepts).
    This tries a few safe click approaches without hard waits.
    """
    try:
        card.scroll_into_view_if_needed()
    except Exception:
        pass

    # Prefer the overlay link if it exists (usually the most reliable click target)
    try:
        overlay_link = card.query_selector('[data-automation="job-list-item-link-overlay"]')
        if overlay_link:
            overlay_link.click()
            return True
    except Exception:
        pass

    # Fallback: click the title link
    try:
        title_link = card.query_selector('[data-automation="jobTitle"]')
        if title_link:
            title_link.click()
            return True
    except Exception:
        pass

    # Last resort: click the whole card
    try:
        card.click()
        return True
    except Exception:
        return False


def wait_for_pane_to_show_new_job(
    page,
    previous_details_fingerprint: str,
    timeout_ms: int = 2500,      # FAST: 2.5s
    minimum_details_length: int = 200,
) -> str:
    """
    Fast wait: Playwright waits until details text fingerprint changes + length is ok.
    No polling loop in Python.
    """
    try:
        page.wait_for_selector('[data-automation="jobAdDetails"]', timeout=timeout_ms)

        page.wait_for_function(
            previous_details_fingerprint,
            minimum_details_length,
            timeout=timeout_ms
        )

        return (page.text_content('[data-automation="jobAdDetails"]') or "").strip()

    except Exception:
        # If fast wait fails, just return whatever is there (caller decides reject/keep)
        return (page.text_content('[data-automation="jobAdDetails"]') or "").strip()



# ---------- MAIN SCRAPER ----------

def scrape_seek_jobs(max_pages_cap: int = 10):
    """
    - Paginates via page=1..N (keeps your existing URL filters)
    - Reads cards: normalJob + premiumJob
    - Clicks each card to load the right-hand details pane (no new tabs)
    - Filters by title + content
    - Outputs a fresh HTML file each run
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        page = browser.new_page()

        # Wide viewport helps Seek keep the right-hand pane layout stable
        page.set_viewport_size({"width": 1400, "height": 900})

        output_path = "seek_results.html"

        try:
            with open(output_path, "w", encoding="utf-8") as out:
                out.write("<html><head><meta charset='utf-8'></head><body>\n")
                out.write("<h1>SEEK – Filtered Results</h1>\n")
                out.write("<ul>\n")

                kept_count = 0
                seen_urls = set()

                current_page_num = 1
                while current_page_num <= max_pages_cap:
                    page_url = set_page_param(SEEK_URL, current_page_num) if current_page_num > 1 else SEEK_URL

                    print(f"\n=== Page {current_page_num} ===")
                    print("URL:", page_url)

                    page.goto(page_url)
                    page.wait_for_load_state("networkidle")

                    job_cards = page.query_selector_all(
                        'article[data-automation="normalJob"], article[data-automation="premiumJob"]'
                    )
                    print(f"Found {len(job_cards)} job cards")

                    if len(job_cards) == 0:
                        print("No cards found. Stopping.")
                        break

                    # Read current details pane fingerprint at start of page
                    try:
                        details_before_click = (page.text_content('[data-automation="jobAdDetails"]') or "").strip()
                    except Exception:
                        details_before_click = ""

                    previous_details_fingerprint = fingerprint_text(details_before_click)

                    for card in job_cards:
                        title_element = card.query_selector('[data-automation="jobTitle"]')
                        company_element = card.query_selector('[data-automation="jobCompany"]')
                        posted_element = card.query_selector('[data-automation="jobListingDate"]')

                        title = title_element.inner_text().strip() if title_element else ""
                        ok_title, title_reason = passes_title_filters(title)
                        if not ok_title:
                            print(f"REJECTED (title) [{title_reason}] {title}")
                            continue

                        company = company_element.inner_text().strip() if company_element else "N/A"
                        posted = posted_element.inner_text().strip() if posted_element else "N/A"

                        relative_url = title_element.get_attribute("href") if title_element else None
                        if not relative_url:
                            print(f"REJECTED (card) [NO_URL] {title} @ {company}")
                            continue

                        full_url = f"https://www.seek.com.au{relative_url}"

                        if full_url in seen_urls:
                            print(f"SKIP (duplicate) {title} @ {company}")
                            continue
                        seen_urls.add(full_url)

                        # Click card (robust)
                        clicked = try_click_job_card(page, card)
                        if not clicked:
                            print(f"REJECTED (click) [CLICK_FAIL] {title} @ {company}")
                            continue

                        # IMPORTANT CHANGE:
                        # Do NOT reject if we can't "prove" pane update via URL/apply link.
                        # Just wait for the pane DETAILS TEXT to change (this is the real objective).
                        details_text = wait_for_pane_to_show_new_job(
                            page=page,
                            previous_details_fingerprint=previous_details_fingerprint,
                            timeout_ms=2500,
                            minimum_details_length=200,
                        )

                        # Update fingerprint so next click expects a change from THIS one
                        previous_details_fingerprint = fingerprint_text(details_text)

                        if not details_text or len(details_text) < 200:
                            print(f"REJECTED (details) [NO_DETAILS] {title} @ {company} | {full_url}")
                            continue

                        ok_desc, desc_reason = passes_content_filters(details_text)
                        if not ok_desc:
                            print(f"REJECTED (content) [{desc_reason}] {title} @ {company}")
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

            print(f"\nSaved jobs to {output_path}")

        finally:
            browser.close()


if __name__ == "__main__":
    scrape_seek_jobs()
