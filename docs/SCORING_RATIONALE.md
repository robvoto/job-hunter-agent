# Fit Score Rationale

Private reference doc. Not committed to the repo.

---

## Model basis

This is a **heuristic multi-criteria ranking model** â€” not a trained classifier, not a single published formula. The approach is grounded in:

- **Person-Job fit (P-J fit) theory** â€” Kristof-Brown (2000), Edwards (1991): alignment between job requirements and candidate attributes is the primary predictor of job satisfaction and performance. This justifies capability matching and title alignment as the dominant signals.
- **Multi-Criteria Decision Analysis (MCDA)** â€” Keeney & Raiffa (1976): combining heterogeneous signals into a single score with explicit, auditable weights is a well-established operations-research methodology for ranking alternatives across incommensurable criteria.
- **Recruiter behaviour research** â€” LinkedIn Talent Insights / TheLadders (2012) eye-tracking study: title is the first and highest-weight screen; the LLM grade replaces the recruiter's full-description read.
- **Competency-based hiring** â€” US DoL O*NET and I/O psychology literature since the 1970s: skill alignment is the primary predictor of job performance.
- **Hedonic wage theory** â€” Rosen (1974): logistics factors (salary, location, contract) are job-bundle attributes that predict acceptance, not fit.
- **Time-to-fill data** â€” BLS / SHRM: most roles fill within 3â€“4 weeks; freshness is a prioritisation signal, not a fit signal.

**What is NOT research-derived:** the specific point allocations â€” why title is 15% of budget and not 12% or 18%, why LLM is 25% and not 22%. These are structured calibration judgements, not empirically derived constants. They are defensible as relative weights but require outcome calibration (tracking interview rates per score band) to become truly empirical. The system is designed to collect that data.

**What the score means:** A relative ranking signal, not an absolute quality measure. 53 vs 57 means one job is ranked slightly above the other by the current weights. It does not mean the lower-scoring job is a 53% fit in any absolute sense. The score answers "which roles should I look at first and which are stretches" â€” not "am I qualified for this role."

---

## Design principle

Each component's point value is derived from a **fixed budget allocation** - a defined percentage of the 100-point ceiling - based on that component's importance in the hiring decision. Values are not tuned to produce target scores; they are the natural consequence of the budget.

If a component produces an unexpected score, look at whether the *budget allocation* is wrong, not the raw number. Changing the number without changing the allocation rationale would reintroduce the same drift this design replaced.

Reviewed signal decisions from `signal_registry.json` are intentionally excluded from scoring. Approving a signal means "learn how to classify or map this term next time", not "boost any job that happens to mention this word". Those signals remain available for explanation and later promotion into normalized profile rules, but they do not contribute points directly.

---

## Budget breakdown

| Category | Budget | Components |
|----------|--------|------------|
| Core fit | 60 pts | Title (15) + LLM grade (25) + Capability evidence (20) |
| Logistics | 30 pts | Contract (10) + Location (8) + Salary (7) + Work mode (5) |
| Freshness | 10 pts | Age of posting |
| Convergence bonus | 5 pts | When multiple strong signals simultaneously confirm fit |
| Quality adjustments | outside budget | Content filter +3, Description confidence âˆ’8, Already viewed âˆ’3 |
| Competitive signal | outside budget | Domain specialist alignment Â±2 to Â±8 |

Maximum achievable: 60 + 30 + 10 + 5 + 3 = 108 â†’ clamped to 100.

---

## Score bands

Final score is clamped to 0â€“100.

| Band | Range | What it requires |
|------|-------|-----------------|
| Strong match | 85â€“100 | Core fit 50+, good logistics, recency, convergence |
| Good match | 70â€“84 | Core fit 40+, decent logistics, some freshness |
| Possible fit | 55â€“69 | Either title or strong LLM, reasonable logistics |
| Stretch | 0â€“54 | Low-confidence fit or significant gaps |

Thresholds are derived from the budget: reaching 85 requires title + STRONG/EXCELLENT LLM + substantial capability evidence + good logistics + recency. They are not arbitrary; they reflect what a "genuine fit" looks like across all dimensions simultaneously.

---

## Core fit budget (60 pts total)

### Title signal â€” budget 15 pts

