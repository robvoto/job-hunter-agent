# Filtering Backlog

### Capability evidence scoring

- [ ] Level-vs-demand mismatch penalty for capability scoring

  Context:
  - When a job explicitly requires STRONG for a capability and the candidate only has BASIC, the current system still awards 2 pts (basic level weight).
  - This is a silent undercount: the job signals a gap but scoring does not penalise it.
  - Deferred from the capability evidence scoring MVP (contextual LLM match implementation, 2026-05).
  - Current behaviour: level weights (STRONG=4, WORKING=3, BASIC=2) provide a natural discount but do not model demand-side signals.

  Goal:
  - Detect when the job description explicitly states a proficiency level requirement (e.g. "must have extensive experience in...", "expert level required") for a specific capability.
  - Apply a penalty (or reduced credit) when the candidate's level is lower than what the job demands.

  Constraints:
  - Requires reliable demand-level extraction — this is an LLM task, not text matching.
  - Must be documented in SCORING_RATIONALE.md before implementation.
  - Must be calibrated against real ads before going live.
  - Do not add complexity to the contextual match path until demand extraction is reliable.

  Acceptance checks:
  - "Expert-level stakeholder management required" + BASIC profile level → penalty applied, visible in breakdown.
  - "Stakeholder management experience desirable" + BASIC profile level → no penalty (desirable ≠ required).
  - Logged demand mismatches appear in application logs for calibration review.

---

- [ ] Configurable LLM capability call trigger threshold

  Context:
  - Currently the LLM contextual capability pass fires on every job that clears hard blockers + title check.
  - If deterministic capability evidence is already strong (e.g. 3+ canonical matches filling the cap), the LLM contextual pass adds zero points but still costs tokens.
  - Deferred from capability evidence scoring MVP (2026-05).

  Goal:
  - Skip the contextual capability pass when deterministic evidence already reaches the cap.
  - Configurable threshold in `scoring_rules.json` (e.g. `skip_contextual_if_deterministic_score_gte: 20`).

  Constraints:
  - Must not change scores for jobs where deterministic evidence is below the threshold.
  - Threshold must have a sensible default (the cap itself, 20) so existing behaviour is unchanged if not configured.

  Acceptance checks:
  - Job with 3 STRONG canonical matches (12 pts) still triggers contextual pass.
  - Job with 5 STRONG canonical matches (20 pts cap hit) skips contextual pass.
  - Application log confirms skip reason.

---

- [ ] Outcome-calibrated capability scoring weights

  Context:
  - Current level weights (STRONG=4, WORKING=3, BASIC=2) and the 20 pt budget are structured judgements, not empirically derived.
  - The SCORING_RATIONALE.md notes this explicitly.
  - Deferred from capability evidence scoring MVP (2026-05).

  Goal:
  - Collect interview/response outcome data per score band.
  - Use that data to calibrate whether the current weights predict outcomes better than alternatives.
  - Document changes in SCORING_RATIONALE.md with rationale grounded in observed outcomes.

  Constraints:
  - Requires at least 30–50 application outcomes before calibration is meaningful.
  - Do not change weights without outcome data — structured judgements are acceptable until then.
  - Any calibration must be documented alongside the data that drove it.

---

### Job boards and source configuration

- [ ] Investigate dynamic job board support

  Context:
  - Question: can we add job boards dynamically?

---

- [ ] Improve SEEK classification IDs

  Context:
  - SEEK classification IDs may help filter better.
  - Needs improvement but is lower priority.

---

### Job card display

- [ ] Improve job metadata highlighting on dashboard cards

  Context:
  - Review whether this information is highlighting properly:
    - Posted 20 Apr 2026 (listed as 1d ago when retrieved)
    - Location Sydney NSW
    - Work mode Hybrid
    - Type Full time
    - Salary 180k per annum
  - Concern:
    - Do not create a full colour palette panel.
    - But the current information blends too much into the background.
    - Salary may need clearer emphasis.

---

- [ ] Improve spacing between job short description and metadata

  Context:
  - Job short title/description needs more spacing before text like:
    - Posted
    - Location
    - Work mode
    - Type
    - Salary

---

### Location handling

- [ ] Add proper location radius support

  Context:
  - Example:
    - “I want jobs 50km from Kellyville NSW”
  - This is more precise than the current broad location field.

---

### Dashboard job detail UX

- [ ] Add right-side job description panel

  Context:
  - When users click a role, show the role description in a right-side panel.
  - This could work well because the dashboard already has a right-side Run Snapshot area.
  - Applying should probably still open the original job in a new tab.

---

- [ ] Allow saved dashboard filters

  Context:
  - Users should be able to save filters and reuse them.
  - Add reset-to-default option.
  - Avoid forcing users to reselect filters every time.

---

### Candidate profile / CV variants

- [ ] Support multiple CV/profile variants

  Context:
  - Need to support:
    - technical CV
    - non-technical CV
    - government-focused CV
    - private-sector-focused CV
  - Current app does not contemplate this.

---

### Mandatory requirement handling (description blockers)

- [ ] Define behaviour for mandatory requirements in job descriptions

  Context:
  - Current idea:
    - block jobs when requirements are mandatory (or appear to be)
  - Open question:
    - should users be able to filter ALL jobs mentioning those terms?
  - Needs flexibility vs strict filtering balance.

---

### Multi-role and search flexibility

- [ ] Support multiple role titles in search

  Context:
  - Example:
    - Scrum Master → also Project Manager
  - Questions:
    - can users select more than one title?
    - how do we explain this clearly in UI?

