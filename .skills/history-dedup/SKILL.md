---
name: history-dedup
description: Use ONLY for job history, viewed/applied/hidden/saved state, duplicate job identity, and cross-source deduplication. Do NOT use for scoring or filtering rules.
---

# Skill: History & Dedup

Use before editing job history, viewed/applied/hidden state, posting timestamps, or deduplication.

## Rules
- History is valuable persistent state stored in the DB; do not discard it.
- Rebuilds must preserve viewed/applied/hidden state.
- Scrape run outputs (run_stats, audit_records, review_data, workspace_pool) are disposable; job history is not.
- History retention is centrally managed through Admin/global settings, not hardcoded in feature code.
- Current retention knobs live in `global_settings.history_settings` and `global_settings.cache_settings`.
- Deduplication should be stable across SEEK and LinkedIn where possible.
- Job keys must not depend on unstable UI-only text when stronger identifiers exist.
- Posting timestamps should be normalised consistently before ranking/filtering.

## Owners
- `history.py`: review state.
- `job_identity.py`: stable job keys and cross-source dedup.
- `posting_utils.py`: posting dates and age.
- `workspace_data.py`: historical workspace records.
- `io_utils.py`: `load_job_history()` / `save_job_history()` — DB-backed; `job_history` table per user.
- `data/config/global_settings.json`: retention defaults for job history and runtime caches.

## Checklist
- Does this preserve applied/hidden/viewed state?
- Does workspace rebuild keep history?
- Are retention limits coming from global settings rather than Python constants?
- Is the job key stable across sources and runs?
- Are timestamps normalised before use?
- Did you run the smallest relevant history/dedup check?
