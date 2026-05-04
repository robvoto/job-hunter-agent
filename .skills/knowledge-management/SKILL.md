# Skill: Knowledge Management

Read this before editing `capability_knowledge.py`, `hard_blocker_rules.py`, `role_title_knowledge.py`, or their backing JSON files.

## The knowledge module pattern

Business rules live in JSON files, not Python constants. Each domain has a pair:
- A **Python module** (`*_knowledge.py` / `*_rules.py`) — API to load, save, and upsert entries
- A **JSON data file** (`data/*.json`) — the actual rule store

Rule 2 in AGENTS.md: "Knowledge-managed. Business rules live in JSON-backed modules — not Python constants. Don't hardcode."

Never access the JSON files directly. Always go through the module API.

## Three knowledge modules

### 1. Capability knowledge (`capability_knowledge.py`)

Stores capability rules — technology/skill concepts the candidate has and the aliases used to match them in job text.

| Function | Purpose |
|---|---|
| `load_capability_knowledge()` | Load `data/capability_knowledge.json` → `list[dict]` |
| `save_capability_knowledge(entries)` | Write entry list back to disk |
| `upsert_capability_entry(value, aliases=None)` | Insert or merge a capability entry |

Entry shape:
```python
{
    "value": str,           # canonical capability name
    "aliases": list[str],   # terms to match in job descriptions
}
```

Entries are deduplicated by `value` on load. `_merge_entries()` handles alias merging when upserted.

### 2. Hard blocker rules (`hard_blocker_rules.py`)

Stores patterns for mandatory requirements the candidate cannot meet (e.g. citizenship, certifications). A matched hard blocker causes hard rejection.

| Function | Purpose |
|---|---|
| `load_hard_blocker_rules()` | Load `data/hard_blocker_rules.json` → `list[dict]` |
| `save_hard_blocker_rules(entries)` | Write back to disk |
| `upsert_hard_blocker_rule(value, aliases=None)` | Insert/merge; value MUST contain `{term}` |
| `expand_hard_blocker_terms(entry)` | Expand `{term}` with entry's aliases → list of match strings |
| `find_hard_block_matches(text, terms=None)` | Returns list of `{term, pattern, snippet}` dicts |
| `generalize_hard_block_pattern(text, term)` | Derives a generalised pattern from a job text match |

**Critical:** `upsert_hard_blocker_rule(value, ...)` requires `value` to contain `{term}` placeholder (e.g. `"must hold {term} clearance"`). Without it, `expand_hard_blocker_terms` won't substitute aliases.

Hard blocker entry shape:
```python
{
    "value": str,           # pattern template with {term} placeholder
    "aliases": list[str],   # substituted into {term} to build match patterns
}
```

`find_hard_block_matches(text)` checks whether any expanded pattern appears in the text. Returns match dicts with `term`, `pattern`, and context `snippet`. Used in `signal_detection.hard_block_entries()`.

`_near_desirable_language()` prevents false positives — patterns near positive language ("not required", "desirable but not essential") are suppressed.

### 3. Role title knowledge (`role_title_knowledge.py`)

Stores approved token patterns for role title filtering. Simple list of value entries without aliases.

| Function | Purpose |
|---|---|
| `load_role_title_knowledge()` | Load `data/role_title_knowledge.json` → `list[dict]` |
| `save_role_title_knowledge(entries)` | Write back |
| `upsert_role_title_entry(value)` | Insert or skip if already present |

Entry shape:
```python
{
    "value": str,   # token or phrase to match in job titles
}
```

Used in `filters.py` title filtering. Role title tokens are approved by the user via signal registry — never hardcode them.

## Common internal pattern across all three modules

All three follow the same internal pattern:
1. `_load_payload()` — reads JSON, returns `{"entries": [...]}` or `{}`
2. `_normalize_entry(entry)` — validates and cleans a single entry dict
3. `_merge_entries(existing, new)` — merges aliases without duplicates
4. Load function applies deduplication after loading
5. Save function writes `{"entries": [...]}` shape back

## `paths.py` — all file paths