| Outcome | Points | Fraction of budget |
|---------|--------|--------------------|
| Direct target title match | 15 | 100% |
| Secondary / potential match | 4 | 27% |
| No title match | 0 | 0% |

Rationale: Title is the primary recruiter filter and the cheapest reliable signal. 15 pts = 15% of total. Secondary match at 27% of budget reflects genuine but uncertain plausibility â€” enough to matter, not enough to substitute for a direct match.

### LLM description grade â€” budget 25 pts

| Grade | Points | Fraction of budget |
|-------|--------|--------------------|
| EXCELLENT | 25 | 100% |
| STRONG | 20 | 80% |
| SOLID | 14 | 56% |
| WEAK | 6 | 24% |
| POOR | 0 | 0% |
| MISMATCH | âˆ’8 | âˆ’32% |

Rationale: 25 pts = 25% of total, the largest single budget, because the LLM reads the full job description against the full candidate profile â€” it has the most information. Grade spacing is non-linear by design: EXCELLENTâ†’STRONG (20%) is a modest gap between two positive signals; STRONGâ†’SOLID (24%) is more significant; SOLIDâ†’WEAK (32%) is large because WEAK means genuine concerns were found. MISMATCH earns a penalty at âˆ’32% of budget â€” it actively signals misalignment.

### Capability evidence â€” budget 20 pts

Capability evidence is collected in three tiers, applied in priority order:

| Tier | Mechanism | Trust model |
|---|---|---|
| **Canonical** | Exact name match in job description text | Deterministic â€” full credit |
| **Alias** | Approved alias match (e.g. "user acceptance testing" for "Acceptance testing") | Deterministic â€” same credit as canonical |
| **Contextual LLM** | LLM identifies that description text implies the capability (e.g. "run discovery workshops" â†’ requirements elicitation) | Binary trust: high-confidence = full credit; medium/low = zero credit + logged |

For each credited capability:

```
level_weight = 4 (strong) / 3 (working) / 2 (basic)
points       = level_weight
```

Matches are sorted by level weight descending; accumulation stops as soon as the 20 pt cap is reached (no wasted LLM lookups beyond that point). Each credited capability appears as a separate line in the score breakdown with its match type tag (`[canonical]`, `[alias: ...]`, or `[contextual_llm]`).

The LLM contextual pass is piggybacked on the existing fit-review call â€” no extra API call is made. Medium and low-confidence contextual matches are logged (INFO and DEBUG respectively) but never credited; they are visible in the application logs for calibration review.

Rationale: 20 pts = 20% of total. Binary trust (rather than partial credit) is used for LLM contextual matches because partial credit requires calibrated confidence thresholds, which would be arbitrary at this stage. The existing level weights (strong > working > basic) already encode the appropriate discount: a "basic" contextual match earns 2 pts, not 4. That discount is meaningful without inventing a separate multiplier for LLM confidence.

Internal levels are `strong`, `working`, and `basic`, displayed in the UI as Strong, Working, and Basic.


| Setting | Value | Rationale |
|---------|-------|-----------|
| `strong_min_months` | 36 | **Duration:** You need 3+ years (36 months) of total experience to be automatically labeled "Strong". |
| `strong_max_years_since_use` | 4 | **Freshness:** If the capability has not been used recently, it should not stay "Strong". One long current role can still be strong if it is recent enough. |
| `working_min_months` | 18 | **Floor:** You need at least 1.5 years (18 months) for "Working" level. Anything less becomes "Basic". |

## Logistics budget (30 pts total)

### Work type / contract â€” budget 10 pts

**Hard filter (pre-scoring):** Selected work types define eligibility. If a role is clearly one of the unselected work types, it is excluded before scoring. Unknown or unclear work type passes through unless a separate deliberate rule already rejects it.

| Outcome | Points |
|---------|--------|
| Permanent role when permanent is selected | 10 |
| 12+ month contract with extension potential | 9 |
| 12+ month contract | 8 |
| 6â€“12 month contract | 5 |
| Contract shorter than preferred | âˆ’4 |

Rationale: 10 pts = 10% of total. Scoring applies only after the work-type filter has already removed explicit mismatches. If multiple work types are selected, or all work types are selected, this category is neutral for scoring.

### Location preference â€” budget 8 pts

