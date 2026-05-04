# Skill: Text & Utilities

Read this before editing `text_processing.py`, `scoring_utils.py`, `description_trust.py`, or any code that does text normalisation, source text building, or role summary generation.

## `text_processing.py` — text normalisation and summaries

Core text utilities used throughout the pipeline. Import from here rather than reimplementing.

| Function | Purpose |
|---|---|
| `compact_whitespace(value)` | Strips + collapses whitespace; returns `""` for None |
| `dedupe_preserve_order(values)` | Remove duplicate strings, preserve insertion order |
| `split_text_snippets(text)` | Split description into sentence/paragraph chunks |
| `list_to_phrase(items)` | `["a", "b", "c"]` → `"a, b, and c"` |
| `summarize_snippet(snippet, max_length=180)` | Truncate snippet to max_length with ellipsis |
| `synthesize_role_snapshot(record)` | `"Senior BA role in Sydney (Contract)"` |
| `description_summary_snippet(record, details_text)` | First non-generic paragraph of description |
| `build_role_summary(record, details_text, profile=None)` | Full human-readable role summary for dashboard card |

### `compact_whitespace`

Used before all text matching. Always call this before `text_contains_term()` or substring searches to avoid false misses from extra whitespace.

```python
compact_whitespace("  hello   world\n\t") == "hello world"
compact_whitespace(None) == ""
```

### `split_text_snippets`

Splits description text into overlapping snippets at paragraph/sentence boundaries. Used by `detect_competitive_signals()` for per-snippet hit counting.

### `build_role_summary`

The most complex text function. Priority order for summary content:
1. LLM-generated summary (if present in record)
2. `description_summary_snippet` — first meaningful paragraph
3. `synthesize_role_snapshot` — synthesised from record fields

Returns one clean paragraph. Used in dashboard cards.

### Internal helpers (not for external use)

`_is_generic_summary_text()`, `_clean_summary_candidate()`, `_is_summary_heading()`, `_looks_like_generic_job_summary()` — filter out boilerplate job ad language ("We are looking for...", "About us", etc.).

## `scoring_utils.py` — score calculation helpers

| Function | Returns | Purpose |
|---|---|---|
| `weighted_points(value, weight)` | `int` | `round(value * weight)` — apply preference weight |
| `build_scoring_source_text(record)` | `str` | Bundle all text fields for capability matching |
| `extract_contract_months(details_text)` | `Optional[int]` | Parse contract duration from description |
| `profile_recency_multiplier(profile, aliases)` | `float` | 1.0 / 0.6 / 0.3 based on experience recency |
| `find_profile_experience_year(profile, aliases)` | `Optional[int]` | Year alias was last mentioned in profile |
| `find_profile_experience_year_in_text(source_text, aliases)` | `Optional[int]` | Year found in arbitrary text |
| `find_old_experience_year(profile, aliases)` | `Optional[int]` | Year from older CV sections only |

### `build_scoring_source_text`

Concatenates all relevant text fields from a record into one string for capability matching:
- `details_text` (full description)
- `title`
- `company`
- `short_description`
- Any other rich text fields

Use this as input to `find_profile_capability_matches()` and similar — don't pass just `details_text`.

### `profile_recency_multiplier`

Returns a multiplier based on how recently the candidate last used a skill:
- 0–5 years ago → `1.0`
- 5–10 years ago → `0.6`
- 10+ years ago → `0.3`

Used by `evidence_tier_alignment_score()` in `capability_matching.py`. Derived from `find_profile_experience_year()` which scans the CV text sections in `profile["evidence_tiers"]`.

### `extract_contract_months`

Parses phrases like "12 month contract", "6-month engagement" from job descriptions. Returns `None` if not found. Used by contract preference assessment.

## `description_trust.py` — description quality classification

| Function | Returns | Purpose |
|---|---|---|
| `full_description_confidence(record)` | `"HIGH"` or `"LOW"` | Whether description is trustworthy |
| `is_description_trusted(record)` | `bool` | True if `full_description_confidence == "HIGH"` |
| `get_trusted_full_description(record)` | `str` | Returns description text if trusted, else `""` |

### Trust classification logic

```python
MIN_TRUSTED_DESCRIPTION_LENGTH = 600   # characters
TRUSTED_DESCRIPTION_SOURCES = frozenset({
    "jobaddetails",            # SEEK full detail page
    "body",                    # generic full body field
    "linkedin_full_description",
})
```

`HIGH` confidence requires:
1. The description source field is in `TRUSTED_DESCRIPTION_SOURCES`, AND
2. Description length ≥ `MIN_TRUSTED_DESCRIPTION_LENGTH`

`LOW` confidence = truncated/partial description, or description from an untrusted source.

### Why trust classification matters

Capability matching and signal detection give different weight to trusted vs. untrusted descriptions. A `LOW` confidence description may miss capabilities; scoring shouldn't penalise for that. `is_description_trusted(record)` is checked before running deep analysis.

## Shared patterns across utilities

**None-safe input:** `compact_whitespace(None)` returns `""`. Most text functions accept `Optional[str]` — check function signatures before assuming non-None.

**No mutation:** All utility functions return new values; they don't modify the input record or text in place.

**Deterministic:** No LLM calls, no random outputs. Same input → same output always.

## Common gotchas

- Always `compact_whitespace()` before any text comparison — raw HTML/scraped text often has irregular whitespace.
- `build_scoring_source_text` includes the title and company — don't pass just `details_text` to `find_profile_capability_matches`. Title keywords matter for matching.
- `full_description_confidence` returns a string `"HIGH"` / `"LOW"`, not a bool. Use `is_description_trusted()` for boolean checks.
- `profile_recency_multiplier` scans the entire profile CV text sections — expensive to call in a tight loop. Cache the result per capability where possible.
- `list_to_phrase([])` returns `""`, `list_to_phrase(["a"])` returns `"a"` (no Oxford comma for single item). Handle empty lists before calling.

## Related files

| File | Role |
|---|---|
| `text_processing.py` | Text normalisation, splitting, role summaries |
| `scoring_utils.py` | `weighted_points`, source text builder, recency |
| `description_trust.py` | Description quality classification |
| `capability_matching.py` | Calls `build_scoring_source_text`, `split_text_snippets` |
| `signal_detection.py` | Calls `compact_whitespace`, `split_text_snippets` |
| `fit_scoring.py` | Calls `build_scoring_source_text` |
| `role_analysis.py` | Calls `text_contains_term`, `compact_whitespace` |
