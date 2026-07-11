# Fit Score Rationale

Private reference doc. Not committed to the repo.

Last checked against code: 2026-06-08.

---

## What the score is

The fit score is a **role-fit ranking signal**, not a qualification percentage.

A score of 57 does **not** mean the candidate is 57% qualified. It means the job is ranked at that level by the current scoring rules, grade band, preference signals, and blockers.

The system answers:

> Which jobs should be reviewed first, which are stretches, and which should be pushed down or rejected?

It does **not** answer:

> Is the candidate objectively qualified for this job?

---

## Current implemented model

The current model is **band-anchored scoring**.

The review grade defines the allowed score band. Other signals move the job inside that band. Hard blockers are applied after the band clamp and can force the score near zero.

The scoring rules are loaded from:

```text
data/knowledge/scoring_rules.json
```

The main scoring consumer is:

```text
job_hunter_agent/fit_scoring.py
```

The requirement-coverage grade derivation is in:

```text
job_hunter_agent/llm_gate.py
```

---

## Process flow overview

This section is the high-level process map for the scoring pipeline. Treat each referenced module or doc as a subprocess owner, not as duplicate instructions to be reimplemented here.

Primary visual diagram:

```text
docs/diagrams/scoring_process_flow.mmd
```

Openable render:

```text
docs/diagrams/scoring_process_flow.html
```

Inline renderable copy:

```mermaid
flowchart TD
    A((Start: Job found)) --> B[Scraper captures job record]
    B --> C[Normalise source fields<br/>title, company, location, salary, work mode, description]
    C --> D{Enough basic data<br/>to assess?}
    D -- No --> D1[Mark incomplete / low trust<br/>do not invent missing data]
    D1 --> Z1((End: Needs review or skipped))
    D -- Yes --> E[Run deterministic pre-LLM checks]
    E --> F{Approved hard blocker?}
    F -- Yes --> F1[Reject before LLM<br/>record blocker reason]
    F1 --> Z2((End: Rejected))
    F -- No --> G{O*NET title / occupation taxonomy<br/>clearly outside target?}
    G -- Yes --> G1[Reject before LLM<br/>title or taxonomy reason]
    G1 --> Z2
    G -- No / uncertain --> H[Prepare fit review input<br/>structured metadata + fit_source_text]
    H --> I{Safe deterministic review<br/>available?}
    I -- Yes --> J[Create deterministic review outcome<br/>reject or keep candidate hint]
    I -- No --> K[Send to LLM fit review]
    K --> L[Extract requirements<br/>and map to candidate capabilities]
    J --> L
    L --> M{Requirement coverage usable?}
    M -- No --> M1[Use model grade fallback<br/>flag coverage missing]
    M -- Yes --> N[Derive grade from coverage]
    M1 --> O[Build frozen score breakdown]
    N --> O
    O --> P[Apply grade band clamp<br/>score stays inside grade band]
    P --> Q{Hard blockers after review?}
    Q -- Yes --> Q1[Apply hard blocker penalty<br/>force score near zero]
    Q -- No --> R[Store frozen score + explanation]
    Q1 --> R
    R --> S[Render recency and history signals<br/>outside the fit score]
    S --> T[Show ranked job to user<br/>with explanation]
    T --> U{User action}
    U -- Apply / save --> U1[Record positive action]
    U -- Skip / not for me --> U2[Record rejection feedback]
    U -- Needs correction --> U3[Improve profile / rules / backlog]
    U1 --> V[Learning signal]
    U2 --> V
    U3 --> V
    V --> W((End: Improves future runs))
```

### Process stages