All paths are defined once in `paths.py` as `pathlib.Path` objects. Never construct paths with string concatenation. Import from `paths`:

```python
from job_hunter_agent.paths import (
    CAPABILITY_KNOWLEDGE_PATH,      # data/capability_knowledge.json
    HARD_BLOCKER_RULES_PATH,        # data/hard_blocker_rules.json
    ROLE_TITLE_KNOWLEDGE_PATH,      # data/role_title_knowledge.json
    SIGNAL_REGISTRY_PATH,           # data/signal_registry.json
    PROFILE_PATH,                   # data/profile.json
    GOVERNMENT_CONTEXT_KNOWLEDGE_PATH,
    # ... etc
)
```

Full list of path constants:

| Constant | Points to |
|---|---|
| `PACKAGE_DIR` | `job_hunter_agent/` package root |
| `REPO_ROOT` | repository root |
| `DATA_DIR` | `data/` |
| `OUTPUT_DIR` | `output/` |
| `TEMPLATES_DIR` | templates directory |
| `DOCS_DIR` | `docs/` |
| `AUDIT_RECORDS_PATH` | `data/audit_records.json` |
| `RUN_STATS_PATH` | `data/run_stats.json` |
| `REVIEW_DATA_PATH` | `data/review_data.json` |
| `JOB_HISTORY_PATH` | `data/job_history.json` |
| `REJECTION_RULES_PATH` | `data/rejection_rules.json` |
| `PROFILE_PATH` | `data/profile.json` |
| `SCORING_RULES_PATH` | scoring rules defaults JSON |
| `MATCH_LEVEL_DEFAULTS_PATH` | `data/match_level_defaults.json` |
| `HARD_BLOCKER_RULES_PATH` | `data/hard_blocker_rules.json` |
| `CAPABILITY_KNOWLEDGE_PATH` | `data/capability_knowledge.json` |
| `ROLE_TITLE_KNOWLEDGE_PATH` | `data/role_title_knowledge.json` |
| `SIGNAL_REGISTRY_PATH` | `data/signal_registry.json` |
| `GOVERNMENT_CONTEXT_KNOWLEDGE_PATH` | `data/government_context_knowledge.json` |
| `GOVERNMENT_CONTEXT_RULES_PATH` | `data/government_context_rules.json` |
| `DASHBOARD_PATH` | output HTML dashboard |
| `WORKSPACE_HTML_PATH` | workspace UI page |
| `SETTINGS_HTML_PATH` | settings UI page |
| `ONBOARDING_HTML_PATH` | onboarding UI page |
| `LLM_CACHE_PATH` | LLM response cache |
| `LLM_COSTS_PATH` | LLM cost tracking |

## Common gotchas

- Load functions return `list[dict]`, not a dict keyed by value — iterate, don't subscript.
- `upsert_capability_entry` and `upsert_hard_blocker_rule` both call `save_*` immediately after merging — they are not batched. For bulk inserts, collect entries then call `save_*` once.
- `find_hard_block_matches` defaults to loading `load_hard_blocker_rules()` if `terms` is not passed. Passing pre-loaded terms avoids repeated disk reads in a scrape loop.
- Changing a hard blocker value (the `{term}` template string) without updating aliases leaves orphaned aliases. Always update both together.
- `paths.py` uses `pathlib.Path` — don't convert to `str` unless a library requires it.

## Related files

| File | Role |
|---|---|
| `capability_knowledge.py` | Capability rules CRUD |
| `hard_blocker_rules.py` | Hard blocker pattern CRUD + matching |
| `role_title_knowledge.py` | Role title token CRUD |
| `paths.py` | All file paths — single source of truth |
| `signal_registry.py` | Writes to knowledge JSONs on `approve_signal` |
| `signal_detection.py` | Calls `find_hard_block_matches` |
| `capability_matching.py` | Reads capability knowledge via matrix expansion |
| `filters.py` | Reads role title knowledge |
| `data/capability_knowledge.json` | Managed capability rules |
| `data/hard_blocker_rules.json` | Managed hard blocker patterns |
| `data/role_title_knowledge.json` | Managed title tokens |
