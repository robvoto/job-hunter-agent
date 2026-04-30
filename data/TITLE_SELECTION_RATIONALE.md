# Title Selection Rationale

Private reference doc. Not committed to the repo.

---

## Design mode

This system is now **strict mode**.

It is a clean deterministic redesign with:

- no backward compatibility
- no legacy title heuristics
- no LLM role inference
- no trust in previously saved title patterns

System priority:

- precision > coverage

If the evidence is weak, the title should be excluded.

---

## What this logic is for

Title selection happens during onboarding/rebuild.

Its job is to decide:

- which titles belong in `target_title_patterns`
- which titles belong in `secondary_title_patterns`
- which title should seed search keywords when the user has not entered one manually

This happens **before** fit scoring.

Fit scoring later consumes the saved title lists, but does not decide them.

---

## Source of truth

Only use:

- parsed CV role headers
- role dates

Do not use:

- skills sections
- descriptions
- profile summaries
- achievements
- inferred adjacent roles
- previously saved title lists

The source of truth is the parsed role history itself.

---

## Role parsing assumption

The role parser should produce, per role:

- title
- employer
- dates
- current vs older status

If the parser cannot extract a role title structurally, title selection should not compensate by guessing from other text.

That is intentional.

---

## Title line recognition guard

A line is only a candidate role title if it passes `_looks_like_role_title_line`.

Key rule: **a multi-word line (2 or more tokens) must contain at least one token from `_GENERIC_ROLE_TOKENS`** to be considered a job title.

`_GENERIC_ROLE_TOKENS` covers the common professional role words: analyst, manager, coordinator, consultant, specialist, developer, engineer, architect, officer, director, administrator, owner, lead, executive, head, staff, master.

This rule exists because multi-word lines without a role token are almost always company names or description fragments, not job titles.

Examples that must be rejected:

- `TechCorp (contract)` — company name, no role token
- `Digital Solutions Group` — company name, no role token
- `NSW eHealth` — employer name, no role token

Examples that must pass:

- `Senior Business Analyst` — contains `analyst`
- `Scrum Master / Project Coordinator` — contains `master` and `coordinator`
- `Operations Support Officer` — contains `officer`

**Do not lower or remove this guard.** Weakening it is the primary cause of company names being promoted to title patterns. The guard is marked SEALED in the source code.

---

## Compound titles

Compound role titles are split into candidate titles.

Example:

`Senior Business Analyst / Scrum Master`

becomes:

- `Senior Business Analyst`
- `Scrum Master`

Important:

Splitting creates candidate titles only.
It does **not** mean those titles are equally strong.

Evidence is still evaluated separately per candidate title.

---

## Evidence model per candidate title

Each candidate title is evaluated independently using only structural evidence from role headers.

### 1. Recency

Signals are ordered by role position and current status:

- current role = strongest
- next 1 to 2 roles = recent
- older roles = weak

This is not fit scoring.
It is title evidence weighting.

### 2. Repetition

Signals strengthen when the same candidate title appears across multiple roles.

- repeated title = stronger evidence
- one-off title = weaker evidence

### 3. Title purity

Signals are stronger when the title appears as a standalone role title.

- standalone title = strong evidence
- title appearing only as part of a compound title = weak evidence

This is a core rule of strict mode.

---

## Classification rules

### Primary titles

A title can go into `target_title_patterns` only if:

- it appears in a current or recent role
- and it has strong structural evidence

Strong structural evidence means:

- standalone usage

or

- repeated usage that is not only weak compound presence

Primary titles should represent roles the user can target directly now.

### Secondary titles

A title can go into `secondary_title_patterns` when it is present in role history but weaker because of one or more of:

- older role placement
- compound-only usage
- low repetition
- weaker purity than a primary title

Secondary titles are allowed only when there is still explicit role-header evidence.

### Reject

Reject the title when evidence is weak or ambiguous.

Examples of rejection conditions:

- appears only once
- older only
- compound-only
- no recent presence
- not structurally parsed from role headers

Strict mode prefers missing a borderline title over admitting a false positive.

---

## Search keyword derivation

Search keywords are derived only from primary titles.

Do not use:

- LLM keyword suggestions
- skills text
- broader adjacent-role guesses

If a primary title exists and the user has not manually set a search keyword, the first primary title becomes the default keyword.

---

## LLM boundary

LLM is not allowed to:

- classify titles
- promote titles
- infer missing roles
- generate primary or secondary title lists

In this design, title selection is deterministic.

LLM may be used in future only for formatting normalization, such as expanding abbreviations, but not for decision-making.

That normalization is optional and non-authoritative.

---

## No backward compatibility rule

This logic does not preserve older title-selection behavior.

Do not:

- translate old title lists into the new system
- merge old saved title patterns into new rebuild output
- keep legacy normalization paths alive

If title direction needs to change, rebuild it from CV parsing.

---

## Relationship to scoring

This file documents title selection.

`data/SCORING_RATIONALE.md` documents how the saved primary and secondary titles affect downstream job scoring.

That downstream scorer only sees:

- direct target match
- secondary title match
- no title match

It does not decide which titles belong in those buckets.

---

## Current product rule

The intended product flow is:

1. parse role headers from the CV
2. deterministically classify candidate titles
3. let the user review and correct the result
4. use the reviewed result for later search and scoring

If title evidence is unclear, the engine should exclude the title and rely on user correction instead of guessing.

---

## Weak CV behaviour

Some CVs have no explicit job title headers — only company names, dates, and description text in the role sections.

The correct behaviour in this case is:

- extract only the titles that pass the parser strictly
- return empty or minimal lists
- show the user what was found and let them add correct titles manually

Do not try to infer titles from descriptions, skills sections, or notes. Do not lower thresholds to produce more output.

**The test CV (`primary_cv.txt`) deliberately represents this scenario.** Jason Lee's first two roles have no job title header — only a company name and a description sentence. The correct extraction output for that CV is:

- Primary: `["operations support officer"]`
- Secondary: `[]`

This is not a bug. It is the correct strict-mode result for a CV with weak title signals.

---

## Files to review

- `job_hunter_agent/profile_learning.py`
- `job_hunter_agent/source_documents.py`
- `data/SCORING_RATIONALE.md`

---

## Review focus

The main questions to review are now simpler:

- Is the role parser extracting the right structural titles?
- Are the primary rules too strict or still too permissive?
- Are compound-only titles being demoted enough?
- Should secondary titles require recent presence, or can older explicit roles still qualify?
- Is default search keyword derivation from primary titles sufficient?

---

## Known recurring failure mode

This logic has been broken repeatedly by AI sessions that:

1. See company names appearing as primary titles and try to "fix" it by lowering `_looks_like_role_title_line` thresholds
2. Re-introduce LLM title inference to get "better" output from weak CVs
3. Modify `primary_cv.txt` to produce nicer test output

None of these are correct fixes. The multi-word role token guard in `_looks_like_role_title_line` and the strict classification rules in `_classify_titles_from_evidence` are the solution — not workarounds to them.
