# Requirement Decomposition Rationale

Why the fit-review `requirement_coverage` / `eligibility_requirements` contract carries an
explicit `decomposition` block, and how AND / OR semantics and the fit-review LLM's
bounded capability judgement are preserved without ever letting the LLM emit learning
records.

Owning skills: `scoring-ranking` (consumes frozen coverage), `signal-registry`
(deterministic pending signals only), `no-hardcoding` (no keyword interpretation),
`dashboard-ui` (card render). This doc is a reference, not an operating rule.

---

## Problem

The previous contract described a compound / disjunctive requirement with three loose
fields on the coverage row:

- `named_alternatives: [...]` — the specific items an "A or B or C" clause offered.
- `canonical_fact_resolved: bool` — the LLM's confidence that `canonical_requirement`
  named one genuine reusable concept.
- `classification_reviewable: bool` — the LLM's confidence that the whole requirement
  could take one reusable requirement type.

Two structural failures followed:

1. **A disjunctive requirement was a dead end.** `"Microsoft Purview or BigID"` became one
   row with `named_alternatives = ["Microsoft Purview", "BigID"]`, empty
   `canonical_requirement`, and `profile_action_allowed = false`. If the candidate held
   neither, the card could not offer them a way to record *either* concept, and the row
   could not state that *either* concept would satisfy the job.
2. **AND vs OR was implicit.** Whether a multi-concept row meant "all of these" or "any of
   these" had to be inferred from `named_alternatives` being populated. Consumers guessed.

## Contract

Every `requirement_coverage` item and every `eligibility_requirements` item carries a
`decomposition` block. It is **the** canonical structure for compound / disjunctive
requirements; `named_alternatives`, row-level `canonical_fact_resolved`, and
`classification_reviewable` are removed from the schema, the prompt, the normalizer, and
every consumer and test.

```jsonc
"decomposition": {
  "operator": "single" | "and" | "or",
  "elements": [
    {
      "text": "<atomic sub-requirement phrase, from the ad>",
      "capability_judgement": "capability" | "uncertain" | "non_capability",
      "canonical_concept": "<reusable profile concept for this element, or ''>",
      "canonical_fact_resolved": true | false,
      "status": "supported" | "partially_supported" | "not_shown" | "mismatch",
      "matched_candidate_fact": "<profile fact matched for this element, or ''>"
    }
  ]
}
```

### `operator`

| value    | meaning                          | `elements` | row `canonical_requirement` | row `profile_action_allowed` | row `status` rollup |
|----------|----------------------------------|------------|-----------------------------|------------------------------|---------------------|
| `single` | one atomic requirement           | exactly 1  | `elements[0].canonical_concept` | derived from `elements[0]` | LLM row status, then the existing deterministic guards |
| `and`    | the ad requires **all** concepts | 2+         | `""`                        | `False`                      | LLM row status, then lowered (never raised) to the **weakest** element status |
| `or`     | **any** listed concept satisfies | 2+         | `""`                        | `False`                      | the **strongest** element status |

`and` / `or` rows never carry a single `canonical_requirement`, so `resolve_custom_blocker`,
`list_custom_blocker_candidates`, and `compute_profile_gaps` — all of which already require
`profile_action_allowed is True` and a non-empty `canonical_requirement` — structurally
cannot resolve a free-text blocker or a profile gap to one branch of a disjunctive or one
half of a conjunctive mandatory requirement. This is the explicit
`resolve_custom_blocker must never resolve to one single OR branch` rule, enforced by
construction rather than by a check.

### Row-level `requirement_type` is retained

`requirement_type` (`capability` / `eligibility` / `qualification`) stays a **row-level**
field set by the LLM and validated deterministically by `classify_requirement_type()`
exactly as before. `elements[]` decompose only the capability / concept dimension.
`eligibility` and `qualification` rows are always `operator: "single"` with one element.
The eligibility gate, grade derivation, hard-reject check, eligibility diagnostics, and
`_atomicize_known_eligibility_rows` continue to read the row-level `requirement_type` and
row-level `status` and need no per-element rework.

### Row-level `requirement_kind` — behavioural expectations vs professional capabilities (JH-298)

A second row-level axis on **`capability` rows only**, set by the fit-review LLM:

