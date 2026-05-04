# Skill: Preferences & Location

Read this before editing `preferences.py`, `salary_utils.py`, `role_analysis.py`, or preference-related sections of `profile.json`.

## What preferences cover

Non-capability score adjustments based on job attributes vs. candidate preferences:
- **Location** — home location, secondary location, remote vs. on-site
- **Contract type** — permanent vs. contract, preferred contract length
- **Government** — prefer or avoid government sector
- **Salary** — salary range vs. candidate expectation

Preferences produce score adjustments, not hard blocks. A bad location scores down; it doesn't reject.

## Preference functions (`preferences.py`)

| Function | Returns | Purpose |
|---|---|---|
| `get_match_preferences(profile=None)` | `dict` | Loads preference config from profile |
| `assess_location_preference(record, profile=None)` | `Optional[dict]` | Location match entry or None |
| `assess_contract_preference(record, profile=None)` | `Optional[dict]` | Contract match entry or None |
| `assess_government_preference(record, profile=None)` | `Optional[dict]` | Government preference entry or None |
| `salary_fit_adjustment(record, profile=None)` | `int` | Point adjustment (positive or negative) |

Each `assess_*` function returns a score entry dict (same shape as `fit_score_breakdown` entries) or `None` if the preference can't be assessed (missing data).

## Match preferences shape (from `get_match_preferences`)

```python
{
    "home_location": str,               # primary preferred location
    "secondary_location": str,          # secondary preferred location (optional)
    "prefer_government": bool,          # True = government roles preferred
    "prefer_permanent": bool,           # True = permanent preferred over contract
    "preferred_contract_months": int,   # ideal contract length
    "short_contract_months": int,       # below this = short contract warning
}
```

Loaded from `profile["location_preferences"]`, `profile["contract_preferences"]`, etc.

## Salary utilities (`salary_utils.py`)

| Function | Returns | Purpose |
|---|---|---|
| `salary_sort_value(value)` | `float` | Lower bound for sort ordering |
| `_salary_max_value(value)` | `float` | Upper bound of salary range |
| `_salary_includes_super_or_package(value)` | `bool` | Detects "inc super", "pkg", "package" |

### Salary string format

Salary values in records are strings like `"$120,000 - $140,000 p.a."` or `"$450 - $700 per day"`. `salary_sort_value` parses these to extract the lower bound for sorting.

Super/packaging detection: if `_salary_includes_super_or_package()` is True, the displayed salary is not take-home — affects comparison logic.

## Role analysis (`role_analysis.py`)

| Function | Returns | Purpose |
|---|---|---|
| `text_contains_term(text, term)` | `bool` | Case-insensitive word-boundary match |
| `has_government_context(text)` | `bool` | Detects government sector indicators |
| `infer_role_sector(record, details_text)` | `dict` | `{kind, label, confidence}` |
| `infer_posting_channel(record, details_text)` | `dict` | Recruiter vs. direct employer |
| `role_text_bundle(record, details_text)` | `str` | Combines title/company/teaser/details |
| `friendly_capability_label(name)` | `str` | "machine_learning" → "Machine Learning" |

### Sector inference output

```python
{
    "kind": "government" | "private" | "unknown",
    "label": str,         # human-readable ("State Government", "Private Sector")
    "confidence": "high" | "medium" | "low",
}
```

### Posting channel output

```python
{
    "channel": "recruiter" | "direct" | "unknown",
    "label": str,
}
```

### Government context detection

`has_government_context(text)` uses rules loaded from:
- `data/government_context_rules.json` — term lists
- `data/government_context_knowledge.json` — approved learned patterns

`_load_government_context_rules()` and `_load_government_context_knowledge_patterns()` load these. Cached per run.

### `text_contains_term` — word-boundary matching

Used extensively across filtering and detection. Uses `\b` word boundaries so "data" doesn't match "database". Always use this instead of `str.find()` or `in` for term matching in job text.

## Preference config keys in `profile.json`

```json
{
  "location_preferences": {
    "home_location": "Sydney, NSW",
    "secondary_location": "Remote",
    "location_weight": 1.0
  },
  "contract_preferences": {
    "prefer_permanent": true,
    "preferred_contract_months": 12,
    "short_contract_months": 3
  },
  "government_preferences": {
    "prefer_government": false,
    "government_weight": 0.5
  },
  "salary_preferences": {
    "min_annual": 120000,
    "max_annual": 160000,
    "min_daily": 650,
    "max_daily": 900
  }
}
```

## Common gotchas

- `assess_location_preference` returns `None` (not a zero-point entry) when location data is missing. Callers must handle `None`.
- Salary comparison must account for daily vs. annual rates — the record's salary string may be either. `salary_sort_value` parses both formats.
- `has_government_context` is called multiple times per job — it loads rules each call. If performance is a concern, call once and pass result downstream.
- `text_contains_term` is case-insensitive but does NOT strip punctuation. "Python." won't match term "python" if the period is inside the match boundary. Use `compact_whitespace` first.
- Government preference is a soft preference — `prefer_government: false` does not hard-block government roles, it just scores them down.

## Related files

| File | Role |
|---|---|
| `preferences.py` | Location, contract, government, salary assessments |
| `salary_utils.py` | Salary string parsing and comparison |
| `role_analysis.py` | Sector inference, posting channel, text term matching |
| `fit_scoring.py` | Calls preference functions as part of `fit_score_breakdown` |
| `scoring_utils.py` | `extract_contract_months()` used by contract preference |
| `data/profile.json` | Location, contract, government, salary preference config |
| `data/government_context_rules.json` | Government sector term lists |
| `data/government_context_knowledge.json` | Approved learned government patterns |
