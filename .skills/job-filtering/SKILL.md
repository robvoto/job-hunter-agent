# Skill: Job Filtering

Use before editing `filters.py`, reject reasons, title/content filters, or hard blocker behaviour.

## Rules
- Deterministic filters run before LLM.
- Hard rejection is only for explicit blockers backed by approved rules.
- Do not reject just because evidence is weak/basic/old.
- Weak or uncertain signals become score impacts, warnings, or review signals.
- Do not add hidden false-negative gates.
- Do not hardcode rejected terms or title dictionaries in Python.
- Use approved knowledge files and profile settings.

## Boundaries
- Title filters are cheap first-pass narrowing, not final fit judgement.
- Content filters handle explicit job requirements and candidate blockers.
- Learning suggestions go to signal registry first; pending signals are not runtime rules.

## Title filter architecture

**`primary_job_title_pattern` and `secondary_title_patterns` are scoring signals only — not hard gates.**

They influence `title_reason` and `match_family`, which feed into fit scoring and LLM context. They do NOT control whether a job is rejected.

The hard gates in the title filter are:
1. Empty title → `TITLE_EMPTY`
2. User-configured `reject_title_rules` → e.g. `TITLE_BAD_KEYWORD`, `TITLE_BAD_ROLE`
3. No pattern match → `TITLE_NOT_TARGET` (hard reject, no LLM call)

**`match_family` values and their scoring impact:**
- `"primary"` — title matched a `target_roles` entry → full title score, `title_reason="OK"`
- `"secondary"` — title matched an `also_consider_roles` entry → partial title score, `title_reason=TITLE_REASON_POTENTIAL_MATCH`
- `"none"` — no pattern matched → hard rejected as `TITLE_NOT_TARGET`, never reaches LLM

**`title_reason` downstream effects:**
- `"OK"` → standard description confidence check
- `TITLE_REASON_POTENTIAL_MATCH` (secondary or none) → stricter description proof required before keeping (`_evaluate_description_confidence` in `filters.py`)

**`title_role_synonyms` in `parsing_rules.json`:**
- Only for genuinely interchangeable spellings of the same role (e.g. "devops engineer" / "dev ops engineer")
- Do NOT add profession-wide synonym tables — that cannot scale and puts semantic judgement into data files instead of the LLM
- The list should stay small or empty

**Two independent systems — mismatch causes silent 0 results:**
- `search_settings.keywords` — what is sent to SEEK/LinkedIn to fetch job listings
- `primary_job_title_pattern` + `secondary_title_patterns` — what `analyze_title_filters()` uses for scoring

If keywords and title patterns diverge (e.g. keywords say "software developer" but pattern says "accounts officer"), every scraped job will still pass the title gate, but the LLM and scoring will correctly assess fit.

**Debugging zero-results:**
1. Check `last_run_error` in `run_stats.json` for scraper-level failures
2. Check audit_records.json for reject_reason distribution by source
3. Check `primary_job_title_pattern` in user's `profile.json` vs `search_settings.keywords` for keyword/pattern divergence
4. Run `analyze_title_filters(title, profile)` directly — pass the user profile explicitly (not `load_profile()` which reads the current user context; use `get_user_id_for_runtime()` or set the user with `set_user_id()` first)

**Onboarding reset:**
- `ONBOARDING_RESET_FIELDS` in `source_documents.py` defines what is wiped on each CV import — includes `primary_job_title_pattern`
- On re-import, the LLM re-extracts the title from the uploaded CV

## Checklist
- Is this an explicit blocker or inferred weakness?
- Is the rule approved/configured, not invented inline?
- Is the rejection reason visible to the user?
- Are uncertain signals preserved for review?
- Is semantic relevance being decided by a deterministic rule instead of the LLM?
