# Skill: Signal Registry & Learning

Read this before editing `signal_registry.py`, the learning side of `signal_detection.py`, or any code that calls `register_signals`, `approve_signal`, or `load_approved_signal_catalog`.

## What the signal registry is

A learning inbox: patterns observed during scraping are surfaced as pending signals awaiting user review. The user approves or ignores them via the UI. Approved signals are promoted into the appropriate knowledge JSON. This is the ONLY path for learned behaviour to enter filters/scoring — nothing is auto-promoted.

Rule 7 in AGENTS.md: "User-controlled learning. Learning flows through the signal registry. Don't embed learned behaviour into filters."

## Signal lifecycle

```
Job scraped
  └─ signal_detection.extract_skill_observations()   → raw observations
       └─ build_job_learning_signals()                → shaped signal dicts
            └─ register_signals(signals, category)    → signal_registry.py
                 └─ signal_registry.json              ← pending / snoozed
                      ↓ user approves in UI
                 approved_knowledge JSON              ← capability_knowledge.json etc.
```

## Signal categories

```python
VALID_SIGNAL_CATEGORIES = frozenset({
    "capability_concept",       # → data/capability_knowledge.json
    "government_context",       # → data/government_context_knowledge.json
    "hard_blocker_pattern",     # → data/hard_blocker_rules.json
    "role_title_token",         # → data/role_title_knowledge.json
})
```

Each signal must have a category before it can be approved. `set_signal_category(key, category)` assigns it.

## Key functions

| Function | Purpose |
|---|---|
| `load_registry()` | Load `data/signal_registry.json` → `{signal_key: record}` |
| `save_registry(registry)` | Write registry back to disk |
| `register_signals(signal_names, category="")` | Add/update pending signals from a scrape run |
| `approve_signal(key, category="")` | Promote a signal into the appropriate knowledge JSON |
| `ignore_signal(key)` | Mark signal as ignored (hidden from review UI) |
| `set_signal_category(key, category)` | Assign category to uncategorised signal |
| `clear_signal_learning_state()` | Reset all pending signals (dev/testing only) |
| `load_approved_signal_catalog()` | Returns all approved signals across all categories |
| `signal_in_approved_knowledge(category, signal, aliases=None)` | Check if signal already exists in a knowledge store |
| `get_learning_status(signal_name)` | Returns "approved" / "ignored" / "pending" / "unknown" |

## Registry record shape

```python
{
    "key": str,                 # normalised signal key (slug)
    "name": str,                # display name
    "category": str,            # one of VALID_SIGNAL_CATEGORIES or ""
    "status": str,              # "pending" | "approved" | "ignored" | "snoozed"
    "sightings": int,           # times seen across runs
    "first_seen": str,          # ISO timestamp
    "last_seen": str,           # ISO timestamp
    "context": dict,            # arbitrary context payload (aliases, examples, etc.)
    "needs_review": bool,       # true = surfaced to UI; false = hidden
    "history": list[dict],      # sighting snapshots
}
```

## Stale/hidden signal constants (also in `history.py`)

```python
ARCHIVE_STALE_AFTER_DAYS = 15     # auto-archive old pending signals
HIDDEN_REVIEW_DAYS = 30           # hide signals not seen recently
MAX_HISTORY_SIGHTINGS = 24        # cap on sighting history entries
```

## Approval flow — what happens on `approve_signal(key)`

1. Loads the registry entry for `key`
2. Reads the target knowledge JSON (via `_CATEGORY_KNOWLEDGE_PATHS[category]`)
3. Calls `_append_knowledge_entry()` — upserts the signal into the knowledge store
4. Sets `status = "approved"` in the registry
5. Saves both registry and knowledge JSON

## What `_append_knowledge_entry` writes

Per-category output:
- `capability_concept` → `capability_knowledge.json`: `{value, aliases, ...}`
- `hard_blocker_pattern` → `hard_blocker_rules.json`: `{value, aliases, ...}` (needs `{term}` placeholder)
- `role_title_token` → `role_title_knowledge.json`: `{value}`
- `government_context` → `government_context_knowledge.json`: `{value, aliases}`

## Interaction with `capability_matching.py`

`reviewed_signal_matches_for_text(details_text)` in `capability_matching.py` calls `load_approved_signal_catalog()` + `load_registry()` to find which signals were matched and what their review status is. When patching tests for this function, patch **both**:
- `capability_matching.load_registry`
- `capability_matching.load_approved_signal_catalog`

(Not `source_connector.load_registry` — that namespace no longer affects this function.)

## `needs_review` flag

Signals with `needs_review: true` are shown in the review UI. Signals with `needs_review: false` are logged but hidden. The flag must be preserved — do not silently drop signals (Rule 4: "Preserve signals").

## Common gotchas

- `register_signals` is idempotent for the same signal key — calling it twice just increments `sightings` and updates `last_seen`.
- A signal without a category cannot be approved. Check `category` before calling `approve_signal`.
- `signal_in_approved_knowledge` returns `(bool, reason_str)` — unpack both, the reason is used in logging.
- `load_approved_signal_catalog()` returns a flat list across all four knowledge files — don't confuse it with `load_registry()` which is only the pending inbox.
- Never directly edit `data/signal_registry.json` in code except through `save_registry()` — it's normalised on load.

## Related files

| File | Role |
|---|---|
| `signal_registry.py` | Registry CRUD, approval flow |
| `signal_detection.py` | `extract_skill_observations`, `build_job_learning_signals` |
| `capability_matching.py` | `reviewed_signal_matches_for_text` — reads registry status |
| `data/signal_registry.json` | Pending signal inbox |
| `data/capability_knowledge.json` | Approved capability signals |
| `data/hard_blocker_rules.json` | Approved hard blocker signals |
| `data/role_title_knowledge.json` | Approved title token signals |