---

- [ ] Allow free-text search interpretation

  Context:
  - Users type what they want instead of selecting options
  - System interprets input and configures filters automatically
  - Needs guidance to avoid chaos

---

### Filtering behaviour

- [ ] Control visibility of jobs from earlier runs

  Context:
  - “filter kept from earlier runs only show in test mode”
  - Needs clear rule:
    - when to show
    - when to hide
 

### Salary logic (critical)

- [ ] Improve salary interpretation and filtering

  Context:
  - Need to detect:
    - salary including super
    - base vs package
  - Not sure how SEEK and LinkedIn expose this
  - Must investigate before implementing

---
ing

- [ ] Add contract duration filter

  Context:
  - Example:
    - show only contracts ≥ 12 months
  - Important:
    - if duration unclear → still show job

---

### Contract filter

### Certifications handling

- [ ] Decide how certifications affect scoring

  Context:
  - Example:
    - CBAP for Business Analysts
    - degrees for regulated professions
  - Questions:
    - already captured by LLM?
    - should be separate for MVP?
    - efficiency vs accuracy tradeoff

---

### Mandatory domain tools

- [ ] Handle mandatory tools (ERP, Salesforce, etc.)

  Context:
  - Many BA roles require specific platforms
  - These should strongly influence filtering

---


### Job parsing edge cases

- [ ] Ensure unknown job attributes are not filtered out

  Context:
  - If job type (contract/permanent) unclear:
    - still show job
  - Avoid silent loss of opportunities

---


### Location & Scoring

- [ ] Clarify and improve location scoring behaviour

  Context:
  - Location will always match because it comes from the search (Seek/LinkedIn).
  - Later we may refine to “close to home”.
  - Current issue:
    - not clear how location affects scoring.

---

### Dashboard Filters (critical UX correctness)

- [ ] Fix misleading score filter behaviour

  Context:
  - Score dropdown only filters loaded jobs.
  - Cannot reveal jobs removed by backend floor.
  - Problem:
    - UI suggests hidden jobs can be revealed.

---

- [ ] Add explicit “borderline roles” mode

  Context:
  - Normal mode: shortlist 50+ jobs
  - Add toggle:
    - “Show borderline roles (35–49)”
  - Do NOT rely on score filter for this

---

- [ ] Evaluate whether borderline mode is user feature or test-only

  Context:
  - Might be useful for testing
  - Not sure for end users

---

- [ ] Add custom day filter

  Context:
  - Same as SEEK:
    - 3 / 7 / 14 / 30
  - Plus custom value ≤ 30

---

### Onboarding Experience (guidance + education)

- [ ] Improve privacy explanation

  Context:
  - Break into bullet points with 🛡️ icon
  - Users read bullets, not paragraphs

---

- [ ] Add real-time AI feedback during onboarding

  Context:
  - Show:
    - “Extracting skills…”
    - “Calculating experience…”
  - Makes AI feel active

---

- [ ] Evaluate adding industry field

  Context:
  - Could complement capability matrix
  - Might improve scoring efficiency

---

- [ ] Add onboarding completion guidance

  Context:
  - After onboarding:
    - review strengths
    - configure search
    - configure salary
  - Also:
    - explain AI is good but not perfect

---

- [ ] Educate users on CV structure importance

  Context:
  - Dates and chronological order matter
  - Needed for correct extraction
  - Could be:
    - one-off message
    - user guide

---

- [ ] Provide CV structure guidance (especially for new users)

  Context:
  - Suggest ideal CV structure
  - Do not force it (avoid frustration)
  - Idea:
    - quick guide
    - visual examples

---

### Capabilities UI (settings + onboarding)

- [ ] Add “Why this matters” tooltip for capabilities

  Context:
  - Example:
    - “This skill makes you a top 10% match for BA roles”

---

- [ ] Add bulk actions for capabilities

  Context:
  - Select All
  - Delete low relevance
  - Needed for large lists

---

### Salary System (important — already strong thinking)

- [ ] Keep conservative salary interpretation (no guessing)

  Context:
  - SEEK:
    - visible salary is free text
    - may be base / + super / package
  - LinkedIn:
    - structured intervals (yearly, daily, etc.)
    - unclear if includes super
  - Therefore:
    - do NOT guess conversions

---

- [ ] Add salary comparability state in UI

  Context:
  - Instead of generic “listed”:
    - meets
    - below
    - includes super/package
    - missing
  - Better than forcing comparisons

---

### Admin Rule Control

- [ ] Expose hard-block rules in admin UI

  Context:
  - Currently configurable in `profile.json`
  - Not exposed in admin UI
  - Should be editable without touching JSON

---

### Architecture / Structure

- [ ] Review need for `instructions_file`

  Context:
  - Question:
    - is it still needed?
  - Goal:
    - more efficient and cohesive filtering structure

---

- [ ] Remove SEEK-specific logic from system

  Context:
  - Ensure system is generic
  - Avoid SEEK-specific naming in:
    - code
    - UI
    - file structure

---

### Classification IDs (SEEK)

- [ ] Improve classification ID handling

  Context:
  - Useful for filtering junk roles
  - Question:
    - do they apply to LinkedIn?
  - Requirements:
    - show names (user-friendly)
    - hide IDs internally
    - provide dropdown from SEEK (static for now)

---

### Location filtering (edge case)

- [ ] Ensure strict location filtering (e.g. Canberra-only jobs)

  Context:
  - Must not show jobs outside allowed location
  - Question:
    - is this configurable now?

---


