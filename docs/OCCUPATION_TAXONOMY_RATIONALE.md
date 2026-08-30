# Occupation Taxonomy Rationale

## Purpose

Job Hunter uses a local O*NET occupation taxonomy as an early, low-cost signal for whether a scraped job title is likely inside or outside the candidate's target role family.

The taxonomy is not the final fit decision. It is a pre-LLM eligibility signal used to avoid wasting LLM calls on obviously unrelated occupations while preserving ambiguous jobs for review.

## Current design principle

A title classification can be:

- `near` — title maps to a target occupation code.
- `far` — title maps to an occupation code outside the candidate's target occupation set.
- `uncertain` — the taxonomy cannot safely decide.

Only clear `far` results should be used as deterministic pre-LLM rejection signals. Ambiguous or weak evidence should not become a hidden hard gate.

## Why ambiguous embedded phrases must not be ignored

Some job titles do not map one-to-one to a single occupation. The U.S. SOC/DMTF guidance gives examples where a title can refer to different occupation types, and recommends examining detailed occupation definitions when titles are not one-to-one.

This means Job Hunter should not treat multi-code O*NET matches as if there was no match at all.

A better model is candidate generation plus disambiguation:

1. Extract possible occupation candidates from the title.
2. Compare candidate occupation codes against the candidate's target occupation codes.
3. Return `far` when every candidate code is outside the target set.
4. Return `uncertain` when candidates are mixed, no target context exists, or the evidence is genuinely ambiguous.

This follows the same general principle used in entity linking: candidate generation produces possible knowledge-base matches, then disambiguation decides which candidate, if any, should be selected.

## Example: Senior Tax Accountant

For a Business Analyst / Technical Business Analyst profile, `Senior Tax Accountant` should not be passed to the LLM merely because `accountant` maps to multiple O*NET occupation codes.

If all matched accountant-related codes are outside the candidate's target occupation set, the correct classification is `far`.

That is different from a user-specific blacklist. The system should not require every user to manually block obvious unrelated professions such as accountant, nurse, chef, mechanic, or property manager. The taxonomy should classify them as far when the evidence is strong enough.

## Example: Transformation Lead

`Transformation Lead` may be genuinely ambiguous. It can be close to business analysis, change delivery, product delivery, or project leadership depending on description context.

If the taxonomy cannot safely map it to only outside-target occupations, it should remain `uncertain` and continue to the LLM or scoring pipeline.

## Decision rule

When an embedded title phrase maps to multiple O*NET codes:

- If target occupation context is missing, return `uncertain`.
- If all candidate codes are outside the target occupation code set, return `far`.
- If at least one candidate code is inside the target set and others are outside, return `uncertain` unless a stronger phrase match resolves it.
- If all candidate codes are inside the target set, return `near`.

This avoids both wasteful LLM calls and broad false-negative gates.

## Title-only LLM fallback before detail fetch

O*NET is the first low-cost occupation signal, but `near` and `uncertain` are not automatic permission to open the full job advertisement. For titles that still need semantic judgment, the pre-detail pipeline calls `llm_gate.llm_judge_title()` with the title and the candidate's target/secondary role directions.

- `no_match` rejects as `LLM_TITLE_NOT_TARGET` before the browser detail fetch.
- `match` and `uncertain` continue to the normal detail-review path.
- A genuine provider or structured-output failure fails open to detail review rather than becoming a false-negative rejection.

The title judgment is a typed structured-output boundary. The current OpenAI adapter uses `responses.parse()` with a Pydantic response model. Do not replace this with raw JSON parsing or add markdown-fence/regex fallback parsers: a formatting wrapper must not turn a valid semantic `no_match` into an unavailable result and cause an unnecessary browser/LLM review.

## What not to do

Do not fix this by adding generic blocked-title keywords to every user profile.

User `reject_title_rules` remain valid for personal preferences, but they are not the correct product-level fix for taxonomy matching failures.

Do not hardcode rejected occupation dictionaries in Python.

If new taxonomy behaviour requires rule data, put that data in approved knowledge/config files and load it through the taxonomy engine.

## Sources

- U.S. SOC / Direct Match Title File guidance, via BLS/SOC material: job titles may not always match one-to-one to occupations; example titles can refer to different occupation types and require occupation definitions/context.
- Entity linking / named-entity disambiguation literature: systems commonly separate candidate generation from disambiguation rather than discarding ambiguous candidates.
- O*NET / SOC are classification references, not perfect truth. Job Hunter uses them as explainable, low-cost evidence, not as the only fit judge.

## Related project rules

- `.skills/job-filtering/SKILL.md`: deterministic filters must be explicit, approved, and visible; uncertain signals should not become hidden false-negative gates.
- `.skills/no-hardcoding/SKILL.md`: business judgement, mappings, thresholds, source rules, and reusable knowledge must not be hidden in Python feature code.
- `docs/CONFIG_AND_RULES_GOVERNANCE.md`: Python is the engine; knowledge files hold rule libraries; Admin/global settings hold operational knobs; tests enforce architecture.

## Full Job Titles data and target-query safety

Runtime classification uses the current full O*NET **Job Titles** dataset rather than the limited legacy OccupationalListings title list. This gives the deterministic gate broad coverage for modern titles such as `Cloud Engineer` without maintaining a product-specific title dictionary.

The full dataset is intentionally many-to-many: one real-world title can map to several occupations. That is useful for classifying scraped jobs but unsafe if every mapping is automatically treated as a candidate target occupation.

`target_occupation_queries` therefore resolve conservatively:

1. exact O*NET occupation titles are trusted;
2. exact Job Titles marked by O*NET as preferred in Sample of Reported Titles / My Next Move are trusted;
3. otherwise an exact Job Title is trusted only when it resolves to one occupation code;
4. ambiguous unpreferred Job Titles do not widen the candidate's target occupation family.

This keeps the authoritative data source broad while preserving the product rule that uncertainty must not become a hidden false-negative gate.

## Exact and embedded multi-code titles

The same candidate-code rule applies whether an O*NET phrase matches the whole job title or appears inside a longer title:

- all candidate codes outside the target set -> `far`;
- all candidate codes inside the target set -> `near`;
- mixed inside/outside codes -> `uncertain`;
- no target occupation context -> `uncertain`.

For example, current O*NET maps `Cloud Engineer` to multiple technical occupations. For a BA / Systems Analyst profile, if all of those codes are outside the target set, both `Cloud Engineer` and `Senior Cloud Engineer` can be rejected cheaply without a title-LLM call.

The existing protection against broad one-word embedded aliases remains: a generic alternate/job title such as `Engineer` is not enough by itself to classify a longer title.

## Data freshness and cache versioning

O*NET-SOC taxonomy version and O*NET database release are different identities. The generated index records:

- `taxonomy_version` (for example O*NET-SOC 2019);
- `database_release` (for example 30.3);
- `dataset_fingerprint` (SHA-256 of the generated title index);
- the official source URL.

The runtime classification cache requires the current taxonomy version, database release and dataset fingerprint, in addition to the candidate-profile hash. A refresh therefore cannot silently reuse a decision made from older title data.

`LOOKUP_MATCHER_VERSION` remains a separate code-algorithm guardrail and is included in the profile hash. Material classification-logic changes must bump it.

The canonical maintenance commands are:

```bash
uv run python -m job_hunter_agent.onet_taxonomy_refresh --check
uv run python -m job_hunter_agent.onet_taxonomy_refresh --update
```

The weekly GitHub Actions refresh checks the official O*NET database metadata, rebuilds and validates only when necessary, and opens/updates a pull request for review. Runtime searches never perform network O*NET lookups.
