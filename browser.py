from playwright.sync_api import sync_playwright

import time

# Your exact filtered search URL - Sydney NSW 3 days top
SEEK_URL = "https://www.seek.com.au/business-analyst-jobs/in-All-Sydney-NSW?classification=6076%2C1209%2C6123%2C6281%2C1223&daterange=3"

def passes_content_filters(text: str) -> bool:
    """
    Rule-based filter on the job description text.
    Returns False for things that are clearly not you.
    """
    if not text:
        return False

    t = text.lower()

    bad_keywords = [
        "wealth management",
        "wealth-management",
        "private banking",
        "private bank",
        "superannuation",
        "super fund",
        "super-fund",
        "financial adviser",
        "financial advisor",
        "financial planning",
        "financial planner",
        "private wealth",
    ]

    for bad in bad_keywords:
        if bad in t:
            return False

    return True


def extract_salary(text: str) -> str:
    """
    Try to pull a salary line from the job details text.

    Very simple: look at the first few non-empty lines and
    return the first one that looks like it contains salary info.
    """
    if not text:
        return "N/A"

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in lines[:10]:
        lower = line.lower()
        if "salary" in lower or "package" in lower or "$" in line or "k p.a." in lower:
            return line

    return "N/A"


def scrape_seek_jobs(max_pages: int = 2):
    """
    Scrape SEEK BA jobs for Consulting & Strategy in All Sydney NSW.

    It will:
    - Start at the base URL (page 1)
    - Increment ?page=2, ?page=3, ...
    - Stop when a page has 0 job cards or when max_pages is reached
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
       
	# Open output HTML file
        output = open("seek_results.html", "w", encoding="utf-8")
        output.write("<html><body>\n")
        output.write("<h1>Seek BA – Consulting & Strategy – Recent roles</h1>\n")
        output.write("<ul>\n")

        page = browser.new_page()

        kept_count = 0

        for page_num in range(1, max_pages + 1):
            # Build the URL for this page
            if page_num == 1:
                page_url = SEEK_URL
            else:
                # If the base URL ever changes, this still works:
                sep = "&" if "?" in SEEK_URL else "?"
                page_url = f"{SEEK_URL}{sep}page={page_num}"

            print(f"\n=== Page {page_num} ===")
            print("URL:", page_url)

            page.goto(page_url)
            page.wait_for_load_state("networkidle")

            # Normal + premium job cards
            job_cards = page.query_selector_all(
                'article[data-automation="normalJob"], article[data-automation="premiumJob"]'
            )

            print(f"Found {len(job_cards)} job cards")

            # If no jobs, we assume there are no more pages
            if len(job_cards) == 0:
                print("No job cards on this page. Stopping pagination.")
                break

            for card in job_cards:
                title_el = card.query_selector('[data-automation="jobTitle"]')
                company_el = card.query_selector('[data-automation="jobCompany"]')
                date_el = card.query_selector('[data-automation="jobListingDate"]')

                title = title_el.inner_text().strip() if title_el else "N/A"
                company = company_el.inner_text().strip() if company_el else "N/A"
                date_text = date_el.inner_text().strip() if date_el else "N/A"

                rel_url = title_el.get_attribute("href") if title_el else None
                full_url = f"https://www.seek.com.au{rel_url}" if rel_url else None

                if not full_url or not title_el:
                    continue

                # Click the card/title to load the details pane on the right
                try:
                    title_el.click()
                except Exception as e:
                    print(f"Could not click job card {title_el}: {e}")
                    continue

                # Give the details pane time to update
                time.sleep(0.7)

                try:
                    details_text = page.text_content('[data-automation="jobAdDetails"]') or ""
                except Exception:
                    details_text = ""

                # Content-based filter (wealth management, super, etc.)
                if not passes_content_filters(details_text):
                    print(f"REJECTED (content): {title} @ {company}")
                    continue

                # Extract salary line (if any)
                salary = extract_salary(details_text)

                kept_count += 1
                print("----- Job (KEPT) -----")
                print("Title:", title)
                print("Company:", company)
                print("Posted:", date_text)
                print("Salary:", salary)
                print("URL:", full_url)

                # HTML-escape double quotes just in case
                safe_url = full_url.replace('"', "&quot;")
                safe_title = title.replace('"', "&quot;")
                safe_company = company.replace('"', "&quot;")
                safe_salary = salary.replace('"', "&quot;")

                # Add to HTML output
                if salary != "N/A":
                    output.write(
                        f'<li><a href="{safe_url}" target="_blank">{safe_title}</a> '
                        f'- {safe_company} (Posted: {date_text}, Salary: {safe_salary})</li>\n'
                    )
                else:
                    output.write(
                        f'<li><a href="{safe_url}" target="_blank">{safe_title}</a> '
                        f'- {safe_company} (Posted: {date_text})</li>\n'
                    )

        output.write("</ul>\n")
        output.write(f"<p>Total kept: {kept_count}</p>\n")
        output.write("</body></html>\n")
        output.close()

        print(f"\nSaved {kept_count} jobs to seek_results.html")

        browser.close()


if __name__ == "__main__":
    scrape_seek_jobs()