| Outcome | Points |
|---------|--------|
| Primary location match | 8 |
| Secondary location with remote/hybrid setup | 4 |
| Secondary location (neutral) | âˆ’1 |
| Secondary location with regular onsite attendance | âˆ’3 |
| Secondary location with mandatory local onsite | âˆ’5 |

Rationale: 8 pts = 8% of total. Primary match = full budget. Secondary match with good work mode = 50% of budget (practical even if not ideal). Penalties reflect the real cost of commute burden or relocation.

### Salary signal â€” budget 7 pts

**Hard filter (pre-scoring):** If salary is explicitly stated, parseable as annual or daily, and falls below your minimum target, the role is excluded before scoring. Unlisted salary, package/super-inclusive figures, and hourly/weekly rates always pass through.

| Outcome | Points |
|---------|--------|
| Meets or exceeds target | 7 |
| 80â€“99% of target | âˆ’1 |
| 60â€“79% of target | âˆ’3 |
| Below 60% of target | âˆ’5 |
| Not listed | 0 |

Rationale: 7 pts = 7% of total. Salary is listed infrequently, so the budget is modest. The hard filter means below-minimum salaries never reach the score table â€” scoring only applies to roles that met or are close to the target, or where salary is unknown.
### Work mode â€” budget 5 pts

**Hard filter (pre-scoring):** Selected work modes define eligibility. If a role is clearly one of the unselected modes, it is excluded before scoring. Unknown or unclear work mode passes through unless a separate deliberate rule already rejects it.

| Outcome | Points |
|---------|--------|
| Confirmed selected mode | 5 |
| Multiple selected modes | 0 |
| All selected | 0 |
| Unknown / unclear | 0 |

Rationale: 5 pts = 5% of total. Work mode is a small confidence/preference signal, not a global ranking where remote is always better than onsite. The score is relative to the user's selected modes. If multiple modes are selected, or all modes are selected, work mode is neutral for scoring.

---

## Freshness budget (10 pts total)

| Age | Points | Fraction |
|-----|--------|----------|
| < 1 hour | 10 | 100% |
| < 1 day | 8 | 80% |
| 1â€“3 days | 5 | 50% |
| 3â€“7 days | 2 | 20% |
| 7â€“15 days | 1 | 10% |
| > 15 days | 0 | 0% |

Rationale: Freshness is a prioritisation signal, not a fit signal. It answers "which job should I act on first" not "how well does this fit". Decay is steep: a job posted 3 days ago is worth only 25% of one posted today, reflecting real recruiter fill rates.

---

## Convergence bonus (0â€“5 pts)

Applies when: title OK + content OK + HIGH description confidence + LLM grade EXCELLENT or STRONG + 2+ core capability matches + no missing evidence.

| Condition | Bonus |
|-----------|-------|
| All above, no soft risks | 5 |
| All above, with soft risks | 3 |

Rationale: When four independent signal sources (title, content filter, LLM, capabilities) simultaneously endorse a job, the combined confidence is greater than the sum of parts. This bonus rewards convergence, not any single signal. It is outside the core budget because it is conditional â€” most jobs will not trigger it.

This replaces the former `calibrated_fit_alignment_entry` (4â€“6 pts) and `clean_fit_bonus` (2 pts), which were overlapping bonuses that accumulated opaquely. A single convergence bonus is transparent and non-overlapping.

---

## Quality adjustments (outside budget)

These apply regardless of preference weights.

| Signal | Points | Rationale |
|--------|--------|-----------|
| Passed content filters | +3 | Data quality bonus: no blockers found |
| Description confidence LOW | âˆ’8 | Unreliable data penalises all signals derived from it |
| Already viewed (not applied) | âˆ’3 | Deprioritises jobs already reviewed without action |

---

## Competitive signal adjustments (outside budget, weighted by `fit`)

Domain specialist clusters (e.g. "deep technical stack", "sector-specific tooling") measured by alias density in the job description.

| Alignment | Adjustment |
|-----------|------------|
| Strong (â‰¥ 0.78 combined score) | +1 to +2 (by dominance level) |
| Partial (0.42â€“0.77) | âˆ’5 to âˆ’7 |
| Weak (< 0.42) | âˆ’6 to âˆ’8 |

