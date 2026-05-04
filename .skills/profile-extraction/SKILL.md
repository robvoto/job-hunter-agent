# Skill: Profile Extraction

Read this before editing `cv_pipeline.py`, `profile_store.py`, `profile_learning.py`, `capability_matrix.py`, or `capability_knowledge.py`.

## What "profile extraction" means

Taking raw CV text and producing structured profile fields that drive all downstream filtering and scoring. Two separate flows:

1. **CV pipeline** (`cv_pipeline.py`) — bulk extraction: raw CV text → `capability_profile_rules`, `dominant_signal_clusters`, `must_not_require_skills`
2. **Profile learning** (`profile_learning.py`) — incremental: free-text updates → structured profile patches

## CV pipeline (`cv_pipeline.py`)

### Pipeline stages

```
run_cv_pipeline(cv_text)
  A  parse_roles(cv_text)         → list of structured role dicts
  B  extract_phrases(roles)       → bigrams/trigrams from role bullets
  C  cluster_phrases(phrases)     → Jaccard-similarity phrase groups
  D  score_and_promote(clusters)  → strength bands (strong/working/basic/low)
  LLM _rename_top_clusters()      → rename top cluster seeds only (label-only, optional)
  →  _build_output(clusters)      → {capability_profile_rules, dominant_signal_clusters, must_not_require_skills}
```

LLM pass is label-only (renaming cluster seeds) — it does not change which rules exist or their strength. If no `llm_client` passed, clusters keep their extracted names.

### Key functions

| Function | Purpose |
|---|---|
| `run_cv_pipeline(cv_text, onboarding_settings=None, llm_client=None)` | Full pipeline, returns profile field dict |
| `parse_roles(cv_text, onboarding_settings=None)` | Extract structured role list from CV text |
| `extract_phrases(roles)` | Bigrams/trigrams from role bullets |
| `cluster_phrases(phrase_items)` | Jaccard-based grouping |
| `score_and_promote(candidates, ...)` | Score clusters into strength bands |
| `_rename_top_clusters(candidates, llm_client=None)` | LLM label pass (top clusters only) |
| `_build_output(clusters, onboarding_settings=None)` | Final profile field dict |

### Role dict shape (from `parse_roles`)

```python
{
    "title": str,
    "company": str,
    "start_year": int | None,
    "end_year": int | None,    # None = current
    "bullets": list[str],
    "tool_terms": list[str],   # from "Tools: ..." lines
}
```

### Output shape (from `run_cv_pipeline`)

```python
{
    "capability_profile_rules": [
        {
            "name": str,          # canonical capability name
            "level": str,         # "strong" | "working" | "basic" | "low"
            "aliases": list[str], # matched terms
            "evidence": str,      # where found (role title + year range)
        }
    ],
    "dominant_signal_clusters": [
        {
            "name": str,
            "fit_label": str,
            "watchout_label": str,
            "aliases": list[str],
            "min_snippet_hits": int,
            "dense_snippet_alias_hits": int,
        }
    ],
    "must_not_require_skills": list[str],
}
```

### Stopword filtering

`_STOPWORDS` (35 common words) filters ngrams. `_is_quality_phrase()` rejects phrases that are all stopwords. Don't add domain terms to `_STOPWORDS` — they belong in `capability_knowledge.py` as rules.

### Jaccard clustering

`_jaccard(left, right)` computes token overlap. Phrases merge into a cluster when similarity ≥ threshold. Threshold tuning affects how broad vs. narrow capability clusters become.

## Profile store (`profile_store.py`)

Single source of truth for loading and saving `data/profile.json`.

### Key functions

| Function | Purpose |
|---|---|
| `load_profile()` | Load + normalise profile.json; returns full profile dict |
| `save_profile(profile)` | Save profile dict back to JSON |
| `patch_profile(patch)` | Deep-merge patch into profile and save |
| `ensure_profile_exists()` | Create default profile if none exists |
| `normalize_capability_rules(rules=None)` | Validate and normalise capability rule list |
| `get_evidence_tiers(profile)` | Returns `{primary_current_evidence: str, ...}` |
| `get_evidence_tier_weights(profile)` | Returns tier weight floats |
| `get_search_settings(profile)` | Returns search settings with clamped limits |
| `get_preference_weights(profile)` | Returns 7-key preference weight dict |
| `get_scoring_rules(profile)` | Returns scoring rules sub-dict |