| Stage | Input | Owner / subprocess | Output | Decision point |
|---|---|---|---|---|
| Source normalisation | Raw scraper fields | `source_connector.py`, scraper modules, source docs | Normalised job record | Missing or low-trust source fields may reduce confidence. |
| Title and occupation filtering | Job title, profile target roles, target occupation queries | `filters.py`, `occupation_taxonomy.py`, `docs/OCCUPATION_TAXONOMY_RATIONALE.md` | Title reason, O*NET near/far/uncertain signal | Approved hard blockers may stop the job before LLM. Uncertain signals continue. |
| Description preparation | Full description, structured scraper metadata | `description_compactor.py`, `description_trust.py`, config/rules governance | `fit_source_text`, description trust metadata | Unsafe compaction is skipped explicitly; full description remains preserved. |
| Review outcome | Title/content signals and fit source text | `llm_gate.py`, `source_learning.py` deterministic shortcut | `llm_fit_grade`, requirement coverage, rationale fields | LLM call may be avoided only by explicit deterministic reject rules. Deterministic keep candidates still require full LLM requirement coverage before any final KEEP is saved. |
| Requirement coverage | Extracted job requirements, candidate capabilities | `llm_gate.py`, capability knowledge/profile modules | Supported / partially supported / not shown / mismatch coverage | Coverage drives grade when present. Unsupported capability claims are dropped. |
| Frozen scoring | Reviewed job record with `llm_fit_grade` | `fit_scoring.py`, `data/knowledge/scoring_rules.json` | Frozen score and score breakdown | Grade band clamps non-hard-block score. Hard blockers apply after clamp. |
| Display scoring | Frozen score | `fit_scoring.py`, UI consumers | Displayed score and ordering | Recency is handled separately from fit score and should not be treated as fit evidence. |
| Human review and learning | User keep/skip/apply/reject decisions | Review history, learning modules, backlog if needed | Future profile/rule improvements | Learning must not silently become hidden scoring logic. |

### Handover points

The main handover from filtering to scoring is the reviewed job record containing `llm_fit_grade`. If that grade is missing, scoring must stop rather than inventing a score.

The main handover from LLM review to scoring is `requirement_coverage`. Coverage is evidence for the grade; the score breakdown displays it for transparency but does not add a second independent capability bonus. A deterministic keep candidate is not complete until this coverage exists and the final reviewed record is saved from the LLM path.

The main handover from frozen scoring to the UI is the stored frozen score plus explanation entries. The user-facing fit explanation should come from `requirement_coverage` only. Recency remains part of the UI and history flow, but it is not new evidence that the candidate fits the job.

### End states

A job can end as pre-LLM rejected, LLM/deterministic rejected, kept for review, displayed lower due to weak fit or hard blockers, or improved later through user feedback. Only reviewed jobs with a valid grade and non-empty requirement coverage enter the normal scoring pipeline.

---

## Grade bands

The grade controls the non-hard-block score range.

| Grade | Base points | Band | Meaning |
|---|---:|---:|---|
| EXCELLENT | 78 | 88-100 | Exceptional alignment |
| STRONG | 52 | 68-87 | Strong fit |
| SOLID | 32 | 48-67 | Decent fit |
| WEAK | 18 | 28-47 | Limited alignment |
| POOR | 6 | 8-27 | Poor alignment |
| MISMATCH | 0 | 0-7 | Clear mismatch |

The score is first built from normal score entries. Then the grade band is applied:

- If the raw non-hard-block score is below the grade floor, a positive **Grade band floor** entry is added.
- If the raw non-hard-block score is above the grade ceiling, a negative **Grade band ceiling** entry is added.
- Hard block penalties are excluded from the band clamp.
- Final score is capped between 0 and 100.

The raw score breakdown behind this table is not shown on job cards outside debug mode. In debug mode it appears in the card's "Debug: LLM fit review" panel — see [Job Card Layout](USER_GUIDE.md#job-card-layout) in the user guide.

The normal-mode "Why this is a good fit" section should come from `requirement_coverage` only, and it should stay short. Debug mode may also show score calculation, matched text, capability mapping, and reviewed-signal evidence.

---

## Current scoring flow

