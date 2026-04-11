# scraper_direct.py

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

from config import MAX_PAGES_CAP, OUTPUT_HTML, SEEK_URL
from filters import passes_content_filters, passes_title_filters
from llm_gate import llm_is_enabled, llm_should_consider
from profile_store import get_search_settings, load_profile
from review_insights import build_review_data, extract_detected_skills
from utils import (
    extract_salary,
    fingerprint_text,
    parse_seek_posted_age_days,
    safe_html,
    set_page_param,
    set_query_param,
)


SELECTOR_CARDS = 'article[data-automation="normalJob"], article[data-automation="premiumJob"]'
SELECTOR_TITLE = '[data-automation="jobTitle"]'
SELECTOR_COMPANY = '[data-automation="jobCompany"]'
SELECTOR_POSTED = '[data-automation="jobListingDate"]'
SELECTOR_LOCATION = '[data-automation="jobLocation"]'
SELECTOR_CARD_SALARY = '[data-automation="jobSalary"]'
SELECTOR_SHORT_DESCRIPTION = '[data-automation="jobShortDescription"]'
SELECTOR_DETAILS = '[data-automation="jobAdDetails"]'

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
MAX_LLM_CHARS = 3000
LLM_CACHE_PATH = DATA_DIR / "llm_cache.json"
DEBUG_JSON_PATH = OUTPUT_DIR / "seek_results.json"
JOB_HISTORY_PATH = DATA_DIR / "job_history.json"
RUN_STATS_PATH = OUTPUT_DIR / "seek_run_stats.json"
REVIEW_DATA_PATH = OUTPUT_DIR / "seek_review_data.json"
SEEK_JOBS_BASE_URL = "https://www.seek.com.au/jobs"


def configure_console_output() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_json_dict(path: Path) -> Dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_llm_cache() -> Dict[str, str]:
    raw = load_json_dict(LLM_CACHE_PATH)
    return {str(k): str(v) for k, v in raw.items()}


def save_llm_cache(cache: Dict[str, str]) -> None:
    save_json(LLM_CACHE_PATH, cache)


def load_job_history() -> Dict[str, dict]:
    return load_json_dict(JOB_HISTORY_PATH)


def save_job_history(history: Dict[str, dict]) -> None:
    save_json(JOB_HISTORY_PATH, history)


def write_debug_json(records: List[dict]) -> None:
    save_json(DEBUG_JSON_PATH, records)


def write_run_stats(payload: dict) -> None:
    save_json(RUN_STATS_PATH, payload)


def write_review_data(payload: dict) -> None:
    save_json(REVIEW_DATA_PATH, payload)


def build_full_url(relative_or_full_url: Optional[str]) -> Optional[str]:
    if not relative_or_full_url:
        return None
    return urljoin("https://www.seek.com.au", relative_or_full_url)