- **`professional_capability`** — an observable skill / activity / domain / tool /
  deliverable that belongs in the candidate profile and is scored. Interpersonal
  activities performed as professional work (stakeholder facilitation, negotiation,
  workshop facilitation, requirements elicitation, team leadership) are
  `professional_capability`.
- **`behavioural_expectation`** — generic personal-conduct / disposition / mindset
  wording: "works autonomously", "excellent communication skills" (as a trait),
  "adaptable", "attention to detail", "proactive", "curious", "willingness to
  embrace AI". These are real employer signals but are **not** capabilities the
  candidate profile tracks or that scoring should reward or penalise.

`eligibility` and `qualification` rows never carry `requirement_kind` (empty string).

A missing, empty, or unrecognised `requirement_kind` on a capability row **fails
closed to `unclassified`** — it is never defaulted to `professional_capability`.
An `unclassified` row is frozen exactly like a behavioural row: `status` forced to
`not_assessed`, `profile_action_allowed = False`, an `unclassified_requirement_kind:
true` marker, all matched-fact / canonical / element action fields cleared, and a
`requirement_kind_unclassified` requirement-coverage warning recorded.
`partition_unclassified_requirement_coverage()` moves it into the record field
`requirement_coverage_unclassified`, frozen next to `requirement_coverage`, so it
is structurally excluded from grade, scoring, profile gaps / custom blockers, and
learning until a fresh review classifies it. It is kept verbatim there for
inspection but gets no card block of its own — `unclassified` is a transient
fail-closed anomaly, not a display category like `behavioural_expectation`. The
classification itself is trusted from the LLM — it is semantic interpretation, not
a keyword gate — and only the token is structurally validated.

**Scoring requires an explicit professional classification.** A row is scored only
when `requirement_type == "capability"` **and** `requirement_kind ==
"professional_capability"`. Trusting `requirement_type` alone is not enough: a row
with a bad or missing kind that somehow reached `requirement_coverage` is skipped
by `fit_scoring` and by `derive_fit_review_grade` (it contributes to neither the
numerator nor the denominator).

**Decompose before classifying.** A mixed sentence is split into atoms first, then
each atom is classified independently. "work through ambiguity, manage complexity
and deliver projects" → "work through ambiguity" and "manage complexity" are
`behavioural_expectation`; "deliver projects" stays `professional_capability` and
scores.

**Structural exclusion by partition.** `normalize_llm_requirement_coverage` emits a
behavioural row with `status` forced to the display-only value `not_assessed`
(deliberately **outside** `_ALLOWED_REQUIREMENT_COVERAGE_STATUSES` so a leaked row
can never satisfy a scored-status check), `profile_action_allowed = False`, and a
`behavioural_expectation: true` marker, with all matched-fact / canonical / element
action fields cleared. `partition_behavioural_requirement_coverage()` then moves
those rows into the record field `requirement_coverage_behavioural`, frozen next to
`requirement_coverage`. Because scoring (`fit_scoring`), profile gaps / custom
blockers (`profile_gaps`), and learning (`source_learning`) all read only
`requirement_coverage`, behavioural rows contribute **zero** to the Requirement Fit
numerator and denominator, never become a gap or blocker candidate, and never mint
a pending `capability_concept` signal — guaranteed by construction, not by a
per-consumer skip flag. The renderer reads `requirement_coverage_behavioural`
separately and shows it in a read-only "Working style / behavioural expectations"
group with a `not_assessed` label and no action buttons.

