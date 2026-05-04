# Skill: Job Filtering Pipeline

> Load this before editing filters, reject reasons, content rules, or hard blockers.

## What this skill covers
How a raw job card goes from "scraped" to "kept or rejected". Every gate, every reason code, every config file.

---

## Filter pipeline — order matters

```
1. passes_quick_card_filters()   ← cheap, card-metadata-only, no description needed
2. passes_title_filters()        ← title must match primary_job_title_pattern or secondary_title_patterns
3. [fetch job detail page]
4. passes_content_filters()      ← description phrases, hard blocker rules, capability check
5. passes_saved_rejection_rules() ← user-saved learned rejection rules (output/rejection_rules.json)
6. [LLM review — optional]       ← constrained to KEEP / REJECT / MAYBE
7. deterministic_review_outcome() ← override LLM if signals are unambiguous (in source_connector.py)
```

All live in `filters.py` except step 7 (in `source_connector.py`).

---

## Key functions

### `passes_title_filters(title) → (bool, reason)`
Thin wrapper around `analyze_title_filters()`. Returns `(True, "OK")` or `(False, "REASON_CODE")`.

### `analyze_title_filters(title, profile) → dict`
Full title analysis. Key output fields:
| Field | Meaning |
|-------|---------|
| `ok` | Whether the title passes |
| `reason` | Reason code (see below) |
| `match_family` | `"primary"` or `"secondary"` |
| `matched_pattern` | Which pattern matched |
| `seniority_adjustment` | Score delta (+3 preferred seniority, -5 lower seniority) |
| `title_seniority` | `"plain"` / `"preferred"` / `"lower"` |

**Config used:** `profile.primary_job_title_pattern` (list), `profile.secondary_title_patterns` (list), `profile.reject_title_rules` (list of `{pattern, reason}`)

### `passes_content_filters(details_text, card_location, title_reason) → (bool, reason)`
Runs in order:
1. Reject description phrase rules (`profile.reject_description_phrase_rules`)
2. Hard blocker pattern matches (`hard_blocker_rules.py`)
3. Capability profile check (`_evaluate_capability_profile`)
4. Description confidence check (`_evaluate_description_confidence`)

### `passes_quick_card_filters(title, teaser, company, ...) → (bool, reason)`
Card-metadata-only filter. Runs before fetching job details.
- Checks `profile.cheap_reject_metadata_rules` — title/teaser pattern matches
- Checks `profile.cheap_keep_counter_patterns` — if enough counter-signals hit, overrides specialist reject
- Returns `(True, "OK")` or `(False, "CARD_SPECIALIST:...")`

### `passes_saved_rejection_rules(text) → (bool, reason)`
Applies user-saved rejection rules from `output/rejection_rules.json`. Called during scraping.

---

## Reject reason codes

### Title filter reasons
| Code | Meaning |
|------|---------|
| `TITLE_NOT_TARGET` | Title doesn't match any target pattern |
| `TITLE_EMPTY` | No title provided |
| `TITLE_POTENTIAL_MATCH` | Secondary-pattern match (scores lower) |
| `OK` | Direct primary match |
| `TITLE_BAD_KEYWORD:<kw>` | Matched a `reject_title_rules` pattern |
| `TITLE_BAD_ROLE:<role>` | Matched a role-family block |

### Content filter reasons
| Code | Meaning |
|------|---------|
| `DESC_EMPTY` | No description text |
| `DESC_REJECT:<phrase>` | Matched a `reject_description_phrase_rules` entry |
| `DESC_HARD_BLOCK_RULE:<term>` | Matched a hard blocker pattern from `hard_blocker_rules.json` |
| `DESC_HARD_BLOCK_KNOWLEDGE:<term>` | Hard block via knowledge module |
| `DESC_CAPABILITY_LOW:<area>` | Capability area detected but assessed as low-fit |
| `DESC_BAD_PHRASE:<phrase>` | Rejected by description phrase rule |
| `DESC_BAD_REGEX:<pattern>` | Rejected by regex content rule |
| `DESC_LOCATION:<place>` | Location mismatch in description |
| `NO_DETAILS` | Could not load full description |
| `DETAILS_CHALLENGE_PAGE` | SEEK blocked by challenge page |
| `DETAILS_BLOCKED_PAGE` | Blocked from reading job details |
| `DETAILS_NAVIGATION_ERROR` | Could not open job ad page |
| `LEARNED_REJECT:<token>` | User-saved rejection rule matched |
| `CARD_SPECIALIST:<pattern>` | Card-level specialist reject |

