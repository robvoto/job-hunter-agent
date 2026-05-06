# Learning Backlog

### Agent memory

- [ ] Add memory for seen, liked, applied, and rejected jobs

  Context:
  - Agent should remember jobs already seen.
  - Agent should remember jobs liked by the user.
  - Agent should remember jobs rejected/hidden by the user.
  - This prevents repeat work and supports learning.

---

### Outcome calibration

- [ ] Add future weight calibration from outcomes

  Context:
  - True weighting should come from outcome calibration.
  - Track which jobs were applied for and whether they produced interviews.
  - After around 30–50 outcomes, fit weights to improve predictive accuracy.

---

### Efficiency learning

- [ ] Track efficiency stats and use them to improve future runs

  Context:
  - Agent should learn how to be more efficient over time.
  - Useful stats may include:
    - jobs scanned
    - jobs shortlisted
    - jobs skipped
    - token usage
    - applied/interview rate

---

### Government context matching

- [ ] Improve `_GOVERNMENT_CONTEXT_PATTERNS`

  Context:
  - Current government context pattern matching needs improvement.

---

- [ ] Improve `_GOVERNMENT_CONTEXT_FALSE_POSITIVE_PATTERNS`

  Context:
  - Current false-positive handling for government context needs improvement.

---

### Learning / ML (future but critical)

- [ ] Define statistical learning approach (keep vs reject prediction)

  Context:
  - Predict keep vs reject from past labels
  - Only useful after enough clean feedback data
  - Not immediate priority, but important architecture decision

---

### Learning system (core differentiator)

- [ ] Implement incremental learning system

  Context:
  - Includes:
    - Learning Inbox
    - pattern learning
    - profile updates

---

- [ ] Improve Decision Weights UX

  Context:
  - Decision Weights are important but hidden
  - Idea:
    - expose during onboarding or advanced step
  - Concern:
    - settings page too large and messy

---

### Behaviour learning

- [ ] Learn patterns from user “hide” actions

  Context:
  - hidden jobs indicate preferences
  - should influence future filtering

---

### Learning System (pattern-based)

- [ ] Define learning-from-patterns capability

  Context:
  - Question:
    - what else can we suggest from patterns?
  - This is powerful but unclear:
    - how do we teach the app?
    - what signals are used?

---

### General System / UX Patterns

- [ ] Apply best practices to large files

  Context:
  - Improve structure and maintainability.

---

- [ ] Replace Years/Months inputs with sliders

  Context:
  - Feels like “calibrating a machine”.
  - Better UX for tuning.

---

- [ ] Decide save behaviour (auto vs manual)

  Context:
  - Option:
    - auto-save like Google Docs
  - Or:
    - Save All Changes button
    - only enabled when changes detected

---

- [ ] Centralise labels

  Context:
  - Single source of truth for labels
  - Ensures consistency across UI

---

### CV Filtering Logic (important edge cases)

- [ ] Improve years-of-experience filtering

  Context:
  - Example:
    - job requires 4 years
    - user has 2 years
  - Needs intelligent handling

---

- [ ] Allow company-level blocking

  Context:
  - Users can hide jobs from specific companies

---

- [ ] Handle “1–3 years” requirement nuance

  Context:
  - Not just experience presence
  - Also experience duration
  - Hard to model correctly

---

- [ ] Decide whether to store companies worked for

  Context:
  - Could improve matching
  - But:
    - no personal data linking currently
    - may require handling sensitive info

---

### Job Rejections Learning

- [ ] Integrate job rejection tracking (Google Sheet)

  Context:
  - Track:
    - company
    - role
    - number of rejections
    - dates
  - Use to lower future scores

---

- [ ] Design generic rejection tracking (not just personal)

  Context:
  - Current sheet is personal
  - Need system for all users later

---

### Learning System (Core — very important)

- [ ] Learn automatically from user actions

  Context:
  - Signals:
    - hide job
    - apply to job
    - revisit job
    - reject recurring skill cluster
  - Expected behaviour:
    - suggest profile updates

  Examples:
  - “You keep applying to delivery transformation roles → boost those patterns”
  - “You keep hiding platform-admin roles → strengthen reject rules”
  - “This skill appears in jobs you keep → classify as supporting”

---

- [ ] Evolve unknown skills into profile updates

  Context:
  - Already have unknown skills review
  - Next step:
    - track frequency
    - track correlation:
      - appears in kept/applied jobs?
      - appears in rejected jobs?
    - suggest classification
    - one-click apply to `capability_profile_rules`

---

- [ ] Add evidence-based rule suggestions in admin

  Context:
  - Instead of:
    - “add keyword X”
  - Show:
    - sample jobs
    - counts
    - impact estimate
    - effect on:
      - false positives
      - false negatives
  - Goal:
    - safe, explainable tuning

---

- [ ] Make admin suggest rules automatically

  Context:
  - Instead of manual typing:
    - “these terms appear in strong matches”
    - “these appear in junk roles”
  - Suggestions:
    - add keyword
    - add reject rule
    - reclassify capability
  - Goal:
    - admin becomes tuning cockpit

---

### Role expansion / augmented search

- [ ] Add augmented search for adjacent roles

  Context:
  - Example:
    - Scrum Master (junior)
    - Product Owner (junior)
    - Implementation consultant
    - SaaS configurator (e.g. Monday.com, Guidewire)
  - These roles may not match “Senior BA” directly
  - But user has evidence of success (interviews)
  - Needs structured way to include them

---

### Codebase clarity

- [ ] Ensure all files have proper headers

  Context:
  - Explain:
    - purpose
    - role in system
  - Improve maintainability

---

- [ ] Create system architecture overview

  Context:
  - Document:
    - all files
    - how they connect
  - Could include visual diagram
  - Useful for:
    - learning
    - showcasing

---


