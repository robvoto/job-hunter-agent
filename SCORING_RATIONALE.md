# Fit Score Rationale

Private reference doc. Not committed to the repo.

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
| Quality adjustments | outside budget | Content filter +3, Description confidence −8, Already viewed −3 |
| Competitive signal | outside budget | Domain specialist alignment ±2 to ±8 |

Maximum achievable: 60 + 30 + 10 + 5 + 3 = 108 → clamped to 100.

---

## Score bands

Final score is clamped to 0–100.

| Band | Range | What it requires |
|------|-------|-----------------|
| Strong match | 85–100 | Core fit 50+, good logistics, recency, convergence |
| Good match | 70–84 | Core fit 40+, decent logistics, some freshness |
| Possible fit | 55–69 | Either title or strong LLM, reasonable logistics |
| Stretch | 0–54 | Low-confidence fit or significant gaps |

Thresholds are derived from the budget: reaching 85 requires title + STRONG/EXCELLENT LLM + substantial capability evidence + good logistics + recency. They are not arbitrary; they reflect what a "genuine fit" looks like across all dimensions simultaneously.

---

## Core fit budget (60 pts total)

### Title signal — budget 15 pts

| Outcome | Points | Fraction of budget |
|---------|--------|--------------------|
| Direct target title match | 15 | 100% |
| Secondary / potential match | 4 | 27% |
| No title match | 0 | 0% |

Rationale: Title is the primary recruiter filter and the cheapest reliable signal. 15 pts = 15% of total. Secondary match at 27% of budget reflects genuine but uncertain plausibility — enough to matter, not enough to substitute for a direct match.

### LLM description grade — budget 25 pts

| Grade | Points | Fraction of budget |
|-------|--------|--------------------|
| EXCELLENT | 25 | 100% |
| STRONG | 20 | 80% |
| SOLID | 14 | 56% |
| WEAK | 6 | 24% |
| POOR | 0 | 0% |
| MISMATCH | −8 | −32% |

Rationale: 25 pts = 25% of total, the largest single budget, because the LLM reads the full job description against the full candidate profile — it has the most information. Grade spacing is non-linear by design: EXCELLENT→STRONG (20%) is a modest gap between two positive signals; STRONG→SOLID (24%) is more significant; SOLID→WEAK (32%) is large because WEAK means genuine concerns were found. MISMATCH earns a penalty at −32% of budget — it actively signals misalignment.

### Capability evidence — budget 20 pts

For each capability rule that matches the job description (fit = core or supporting, level = strong/working/basic):

```
rule_strength  = _capability_rule_strength(rule)       # 0.0–1.05, from rule level + fit
evidence_score = evidence_tier_alignment_score(profile, aliases)  # 0.0–1.0, from profile text
combined       = max(rule_strength, evidence_score)
contribution   = combined × fit_weight                 # fit_weight: 4 for core, 2 for supporting
```

Total = sum of contributions, capped at 20.

Rationale: 20 pts = 20% of total. The `max()` rule means the stronger of the two signals wins — self-assessed proficiency or demonstrated evidence. The cap at 20 matches the budget.

**Why `max` not average:** If your evidence text shows deep usage even though the rule is "basic", the stronger signal should count. If your rule is "strong" but the profile has thin evidence for this term, the rule still anchors the contribution.

---

## Logistics budget (30 pts total)

### Contract preference — budget 10 pts

| Outcome | Points |
|---------|--------|
| Preferred contract type (exact) | 10 |
| 12+ month contract with extension potential | 9 |
| 12+ month contract | 8 |
| 6–12 month contract | 5 |
| Contract shorter than preferred | −4 |
| Wrong engagement type | −5 |

Rationale: 10 pts = 10% of total. The largest logistics component because contract type is a hard, early filter. Tiers step down proportionally from the 10-pt maximum.

### Location preference — budget 8 pts

| Outcome | Points |
|---------|--------|
| Primary location match | 8 |
| Secondary location with remote/hybrid setup | 4 |
| Secondary location (neutral) | −1 |
| Secondary location with regular onsite attendance | −3 |
| Secondary location with mandatory local onsite | −5 |

Rationale: 8 pts = 8% of total. Primary match = full budget. Secondary match with good work mode = 50% of budget (practical even if not ideal). Penalties reflect the real cost of commute burden or relocation.

### Salary signal — budget 7 pts

| Outcome | Points |
|---------|--------|
| Meets or exceeds target | 7 |
| 80–99% of target | −1 |
| 60–79% of target | −3 |
| Below 60% of target | −5 |
| Not listed | 0 |

Rationale: 7 pts = 7% of total. Salary is listed infrequently, so the budget is modest. When it does appear and meets target, it's a full-budget positive. Below target penalises increasingly steeply — 60% of target is a genuine dealbreaker.

### Work mode — budget 5 pts

| Mode | Points |
|------|--------|
| Remote | 5 |
| Hybrid | 3 |
| On-site | −2 |

Rationale: 5 pts = 5% of total. Smallest logistics component because work mode is a preference, not a hard constraint for most candidates. On-site earns −2 rather than the larger penalties in other components — it's a miss, not a blocker. Preference weights (1.0–2.0) can amplify this for candidates where work mode is critical.

---

## Freshness budget (10 pts total)

| Age | Points | Fraction |
|-----|--------|----------|
| < 1 hour | 10 | 100% |
| < 1 day | 8 | 80% |
| 1–3 days | 5 | 50% |
| 3–7 days | 2 | 20% |
| 7–15 days | 1 | 10% |
| > 15 days | 0 | 0% |

