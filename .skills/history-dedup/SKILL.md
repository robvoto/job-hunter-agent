# Skill: History & Deduplication

Read this before editing `history.py`, `job_identity.py`, `posting_utils.py`, or any code touching `data/job_history.json`.

## What this area covers

Three distinct concerns that work together:

1. **Job history** (`history.py`) — tracks every job across runs: first/last seen, kept snapshots, warning signals (repeated listings, multi-listings)
2. **Cross-source deduplication** (`job_identity.py`) — collapses the same job appearing on both SEEK and LinkedIn into one record
3. **Timestamp & key utilities** (`posting_utils.py`) — normalises "3d ago" posted text, derives stable job keys, formats display labels

## History flow

```
source_connector.py
  ├─ build_history_cluster_index(history)    → clusters by source+company+title
  ├─ For each scraped record:
  │    ├─ can_reuse_kept_job()               → reuse saved score/highlights if unchanged
  │    ├─ assess_history_warning_signals()   → repeated listing / multi-listing flags
  │    └─ update_job_history()               → upsert sighting record
  └─ finalize_record()                       → attach history state to record
```

## Key functions in `history.py`

| Function | Purpose |
|---|---|
| `build_history_cluster_index(history)` | Groups history by `(source, company, title)` key → `{cluster_key: entry}` |
| `history_cluster_key(record)` | Returns cluster key string for a record |
| `history_cluster_key_from_parts(source, company, title)` | Build cluster key from raw strings |
| `can_reuse_kept_job(history_entry, record, profile=None)` | True if previous kept snapshot is still valid |
| `apply_kept_job_reuse(record, history_entry)` | Copy score/highlights from history to avoid re-scoring |
| `viewed_by_user(record)` | True if user has seen this job in the dashboard |
| `build_history_sighting(record, run_iso)` | Snapshot of a single run's observation |
| `assess_history_warning_signals(record, history_clusters=None)` | Returns list of warning strings |
| `update_job_history(history, record, run_iso)` | Upsert job into history dict |
| `finalize_record(history, audit_rows, record, run_iso)` | Attach history state + add to audit |
| `build_keep_snapshot(record)` | Preserve `KEEP_SNAPSHOT_FIELDS` from a record |

## Warning signal detection

`assess_history_warning_signals()` checks for:
- **Repeated listing**: same job seen ≥ `REPEATED_LISTING_MIN_TIMES_SEEN` (4) times over ≥ `REPEATED_LISTING_MIN_SPAN_DAYS` (21) days
- **Multi-listing red flag**: ≥ `MULTI_LISTING_RED_FLAG_MIN_LISTINGS` (3) listings from the same company in ≥ `MULTI_LISTING_RED_FLAG_MIN_SPAN_DAYS` (30) days

These surface as strings in `record["history_warning_signals"]`. They are warnings, not blockers — they stay visible and score down.

## History constants

```python
ARCHIVE_STALE_AFTER_DAYS = 15        # job disappears → archive after N days
HIDDEN_REVIEW_DAYS = 30              # hide from "new" view after N days without sighting
MAX_HISTORY_SIGHTINGS = 24           # cap sighting list length per job
REPEATED_LISTING_MIN_TIMES_SEEN = 4
REPEATED_LISTING_MIN_SPAN_DAYS = 21
MULTI_LISTING_RED_FLAG_MIN_LISTINGS = 3
MULTI_LISTING_RED_FLAG_MIN_SPAN_DAYS = 30
TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING = bool  # from --treat-all-as-new CLI flag
```

`TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING` is derived from `sys.argv` at import time — used in `viewed_by_user()` to disable history for test runs.

## `KEEP_SNAPSHOT_FIELDS`

27-field tuple capturing the parts of a record that should persist across runs when a job is kept. Includes: fit_score, fit_highlights, fit_score_breakdown, hard_block_reasons, risk_reasons, missing_evidence, llm_fit_grade, competitive_signals, and similar scoring outputs.

`can_reuse_kept_job()` checks if these snapshot fields still match — if yes, skips re-scoring.

## Cross-source deduplication (`job_identity.py`)

`deduplicate_across_sources(records)` collapses jobs where:
- `are_jobs_semantically_similar(a, b)` returns True (title word overlap ≥ `TITLE_SIMILARITY_THRESHOLD` = 0.8)
- Different sources

When collapsing, SEEK record wins over LinkedIn (`_SOURCE_PRIORITY = {"seek": 0, "linkedin": 1}`). This is intentional — SEEK detail pages have higher description quality.

```python
TITLE_SIMILARITY_THRESHOLD = 0.8
COMPANY_SUFFIXES = ["pty", "ltd", "inc", "corp", ...]  # stripped before comparison
```

## Timestamp utilities (`posting_utils.py`)

| Function | Purpose |
|---|---|
| `normalize_job_key(raw)` | Extracts numeric ID from SEEK/LinkedIn URL |
| `parse_timestamp(value)` | ISO string → datetime |
| `days_since(value, reference)` | Days between ISO timestamp and reference |
| `format_timestamp_label(value)` | ISO → "3 May 2026" display string |
| `posted_datetime_from_age(age_days, reference_time)` | Reconstructs datetime from "3d ago" age |
| `format_posted_date_label(posted_text, age_days, reference_time)` | Display label: "Today", "Yesterday", "3 days ago" |
| `relative_posted_age_label(posted_at, now=None)` | "today" / "yesterday" / "N days ago" |
| `posted_display_label(record, now=None)` | Full display label from record fields |
| `current_posted_age_days(record, now=None)` | Float days since posting |
| `get_manual_skip_sets(profile)` | Returns `(applied_keys, hidden_keys)` from profile |
| `is_relative_posted_text(value)` | True if text is relative ("3d ago") not absolute |
| `posted_reference_time(record)` | Extracts reference datetime from record fields |

## Job key normalisation

`normalize_job_key(raw)` strips tracking params and extracts the stable numeric ID. Two jobs with different tracking params but the same ID are the same job. This is what `stable_job_key()` in `scrapers/seek.py` ultimately uses.

## Common gotchas

- `viewed_by_user(record)` returns `False` if `TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING` is set — don't use this in production scoring logic without checking the flag's context.
- `can_reuse_kept_job()` should be called BEFORE re-scoring — it's the performance optimisation that avoids redundant LLM calls for unchanged jobs.
- History is stored as a flat dict keyed by `job_key`. The cluster index (`build_history_cluster_index`) is built on top of it each run — it's not persisted.
- `deduplicate_across_sources` must run AFTER all records from all scrapers are collected, not per-scraper.
- `finalize_record()` mutates both the record dict and the audit_rows list — ensure you're not calling it on a copy.

## Related files

| File | Role |
|---|---|
| `history.py` | History tracking, warning signals, keep snapshots |
| `job_identity.py` | Cross-source deduplication |
| `posting_utils.py` | Timestamp parsing, job key normalisation |
| `source_connector.py` | Orchestrates history update flow |
| `dashboard_data.py` | Reads history to build archive/applied/hidden record sets |
| `data/job_history.json` | Persisted history (keyed by job_key) |
