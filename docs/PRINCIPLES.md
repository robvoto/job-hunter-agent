# Principles — Job Hunter Agent

> Product and decision philosophy. This file explains how to think about changes. It is not a runtime rules file.

## Product intent

This is a strict, explainable job-fit system, not a vague recommender.

The system should find roles worth human attention, hide obvious mismatches, and make every decision inspectable. It should improve through explicit user review, not hidden magic.

## Filtering philosophy

- Avoid false positives, but do not create hidden false negatives.
- Competitive fit is preferred over merely transferable fit.
- Domain-heavy roles should not pass unless clearly supported by candidate evidence.
- Hard rejection is reserved for explicit blockers, not inferred weakness.
- Weak, basic, old, or uncertain capability evidence should normally reduce score or create a review signal, not silently reject a job.
- Questionable signals should be preserved with `needs_review: true` where relevant.

## Decision model

- Deterministic filters run before any LLM call.
- Titles are useful as a cheap first pass, but job-description evidence and profile fit matter more.
- The LLM is optional, constrained, and never the owner of hidden policy.
- The LLM may review and label fit; it must not create approved runtime knowledge by itself.
- The system should explain why a job was kept, rejected, hidden, or downgraded.

## Knowledge and learning

- Business judgement belongs in managed JSON-backed knowledge modules, not sealed Python constants.
- New learned patterns must enter the signal registry as pending review before affecting runtime behaviour.
- Approved knowledge is valuable state and should not be discarded or regenerated silently.
- Do not silently delete candidate or job signals during extraction; preserve doubtful signals for review.

## Profile truth model

- Source documents are the human truth.
- `data/profile.json` is the runtime machine truth.
- Settings is the maintenance surface for the runtime truth.
- Generated application outputs are derived artefacts, not primary sources.

## Change discipline

- Make small, targeted changes.
- Do not modify unrelated files.
- Do not reintroduce hidden scoring shortcuts or fixed dictionaries to force outcomes.
- Prefer warnings, review signals, neutral metrics, and configurable scoring over hard rejection.
- When uncertain, preserve evidence and surface it for review instead of dropping it.