Rationale: Freshness is a prioritisation signal, not a fit signal. It answers "which job should I act on first" not "how well does this fit". Decay is steep: a job posted 3 days ago is worth only 25% of one posted today, reflecting real recruiter fill rates.

---

## Convergence bonus (0–5 pts)

Applies when: title OK + content OK + HIGH description confidence + LLM grade EXCELLENT or STRONG + 2+ core capability matches + no missing evidence.

| Condition | Bonus |
|-----------|-------|
| All above, no soft risks | 5 |
| All above, with soft risks | 3 |

Rationale: When four independent signal sources (title, content filter, LLM, capabilities) simultaneously endorse a job, the combined confidence is greater than the sum of parts. This bonus rewards convergence, not any single signal. It is outside the core budget because it is conditional — most jobs will not trigger it.

This replaces the former `calibrated_fit_alignment_entry` (4–6 pts) and `clean_fit_bonus` (2 pts), which were overlapping bonuses that accumulated opaquely. A single convergence bonus is transparent and non-overlapping.

---

## Quality adjustments (outside budget)

These apply regardless of preference weights.

| Signal | Points | Rationale |
|--------|--------|-----------|
| Passed content filters | +3 | Data quality bonus: no blockers found |
| Description confidence LOW | −8 | Unreliable data penalises all signals derived from it |
| Already viewed (not applied) | −3 | Deprioritises jobs already reviewed without action |

---

## Competitive signal adjustments (outside budget, weighted by `fit`)

Domain specialist clusters (e.g. "deep technical stack", "sector-specific tooling") measured by alias density in the job description.

| Alignment | Adjustment |
|-----------|------------|
| Strong (≥ 0.78 combined score) | +1 to +2 (by dominance level) |
| Partial (0.42–0.77) | −5 to −7 |
| Weak (< 0.42) | −6 to −8 |

Penalties are intentionally smaller than in earlier versions. The capability evidence component already handles skill gaps; competitive signals handle the case where a job is saturated with a specialist domain the candidate does not lead with.

---

## Preference weights

Each component belongs to a weight category (fit, freshness, location, contract, work_mode, salary, government). Weights default to 1.0 and can be raised up to 2.0 from the settings UI.

A weight of 2.0 doubles all points (positive and negative) in that category. This is a blunt importance multiplier — it shifts relative weight between categories, not within them. The clamping at 0–100 means very high weights on fit can push strong-fit scores to 100 even without logistics points.

---

## What can be explained

- Why a job scored high: "title matched (15), LLM grade STRONG (20), 3 core capabilities with strong evidence (18), Sydney location (8), permanent role (10), posted 2 hours ago (10), convergence bonus (5)"
- Why a job scored low: "no title match (0), capability evidence thin (4), LLM WEAK (6), salary below target (−5)"
- Why capability X contributed less than Y: "evidence score 0.12 vs 0.90 — thin vs deep profile evidence"
- Why the convergence bonus did not fire: "LLM grade was SOLID, not STRONG or EXCELLENT"

## What requires a budget change to fix, not a number tweak

- Why title is worth 15 pts and not 12 or 18 → change the 15% budget allocation
- Why EXCELLENT beats STRONG by 5 pts → change the 80% fraction for STRONG
- Why the freshness breakpoints are 1/3/7/15 days → change the decay curve rationale
- Why the score bands sit at 85/70/55 → change what the bands are meant to represent


EVIDENCE
--------

What IS grounded in evidence
The choice of what to measure — and the rough ordering of importance — aligns with published research:

Title as primary filter: Recruiter behaviour studies (LinkedIn Talent Insights, TheLadders 2012 eye-tracking study) consistently show job title is the first and highest-weight screen. Recruiters spend 6–7 seconds on a candidate — title is what they look at first.

Skills/capabilities as the core criterion: The entire competency-based hiring movement (widely adopted since the 1970s, standardised in frameworks like the US DoL's O*NET) treats skill alignment as the primary predictor of job performance. This is well-documented in industrial/organisational psychology literature.

Logistics (salary, location, contract) as constraints not fit signals: Labour economics treats these as job attributes workers bundle-evaluate, not fit signals. Hedonic wage theory (Rosen, 1974) formalises this — workers trade off job characteristics; they don't predict success, they predict acceptance.

Freshness as a prioritisation signal: Time-to-fill data (BLS, SHRM) shows most roles fill within 3–4 weeks; acting on fresh postings has demonstrably better outcomes than acting on stale ones.

The budget-based approach itself: Multi-Criteria Decision Analysis (MCDA) is a well-established operations research methodology for exactly this problem — combining heterogeneous signals into a single score using explicit, auditable weights.

What is NOT grounded in evidence
The specific percentages — why 15% for title and not 13% or 18%, why LLM is 25% and not 22%. There is no paper that derives these numbers. They are structured judgments.

What makes them better than the old system is not that they're empirically correct — it's that they are explicit and reasoned, so they can be argued about on principled terms rather than tuned by feel.

How to make it genuinely evidence-based
The only way to derive the weights from data is outcome calibration: track which jobs you applied for and whether you got an interview, then fit the weights to maximise predictive accuracy. After ~30–50 outcomes you'd have enough signal to calibrate. That's the path to true empirical grounding — but it requires your own historical data, which this system could start collecting now.
 
