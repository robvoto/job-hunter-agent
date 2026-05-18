# Capability Aging & Strength Rationale

Private reference doc. Not committed to the repo.

This logic decides the default strength for extracted capabilities during rebuild.
It does not create a permanent truth. Manual edits in Settings still win.

## What the preset does

The onboarding UI shows one visible control:

- `Capability strength preset`

It maps to one of three preset names:

- `recent_focus`
- `balanced`
- `include_older_experience`

The numbers are implementation detail and live in managed settings.

## Internal levels

The code stores these internal levels:

- `strong`
- `working`
- `basic`

The UI presents them as:

- `strong` -> `Strong`
- `working` -> `Working`
- `basic` -> `Basic`

`Background` is not a stored level in the current code. It is only plain-English wording for very old evidence that should not count as current strength.

## How classification works

The classifier looks at two things:

- `Depth`: how much total experience exists
- `Freshness`: how recently that capability was used

Balanced preset at a glance:

- recent window: 4 years
- `strong`: used within 4 years and at least 36 months total
- `working`: used within 8 years and at least 18 months total
- deep older history can still stay `working` up to 12 years
- after 12 years, the level becomes `basic`

Simple reading:

- `strong` means the capability is recent and substantial
- `working` means the capability is still useful, but not strong enough for the top tier
- `basic` means the capability is real, but too old or too thin to count as current strength

## Why there is no role-count gate

The old `strong_min_roles` rule was removed.

Reason:

- a long current role can still be genuinely strong
- forcing two roles blocked real single-company experience
- recency and total depth are enough for the current model

So this is now false:

- "You must have used it in at least two jobs before it can be strong"

And this is true:

- "A long enough and recent enough current role can still be strong"

## What each preset means

- `recent_focus`: bias toward current usage and faster downgrade of stale evidence
- `balanced`: the default middle ground
- `include_older_experience`: keep older deep experience visible for longer

## How to read the age bands

The bands below are the mental model, not extra stored states:

| Last used | Result |
|-----------|--------|
| 0 to 4 years ago | `strong` can remain `strong` |
| 4 to 8 years ago | usually drops to `working` |
| 8 to 12 years ago | becomes `basic` |
| 12+ years ago | only background context, not a strength signal |

## What the user should remember

- Pick one preset in onboarding.
- Leave the numeric thresholds alone unless you are tuning the system.
- If a capability is still current and deep, it can be `strong` even from one long role.
- If a capability is old, it should become `basic` in storage and `Basic` in the UI.

## What not to do

- do not reintroduce a two-role requirement for `strong`
- do not treat `Background` as a real stored level
- do not expose the threshold numbers in the normal onboarding path