Penalties are intentionally smaller than in earlier versions. The capability evidence component already handles skill gaps; competitive signals handle the case where a job is saturated with a specialist domain the candidate does not lead with.

---

## Sector preference

**Hard filter (pre-scoring):** Sector selection defines eligibility. If a role is clearly public sector and the user selected private only, the role is excluded before scoring. If a role is clearly public sector and the user selected public only, it remains eligible. Unknown sector always passes through unless a separate deliberate rule already rejects it.

**Scoring:** Sector is a small preference signal, not a universal ranking. Public sector evidence can earn the configured sector bonus when public is the only selected sector. If both sectors are selected, sector is neutral for scoring.

The public-sector classifier still uses public-sector context evidence internally. That is classification input only, not the user-facing model.

---

## Preference weights

Each component belongs to a weight category (fit, freshness, location, contract, work_mode, salary, government). Weights default to 1.0 and can be raised up to 2.0 from the settings UI. The `government` weight name remains internal, but it now drives the user-facing sector signal.

A weight of 2.0 doubles all points (positive and negative) in that category. This is a blunt importance multiplier — it shifts relative weight between categories, not within them. The clamping at 0–100 means very high weights on fit can push strong-fit scores to 100 even without logistics points.

---

## What can be explained

- Why a job scored high: "title matched (15), LLM grade STRONG (20), 3 core capabilities with strong evidence (18), Sydney location (8), permanent role (10), posted 2 hours ago (10), convergence bonus (5)"
- Why a job scored low: "no title match (0), capability evidence thin (4), LLM WEAK (6), salary below target (âˆ’5)"
- Why capability X contributed less than Y: "evidence score 0.12 vs 0.90 â€” thin vs deep profile evidence"
- Why the convergence bonus did not fire: "LLM grade was SOLID, not STRONG or EXCELLENT"

## What requires a budget change to fix, not a number tweak

- Why title is worth 15 pts and not 12 or 18 â†’ change the 15% budget allocation
- Why EXCELLENT beats STRONG by 5 pts â†’ change the 80% fraction for STRONG
- Why the freshness breakpoints are 1/3/7/15 days â†’ change the decay curve rationale
- Why the score bands sit at 85/70/55 â†’ change what the bands are meant to represent


EVIDENCE
--------

What IS grounded in evidence
The choice of what to measure â€” and the rough ordering of importance â€” aligns with published research:

Title as primary filter: Recruiter behaviour studies (LinkedIn Talent Insights, TheLadders 2012 eye-tracking study) consistently show job title is the first and highest-weight screen. Recruiters spend 6â€“7 seconds on a candidate â€” title is what they look at first.

Skills/capabilities as the core criterion: The entire competency-based hiring movement (widely adopted since the 1970s, standardised in frameworks like the US DoL's O*NET) treats skill alignment as the primary predictor of job performance. This is well-documented in industrial/organisational psychology literature.

Logistics (salary, location, contract) as constraints not fit signals: Labour economics treats these as job attributes workers bundle-evaluate, not fit signals. Hedonic wage theory (Rosen, 1974) formalises this â€” workers trade off job characteristics; they don't predict success, they predict acceptance.

Freshness as a prioritisation signal: Time-to-fill data (BLS, SHRM) shows most roles fill within 3â€“4 weeks; acting on fresh postings has demonstrably better outcomes than acting on stale ones.

The budget-based approach itself: Multi-Criteria Decision Analysis (MCDA) is a well-established operations research methodology for exactly this problem â€” combining heterogeneous signals into a single score using explicit, auditable weights.

What is NOT grounded in evidence
The specific percentages â€” why 15% for title and not 13% or 18%, why LLM is 25% and not 22%. There is no paper that derives these numbers. They are structured judgments.

What makes them better than the old system is not that they're empirically correct â€” it's that they are explicit and reasoned, so they can be argued about on principled terms rather than tuned by feel.

How to make it genuinely evidence-based
The only way to derive the weights from data is outcome calibration: track which jobs you applied for and whether you got an interview, then fit the weights to maximise predictive accuracy. After ~30â€“50 outcomes you'd have enough signal to calibrate. That's the path to true empirical grounding â€” but it requires your own historical data, which this system could start collecting now.
 