def dedupe_preserve_order(values: List[str]) -> List[str]:
    seen: Set[str] = set()
    result: List[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def extract_work_type(card_text: str) -> str:
    match = re.search(r"This is a ([^\n]+?) job", card_text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "N/A"


def extract_card_metadata(card) -> dict:
    location_values = [
        (element.inner_text() or "").strip()
        for element in card.query_selector_all(SELECTOR_LOCATION)
    ]
    salary_el = card.query_selector(SELECTOR_CARD_SALARY)
    teaser_el = card.query_selector(SELECTOR_SHORT_DESCRIPTION)
    salary_text = salary_el.inner_text().strip() if salary_el else ""
    teaser_text = teaser_el.inner_text().strip() if teaser_el else ""
    card_text = (card.inner_text() or "").strip()

    return {
        "location": ", ".join(dedupe_preserve_order(location_values)) or "N/A",
        "work_type": extract_work_type(card_text),
        "card_salary": salary_text or "N/A",
        "teaser": teaser_text or "N/A",
    }


def build_seek_search_targets(profile: dict, configured_date_range: int, sort_newest_first: bool) -> List[dict]:
    search_settings = get_search_settings(profile)
    keywords = str(search_settings.get("keywords") or "").strip()
    locations = dedupe_preserve_order(
        [str(value).strip() for value in search_settings.get("locations", []) if str(value).strip()]
    ) or list(get_search_settings({}).get("locations", []))
    classification_ids = dedupe_preserve_order(
        [str(value).strip() for value in search_settings.get("classification_ids", []) if str(value).strip()]
    )

    targets: List[dict] = []
    for location in locations:
        search_url = SEEK_JOBS_BASE_URL
        search_url = set_query_param(search_url, "keywords", keywords)
        search_url = set_query_param(search_url, "where", location)
        if classification_ids:
            search_url = set_query_param(search_url, "classification", ",".join(classification_ids))
        search_url = set_query_param(search_url, "daterange", configured_date_range)
        if sort_newest_first:
            search_url = set_query_param(search_url, "sortMode", "ListedDate")
        targets.append(
            {
                "keywords": keywords,
                "location": location,
                "classification_ids": classification_ids,
                "url": search_url,
            }
        )
    return targets


def fetch_job_details_text(detail_page, full_url: str) -> str:
    try:
        detail_page.goto(full_url, wait_until="domcontentloaded")
    except Exception:
        return ""

    for selector in [
        'button:has-text("Show more")',
        'button:has-text("Read more")',
        'button:has-text("More")',
        '[aria-expanded="false"]',
    ]:
        try:
            locator = detail_page.locator(selector)
            max_clicks = min(locator.count(), 5)
            for index in range(max_clicks):
                try:
                    locator.nth(index).click(timeout=700)
                except Exception:
                    continue
        except Exception:
            continue

    try:
        detail_page.wait_for_selector(SELECTOR_DETAILS, timeout=8000)
        details_text = (detail_page.text_content(SELECTOR_DETAILS) or "").strip()
        if details_text:
            return details_text
    except Exception:
        pass

    try:
        detail_page.wait_for_load_state("networkidle", timeout=4000)
    except Exception:
        pass

    try:
        return (detail_page.text_content("body") or "").strip()
    except Exception:
        return ""


def stable_job_key(full_url: Optional[str]) -> Optional[str]:
    if not full_url:
        return None
    match = re.search(r"/job/(\d+)", full_url)
    if match:
        return match.group(1)
    return full_url.split("#", 1)[0]


def normalize_job_key(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    match = re.search(r"/job/(\d+)", value)
    if match:
        return match.group(1)
    id_match = re.fullmatch(r"\d+", value)
    if id_match:
        return value
    return value.split("#", 1)[0]


def get_manual_skip_sets(profile: dict) -> tuple[Set[str], Set[str]]:
    review_controls = profile.get("review_controls", {})
    applied = {
        normalize_job_key(value)
        for value in review_controls.get("applied_job_keys", [])
        if normalize_job_key(value)
    }
    hidden = {
        normalize_job_key(value)
        for value in review_controls.get("hidden_job_keys", [])
        if normalize_job_key(value)
    }
    return applied, hidden


def format_timestamp_label(value: Optional[str]) -> str:
    if not value:
        return "N/A"
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y %I:%M %p")
    except Exception:
        return value


def update_job_history(history: Dict[str, dict], record: dict, run_iso: str) -> None:
    job_key = record.get("job_key")
    if not job_key:
        record["seen_before"] = False
        record["times_kept"] = 0
        record["first_kept_at"] = None
        return

    entry = history.get(job_key, {})
    prior_kept_count = int(entry.get("times_kept", 0) or 0)

    entry["job_key"] = job_key
    entry["title"] = record.get("title")
    entry["company"] = record.get("company")
    entry["url"] = record.get("url")
    entry["last_seen_at"] = run_iso
    entry["times_seen"] = int(entry.get("times_seen", 0) or 0) + 1
    if not entry.get("first_seen_at"):
        entry["first_seen_at"] = run_iso

    record["seen_before"] = prior_kept_count > 0
    record["times_kept"] = prior_kept_count
    record["first_kept_at"] = entry.get("first_kept_at")
    record["first_seen_at"] = entry.get("first_seen_at")

    if record.get("decision") == "KEEP":
        if not entry.get("first_kept_at"):
            entry["first_kept_at"] = run_iso
        entry["last_kept_at"] = run_iso
        entry["times_kept"] = prior_kept_count + 1
        record["times_kept"] = entry["times_kept"]
        record["first_kept_at"] = entry["first_kept_at"]
        record["last_kept_at"] = entry["last_kept_at"]

    history[job_key] = entry


def finalize_record(history: Dict[str, dict], audit_rows: List[dict], record: dict, run_iso: str) -> None:
    update_job_history(history, record, run_iso)
    audit_rows.append(record)


def render_job_card(record: dict) -> str:
    title = safe_html(record.get("title", "Untitled"))
    company = safe_html(record.get("company", "N/A"))
    url = safe_html(record.get("url", "#"))
    job_key = safe_html(str(record.get("job_key") or ""))
    teaser = record.get("teaser", "N/A")
    title_reason = record.get("title_reason")
    seen_before = bool(record.get("seen_before"))

    badges = []
    if seen_before:
        badges.append('<span class="badge badge-seen">Seen Before</span>')
    else:
        badges.append('<span class="badge badge-new">New Match</span>')
    if title_reason == "TITLE_POTENTIAL_MATCH":
        badges.append('<span class="badge badge-potential">Potential Match</span>')

    chips = []
    for label, value in [
        ("Published", record.get("posted")),
        ("Location", record.get("location")),
        ("Type", record.get("work_type")),
        ("Salary", record.get("salary")),
    ]:
        if value and value != "N/A":
            chips.append(
                f'<span class="chip"><strong>{safe_html(label)}:</strong> {safe_html(str(value))}</span>'
            )

    history_line = (
        f"Seen kept before since {safe_html(format_timestamp_label(record.get('first_kept_at')))}"
        if seen_before
        else "First time this scraper has kept it"
    )

    teaser_html = (
        f'<p class="job-teaser">{safe_html(teaser)}</p>'
        if teaser and teaser != "N/A"
        else ""
    )

    return (
        '<article class="job-card">'
        f'<div class="job-badges">{"".join(badges)}</div>'
        f'<a class="job-link" href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>'
        f'<div class="job-company">{company}</div>'
        f'<div class="job-meta">{"".join(chips)}</div>'
        f"{teaser_html}"
        '<div class="job-actions">'
        f'<button class="review-button review-applied" type="button" data-review-action="applied" data-job-key="{job_key}" data-job-url="{url}">Applied</button>'
        f'<button class="review-button review-hide" type="button" data-review-action="hidden" data-job-key="{job_key}" data-job-url="{url}">Hide</button>'
        '<span class="review-status" aria-live="polite"></span>'
        "</div>"
        f'<div class="job-history">{safe_html(history_line)}</div>'
        "</article>"
    )


def render_section(title: str, records: List[dict], empty_message: str) -> str:
    if not records:
        return (
            f'<section class="section"><h2>{safe_html(title)}</h2>'
            f'<p class="empty-state">{safe_html(empty_message)}</p></section>'
        )
    cards = "".join(render_job_card(record) for record in records)
    return f'<section class="section"><h2>{safe_html(title)}</h2><div class="job-grid">{cards}</div></section>'


def build_run_stats(
    audit_rows: List[dict],
    kept_records: List[dict],
    run_started_at: datetime,
    date_range_days: int,
    sort_newest_first: bool,
    max_pages_cap: int,
) -> dict:
    search_targets: Dict[str, Set[int]] = {}
    reject_counts: Dict[str, int] = {}
    skip_counts: Dict[str, int] = {}

    for row in audit_rows:
        search_location = str(row.get("search_location") or "Unknown")
        page_num = row.get("page")
        if page_num is not None:
            search_targets.setdefault(search_location, set()).add(int(page_num))

        reason = row.get("reject_reason") or "UNKNOWN"
        decision = row.get("decision")
        if decision == "SKIP":
            skip_counts[reason] = skip_counts.get(reason, 0) + 1
        elif decision != "KEEP":
            reject_counts[reason] = reject_counts.get(reason, 0) + 1

    top_reject_reasons = [
        {"reason": reason, "count": count}
        for reason, count in sorted(reject_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
    ]

    detail_fetches = sum(1 for row in audit_rows if int(row.get("details_length") or 0) > 0)
    cards_seen = len(audit_rows)
    kept_count = len(kept_records)

    return {
        "run_started_at": run_started_at.isoformat(timespec="seconds"),
        "search_window_days": date_range_days,
        "sort_newest_first": sort_newest_first,
        "max_pages_cap": max_pages_cap,
        "search_targets": {
            location: sorted(pages)
            for location, pages in sorted(search_targets.items())
        },
        "page_count": sum(len(pages) for pages in search_targets.values()),
        "cards_seen": cards_seen,
        "detail_fetches": detail_fetches,
        "kept_count": kept_count,
        "keep_rate": round((kept_count / cards_seen), 4) if cards_seen else 0.0,
        "top_reject_reasons": top_reject_reasons,
        "skip_counts": skip_counts,
    }


def render_html(
    output_path: str,
    kept_records: List[dict],
    run_started_at: datetime,
    date_range_days: int,
    sort_newest_first: bool,
    run_stats: dict,
) -> None:
    new_records = [record for record in kept_records if not record.get("seen_before")]
    seen_records = [record for record in kept_records if record.get("seen_before")]
    run_label = run_started_at.strftime("%d %b %Y %I:%M %p")
    target_summaries = []
    for location, pages in (run_stats.get("search_targets") or {}).items():
        page_label = ", ".join(str(page) for page in pages) if pages else "none"
        target_summaries.append(f"{location}: pages {page_label}")

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SEEK Filtered Results</title>
  <style>
    :root {{
      --bg: #f4efe7;
      --panel: #fffaf2;
      --card: #ffffff;
      --ink: #1f2933;
      --muted: #5b6470;
      --line: #e6dccd;
      --accent: #14532d;
      --accent-soft: #e6f4ea;
      --warm: #9a3412;
      --warm-soft: #fff0e6;
      --cool: #1d4ed8;
      --cool-soft: #e8f0ff;
      --shadow: 0 12px 30px rgba(31, 41, 51, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      background:
        radial-gradient(circle at top left, rgba(20, 83, 45, 0.08), transparent 28%),
        radial-gradient(circle at top right, rgba(154, 52, 18, 0.08), transparent 24%),
        var(--bg);
      color: var(--ink);
    }}
    .page {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 32px 20px 64px;
    }}
    .hero {{
      background: linear-gradient(135deg, rgba(255, 250, 242, 0.96), rgba(255, 255, 255, 0.96));
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 28px;
      box-shadow: var(--shadow);
      margin-bottom: 24px;
    }}
    .hero h1 {{
      margin: 0 0 8px;
      font-size: clamp(2rem, 4vw, 3.2rem);
      line-height: 1;
      letter-spacing: -0.04em;
    }}
    .hero p {{
      margin: 0;
      color: var(--muted);
      font-size: 1rem;
    }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin: 20px 0 0;
    }}
    .summary-card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
    }}
    .summary-card strong {{
      display: block;
      font-size: 1.75rem;
      margin-bottom: 6px;
    }}
    .summary-card span {{
      color: var(--muted);
      font-size: 0.95rem;
    }}
    .section {{
      margin-top: 28px;
    }}
    .section h2 {{
      margin: 0 0 14px;
      font-size: 1.35rem;
      letter-spacing: -0.02em;
    }}
    .job-grid {{
      display: grid;
      gap: 16px;
    }}
    .job-card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 18px;
      box-shadow: var(--shadow);
    }}
    .job-badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 12px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 0.78rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .badge-new {{ background: var(--accent-soft); color: var(--accent); }}
    .badge-seen {{ background: var(--cool-soft); color: var(--cool); }}
    .badge-potential {{ background: var(--warm-soft); color: var(--warm); }}
    .job-link {{
      display: inline-block;
      color: var(--ink);
      text-decoration: none;
      font-size: 1.35rem;
      font-weight: 750;
      line-height: 1.2;
      margin-bottom: 6px;
    }}
    .job-link:hover {{ text-decoration: underline; }}
    .job-company {{
      color: var(--muted);
      font-size: 1rem;
      margin-bottom: 14px;
    }}
    .job-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 12px;
    }}
    .chip {{
      display: inline-flex;
      gap: 6px;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      background: var(--panel);
      border: 1px solid var(--line);
      font-size: 0.92rem;
    }}
    .job-teaser {{
      margin: 0 0 10px;
      color: var(--ink);
      line-height: 1.45;
    }}
    .job-history {{
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .job-actions {{
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      margin: 14px 0 10px;
    }}
    .review-button {{
      border: 0;
      border-radius: 999px;
      padding: 9px 14px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      transition: transform 120ms ease, opacity 120ms ease;
    }}
    .review-button:hover {{
      transform: translateY(-1px);
    }}
    .review-applied {{
      background: var(--accent-soft);
      color: var(--accent);
    }}
    .review-hide {{
      background: var(--warm-soft);
      color: var(--warm);
    }}
    .review-button[disabled] {{
      opacity: 0.6;
      cursor: progress;
      transform: none;
    }}
    .review-status {{
      color: var(--muted);
      font-size: 0.9rem;
      min-height: 1.2rem;
    }}
    .job-card.is-reviewed {{
      opacity: 0.55;
    }}
    .empty-state {{
      margin: 0;
      padding: 18px;
      background: var(--card);
      border: 1px dashed var(--line);
      border-radius: 18px;
      color: var(--muted);
    }}
    @media (max-width: 700px) {{
      .page {{ padding: 20px 14px 40px; }}
      .hero {{ padding: 22px 18px; }}
      .job-card {{ padding: 16px; }}
      .job-link {{ font-size: 1.15rem; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <h1>SEEK Filtered Results</h1>
      <p>Latest run: {safe_html(run_label)}. Search window: roles published within the last {date_range_days} day(s). SEEK sort: {"newest first" if sort_newest_first else "default relevance"}. This file updates each run, while history is tracked separately so repeats are clearly marked.</p>
      <div class="summary-grid">
        <div class="summary-card"><strong>{len(kept_records)}</strong><span>Kept This Run</span></div>
        <div class="summary-card"><strong>{len(new_records)}</strong><span>New Matches</span></div>
        <div class="summary-card"><strong>{len(seen_records)}</strong><span>Previously Seen</span></div>
        <div class="summary-card"><strong>{run_stats.get("page_count", 0)}</strong><span>Pages Crawled</span></div>
        <div class="summary-card"><strong>{run_stats.get("cards_seen", 0)}</strong><span>Cards Seen</span></div>
        <div class="summary-card"><strong>{run_stats.get("detail_fetches", 0)}</strong><span>Detail Pages Opened</span></div>
        <div class="summary-card"><strong>{round(float(run_stats.get("keep_rate", 0.0)) * 100, 1)}%</strong><span>Keep Rate</span></div>
      </div>
    </section>
    <section class="section">
      <h2>Run Efficiency</h2>
      <div class="job-card">
        <p class="job-teaser">Search targets this run: {safe_html(" | ".join(target_summaries) or "None")}. This is the fastest way to tell whether we stopped early because SEEK ran out of fresh pages or because the current page cap was reached.</p>
        <div class="job-meta">
          {''.join(f'<span class="chip"><strong>{safe_html(str(item.get("reason", "UNKNOWN")))}:</strong> {safe_html(str(item.get("count", 0)))}</span>' for item in run_stats.get("top_reject_reasons", []))}
        </div>
      </div>
    </section>
    {render_section("New Matches", new_records, "No brand-new kept roles this run.")}
    {render_section("Previously Seen Matches", seen_records, "No repeated kept roles this run.")}
  </main>
  <script>
    const REVIEW_API_URL = 'http://127.0.0.1:8765/api/review';

    async function saveReviewAction(button) {{
      const card = button.closest('.job-card');
      const status = card?.querySelector('.review-status');
      const action = button.dataset.reviewAction;
      const jobKey = button.dataset.jobKey || '';
      const jobUrl = button.dataset.jobUrl || '';

      if (!status) {{
        return;
      }}

      const buttons = card.querySelectorAll('.review-button');
      buttons.forEach(item => item.disabled = true);
      status.textContent = action === 'applied' ? 'Saving as applied...' : 'Saving hidden job...';

      try {{
        const response = await fetch(REVIEW_API_URL, {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            action,
            job_key: jobKey,
            url: jobUrl
          }})
        }});

        const payload = await response.json().catch(() => ({{}}));
        if (!response.ok) {{
          throw new Error(payload.error || 'Could not save review action');
        }}

        card.classList.add('is-reviewed');
        status.textContent = action === 'applied'
          ? 'Saved to Applied jobs. It will be hidden in future runs.'
          : 'Saved to Hidden jobs. It will stay out of future runs.';
        window.setTimeout(() => {{
          card.style.display = 'none';
        }}, 900);
      }} catch (error) {{
        buttons.forEach(item => item.disabled = false);
        status.textContent = error.message || 'Could not save review action.';
      }}
    }}

    document.addEventListener('click', event => {{
      const button = event.target.closest('.review-button');
      if (!button) {{
        return;
      }}
      saveReviewAction(button);
    }});
  </script>
</body>
</html>
"""
    output_file = Path(output_path)
    if not output_file.is_absolute():
        output_file = ROOT_DIR / output_file
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html, encoding="utf-8")


def scrape_seek_jobs_direct(max_pages_cap: int = MAX_PAGES_CAP, headless: bool = False) -> str:
    configure_console_output()

    profile = load_profile()
    search_settings = get_search_settings(profile)
    configured_max_pages = int(search_settings.get("max_pages_cap", max_pages_cap) or max_pages_cap)
    configured_date_range = int(search_settings.get("date_range_days", 3) or 3)
    enforce_posted_age_limit = bool(search_settings.get("enforce_posted_age_limit", True))
    sort_newest_first = bool(search_settings.get("sort_newest_first", True))
    search_targets = build_seek_search_targets(profile, configured_date_range, sort_newest_first)
    applied_job_keys, hidden_job_keys = get_manual_skip_sets(profile)

    run_started_at = datetime.now().astimezone()
    run_iso = run_started_at.isoformat(timespec="seconds")
    llm_cache: Dict[str, str] = load_llm_cache()
    job_history = load_job_history()
    audit_rows: List[dict] = []
    kept_records: List[dict] = []
    skill_observations: List[dict] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        list_page = browser.new_page(viewport={"width": 1400, "height": 900})
        detail_page = browser.new_page(viewport={"width": 1400, "height": 900})

        try:
            seen_urls: Set[str] = set()
            for search_target in search_targets:
                base_search_url = search_target["url"]
                search_location = search_target["location"]
                search_keywords = search_target["keywords"]
                classification_ids = ",".join(search_target.get("classification_ids", []))
                current_page_num = 1

                while current_page_num <= configured_max_pages:
                    page_url = set_page_param(base_search_url, current_page_num) if current_page_num > 1 else base_search_url

                    print(f"\n=== {search_location} | Page {current_page_num} ===")
                    print("URL:", page_url)

                    try:
                        list_page.goto(page_url, wait_until="domcontentloaded")
                        list_page.wait_for_selector(SELECTOR_CARDS, timeout=8000)
                    except Exception as exc:
                        print(
                            f"No visible job cards for {search_location} on page {current_page_num}. "
                            f"Stopping this target. [{type(exc).__name__}]"
                        )
                        break

                    job_cards = list_page.query_selector_all(SELECTOR_CARDS)
                    print(f"Found {len(job_cards)} job cards")

                    if len(job_cards) == 0:
                        print("No cards found. Stopping this target.")
                        break

                    page_has_fresh_card = False

                    for card in job_cards:
                        title = ""
                        company = "N/A"
                        record = {
                            "run_started_at": run_iso,
                            "search_location": search_location,
                            "search_keywords": search_keywords,
                            "search_classifications": classification_ids,
                            "page": current_page_num,
                            "job_key": None,
                            "title": "",
                            "company": company,
                            "posted": "N/A",
                            "posted_age_days": None,
                            "url": None,
                            "salary": "N/A",
                            "location": "N/A",
                            "work_type": "N/A",
                            "teaser": "N/A",
                            "decision": "REJECT",
                            "reject_reason": None,
                            "title_reason": None,
                            "content_reason": None,
                            "llm_decision": None,
                            "details_length": 0,
                        }

                        try:
                            title_el = card.query_selector(SELECTOR_TITLE)
                            company_el = card.query_selector(SELECTOR_COMPANY)
                            posted_el = card.query_selector(SELECTOR_POSTED)
                            card_meta = extract_card_metadata(card)

                            title = title_el.inner_text().strip() if title_el else ""
                            company = company_el.inner_text().strip() if company_el else "N/A"
                            posted = posted_el.inner_text().strip() if posted_el else "N/A"
                            posted_age_days = parse_seek_posted_age_days(posted)
                            record.update({
                                "title": title,
                                "company": company,
                                "posted": posted,
                                "posted_age_days": posted_age_days,
                                "location": card_meta["location"],
                                "work_type": card_meta["work_type"],
                                "teaser": card_meta["teaser"],
                            })

                            if posted_age_days is None or posted_age_days <= configured_date_range:
                                page_has_fresh_card = True

                            ok_title, title_reason = passes_title_filters(title)
                            record["title_reason"] = title_reason
                            if not ok_title:
                                print(f"REJECTED (title) [{title_reason}] {title}")
                                record["reject_reason"] = title_reason
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            relative_url = title_el.get_attribute("href") if title_el else None
                            full_url = build_full_url(relative_url)
                            record["url"] = full_url
                            record["job_key"] = stable_job_key(full_url)
                            if not full_url:
                                print(f"REJECTED (card) [NO_URL] {title} @ {company}")
                                record["reject_reason"] = "NO_URL"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if record["job_key"] in applied_job_keys:
                                print(f"SKIP (applied) {title} @ {company}")
                                record["decision"] = "SKIP"
                                record["reject_reason"] = "ALREADY_APPLIED"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if record["job_key"] in hidden_job_keys:
                                print(f"SKIP (hidden) {title} @ {company}")
                                record["decision"] = "SKIP"
                                record["reject_reason"] = "MANUALLY_HIDDEN"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if (
                                enforce_posted_age_limit
                                and posted_age_days is not None
                                and posted_age_days > configured_date_range
                            ):
                                print(
                                    f"REJECTED (posted) [POSTED_TOO_OLD:{configured_date_range}] "
                                    f"{title} @ {company} | {posted}"
                                )
                                record["reject_reason"] = f"POSTED_TOO_OLD:{configured_date_range}"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if full_url in seen_urls:
                                print(f"SKIP (duplicate) {title} @ {company}")
                                record["decision"] = "SKIP"
                                record["reject_reason"] = "DUPLICATE_URL"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue
                            seen_urls.add(full_url)

                            details_text = fetch_job_details_text(detail_page, full_url)
                            record["details_length"] = len(details_text)
                            if not details_text:
                                print(f"REJECTED (details) [NO_DETAILS] {title} @ {company} | {full_url}")
                                record["reject_reason"] = "NO_DETAILS"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            for skill in extract_detected_skills(details_text):
                                skill_observations.append(
                                    {
                                        "skill": skill,
                                        "title": title,
                                        "company": company,
                                        "url": full_url,
                                        "search_location": search_location,
                                    }
                                )

                            ok_desc, desc_reason = passes_content_filters(details_text, record["location"])
                            record["content_reason"] = desc_reason
                            if not ok_desc:
                                print(f"REJECTED (content) [{desc_reason}] {title} @ {company}")
                                record["reject_reason"] = desc_reason
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            llm_input_text = details_text[:MAX_LLM_CHARS]
                            llm_fp = fingerprint_text(llm_input_text)

                            if not llm_is_enabled():
                                llm_decision = "MAYBE"
                                print(f"[LLM][DISABLED] {llm_decision} {title} @ {company}")
                            elif llm_fp in llm_cache:
                                llm_decision = llm_cache[llm_fp]
                                print(f"[LLM][CACHE] {llm_decision} {title} @ {company}")
                            else:
                                llm_decision = llm_should_consider(llm_input_text)
                                llm_cache[llm_fp] = llm_decision
                                print(f"[LLM] {llm_decision} {title} @ {company}")

                            record["llm_decision"] = llm_decision
                            if llm_decision == "REJECT":
                                print(f"REJECTED (llm) [LLM_REJECT] {title} @ {company}")
                                record["reject_reason"] = "LLM_REJECT"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            salary = extract_salary(details_text)
                            if salary == "N/A":
                                salary = card_meta["card_salary"]
                            record["salary"] = salary
                            record["decision"] = "KEEP"

                            finalize_record(job_history, audit_rows, record, run_iso)
                            kept_records.append(record)
                            print(
                                f"KEPT: {title} @ {company} | {posted} | "
                                f"{record['location']} | {record['work_type']} | {salary} | "
                                f"{'SEEN_BEFORE' if record.get('seen_before') else 'NEW'}"
                            )
                        except Exception as exc:
                            record["reject_reason"] = f"CARD_EXCEPTION:{type(exc).__name__}"
                            print(f"REJECTED (card) [CARD_EXCEPTION:{type(exc).__name__}] {title} @ {company}")
                            finalize_record(job_history, audit_rows, record, run_iso)

                    if enforce_posted_age_limit and not page_has_fresh_card:
                        print(
                            f"All cards for {search_location} on page {current_page_num} "
                            f"were older than {configured_date_range} day(s). Stopping this target."
                        )
                        break

                    current_page_num += 1

            run_stats = build_run_stats(
                audit_rows,
                kept_records,
                run_started_at,
                configured_date_range,
                sort_newest_first,
                configured_max_pages,
            )

            render_html(
                OUTPUT_HTML,
                kept_records,
                run_started_at,
                configured_date_range,
                sort_newest_first,
                run_stats,
            )
            save_llm_cache(llm_cache)
            save_job_history(job_history)
            write_debug_json(audit_rows)
            write_run_stats(run_stats)
            write_review_data(build_review_data(audit_rows, skill_observations, profile))
            print(f"\nSaved {len(kept_records)} jobs to {OUTPUT_HTML}")
            print(f"Saved {len(audit_rows)} audit rows to {DEBUG_JSON_PATH}")
            print(f"Saved run stats to {RUN_STATS_PATH}")
            print(f"Saved review data to {REVIEW_DATA_PATH}")
            print(f"Saved history for {len(job_history)} jobs to {JOB_HISTORY_PATH}")
            return OUTPUT_HTML

        finally:
            browser.close()


if __name__ == "__main__":
    scrape_seek_jobs_direct()
