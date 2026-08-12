# Config and Rules Governance

## Purpose

This document defines where Job Hunter rules, settings, and operational knobs must live.

It exists because the application has started to spread behaviour across Python code, knowledge JSON, global settings, and tests. That makes the system harder to operate and easier for coding agents to break.

## Reference sources

Primary reference: Martin Fowler, **Feature Toggles (aka Feature Flags)**, 2017. The article separates runtime behaviour control from code changes, discusses toggle categories, toggle configuration, exposing current configuration, and the carrying cost of unmanaged toggles.

Supporting reference: Mahdavi-Hezaveh, Dremann, and Williams, **Software Development with Feature Toggles: Practices used by Practitioners**, 2019. The paper identifies practitioner practices including dedicated toggle management, metadata, default values, change logging, and cleanup.

## Governance rule

Python code is the engine.

Python may load rules, validate them, apply them, and emit metadata. Python must not hide business judgement, scoring policy, source-specific parsing rules, reusable labels, prompt copy, or tunable thresholds inside feature code.

## Ownership model

### Admin / global settings

Use Admin/global settings for operational knobs that a product owner may reasonably tune without editing code.

Examples:

- enabled / disabled flags
- max input characters
- history retention windows
- cache retention caps
- minimum trusted character counts
- retention ratios
- thresholds
- scoring weights
- model and cost settings
- search limits
- timeout settings

These settings should be visible in the Admin/global console when they affect runtime behaviour.

Examples now managed in global settings include:

- `history_settings.job_history_max_entries`
- `history_settings.job_history_max_age_days`
- `cache_settings.llm_cache_max_entries`
- `cache_settings.cv_extraction_cache_max_entries`
- `cache_settings.candidate_application_history_cache_max_entries`
- `cache_settings.occupation_title_cache_max_entries`
- `cache_settings.occupation_title_cache_max_age_days`

### Prompt copy

Use `data/knowledge/llm_*_defaults.json` for all behavioural guidance text sent to the LLM.

Each file has a `"lines"` array. `llm_gate.py` loads them at import time via `_load_managed_prompt_lines()` and assembles them into prompts through named builder functions (`build_fit_review_guidance()`, `build_requirement_coverage_guidance()`, etc.).

Ownership:
- Behavioural guidance lines → `data/knowledge/llm_*_defaults.json`
- Protocol constants (allowed output values, JSON output shapes, short headers, single-line control strings) → `llm_protocol.py`
- Operational knobs (model, max tokens, pricing, timeouts) → `global_settings.json` / Admin

Python code enforces allowed output values. It does not own the guidance text.

### data/knowledge

Use `data/knowledge` for governed rule libraries and reusable knowledge.

Examples:

- scoring rule definitions
- title/occupation taxonomy
- source registry
- parsing patterns
- UI labels
- work type mappings
- work mode rules
- salary parsing rules
- source-specific description cleanup patterns

These files may contain patterns, mappings, labels, and structured rule definitions. They should not become hidden operational control panels.
Managed UI copy must be validated at load time so mojibake or other encoding-corruption slips fail loudly before render instead of hiding behind fallback text.

### Python modules

Use Python modules as engines only.

A Python engine may:

- load configured rules
- validate required fields
- compile patterns
- apply rules
- produce audit metadata
- fail clearly when required config is missing

A Python engine must not:

- define source-specific rule lists directly in code
- define business scoring values directly in code
- invent fallback labels or fallback rules
- silently guess missing configuration
- hide tunable thresholds in local constants

## Description compaction decision

For description compaction, the correct split is:

- `description_compactor.py`: engine only
- `data/knowledge/description_compaction_rules.json`: removable/protected pattern library
- Admin/global settings: enabled flag, minimum compacted chars, retention ratio, and any max character budget used before LLM review
- tests: prevent source-specific cleanup rules from returning to Python

The current implementation already moved the pattern library into `data/knowledge`. The next improvement is to move tunable safety knobs into global/Admin settings if this feature remains active.

## Enforcement

Every new or changed rule/config feature must answer these questions before coding:

1. Is this a product/business decision? If yes, it must not live in Python.
2. Is this an operational knob? If yes, it belongs in Admin/global settings.
3. Is this a reusable rule library? If yes, it belongs in `data/knowledge` or a managed DB-backed knowledge store.
4. Can an agent accidentally hardcode this again? If yes, add a regression test.

## Agent rule

Coding agents must inspect the relevant skills and docs before editing. If a task would place business rules, source rules, scoring policy, labels, prompts, or thresholds in Python, the agent must stop or move the rule to the correct owner.

The `no-hardcoding` skill is required for changes involving thresholds, mappings, labels, rule IDs, source parsing, scoring, prompt copy, or reusable knowledge.