### 1. Review state gate

A job cannot be scored unless `llm_fit_grade` is present.

If the job has not been reviewed, scoring raises an error instead of inventing a score.

### 2. Core fit entries

Core entries include:

| Signal | Current behaviour |
|---|---|
| Title direct match | Adds `title_direct` points, currently 15 before weighting. |
| Title secondary/potential match | Adds `title_secondary` points, currently 4 before weighting. |
| LLM / derived grade | Adds base grade points from `llm_grade_points`. |
| Requirement coverage | Displayed as transparency entries with value 0. |
| Description capture incomplete | Adds a negative entry, currently -8 before weighting. |

### 3. Context entries

Salary, location, freshness, Easy Apply / Quick Apply, viewed status, and action recommendations are still shown in the UI, but they are metadata, filter, sort, or check signals rather than fit evidence.

| Signal | Behaviour |
|---|---|
| Salary / rate | Shown as context and used for salary filtering / comparison. |
| Location | Shown as metadata and search context only. |
| Freshness | Used for recency and sorting, not proof of fit. |
| Easy Apply / Quick Apply | Shown as action metadata, not fit evidence. |
| Already viewed | Shown as history-aware display state. |
| Checks before applying | Shown as a review panel for missing requirements, red flags, salary issues, and similar pre-apply checks. |

### 5. Grade band clamp

The non-hard-block entries are summed and clamped to the current grade band.

There are two scoring variants:

| Function | Behaviour |
|---|---|
| `fit_score_breakdown_frozen` / `fit_score_frozen` | Stored at scrape/review time. Excludes freshness and viewed status. |
| `fit_score_and_breakdown_displayed` / `fit_score_displayed` | Display-time score. Starts from frozen score. Falls back to live scoring for old records without a frozen score. |

### 6. Hard blockers

Hard blockers are applied after the band clamp.

Each hard blocker currently adds a `hard_block_penalty` of -100.

This means a job can have a good grade but still be forced near zero if it has a hard blocker.

---

## Requirement coverage and grade derivation

`requirement_coverage` is the source of truth for capability support when LLM coverage is available.

Allowed coverage statuses:

| Status | Meaning |
|---|---|
| supported | Requirement directly supported by a known profile capability. Must include `capability_name`. |
| partially_supported | Partial or indirect support. Must include `capability_name`. |
| not_shown | No candidate evidence found. |
| mismatch | Explicit conflict. |

Coverage entries are shown in the score breakdown for transparency, but they do not add separate score points.

In this cleanup, the fit score is intentionally narrow: title match, LLM grade, requirement-coverage transparency, hard blockers, and grade-band calibration. The user-facing "Why this is a good fit" panel now uses requirement coverage only. Convenience or preference signals such as Easy Apply, freshness, viewed status, salary, and location are better handled as badges, filters, or sort signals, and approved-experience or subtitle detail stays in debug-mode transparency. Workspace run summaries report collection counts, not fit evidence.

Debug mode may still expose internal score calculation, matched source text, capability mapping, and reviewed-signal evidence for troubleshooting. That extra transparency is for investigation, not a second competing normal-mode fit explanation.

### Location scoring decision

Location is a weak preference signal rather than strong fit evidence in this cleanup.

- It stays visible as metadata and search context.
- It can still help with filtering, sorting, and badge-style cues.
- Future radius support should make the decision explicit rather than burying it inside fit scoring.

The grade is derived from coverage when coverage exists. The model's raw grade is used only as fallback when coverage is missing.

Current importance weights used by `derive_fit_review_grade`:

| Importance | Weight |
|---|---:|
| mandatory | 3.0 |
| strongly_preferred | 2.0 |
| preferred | 1.0 |
| nice_to_have | 0.25 |

Current derivation rules:

- `supported` contributes full weight.
- `partially_supported` contributes half weight.
- `not_shown` contributes zero but still counts against the maximum possible score.
- `mismatch` contributes zero and caps the grade at WEAK if there is any coverage.
- Missing coverage items from `job_requirements` are treated as uncovered preferred-weight items.
- If there are no covered items, the grade becomes MISMATCH when a mismatch exists, otherwise POOR.
- Full support across all requirements gives EXCELLENT only when there are at least 3 requirements; otherwise STRONG.
- Strong coverage ratio can produce STRONG.
- Moderate coverage ratio can produce SOLID.
- Low coverage produces WEAK.

Important limitation:

Mandatory `not_shown` lowers the weighted ratio but does not automatically reject the job. That is deliberate for now, because a missing profile capability may mean the candidate profile is incomplete rather than the candidate cannot do it.

### Missing CV evidence default

Default rule for new or incomplete profiles:

- if a capability, tool, certification, clearance, domain, or role duration is not present in the runtime profile, the system must not claim the candidate has it
- missing evidence is treated as `not_shown`, not as supported evidence
- missing evidence can lower requirement coverage and score
- missing evidence should not automatically become a hard rejection unless an approved hard-block rule applies
- when the missing item looks important, surface it as a visible gap or review signal so the user can improve the profile if the CV omitted real experience

This keeps the system strict without pretending the CV is perfect. The profile is the current evidence source, not an omniscient model of the candidate.

---

## Deterministic pre-LLM review shortcut

Some jobs can be decided before the LLM review.

The shortcut is implemented in:

```text
job_hunter_agent/source_learning.py
```

Function:

```text
deterministic_review_outcome
```

It uses:

- title reason
- count of strong fit highlights
- count of missing profile support items
- count of soft risk reasons
- thresholds from `deterministic_review_thresholds` in `scoring_rules.json`

Current outcomes:

| Rule | Outcome |
|---|---|
| Too many high risks and too few strong signals | REJECT / MISMATCH |
| Potential title plus high risk and weak signals | REJECT / POOR |
| OK title plus enough strong signals and no high risks | KEEP / STRONG |
| OK title plus enough strong signals, no high risks, and limited medium risks | KEEP / SOLID |

These rule-based outcomes still produce `llm_fit_grade` and can therefore be scored by the same scoring pipeline.

---

## Capability support rules

Capability support is not a free-text bonus bucket.

Current principle:

> Do not match whole job sentences directly to capabilities.

The LLM should extract job requirements, then map each requirement to candidate-side capabilities or evidence.

A supported or partially supported requirement must name a known `capability_name`. If the LLM returns support without a valid capability name, the coverage item is dropped during normalisation.

This prevents the system from treating a job sentence as proof of capability merely because words overlap.

---

## What is deliberately not counted as capability proof

These signals can help ranking but should not prove mandatory requirement fit:

- location
- salary/rate
- work mode
- work type / contract preference
- freshness
- viewed/not viewed status
- competitive-domain hints by themselves

They are useful for ordering jobs, not for proving the candidate meets the role.

---

## Reviewed signal registry

Reviewed signal decisions from `signal_registry.json` are intentionally excluded from direct scoring.

Approving a signal means:

> Learn how to classify or map this term next time.

It does not mean:

> Add points to every job mentioning this word.

Signals can later be promoted into normalised profile rules or capability mappings, but they do not directly add score points.

---

## Design basis

The model is an **auditable ranking model with configured rules and LLM-derived requirement coverage**.

Do not describe the current design as simply "heuristic scoring" without qualification. That wording is too broad and makes it sound like the system is mainly a pile of hardcoded guesses. The current direction is more specific:

- use the LLM to extract job requirements and requirement coverage
- derive the grade from structured coverage where available
- keep scoring values in managed config, not hidden code constants
- show requirement coverage as transparent evidence
- keep logistics/preferences separate from capability proof
- keep remaining rule-based shortcuts explicit, logged, and configurable