**Contract-version bump.** The JH-298 split took
`REQUIREMENT_COVERAGE_CONTRACT_VERSION` → 4 and `FIT_REVIEW_CACHE_CONTRACT_VERSION`
→ 6. The JH-298 correction (fail-closed `unclassified` instead of a
`professional_capability` default, plus the explicit scoring predicate) takes them
→ **5** and → **7**: v4 coverage may hold rows scored under the old default, so it
is re-reviewed, not migrated. Kept-job coverage snapshots and cached fit-review
payloads produced before the current versions are unsafe to reuse; the history
reuse guard forces a fresh fit review (the AC "fails closed / re-reviewed, never
guessed" mechanism). No migration shim — stale dev caches are disposable.

### Evidence integrity for positive coverage (JH-299)

A `supported` / `partially_supported` `capability` row must trace to specific
candidate evidence that entails the **same** professional concept. Three
structural guards in `normalize_llm_requirement_coverage` enforce this; none of
them do semantic interpretation — that stays in the managed prompt or fails
closed.

- **A held role / job title is not capability proof.** A title the candidate has
  held (including a `role_experience` family) proves only explicit role-family and
  duration facts. It never resolves to a `capability_name`, so the existing
  missing-`capability_name` guard already forces such a positive row to
  `not_shown` and clears the match. The managed prompt now states the rule
  explicitly so the model does not put a bare title in `matched_candidate_fact`.
- **`_has_meaningful_requirement_evidence` requires a traceable same-concept
  link.** A single shared content token via free-text `profile_support` is no
  longer sufficient. A positive row survives only when the resolved candidate
  concept is itself named in the requirement wording, **or** the whole requirement
  concept is present in the candidate evidence, **or** requirement and evidence
  share **at least two** substantive tokens. One shared generic word ("AI",
  "data", "systems", a title token) is transferable framing, not proof. The
  digit-token specificity rule is
  unchanged: `SAP` still cannot prove `SAP S/4HANA` without evidence of the
  versioned platform. On failure the call site forces `not_shown`, clears the
  match, and records `generic_transferable_capability_not_requirement_evidence`.
- **Non-positive rows carry no positive-looking evidence.** Immediately before a
  row is appended, any `capability` / `qualification` row whose final status is
  not `supported` / `partially_supported` has `matched_candidate_fact`,
  `capability_name`, `qualification_name`, `profile_support`,
  `covered_requirement_elements`, `match_source`, every
  `decomposition.elements[*].matched_candidate_fact`, and any
  `experience_components[*]` support neutralised. `canonical_requirement` /
  `requirement` are kept so profile-gap and renderer consumers still have the
  concept. `eligibility` rows are exempt: their `eligibility_name` /
  `matched_candidate_fact` are the canonical gate identity owned by
  `_atomicize_known_eligibility_rows`, not a "candidate has it" claim.

Behavioural (`not_assessed`) rows are cleared upstream by the JH-298 partition and
never reach these guards.

**Contract-version bump.** `REQUIREMENT_COVERAGE_CONTRACT_VERSION` → 6 and
`FIT_REVIEW_CACHE_CONTRACT_VERSION` → 8. Persisted coverage and cached fit-review
payloads from before JH-299 can hold over-stated matches, so they are re-reviewed,
not migrated — the same fail-closed mechanism as JH-298. No migration shim.

### `capability_judgement` (per element)

The fit-review LLM's bounded interpretation of whether the element names a reusable
capability concept. This is interpretation, **not** a learning field: the LLM never names a
signal category and never emits a learning record. Pending Signals are created afterward by
deterministic code (`source_learning.build_ad_learning_signals`).

- **`capability`** — a reusable capability / qualification concept. Normal behaviour.
- **`uncertain`** — the LLM is not confident this is a clean reusable concept. The row
  stays visible and scores normally on its `status`. `build_ad_learning_signals` creates a
  pending `capability_concept` Signal carrying the element `text` and the row
  `matched_job_text` as evidence. Pending only — not auto-promoted, not runtime-active.
- **`non_capability`** — the element is not a reusable capability concept (a bare
  responsibility clause, a restated sentence fragment, ad boilerplate).
  - **Optional** (`importance` != `mandatory`): the row is moved out of
    `requirement_coverage` into the record field `requirement_coverage_hidden`. It never
    scores, never grades, never renders on the card, but is retained verbatim for later
    analysis. (This replaces the previous silent drop of non-mandatory invalid rows.)
  - **Mandatory**: never disappears. If the element supplies a `canonical_concept` with
    `canonical_fact_resolved: true`, that is accepted as the smallest defensible reusable
    capability concept and the row behaves as a normal `single` capability row. Otherwise
    the row stays visible as an unresolved mandatory requirement (`status` forced
    `not_shown`, `profile_action_allowed = False`) **and** `build_ad_learning_signals`
    creates a pending `capability_concept` Signal. No second LLM call is made — the
    derivation is deterministic or it stays visible-and-pending.
  - **Mandatory AND / OR row, every branch `non_capability` and unresolved**: the same
    guarantee applies to the compound row itself. It is never hidden, never
    profile-actionable, and no single branch is minted into a standalone capability.
    `mandatory_non_capability_unresolved` is set on the compound row, and
    `build_ad_learning_signals` emits **exactly one** pending `capability_concept` Signal
    whose `signal` text joins every branch label with the relationship word (` or ` /
    ` and `) and whose `original_texts` carry each branch `text` plus the row
    `matched_job_text` — preserving all branches and the AND / OR relationship in one
    candidate rather than one misleading candidate per branch.

### Deterministic classification-review path is unchanged

`classify_requirement_type()` still returns `uncertain` when an ad clause carries **both**
an eligibility term and an explicit years / months duration signal — a genuine
capability-vs-eligibility conflict it must not guess. Such a row still becomes a pending
`requirement_classification_review` signal via
`job_review_pipeline._build_requirement_classification_review_signals`. The only change:
that path no longer gates on the removed LLM `classification_reviewable` flag, so a
deterministic conflict now always surfaces for human classification. `capability_judgement`
is a separate axis ("is this a reusable capability concept at all") and does not feed the
classification-review path.

### Per-element computed field

Normalization adds `element_profile_action_allowed` to each element:

```
element_profile_action_allowed =
    bool(canonical_concept)
    and canonical_fact_resolved
    and capability_judgement == "capability"
```

For `operator: "or"` the card uses this to offer one primary **Add** action for the
*closest* branch (the element with the best `status`; first element on a tie) while still
rendering every branch's `canonical_concept` in an "either **X** or **Y**" line, so the
requirement is never shown as if only one branch existed. For `operator: "single"` the
row-level `profile_action_allowed` remains authoritative and the element flag simply
mirrors it.

---

## Worked example — "Experience with Microsoft Purview or BigID"

Mandatory requirement, candidate holds neither.

```jsonc
{
  "requirement": "Experience with Microsoft Purview or BigID",
  "importance": "mandatory",
  "requirement_type": "capability",
  "canonical_requirement": "",          // OR row: no single reusable concept
  "profile_action_allowed": false,      // never resolve a blocker/gap to one branch
  "status": "not_shown",                // strongest of {not_shown, not_shown}
  "matched_candidate_fact": "",
  "decomposition": {
    "operator": "or",
    "elements": [
      {
        "text": "Microsoft Purview",
        "capability_judgement": "capability",
        "canonical_concept": "Microsoft Purview",
        "canonical_fact_resolved": true,
        "status": "not_shown",
        "matched_candidate_fact": "",
        "element_profile_action_allowed": true
      },
      {
        "text": "BigID",
        "capability_judgement": "capability",
        "canonical_concept": "BigID",
        "canonical_fact_resolved": true,
        "status": "not_shown",
        "matched_candidate_fact": "",
        "element_profile_action_allowed": true
      }
    ]
  }
}
```

Card behaviour: the row renders under **Needs attention** with the line
"Either **Microsoft Purview** or **BigID** satisfies this" and **one** primary
"Add Microsoft Purview" action (first branch, tie on status). "BigID" is still named and is
reachable from the row's expanded detail. Both atomic concepts and the OR relationship are
retained on the frozen record; nothing is discarded. If the candidate later records BigID,
re-review flips `elements[1].status` and the row rolls up to `supported`.

`resolve_custom_blocker("Microsoft Purview", coverage)` returns `no_match` for this row —
the row is not `profile_action_allowed` and has no row `canonical_requirement`, so a
free-text "Not For Me" blocker cannot be persisted as though Purview alone were the
mandatory requirement.

---

## Affected consumers

| Area | Change |
|------|--------|
| `llm_gate.py` schema | `_LLMRequirementCoverageItem`: drop `named_alternatives`, `canonical_fact_resolved`, `classification_reviewable`; add `decomposition: _LLMRequirementDecomposition` (`_LLMRequirementDecomposition` / `_LLMRequirementElement`). |
| `llm_gate.normalize_llm_requirement_coverage` | Parse + validate `decomposition`; roll row `status` (`and` weakest-only-lower, `or` strongest); derive row `canonical_requirement` / `profile_action_allowed` from the `single` element; add `element_profile_action_allowed`; tag optional `non_capability` rows `hidden_reason="optional_non_capability"`; resolve or hold-and-flag mandatory `non_capability` (single rows, and compound `and` / `or` rows whose every branch is an unresolved `non_capability`). |
| `llm_gate.normalize_llm_review_payload` + non-review path | Partition normalized rows into visible `requirement_coverage` and `requirement_coverage_hidden`; grade / gate / freeze run on the visible partition only. |
| `llm_protocol.py` | Rewrite `LLM_FIT_REVIEW_PROMPT_SHAPE` / `LLM_FIT_REVIEW_DEBUG_PROMPT_SHAPE` to the `decomposition` shape. `LLM_UNCERTAIN_COVERAGE_REQUIREMENT_TYPE` retained (deterministic path only). |
| `data/knowledge/llm_requirement_coverage_defaults.json` | Rewrite the named-alternatives / `canonical_fact_resolved` / `classification_reviewable` guidance lines as `decomposition` guidance. Bump `version`. |
| `job_review_pipeline.py` | `_build_requirement_classification_review_signals`: drop the `classification_reviewable` gate. Freeze `requirement_coverage_hidden` onto kept records. |
| `source_learning.build_ad_learning_signals` | Emit pending `capability_concept` Signals from `capability_judgement == "uncertain"` elements and from unresolved mandatory `non_capability` elements. A flagged compound `and` / `or` row yields **one** combined Signal joining every branch label with the relationship word, not one per branch. |
| `fit_scoring.py` | No rollup change (row-level `status` / `requirement_type` survive). Hidden rows are already absent from `requirement_coverage`. |
| `workspace_renderer.py` | Per-element rendering for `and` / `or` rows; OR-group "either X or Y" line + one primary Add for the closest branch; optional `non_capability` rows are already absent. |
| `profile_gaps.py` | No logic change — `and` / `or` exclusion is structural. Comment added noting the OR-branch guarantee. |
| `record_schema.py` | Add `RECORD_REQUIREMENT_COVERAGE_HIDDEN_KEY`; bump `REQUIREMENT_COVERAGE_CONTRACT_VERSION`. |
| `.agents/skills/signal-registry/SKILL.md` | Note that bounded requirement-interpretation fields are allowed on the fit-review schema; they are not learning fields; pending Signals stay deterministic-only. |

## Regression tests

- `single` capability row: `canonical_concept` resolved and absent from profile →
  `compute_profile_gaps` returns it with the exact concept; present in profile → not
  returned; adjacent `matched_candidate_fact` alone is never credited as the exact concept.
- `or` row, neither branch in profile → row `status = not_shown`,
  `profile_action_allowed = false`, `canonical_requirement = ""`, both branch concepts
  retained, `element_profile_action_allowed` true on each.
- `or` row, one branch in profile → row rolls up `supported`.
- **OR UI still communicates the full requirement when only one primary action is shown**:
  the rendered card names every branch concept and states "either / or", not just the
  primary branch.
- `resolve_custom_blocker` / `list_custom_blocker_candidates` never return an `or` (or
  `and`) branch as a resolved mandatory blocker.
- `and` row where one element is `not_shown` → row `status` cannot exceed `not_shown` even
  if the LLM returned `supported`.
- `capability_judgement == "uncertain"` element → pending `capability_concept` Signal with
  original ad evidence; row still scores on its `status`.
- Optional `non_capability` row → absent from `requirement_coverage`, present in
  `requirement_coverage_hidden`; does not affect grade or score.
- Mandatory `non_capability` row with a resolved `canonical_concept` → behaves as a normal
  actionable `single` capability row.
- Mandatory `non_capability` row without a safe concept → stays visible (`not_shown`,
  not actionable) **and** a pending `capability_concept` Signal is created.
- Mandatory `or` (or `and`) row where every branch is an unresolved `non_capability` →
  the whole row stays visible and non-actionable, is never surfaced as a single-concept
  gap or blocker, and produces **exactly one** pending `capability_concept` Signal that
  joins all branch labels with the relationship word and keeps every branch `text` plus
  the row `matched_job_text` as evidence — never one candidate per branch.
- Deterministic `classify_requirement_type` conflict (eligibility term + duration) → still
  a pending `requirement_classification_review` signal, with no `classification_reviewable`
  field present anywhere.
- Requirement-group render order stays Needs attention → Partial matches → Matched.
