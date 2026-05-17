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

**Two independent systems — mismatch causes 0 results:**
- `search_settings.keywords` — what is sent to SEEK/LinkedIn to fetch job listings
- `primary_job_title_pattern` + `secondary_title_patterns` — what `analyze_title_filters()` checks scraped job titles against

If keywords and title patterns diverge (e.g. keywords say "software developer" but pattern says "accounts officer"), every scraped job will be `TITLE_NOT_TARGET`.

**Synonym support:**
- `data/knowledge/parsing_rules.json` → `title_role_synonyms`: list of synonym groups (e.g. `["software developer", "software engineer"]`)
- `_get_synonym_group(role)` in `filters.py`: looks up a role and returns all equivalents
- `_find_matching_title_pattern()` expands both the job title and profile pattern through synonyms before comparing — so "Software Engineer" matches a profile pattern of "software developer"
- Add new synonym groups to `parsing_rules.json`; do not hardcode them in Python

**Onboarding reset:**
- `ONBOARDING_RESET_FIELDS` in `source_documents.py` defines what is wiped on each CV import — includes `primary_job_title_pattern`
- On re-import, the LLM re-extracts the title from the uploaded CV; if the CV is for a different role than the user is targeting, the pattern will be wrong
- If the extracted pattern doesn't match search keywords, correct it via profile patch or Settings UI

**Debugging zero-results:**
1. Check server.log for `REJECTED (title) [TITLE_NOT_TARGET]` on every card → title filter mismatch
2. Check `primary_job_title_pattern` in user's `profile.json` vs `search_settings.keywords`
3. Check `analyze_title_filters(title, profile)` directly — pass the user profile explicitly (not `load_profile()` which resolves to `_local` in CLI context)

## Checklist
- Is this an explicit blocker or inferred weakness?
- Is the rule approved/configured, not invented inline?
- Is the rejection reason visible to the user?
- Are uncertain signals preserved for review?
- Do `search_settings.keywords` and `primary_job_title_pattern` target the same roles?