There are still heuristic elements, but they are now treated as **controlled calibration rules**, not as the core source of truth.

Remaining heuristic / calibration areas include:

| Area | Current status |
|---|---|
| Grade band values | Configured in `scoring_rules.json`; not empirically proven. |
| Preference weights | Managed/profile-side weights; affect ranking, not capability proof. |
| Deterministic shortcut thresholds | Configured under `deterministic_review_thresholds`; audit the shortcut trigger via `det_rule` and the final reviewed keep via `review_source` and `requirement_coverage`. |
| Convergence bonus | Explicit rule-based bonus; useful but still a calibration rule. |
| Freshness bonus | Ranking urgency only; not fit evidence. |

The model is grounded in:

- person-job fit theory: job requirements should be compared to candidate attributes
- multi-criteria decision analysis: heterogeneous signals can be combined when weights are explicit and auditable
- competency-based hiring: capability and evidence alignment are central
- recruiter screening behaviour: title and role alignment matter early
- practical job search workflow: freshness and logistics affect action priority, not capability fit

The specific point values are calibration choices, not empirically proven constants.

They should be calibrated over time against real outcomes such as:

- reviewed jobs
- jobs skipped manually
- applications submitted
- recruiter responses
- interviews
- false positives
- false rejections

---

## Recent removals / direction of travel

Recent scoring and matching work has been moving away from hidden hardcoded judgement and toward explicit, reviewable mechanisms.

Current direction:

| Old / risky pattern | Replacement direction |
|---|---|
| Whole job sentence matched directly to a capability | Extract requirement first, then map it to a known candidate capability. |
| Capability mentions adding independent score points | Requirement coverage drives grade; coverage entries are transparency-only in the score breakdown. |
| Broad "fit" claims based on preferences or logistics | Preferences move ranking only; they do not prove mandatory fit. |
| Location / approved-experience snippets in the fit summary | Keep them out of the normal fit explanation; show them as badges, filters, or debug-only detail instead. |
| Hidden hardcoded scoring budget | Band-anchored score controlled by `data/knowledge/scoring_rules.json`. |
| Hardcoded judgement buried in code | Move values to managed config / global settings where possible. |
| Signals directly boosting score | Reviewed signals inform future classification/mapping; they do not directly add points. |
| Scoring every scraped record regardless of review state | Scoring is blocked unless `llm_fit_grade` exists. |

Important wording rule:

> The system may still contain calibrated rules, but the intended architecture is not "heuristics decide fit." The intended architecture is "LLM extracts requirements, structured coverage derives the grade, configured scoring ranks the reviewed job, and remaining heuristics are explicit and auditable."

---

## Current known limitations

1. The grade derivation is coverage-based from `requirement_coverage`. A `KEEP` review is invalid unless `requirement_coverage` is present and non-empty.
2. Mandatory missing evidence does not automatically reject. It reduces the weighted coverage score but may still allow weak/solid outcomes depending on the rest of the coverage.
3. Preference signals can move jobs within grade bands and can affect display-time ranking, but they are not capability evidence.
4. Deterministic shortcuts can still produce early rejects without an LLM call. Deterministic keep candidates must still be confirmed by the LLM fit review before they become final KEEP rows. Audit the shortcut trigger via `det_rule`; audit final keeps via `review_source` and `requirement_coverage`.
5. Some older docs and backlog items may still use broad "heuristic" language. Treat that as technical debt unless it points to an actual remaining hardcoded judgement.

---

## Do not redesign during bug fixes

Do not opportunistically rewrite scoring during unrelated fixes.

Safe changes:

- update labels
- fix stale documentation
- fix broken config loading
- fix score display bugs
- add logging
- add tests around existing behaviour

Unsafe changes without explicit approval:

- changing grade bands
- changing coverage thresholds
- adding new scoring categories
- making mandatory gaps auto-reject
- changing deterministic shortcut thresholds
- making signal registry entries add direct score points
