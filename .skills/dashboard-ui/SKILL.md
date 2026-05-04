# Skill: Dashboard & UI

Read this before editing `local_server.py`, `dashboard_data.py`, `score_labels.py`, `match_labels.py`, or any HTML/CSS/JS templates.

## Architecture overview

```
local_server.py          ← HTTP server (routes, API handlers, run trigger)
  └─ dashboard_data.py   ← builds record sets (active, archived, hidden, applied)
       └─ history.py     ← reads job_history.json for archive/applied sets
  └─ score_labels.py     ← score → label mapping
  └─ match_labels.py     ← score → badge HTML, tone classes
  └─ templates/          ← HTML page templates (Jinja-style)
  └─ static/             ← CSS, JS, images
```

## Local server (`local_server.py`)

**Technology:** Python `http.server` (stdlib) — no framework.

**Run:** `python -m job_hunter_agent.local_server`

**Global state:**
```python
_run_in_progress: bool           # True while a scrape run is executing
_run_state_lock: threading.Lock  # protects _run_in_progress
_rejection_suggestions_cache: dict[str, dict]
```

**Key functions:**

| Function | Purpose |
|---|---|
| `_try_mark_run_started()` | Atomically set `_run_in_progress = True`; returns False if already running |
| `_is_run_in_progress()` | Thread-safe check |
| `_run_scrape_job()` | Runs `source_connector` in a background thread |
| `_render_template(path)` | Read and return HTML template as string |
| `_normalize_search_settings_payload(payload)` | Validate/clamp settings from POST body |
| `_normalize_onboarding_settings_payload(payload)` | Validate onboarding form inputs |
| `_onboarding_complete(profile)` | True if minimum profile data is present |
| `_parse_locations_override(value)` | Parse locations list from settings POST |
| `_read_last_run_timestamp()` | Read last run ISO timestamp from disk |

**MIME overrides:**
```python
_STATIC_MIME_OVERRIDES = {
    ".css": "text/css",
    ".js": "text/javascript",
    ".png": "image/png",
}
```

**Concurrency:** Only one scrape run at a time. `_try_mark_run_started()` returns `False` if a run is already in progress — the route handler should respond 409.

**Validation sets:**
```python
_VALID_REJECTION_RULE_CATEGORIES  # frozenset, loaded from JSON
_REJECTION_RULE_JUNK_VALUES       # frozenset, loaded from JSON
_VALID_ENGAGEMENT_TYPES = {"both", "permanent", "contract"}
```

## Dashboard data (`dashboard_data.py`)

Builds the four record sets used to render the dashboard sections:

| Set | What it contains |
|---|---|
| Active / kept | Jobs from the current run that passed all filters |
| Archived | Jobs no longer appearing in search but still within `ARCHIVE_STALE_AFTER_DAYS` |
| Hidden | Jobs the user manually hid |
| Applied | Jobs the user marked as applied |

**Key functions:**

| Function | Purpose |
|---|---|
| `build_dashboard_record_sets(...)` | Top-level: returns `{active, archived, hidden, applied}` |
| `build_history_dashboard_record(job_key, entry, ...)` | Build one archive record from history entry |
| `build_archive_records(history, current_run_keys, ...)` | All archive records for jobs no longer in current run |
| `build_hidden_records(...)` | Records for user-hidden jobs |
| `build_applied_records(...)` | Records for applied jobs |
| `load_last_kept_records(audit_rows, ...)` | Rebuild kept records from audit trail |
| `build_run_stats(...)` | Summary stats dict for run status display |

`build_dashboard_record_sets` takes functions as arguments (`normalize_job_key_fn`, `parse_timestamp_fn`, etc.) — this is dependency injection to avoid circular imports.

## Score labels (`score_labels.py`)

Maps integer fit scores to human-readable match levels. Thresholds come from `data/match_level_defaults.json`, not hardcoded.

| Function | Returns | Purpose |
|---|---|---|
| `score_to_match_level(score, match_levels=None)` | `dict` | Full match level record `{label, tone, min_score}` |
| `score_to_match_label(score, match_levels=None)` | `str` | Just the label string |
| `normalize_match_levels(levels)` | `list[dict]` | Validate/sort match level list |

`MATCH_LEVELS` constant — default levels loaded from `data/match_level_defaults.json` at import time.

## Match labels (`match_labels.py`)

UI rendering helpers — badge HTML, tone CSS classes, salary labels.

| Function | Returns | Purpose |
|---|---|---|
| `score_to_tone_class(score, profile=None)` | `str` | CSS class: "tone-strong", "tone-good", "tone-borderline", "tone-low" |
| `salary_fit_label(record, profile=None)` | `str` | "missing", "meets", "below", or "listed" |
| `compact_score_label(label)` | `str` | Long label → short category string |
| `render_badge(label, class_name, explanation)` | `str` | HTML `<span class="badge ...">` |
| `viewed_badge_html()` | `str` | Viewed indicator badge HTML |
| `format_score_breakdown_for_console(breakdown)` | `str` | Multi-line string for CLI output |

## Template rendering

Templates live in `templates/` as HTML files. `_render_template(path)` reads and returns the raw HTML — no template engine. Dynamic content is injected via string replacement or passed as JSON to JavaScript.

Template pages:
- `workspace.html` — main dashboard view
- `settings.html` — search/preference settings
- `onboarding.html` — first-run profile setup
- `showcase.html` — design showcase / dev testing

Static assets in `static/`: CSS, JS, images. Served with MIME type overrides from `_STATIC_MIME_OVERRIDES`.

## `data/match_level_defaults.json` shape

```json
[
    {"label": "Strong match", "tone": "strong", "min_score": 85},
    {"label": "Good match",   "tone": "good",   "min_score": 65},
    {"label": "Possible",     "tone": "borderline", "min_score": 45},
    {"label": "Weak match",   "tone": "low",    "min_score": 0}
]
```

These thresholds are user-configurable via `profile.json`. Never hardcode score numbers in Python — always use `score_to_match_level()`.

## Common gotchas

- `_run_scrape_job()` runs in a thread — any exception inside it must be caught and logged, not propagated. The HTTP handler has already returned `202 Accepted`.
- `build_dashboard_record_sets` uses injected function references, not direct imports, to avoid circular deps with `source_connector.py`. Don't refactor away from this pattern.
- Badge HTML (`render_badge`) uses `class_name` directly in the `<span>` — do not pass user-supplied strings without sanitising first (XSS risk).
- `score_to_tone_class` loads `match_levels` from profile on each call if not passed — for dashboard renders, load once and pass in.
- Adding new dashboard sections requires updating both `dashboard_data.py` (data) and the JavaScript in `workspace.html` (rendering). They're not automatically synchronised.

## Related files

| File | Role |
|---|---|
| `local_server.py` | HTTP server, routes, run trigger |
| `dashboard_data.py` | Record set building (active/archived/hidden/applied) |
| `score_labels.py` | Score → label mapping |
| `match_labels.py` | Badge HTML, tone CSS classes |
| `history.py` | Source of archive/applied/hidden record data |
| `source_connector.py` | Invoked by `_run_scrape_job()` |
| `templates/` | HTML page templates |
| `static/` | CSS, JS, images |
| `data/match_level_defaults.json` | Configurable score band thresholds |