### Evidence tiers

Three tiers classify CV sections by recency:
```json
{
  "primary_current_evidence": "last 5 years content here",
  "secondary_older_evidence": "5-10 years content here",
  "background_optional_evidence": "10+ years content here"
}
```

`infer_evidence_tiers_from_cv_text()` auto-classifies sections. `build_evidence_tiers_from_sections()` assembles them from a parsed sections list.

### Default weights and limits

| Constant | Value |
|---|---|
| `DEFAULT_EVIDENCE_TIER_WEIGHTS` | `{primary: 1.0, secondary: 0.55, background: 0.25}` |
| `DEFAULT_PREFERENCE_WEIGHTS` | All 1.0 for 7 categories |
| `MIN_DATE_RANGE_DAYS` / `MAX_DATE_RANGE_DAYS` | 1 / 30 |
| `MIN_SEEK_PAGES` / `MAX_SEEK_PAGES` | 1 / 10 |
| `MIN_LINKEDIN_HOURS_OLD` / `MAX_LINKEDIN_HOURS_OLD` | 1 / 168 |

### Profile protection rule

Never regenerate or discard `data/profile.json` silently. It is the runtime source of truth — candidate's CV, scoring rules, weights, evidence tiers all live here. (Rule 8 in AGENTS.md)

## Capability matrix (`capability_matrix.py`)

Provides canonical naming and alias expansion for capability rules.

| Function | Purpose |
|---|---|
| `choose_capability_name(terms)` | Pick canonical name from a set of terms |
| `derive_job_description_aliases(name)` | Generate match aliases from a capability name |
| `expand_capability_terms(terms)` | Expand terms list with known aliases |
| `canonical_capability_term(term)` | Normalise a term to canonical form |

Aliases are used in matching — they are NOT stored in `capability_profile_rules`, only generated at match time. Don't store aliases in profile JSON; derive them dynamically.

## Capability knowledge (`capability_knowledge.py`)

JSON-backed module. Business rules live in `data/capability_knowledge.json` — not hardcoded.

Access via the module API, never by reading the JSON file directly:
```python
from job_hunter_agent.capability_knowledge import get_capability_rules, find_rule_by_name
```

## Profile learning (`profile_learning.py`)

Incremental updates from free-text (user onboarding, CV fragments). Produces patches that `patch_profile()` applies.

Key helpers used internally by `cv_pipeline.py`:
- `_parse_role_entries(text)` — parse role blocks from raw text
- `_normalize_token(s)` / `_normalize_phrase(s)` — text normalisation
- `_role_title_review_token(title)` — extract review token from title
- `_cap_log(msg)` — internal capability logging
- `_CURRENT_YEAR`, `_resolve_extraction_lookback_years(settings)` — year constants

## Common gotchas

- `cv_pipeline.py` imports several private helpers from `profile_learning.py` (`_CURRENT_YEAR`, `_cap_log`, etc.). Don't make these public or rename them without updating `cv_pipeline.py`.
- `run_cv_pipeline` output is a **patch dict**, not a full profile. Apply it with `patch_profile()`, don't overwrite the entire profile.
- Capability rules must have a `"level"` field. Missing level defaults to `0.45` strength in `signal_detection._capability_rule_strength()`.
- `dominant_signal_clusters` entries need `min_snippet_hits` and `dense_snippet_alias_hits` — without them, `detect_competitive_signals()` defaults to 2 and 4 respectively.
- `must_not_require_skills` feeds into hard blocker checking — adding entries here means jobs requiring those skills get hard-blocked.

## Related files

| File | Role |
|---|---|
| `cv_pipeline.py` | CV text → structured profile fields |
| `profile_store.py` | Profile CRUD, defaults, normalisation |
| `profile_learning.py` | Free-text → profile patches, shared helpers |
| `capability_matrix.py` | Canonical naming + alias expansion |
| `capability_knowledge.py` | JSON-backed capability rules module |
| `hard_blocker_rules.py` | JSON-backed hard blocker patterns |
| `role_title_knowledge.py` | JSON-backed role title token patterns |
| `data/profile.json` | Runtime candidate profile (never discard) |
| `data/capability_knowledge.json` | Managed capability rules + aliases |
