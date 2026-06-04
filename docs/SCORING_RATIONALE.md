# Fit Score Rationale

Private reference doc. Not committed to the repo.

---

## Model basis

This is a **heuristic multi-criteria ranking model** - not a trained classifier, not a single published formula. The approach is grounded in:

- **Person-Job fit (P-J fit) theory** - Kristof-Brown (2000), Edwards (1991): alignment between job requirements and candidate attributes is the primary predictor of job satisfaction and performance. This justifies capability matching and title alignment as the dominant signals.
- **Multi-Criteria Decision Analysis (MCDA)** - Keeney & Raiffa (1976): combining heterogeneous signals into a single score with explicit, auditable weights is a well-established operations-research methodology for ranking alternatives across incommensurable criteria.
- **Recruiter behaviour research** - LinkedIn Talent Insights / TheLadders (2012) eye-tracking study: title is the first and highest-weight screen; the LLM grade replaces the recruiter's full-description read.
- **Competency-based hiring** - US DoL O*NET and I/O psychology literature since the 1970s: skill alignment is the primary predictor of job performance.
- **Hedonic wage theory** - Rosen (1974): logistics factors (salary, location, contract) are job-bundle attributes that predict acceptance, not fit.
- **Time-to-fill data** - BLS / SHRM: most roles fill within 3-4 weeks; freshness is a prioritisation signal, not a fit signal.

**What is NOT research-derived:** the specific point allocations - why title is 15% of budget and not 12% or 18%, why LLM is 25% and not 22%. These are structured calibration judgements, not empirically derived constants. They are defensible as relative weights but require outcome calibration (tracking interview rates per score band) to become truly empirical. The system is designed to collect that data.

**What the score means:** A relative ranking signal, not an absolute quality measure. 53 vs 57 means one job is ranked slightly above the other by the current weights. It does not mean the lower-scoring job is a 53% fit in any absolute sense. The score answers "which roles should I look at first and which are stretches" - not "am I qualified for this role."

---

## Design principle

Each component's point value is derived from a **fixed budget allocation** - a defined percentage of the 100-point ceiling - based on that component's importance in the hiring decision. Values are not tuned to produce target scores; they are the natural consequence of the budget.

If a component produces an unexpected score, look at whether the *budget allocation* is wrong, not the raw number. Changing the number without changing the allocation rationale would reintroduce the same drift this design replaced.

Reviewed signal decisions from `signal_registry.json` are intentionally excluded from scoring. Approving a signal means "learn how to classify or map this term next time", not "boost any job that happens to mention this word". Those signals remain available for explanation and later promotion into normalized profile rules, but they do not contribute points directly.

---

## Current implemented scoring model

The old fixed budget model is no longer current. The active model is band-anchored scoring controlled by data/knowledge/scoring_rules.json.

### Main rule

The LLM fit grade defines the allowed score band. Other signals move the job within that band. Hard blockers are applied after the band clamp and can force the score near zero.

| LLM grade | Base points | Score band | Meaning |
|-----------|-------------|------------|---------|
| EXCELLENT | 78 | 88-100 | Exceptional alignment |
| STRONG | 52 | 68-87 | Strong fit with supporting evidence |
| SOLID | 32 | 48-67 | Decent fit with manageable gaps |
| WEAK | 18 | 28-47 | Limited alignment |
| POOR | 6 | 8-27 | Poor alignment |
| MISMATCH | 0 | 0-7 | Clear mismatch |

### Score contributors

| Component | Current role |
|-----------|--------------|
| Title match | Adds role-alignment evidence: direct target title = +15, secondary/potential title = +4. |
| LLM grade | Primary semantic fit signal. Currently holistic; future redesign should derive it from mandatory requirement coverage. |
| Capability evidence | Adds up to +20 from high-confidence contextual_capability_matches using exact profile capability names. |
| Content passed | Adds +3 only for no content blocker found. This is weak data-quality evidence, not proof of fit. |
| Location, work type, work mode, salary | Preference/logistics signals. They help ranking but should not prove mandatory fit. |
| Freshness | Ranking urgency only. Current config gives +10 within 6 hours and +8 within 1 day. Older postings receive no freshness bonus. |
| Convergence | Adds +5 or +3 only when multiple strong signals align. |
| Competitive signals | Specialist-domain adjustment outside the main score band. |
| Hard blockers | Apply after band clamping and can force the score near zero. |

### Capability confidence handling

capability_contextual_llm controls how LLM capability matches are treated:

| Confidence | Treatment |
|------------|-----------|
| high | Credited in scoring |
| medium | Logged only / no score credit |
| low | Ignored / no score credit |

Confidence values must remain lowercase. A previous normalisation bug uppercased these values and caused high-confidence matches to be dropped; that has been fixed.

### Known limitation

This model is still grade-driven. It is not yet fully mandatory-requirement-coverage-driven.

Target direction:

1. Extract mandatory/core job requirements.
2. Match each requirement to candidate capabilities and CV evidence.
3. Derive grade/score from requirement coverage.
4. Use logistics and freshness only as ranking boosts, not proof of fit.

---

## Current scoring status 2026-06-02

Current implemented model:
- The LLM fit review returns fit_review decision plus grade, contextual_capability_matches, and job_requirements.
- fit_scoring.py is a consumer only; it reads stored LLM output and does not call the LLM.
- contextual_capability_matches must use exact candidate capability rule names. Invalid names are logged and skipped.
- High-confidence contextual capability matches are credited using capability evidence scoring.
- Medium confidence is logged only. Low confidence is ignored and logged separately.
- The confidence lists are managed in scoring_rules.capability_contextual_llm and must preserve lowercase values.
- The current grade bands are band-anchored: EXCELLENT, STRONG, SOLID, WEAK, POOR, MISMATCH.

Known design limitation:
- The current LLM grade is holistic. It is not yet derived from mandatory requirement coverage.
- Location, work type, work mode, salary, and freshness are ranking/preference signals. They should not be treated as proof that the candidate meets mandatory requirements.
- Content passed means no hard blocker was found. It is not strong positive evidence by itself.

Deferred architecture decision:
- Move toward requirement-coverage scoring: extract mandatory job requirements, match them to candidate capabilities/CV evidence, then derive grade/score from coverage.
- In that model, capabilities are the candidate-side evidence model used to prove requirements, not an independent bonus category.
- Do not redesign this opportunistically during bug fixes.
