# Scoring & Ranking Details

Loaded only when the task needs the detailed contracts/examples below.

## Breakdown label ownership
Score breakdown labels shown to users must come from `data/knowledge/ui_labels.json`, never hardcoded:
- `grade_labels`: human-readable LLM grade descriptions (e.g. "The job ad matches your experience well")
- `title_match_labels`: human-readable title match descriptions (e.g. "The job title matches one of your target roles")
- `fit_highlight_labels.capability_match_sentence`: template for capability matches shown in fit reasons

When changing these labels, bump `ui_labels.json` version so `db_seed --upgrade` re-seeds the DB on deploy.

## Requirement evidence validation

For every `supported` or `partially_supported` capability mapping:

1. Confirm the mapped capability exists in the candidate profile.
2. Confirm candidate evidence covers at least one substantive element from the requirement wording.
3. Do not accept thematic, occupational, or generally transferable similarity as proof.
4. If only transferable background exists, normalize the requirement to `not_shown`, clear the matched capability, award zero credit, and record the validation reason.
5. Preserve genuine partial matches where the evidence proves a real component of a compound requirement.
6. Add a regression test for the reported profession and another unrelated profession/domain when the defect is generic.

Examples of invalid partial mappings:
- agile delivery management -> investment appraisal / ROI
- general business analysis -> banking or telecommunications experience
- policy interpretation -> complaints, fraud, or case-management experience

Examples are diagnostic only. Do not hardcode these phrases as the rule.

## LLM output validation

For LLM review data:

- `decision` must be one of `KEEP`, `REJECT`, or `MAYBE`
- `grade` must be present if the scoring path uses it
- missing or invalid values must not silently become neutral/default values
- return an explicit degraded state instead
- log or expose the degraded state in audit output
- add/adjust tests for the degraded path

## LLM call paths - two schemas, two purposes

There are two separate LLM calls with different schemas. Do not conflate them.

**Fit review** (`_LLMFitReviewPayload`, `fit_review=True`):
- Returns: `fit_review` (decision + grade), `requirement_coverage`, `debug_reason`, `occupation_alignment`, `occupation_alignment_reason`
- No `learning_candidates` field; the fit-review path does not extract learning signals
- `requirement_coverage` is the single source for capability support — entries must link to profile capability rule names for `supported`/`partially_supported` status
- Do NOT include learning category guidance (`LLM_PROMPT_ROLE_TITLE_PATTERN_GUIDANCE`) in this prompt
- `debug_reason` is a short internal explanation for logs/admin only — not shown in the main UI

**Learning-only** (`_LLMReviewPayload`, `fit_review=False`):
- Returns: `learning_candidates` only
- Called only when deterministic scoring fires AND high-value ambiguous learning candidates exist
- Candidates are validated against `llm_gate.ALLOWED_LEARNING_CATEGORIES`, derived from `signal_schema.VALID_SIGNAL_CATEGORIES`; removed legacy categories must not be reintroduced

**Consequence for `requirement_coverage` in scoring:**
- `covered_requirement_elements` identifies the exact substantive requirement fragments supported by candidate evidence; it is evidence metadata, not a score chosen by the LLM.
- `role_defining` and `role_defining_group` identify specialist clusters that distinguish the actual role from routine occupation duties. Numeric caps/thresholds remain server-owned in `scoring_rules.json`.
- `fit_scoring.py` is a consumer only - it reads stored LLM output from the record, never calls the LLM
- `requirement_coverage` entries are typed. Use `requirement_type="capability"` for skill coverage and `requirement_type="eligibility"` for explicit facts like clearances or work rights.
- Capability rows also carry `requirement_kind` (`professional_capability` | `behavioural_expectation`, JH-298). Rows the LLM tags `behavioural_expectation` (generic conduct / disposition wording — "works autonomously", "attention to detail", "willingness to embrace AI") are partitioned out into the record's `requirement_coverage_behavioural` field by `normalize_llm_review_payload` and never appear in `requirement_coverage`. They therefore add **zero** to the Requirement Fit numerator and denominator, are absent from `requirement_fit_audit_rows`, and never seed convergence. Observable professional interpersonal work (stakeholder facilitation, negotiation, workshop facilitation) stays `professional_capability` and scores. Do not re-merge the two lists in `fit_scoring.py`.
- **Fail closed on `requirement_kind` (JH-298 correction).** A capability row with a missing, empty, or unrecognised `requirement_kind` is **not** defaulted to `professional_capability`. It becomes `unclassified`: forced `status = not_assessed`, partitioned by `partition_unclassified_requirement_coverage` into the record's `requirement_coverage_unclassified` field, and — exactly like a behavioural row — non-scoring, non-gap, non-learning, non-actionable until a fresh review classifies it. Scoring credits a row **only** when `requirement_type == "capability"` AND `requirement_kind == "professional_capability"`; `fit_scoring._capability_row_excluded_by_kind` and the `derive_fit_review_grade` loop both skip any other kind that leaks into `requirement_coverage` (no numerator, no denominator). Contract versions: `REQUIREMENT_COVERAGE_CONTRACT_VERSION` = 5 (`record_schema.py`), `FIT_REVIEW_CACHE_CONTRACT_VERSION` = 7 (`llm_gate.py`) — pre-correction coverage / cache is re-reviewed, not migrated.
- `requirement_coverage` entries with `supported`/`partially_supported` status that lack the matching profile fact name are skipped (logged at WARNING)
- Convergence bonus uses `requirement_coverage` supported count — `min_positive_matches` from `scoring_rules.convergence`
- The learning pipeline handles signal routing via `build_ad_learning_signals` and the learning-only LLM call - do not route from `fit_scoring.py`

**`derive_fit_review_grade` contract (in `llm_gate.py`):**
- `supported` = 1.0, `partially_supported` = 0.5, `not_shown`/`mismatch` = 0.0
- Any `mismatch` present + zero positive coverage → MISMATCH
- Any `mismatch` present + some positive coverage → WEAK (hard cap, cannot be SOLID/STRONG/EXCELLENT)
- No mismatch: EXCELLENT (all supported, ≥3 reqs), STRONG (≥80% support, ≤1 partial), SOLID (≥50% support), WEAK (some support), POOR (no support)
- Grade derivation tests live in `tests/test_llm_gate.py` (section: derive_fit_review_grade contract)

## Occupation alignment scoring

`final_score = requirement_fit + occupation_adjustment`, clamped 0–100.

- The LLM classifies `occupation_alignment` as one of `same`/`adjacent`/`different` (title + dominant duties vs. candidate target roles). It never sets the numeric penalty.
- The adjustment is looked up server-side from `scoring_rules.json` `occupation_alignment` (`same=0`, `adjacent=-10`, `different=-20`) via `_occupation_alignment_adjustments()` in `fit_scoring.py`.
- Missing or invalid values degrade to the `LLM_INVALID_OCCUPATION_ALIGNMENT` sentinel (`_normalize_llm_occupation_alignment` in `llm_gate.py`) — shown as "Needs review (not classified)" with a zero adjustment. This never blocks a KEEP or rejects the job; see `has_complete_llm_keep_data()` in `llm_review_state.py`, which deliberately does not require `occupation_alignment`.
- `occupation_alignment_diagnostics()` / `format_occupation_alignment_diagnostics_block()` in `fit_scoring.py` are the single source for alignment, reason, adjustment, and final-calculation text shown in `server.log` (logged from `_freeze_fit_score_fields()` in `job_review_pipeline.py`) and in the "Debug: LLM fit review" panel (`workspace_renderer.py`).
