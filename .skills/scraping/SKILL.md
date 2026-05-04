# Skill: Scraping

Read this before editing `scrapers/seek.py`, `scrapers/linkedin.py`, or scraper-related sections of `source_connector.py`.

## Scraper architecture

Both scrapers implement `BaseJobScraper` from `scrapers/base.py`. Entry point for each is `.scrape()` which returns `(kept_records, audit_rows, skill_observations)`.

```
source_connector.py
  ├─ SeekScraper.scrape()          # scrapers/seek.py — Playwright, direct detail pages
  └─ LinkedInScraper.scrape()      # scrapers/linkedin.py — python-jobspy
```

## SEEK scraper (`scrapers/seek.py`)

**Technology:** Playwright (async browser automation)

**Critical rule:** No pane-based scraping. Always navigate to the full detail page URL directly. (Rule 9 in AGENTS.md)

### DOM selectors (constants)

```python
SELECTOR_CARDS = 'article[data-automation="normalJob"], article[data-automation="premiumJob"]'
SELECTOR_TITLE = '[data-automation="jobTitle"]'
SELECTOR_COMPANY = '[data-automation="jobCompany"]'
SELECTOR_POSTED = '[data-automation="jobListingDate"]'
SELECTOR_LOCATION = '[data-automation="jobLocation"]'
SELECTOR_CARD_SALARY = '[data-automation="jobSalary"]'
SELECTOR_SHORT_DESCRIPTION = '[data-automation="jobShortDescription"]'
SELECTOR_DETAILS = '[data-automation="jobAdDetails"]'
SEEK_JOBS_BASE_URL = "https://www.seek.com.au/jobs"
```

These selectors break when SEEK updates their DOM. If jobs stop being found, check these first.

### Detail page result classification

`classify_detail_page_text(text)` returns one of:
- `"ok"` — valid job detail
- `"challenge"` — Cloudflare / bot-detection gate (see `DETAIL_PAGE_CHALLENGE_MARKERS`)
- `"blocked"` — access denied (see `DETAIL_PAGE_BLOCK_MARKERS`)

Challenge responses should be retried or skipped, not treated as job content.

### Key SEEK functions

| Function | Purpose |
|---|---|
| `build_seek_search_targets(profile, date_range, sort_newest_first)` | Returns list of search dicts from profile settings |
| `extract_card_metadata(card)` | Extracts title, company, location, posted, salary from card DOM |
| `fetch_job_details_payload(detail_page, full_url, attempts=2)` | Fetches detail page, returns payload dict |
| `stable_job_key(full_url)` | Derives deduplication key from URL (strips tracking params) |
| `build_full_seek_url(relative_or_full_url)` | Resolves relative SEEK URLs to absolute |
| `extract_posted_text_from_card(card_text)` | Normalises "Posted 3d ago" → "3d ago" |
| `extract_work_type(card_text)` | Extracts full-time/part-time/contract from card text |

### Search target shape

```python
{
    "keywords": str,       # search string
    "location": str,       # location filter
    "date_range": int,     # days back
    "sort_newest_first": bool,
}
```

Built from `profile["search_settings"]` via `get_search_settings(profile)`.

## LinkedIn scraper (`scrapers/linkedin.py`)

**Technology:** `python-jobspy` library (`jobspy.scrape_jobs()`)

**Class:** `LinkedInScraper(BaseJobScraper)` with `source_name = "linkedin"`

### Full scrape pipeline (inside `LinkedInScraper.scrape()`)

1. `_build_search_targets()` — targets from profile settings
2. `_fetch_jobspy(target)` — calls `jobspy.scrape_jobs()`, returns DataFrame
3. For each DataFrame row:
   - Normalize jobspy record → standard record shape
   - Title filter → content filter (hard blocks, learned rules)
   - History reuse check (`can_reuse_kept_job`)
   - Extract salary + work mode from full description
   - Detect competitive signals + hard blocks
   - Build role summary, fit highlights, risk/missing evidence
   - LLM gate (`llm_should_consider` or deterministic pass-through)
   - Extract skill observations → register signals
4. Return `(kept_records, audit_rows, skill_observations)`

### Location normalization

`_normalize_location_for_jobspy(seek_location)` maps AU location shortforms to jobspy-compatible strings using `_LOCATION_NORMALIZATION_MAP`. Example: `"nsw"` → `"New South Wales, Australia"`. Add new mappings here if searches return wrong locations.

### jobspy record shape (after normalization)

Fields populated from jobspy: `title`, `company`, `location`, `description`, `job_url`, `date_posted`, `salary_source`, `job_type`, `site`.

## Standard record shape (both scrapers)

After scraping and enrichment, every kept record has:

```python
{
    # Identity
    "job_key": str,              # stable dedup key
    "title": str,
    "company": str,
    "location": str,
    "source": str,               # "seek" | "linkedin"
    "full_url": str,

    # Dates
    "posted_text": str,          # human-readable "3d ago"
    "date_posted": str,          # ISO date string

    # Content
    "details_text": str,         # full description
    "short_description": str,

    # Scoring outputs
    "fit_score": int,
    "fit_highlights": list[str],
    "fit_score_breakdown": list[dict],
    "hard_block_reasons": list[str],
    "risk_reasons": list[str],
    "missing_evidence": list[str],
    "competitive_signals": list[dict],

    # Classification
    "llm_fit_grade": str,        # "good_fit" etc. or None
    "work_type": str,
    "work_mode": str,
    "salary_min": int | None,
    "salary_max": int | None,

    # History
    "first_seen": str,
    "last_seen": str,
    "view_count": int,
}
```

## Search settings config keys in `profile.json`

```json
{
  "search_settings": {
    "keywords": ["..."],
    "locations": ["..."],
    "date_range_days": 7,
    "sort_newest_first": true,
    "seek_pages": 3,
    "linkedin_hours_old": 72,
    "linkedin_results_per_search": 25
  }
}
```

Limits: `seek_pages` 1–10, `linkedin_hours_old` 1–168, `linkedin_results_per_search` 5–100.

## Common gotchas

- SEEK challenges (`classify_detail_page_text` returns `"challenge"`) are not errors — jobspy or SEEK infrastructure triggers Cloudflare intermittently. Log and skip, don't crash.
- `stable_job_key` must strip UTM/tracking params before hashing — same job appears with different tracking params across searches.
- jobspy returns a pandas DataFrame; iterate rows with `.itertuples()` or `.iterrows()`, not direct indexing.
- LinkedIn descriptions often come pre-truncated from jobspy; `description_trust.py` classifies confidence level (`HIGH`/`LOW`).
- Don't change `source_name` on the scraper class — it's used as the `"source"` field in every record and affects deduplication.

## Related files

| File | Role |
|---|---|
| `scrapers/seek.py` | SEEK Playwright scraper |
| `scrapers/linkedin.py` | LinkedIn jobspy scraper |
| `scrapers/base.py` | Base scraper class |
| `source_connector.py` | Orchestrates both scrapers |
| `job_identity.py` | Cross-source deduplication |
| `description_trust.py` | Full-description confidence classification |
| `posting_utils.py` | Timestamp parsing, job key normalisation |
| `profile_store.py` | `get_search_settings()` |
