# Capability Aging Rationale

Private reference doc. Not committed to the repo.

Run commands relevant to this logic:

```powershell
# normal user-style UI
python -m job_hunter_agent.local_server

# test/debug mode for rebuild internals and local diagnostics
python -m job_hunter_agent.local_server --test-mode
```

---

## Design principle

Capability strength should reflect **current usable depth**, not just keyword presence in a CV.

The aging logic exists to stop old experience from being overrated simply because:

- a word appears in the CV
- the capability was once strong many years ago
- recruiters would still match on that keyword

This logic is separate from fit scoring. Its job is earlier in the pipeline:

1. extract capability-like signals from CV history
2. estimate how current and substantial each signal is
3. assign a default strength
4. let the user manually override that strength later

The default must be conservative. It is safer to under-rank stale experience and let the user raise it than to over-rank stale experience and pollute matching.

---

## What this logic is trying to solve

Examples:

- `Guidewire` used once 14 years ago should not default to a strong capability
- `Financial systems` mentioned in old roles should not stay strong just because the CV still contains the word
- `Java` used deeply for years but not recently may still matter, but should usually downgrade from Expert

This is the core distinction:

- **historical evidence** = the CV proves the user once did it
- **current strength** = how much the system should rely on that capability now

The aging logic converts the first into the second.

---

## Inputs used

Each extracted capability cluster is evaluated using:

- `most_recent_year`
- `total_duration_months`
- `role_count`
- `current_role_count`
- `recent_role_count`
- `occurrences`
- `action_verb_count`

These come from structured CV role parsing plus phrase clustering.

---

## Cluster score

Before strength assignment, each cluster gets a structural score:

```text
recurrence   = min(occurrences / 10, 1.0)
breadth      = min(role_count / 5, 1.0)
recency      = recent_role_count / occurrences
current_depth = min(total_duration_months / 72, 1.0)
action_ratio = action_verb_count / occurrences

score =
  recurrence   * 0.28 +
  breadth      * 0.22 +
  recency      * 0.22 +
  current_depth * 0.20 +
  action_ratio * 0.08
```

Purpose of each term:

- `recurrence`: repeated mentions should matter, but not dominate
- `breadth`: experience across roles is stronger than one concentrated mention
- `recency`: newer evidence should carry more weight
- `current_depth`: long duration should help older but genuinely deep experience
- `action_ratio`: “did the work” language is stronger than passive mentions

This score is not the final strength. It is only one input into promotion.

---

## Default strength assignment

The app currently maps one of three presets to hidden numeric thresholds:

- `recent_focus` (Recent Focus)
- `balanced`
- `include_older_experience`

The visible preset is the user-facing control.
The numeric thresholds are implementation detail.

The strength decision uses:

- max years since last use for `strong`
- minimum months for `strong`
- minimum role spread for `strong`
- max years since last use for normal `working`
- months required for normal `working`
- separate allowance for older but deep history to remain `working`
- forced downgrade rules for old single-role evidence
- hard upper limit after which anything drops to `basic`

---

## Balanced preset

This is the current default preset.

```text
recent window: 4 years
strong max years since use: 4
strong min months: 36
strong min roles: 2

working max years since use: 8
working min months: 18

working long-history max years since use: 12
working long-history min months: 48

single-role old evidence drops after: 8 years
hard drop to basic after: 12 years
```

Interpretation:

- `strong` means recent and substantial
- `working` allows either recent solid usage or older but deep history
- `basic` is the fallback for stale, shallow, or one-off experience

---

## Promotion rules in plain language

### Default to `strong`

A capability can default to `strong` when it is:

- recent enough
- substantial enough in total duration
- spread across enough roles
- and the structural score is high enough

There is also a shortcut for currently active evidence:

- if the capability appears in a current role
- and there is enough total duration
- and the score is strong enough

then it can still reach `strong`

This prevents deep current capability from being dragged down by sparse wording.

### Default to `working`

A capability can default to `working` when it is either:

- not too old and reasonably substantial

or

- older, but clearly deep and repeated enough to remain useful

This is the “Java used heavily years ago” case.

### Force to `basic`

The system forces `basic` when:

- the capability is old and came from only one role
- or it is beyond the hard maximum age limit

This catches the “Guidewire from one old role” case.

---

## Why the user sees presets, not numbers

Users generally do not know what values like `8` vs `12` should be.
Those are implementation decisions, not meaningful user choices.

So the UI dropdown **Experience Focus** should ask for intent:

- `Recent Focus`
- `Balanced`
- `Full History`

and the engine should translate that into thresholds.

This keeps the rebuild flow understandable while still making the logic easy to change later.

---

## Relationship to manual editing

This logic only produces **default strengths during rebuild**.

After rebuild:

- the user can edit the capability strength manually
- the manual strength is the authority
- the aging logic does not exist to fight user edits

The point of this system is not to be perfect.
It is to generate a sane starting point that does not overstate stale experience.

---

## What to improve next

Likely improvement areas:

- distinguish “certified long ago” from “used long ago”
- detect stronger duration from condensed earlier-career summary text
- handle capabilities that resurface in side projects or AI tooling after long gaps
- reduce false promotion from crowded “key skills” sections
- improve phrase clustering so domain labels like `financial systems` are less blunt

Potential future refinement:

- combine CV recency with explicit user confirmation signals
- e.g. if the user keeps a capability at `strong`, treat that as a trusted override and reuse it across rebuilds

---

## What not to do

- do not let raw keyword presence imply current strength
- do not let repeated old mentions automatically become `strong`
- do not expose implementation thresholds in the main user path
- do not mix rebuild-only aging controls into everyday settings

---

## Current product rule

Clean UX rule:

- onboarding/rebuild asks for one visible aging preset
- advanced rebuild options can expose a small number of technical controls if needed
- everyday settings should not expose aging internals

That is the current intended shape unless evidence shows it is insufficient.
