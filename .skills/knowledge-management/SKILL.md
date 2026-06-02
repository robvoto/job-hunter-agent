---
name: knowledge-management
description: Use ONLY for managed knowledge/config sources, DB-seeded knowledge, rule loaders, file/path ownership, and source-of-truth questions. Do NOT use for UI or scraper logic directly.
---

# Skill: Knowledge Management

Use before editing managed JSON knowledge, rule loaders, paths, or approval-backed runtime knowledge.

## Storage model
- All managed knowledge (`data/knowledge/*.json`, `data/config/*.json`, `data/signals/*.json`) is seeded into the `knowledge` table in SQLite on first deploy via `db_seed.py`.
- On every startup (`fastapi_app`, `source_connector`, `agent_runner`), `upgrade_knowledge_from_dir()` runs automatically and merges any new baseline entries without touching existing DB entries (including user-approved ones).
- `db_seed --overwrite` is a hard reset for corruption recovery only — it wipes user-approved additions.
- The JSON files in `data/knowledge/` are the baseline source of truth. The DB is the runtime truth.

## Upgrade tiers (version-aware merge)
- No `version` field → always replaced (pure reference data).
- Has `version` + `entries` list with `value` field → additive merge: new entries appended, existing preserved.
- Has `version`, no `entries` list → full replace only when file version > DB version.

`data/config/global_settings.json` is NOT a knowledge entry — it is stored in the `global_settings` DB table and always overwritten by `db_seed --upgrade`. When adding new required fields to the global settings schema, ship the JSON change and document that `--upgrade` is needed on deploy.

## Rules
- Business knowledge belongs in managed JSON/profile/config, not sealed Python constants.
- JSON knowledge must have one owner module, clear metadata, and validation.
- Do not dump arbitrary dictionaries into JSON without schema and meaning.
- Pending suggestions require approval before becoming trusted runtime knowledge.
- Feature code consumes owner loaders, not raw files.
- Consumers use canonical fields only; no alternate-key guessing.
- When adding new baseline entries to a knowledge JSON, bump its `version` field so the auto-upgrade picks them up.

## Owners
- `paths.py`: file paths.
- `profile_store.py`: profile, scoring, settings normalisation.
- `capability_knowledge.py`: capability knowledge.
- `hard_blocker_rules.py`: hard blocker patterns.
- `role_title_knowledge.py`: title knowledge.
- `job_quality.py`: quality-rule loaders and learnable CV-farming patterns.
- `signal_registry.py`: pending learned signals.

## Checklist
- Is this stable approved knowledge or a pending suggestion?
- Is there one owner/loader?
- Is schema validated at load/normalisation time?
- Are defaults explicit in the owner, not feature code?
- Are consumers using canonical fields only?
