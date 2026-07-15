# Skill: Scraping

Use before editing SEEK/LinkedIn scrapers or scraped job data shape.

## Rules
- SEEK uses direct job pages only; do not restore pane scraping.
- Scrapers collect evidence; they do not decide fit.
- Preserve raw/important job signals where possible.
- Capture source metadata separately from classification, including apply URL/domain, company links, poster identity, and ATS hints.
- Keep posting-channel fallback heuristics data-driven in managed JSON, not hardcoded in scraper code, and keep the extracted evidence unique/canonical.
- Use strong metadata first; only use fallback heuristics when trusted metadata is unavailable.
- When debug capture is enabled, persist raw HTML, raw JSON, and normalized records for source payload review.
- Do not add filtering, scoring, or rejection judgement inside scraper code.
- Normalise job identity consistently for dedup/history.
- Surface partial or low-confidence descriptions; do not hide them.
- Prefer board-declared metadata over text inference when extracting work mode.
- Only use fallback text heuristics for work mode when no structured or visible board metadata is available.
- Preserve work mode provenance so later review can distinguish trusted board metadata from inferred text.

## SEEK card processing pipeline

`seek_scrape_to_records()` in `seek_runner.py` processes cards in 4 phases per results page:

1. **Phase 1 — DOM extraction (sequential):** Read all cards from the list page into plain dicts before any page navigation. Sets `job_quality_signals`.
2. **Phase 2 — Pre-detail gate (sequential):** Run `review_pre_detail_normalized_job()` for each card. Fast: no network. Splits cards into `pre_decided` (fast-path REJECT/SKIP/seen-before KEEP) and `needs_detail`.
3. **Phase 3 — Async parallel detail fetch + LLM:** `detail_session.run_batch(needs_detail, review_context)` — submits the batch to a persistent `_AsyncDetailSession` (background daemon thread + single async Playwright browser kept alive for the whole run). Each coroutine fetches one page via `asyncio.gather` + `asyncio.Semaphore(n_workers)`, then calls `asyncio.to_thread(_review_seek_job_detail)` for the LLM step. Results merged back by card index. The async browser is independent of the sync list-page browser.
4. **Phase 4 — Result processing (sequential):** Iterate results in original card order — score, log, keep.

`n_detail_workers` comes from `seek_parallel_detail_workers` in `playwright_settings` (global_settings.json, default 3). Change it there, not in code.

Do not add filtering or scoring logic to Phases 1–3. Phase 4 is the only place that calls `fit_score_and_breakdown_displayed`.

## Work type normalization
Both Seek and LinkedIn normalize the raw work_type string through `map_job_type(raw, load_job_type())` from `scrapers/base.py` and `job_types.py`. The normalization mapping lives in `data/job_type.json` under the `"mapping"` key — no source-specific logic or hardcoded labels in scraper code. Unknown values are passed through and registered via the signal registry. The `"filter_groups"` key in the same file defines how canonical values map to workspace filter options; scrapers do not use filter_groups.

## Owners
- `scrapers/seek_runner.py`: SEEK scrape loop, card review dispatch, parallel detail fetch, result collection.
- `scrapers/seek.py`: SEEK low-level page helpers, selectors, URL building, detail payload fetch.
- `scrapers/linkedin.py`: LinkedIn via python-jobspy.
- `source_runner.py`: routes enabled sources (SEEK/LinkedIn) in a single run.
- `source_connector.py`: orchestration entry point.
- `job_identity.py`: cross-source identity/dedup.
- `description_trust.py`: full-description confidence.
- `job_types.py`: work type normalization mapping and filter group definitions.

## Work mode extraction

Work mode extraction is evidence collection only. It must not score, reject, rank, or apply candidate preference.

Expected output fields when available:

```json
{
  "work_mode": "remote | hybrid | onsite | unknown",
  "work_mode_source": "seek_filter | seek_card | seek_detail_visible | seek_detail_payload | linkedin_structured | fallback_text | unknown",
  "work_mode_evidence": "exact text, selector, or structured field used",
  "work_mode_needs_review": true
}
```

### SEEK order
1. Search/listing metadata and selected work arrangement filter:
   - `[data-automation="refineWorkArrangement"]`
   - option links containing `/jobs/on-site`, `/jobs/hybrid`, `/jobs/remote`
   - visible option text or `aria-label`: `On-site`, `Hybrid`, `Remote`
   - selected state via checkbox / `aria-checked="true"`
2. Job card visible work arrangement/location metadata.
3. Direct job page visible metadata.
4. Embedded SEEK state/payload fields if already captured, especially fields containing:
   - `workArrangement`
   - `workArrangements`
   - `remote`
   - `hybrid`
   - `onsite`
   - `workplace`
   - `location`
5. Description text fallback only when metadata is unavailable.

Search filters are search context, not always job-level proof. If a filter value is used, preserve `work_mode_source="seek_filter"` and the exact filter evidence.

### LinkedIn order
1. Use python-jobspy structured output first when present:
   - `workplace_type`
   - `workplaceType`
   - `job_workplace`
   - `work_type`
   - `remote_allowed`
   - `is_remote`
   - `location`
2. If LinkedIn HTML is inspected directly, only use structured job-level state as metadata.
3. Do not treat search keywords such as `hybrid or remote` as job-level work mode evidence.
4. Description text fallback only when metadata is unavailable.

### Logging
Add structured debug logs when work mode is extracted:

- `job_id`
- `source_board`
- `work_mode`
- `work_mode_source`
- `work_mode_evidence`
- `fallback_used`
- `work_mode_needs_review`

These logs exist to support later review and learning. They must not promote new rules automatically.

## Age filtering

- Both SEEK and LinkedIn **always** reject ads whose `posted_age_days` exceeds `date_range_days` (hard-reject, reason `POSTED_TOO_OLD:<n>`) before scoring.
- There is no configurable bypass — the window is always enforced.

## Search parameter guards

- `build_seek_search_targets` raises `ValueError` if keywords are empty — never send a blank keyword search to SEEK.
- `/api/run` checks `_onboarding_complete()` before starting a scrape job — returns HTTP 400 if onboarding is not done.
- Onboarding is complete when `primary_job_title_pattern`, `search_settings.keywords`, and `search_settings.locations` are all non-empty.
- These guards are application-level validation, not scraper filtering logic.
- `search_settings.keywords` and `primary_job_title_pattern` are independent — keywords control what SEEK returns, patterns control what the title filter passes. A mismatch (e.g. keywords = "software developer" but pattern = "accounts officer") silently yields 0 kept records. When debugging zero results, verify both fields agree.

## Where to find current run logs

When debugging a scrape run:

- use **`output/server.log`** for the curated human view: one readable block per finished job plus board/run summaries
- use **`output/server-debug.log`** for the full technical stream: FastAPI/uvicorn lines, raw `job_hunter_agent.app` pipeline output, interleaved worker activity, LLM/API detail, and machine-oriented diagnostics

Both files are appended on every run, so the bottom is always the most recent run.

Do **not** use `output/console.log` for diagnosing current behaviour — it is written by a separate PowerShell redirect mechanism and is stale from a previous run.

## Checklist
- Is this collection logic, not judgement?
- Is full-description confidence preserved?
- Are missing/partial descriptions surfaced, not hidden?
- Is job identity stable across sources?
- Is work mode extracted from board metadata before fallback text inference?
- Is work mode provenance preserved for review/debugging?
- Are search keywords avoided as job-level work mode proof?
- Are search parameters validated before the scraper fires (non-empty keywords, location, completed onboarding)?
- Did you run the smallest relevant scraper/data-shape check?

