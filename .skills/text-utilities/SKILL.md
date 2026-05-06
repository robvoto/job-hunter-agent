# Skill: Text Utilities

Use before editing text normalisation, matching helpers, scoring source text, or description-trust utilities.

## Rules
- Utility code should stay judgement-free.
- Do not add business categories, labels, thresholds, or scoring policy here.
- Keep helpers small, deterministic, and reusable.
- Do not hide data loss in aggressive cleaning.
- Text utilities may normalise shape; they must not decide fit.
- Consumers should receive predictable canonical output.

## Owners
- `text_processing.py`: whitespace/dedup/text cleanup.
- `scoring_utils.py`: scoring source text and weighted points helper.
- `description_trust.py`: full-description confidence.
- `role_analysis.py`: role text bundles and context helpers.

## Checklist
- Is this truly generic utility logic?
- Could cleaning remove useful evidence?
- Is any business meaning leaking into utility code?
- Is output canonical and predictable?
- Did you run the smallest relevant utility check?