### Post-LLM reasons
| Code | Meaning |
|------|---------|
| `LLM_REJECT` | LLM returned REJECT |
| `DET_REJECT` | Deterministic override — unambiguous mismatch |
| `DUPLICATE_URL` | Duplicate listing removed |
| `ALREADY_APPLIED` | Already marked as applied |
| `MANUALLY_HIDDEN` | Already hidden by user |
| `POSTED_TOO_OLD:<days>` | Older than the search window |

Human-readable versions of all codes: `humanize_reject_reason()` in `source_connector.py`.

---

## Hard blocker rules

File: `data/hard_blocker_rules.json` (managed by `hard_blocker_rules.py`)

Hard blockers cause immediate reject for explicit non-negotiable requirements:
- Work rights (must be citizen / PR / clearance)
- Mandatory certifications
- Mandatory location requirements

Code path: `find_hard_block_matches(text, must_not_require_skills)` in `hard_blocker_rules.py`.
Profile has a `must_not_require_skills` list — these are skills the candidate cannot claim.

**Do not add hard blockers for soft mismatches.** Soft mismatches score down, not hard-block.

---

## Title normalisation

`title_normalization_rules.py` handles:
- `normalize_title_text(title)` — strips punctuation, lowercases, normalises whitespace
- `decompose_title_text(title)` — returns `{normalized_title, base_role, seniority_modifiers, variant_terms}`

Seniority modifiers detected: `senior`, `lead`, `principal`, `staff`, `head`, `manager`, `junior`, `graduate`, `associate`, etc.

---

## Config in `data/profile.json`

| Key | Used by | Type |
|-----|---------|------|
| `primary_job_title_pattern` | `passes_title_filters` | list of pattern strings |
| `secondary_title_patterns` | `passes_title_filters` | list of pattern strings |
| `reject_title_rules` | `analyze_title_filters` | list of `{pattern, reason}` |
| `reject_description_phrase_rules` | `passes_content_filters` | list of `{phrase, reason}` |
| `cheap_reject_metadata_rules` | `passes_quick_card_filters` | list of `{pattern, reason, scope}` |
| `cheap_keep_counter_patterns` | `passes_quick_card_filters` | list of regex strings |
| `must_not_require_skills` | `passes_content_filters` (hard block) | list of skill strings |

---

## Common gotchas

- **`TITLE_POTENTIAL_MATCH` is not a reject.** It passes the title filter but scores lower (secondary match) and gets a lower `title_reason` in the record. Don't mistake it for a failure.
- **Cheap card filters run without description.** Don't put description-dependent logic in `passes_quick_card_filters`.
- **`reject_description_phrase_rules` are exact lowercased substring matches**, not regex. Use `reject_description_regex_rules` if you need a pattern.
- **Hard blockers are not the same as capability gaps.** A capability gap scores down; a hard blocker rejects immediately.
- **`passes_saved_rejection_rules` reads from `output/rejection_rules.json`**, not from `data/profile.json`. This is for user-saved learned rules, not profile config.

---

## Related files
| File | Role |
|------|------|
| `filters.py` | All filter functions |
| `hard_blocker_rules.py` | Hard blocker pattern matching module |
| `data/hard_blocker_rules.json` | Hard blocker rule definitions |
| `role_title_knowledge.py` | Title token pattern knowledge module |
| `data/role_title_knowledge.json` | Role title pattern definitions |
| `title_normalization_rules.py` | Title text normalisation |
| `source_connector.py` | Orchestrates the full filter pipeline |
| `signal_detection.py` | `hard_block_entries()`, `hard_block_reasons()` |
