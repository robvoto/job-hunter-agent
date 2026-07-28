---
name: suggested-tuning
description: "Use ONLY for Settings > Optimise > Suggested Tuning: empty suggestions, scrape/review-derived tuning items, capability suggestion confirmation, and rejection-pattern exclusion suggestions."
---

# Suggested Tuning

Use this skill for the Settings > Optimise > Suggested Tuning panel.

## Product intent

Suggested Tuning is a confirmation layer, not automatic learning.

It should surface:

- repeated capability signals from roles that were kept
- repeated rejection patterns that may justify a rule or exclusion

It must not silently change the candidate profile without user confirmation.

## Runtime flow

1. `scrape_finalize.py` calls `review_insights.build_review_data()` when finalising a run.
2. `build_review_data()` creates the `suggested_tuning` payload through `build_suggested_tuning()` and persists it with `write_review_data()`.
3. `GET /api/review-data` returns the saved payload through `workspace_api.api_review_data()`; it does not rebuild suggestions.
4. The frontend renders into `#tuning_suggestions_panel` from `templates/static/settings/shared/settings-review-panel.js`.
5. The HTML shell lives in `templates/partials/settings/standard/settings-optimise.html`.

## Empty state

An empty panel is valid when there is no saved review data or no repeated signal meets the configured thresholds.

Do not treat this message as a UI failure by itself:

`No suggested tuning yet. After a scrape run, repeated useful capabilities and repeated exclusion patterns will show up here for confirmation.`

Check data and thresholds before changing UI code.

## Capability suggestions

Capability suggestions are built by `build_capability_tuning_suggestions()`.

Rules:

- Only skills observed on kept roles are candidates.
- Already classified capability rules are skipped.
- Repeated unclassified skills become suggestions once they meet `review_capability_suggestion_min_count`.
- Suggested strength is `working` only when count meets `review_capability_working_min_count`; otherwise it is `basic`.

Confirming a suggestion calls:

- `POST /api/tuning-decisions`
- `apply_capability_tuning_decisions()`

This writes to `candidate_capabilities` in the runtime profile.

## Rule suggestions

Repeated rejection patterns are built from `rejections_by_reason` via `_build_rule_tuning_suggestions_from_reviews()`.

Supported patterns include:

- `ONET_FAR_OCCUPATION` (title didn't match target/adjacent patterns and O*NET confirmed a far occupation family; see `.skills/job-filtering/SKILL.md`)
- `CARD_SPECIALIST:*`
- `DESC_CAPABILITY_LOW:*`
- `TITLE_BAD_KEYWORD:*`
- `DESC_MANDATORY_SKILL:*`

Adding a phrase exclusion from the panel calls:

- `POST /api/rule/phrase`

This writes to `reject_description_phrase_rules` and rebuilds the workspace after the rule change.

## Optimization suggestions (uncertain titles)

`build_title_optimization_suggestions()` is a separate, softer signal from rule suggestions above: titles where O*NET could not confidently classify the occupation family (`onet_classification.result == "uncertain"`) on a row that was ultimately rejected for some other reason downstream. It reads `onet_classification` directly rather than `title_reason`/`reject_reason`, since those fields get overwritten or reused once a row proceeds past the title gate — see `.skills/job-filtering/SKILL.md`.

## Files to inspect first

- `templates/partials/settings/standard/settings-optimise.html`
- `templates/static/settings/shared/settings-review-panel.js`
- `job_hunter_agent/routes/workspace_api.py`
- `job_hunter_agent/routes/review.py`
- `job_hunter_agent/review_insights.py`
- `job_hunter_agent/global_settings.py`

## Tests

For logic changes, add or update focused tests around `review_insights.py`.

Minimum checks:

- saved review data produces capability suggestions for repeated kept-role skills
- already classified capabilities are not suggested again
- repeated rejection reasons produce rule suggestions at threshold
- capability confirmation writes `candidate_capabilities`

For UI shell changes, keep settings rendering tests aligned with current class names and element IDs.

## Guardrails

- Do not auto-apply suggestions.
- Do not suggest from rejected-role skills as useful capability support.
- Do not lower thresholds to hide data issues.
- Do not confuse this panel with onboarding capability review or admin signal registry.
- Do not invent capabilities, aliases, or exclusions without evidence.
