---
name: history-dedup
description: Use ONLY for job history, viewed/applied/hidden/saved state, duplicate job identity, and cross-source deduplication. Do NOT use for scoring or filtering rules.
---

# Skill: History & Dedup

Use before editing job history, viewed/applied/hidden state, posting timestamps, or deduplication.

## Rules
- Preserve valid **current-schema** job history and viewed/applied/hidden state; rebuilds must not lose valid user review state.
- **Pre-live exception:** malformed, obsolete, or superseded dev/test history is disposable under the canonical-contract rule in `code-change/SKILL.md`. Delete/reset incompatible dev data rather than adding migration, alias, fallback, or compatibility logic solely to preserve it.
- Scrape run outputs (`run_stats`, `audit_records`, `review_data`, `workspace_pool`) are disposable. Current-schema job history is persistent; incompatible pre-live history is not.
- History retention is centrally managed through Admin/global settings, not hardcoded in feature code.
- Current retention knobs live in `global_settings.history_settings` and `global_settings.cache_settings`.
- Deduplication should be stable across SEEK, LinkedIn, and APSJobs where possible; prefer source-native IDs before expensive work and cross-source identity only where evidence is strong enough.
- Job keys must not depend on unstable UI-only text when stronger identifiers exist.
- Posting timestamps should be normalised consistently before ranking/filtering.
- Historical/applied cards must fail visibly on missing core identity instead of inventing `Untitled`/`N/A`; never create a fake `href="#"` job link. Recover SEEK/LinkedIn URLs only from stable source job IDs when the persisted URL is missing.
- Confirmed cross-source duplicates are alternate postings of the same vacancy: present them as **Also posted on** with the source link when available. Keep uncertain candidates separate as **Possible same job** for human review; do not call both cases “Related cards”.

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
