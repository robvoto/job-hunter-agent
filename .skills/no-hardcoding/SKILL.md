# Skill: No Hardcoding

Use before adding/changing thresholds, mappings, defaults, labels, scoring values, rule IDs, schema fields, or business judgement.

## Core rule
Business judgement must not hide in feature code.

## Forbidden
- Inline scoring maps, e.g. `{ "strong": 4, "working": 3 }`
- Local fallback defaults, e.g. `.get("bonus", 5)`
- Fallback display labels, e.g. `or "competitive signal"`
- Consumer-side schema guessing, e.g. `signal.get("fit_label") or signal.get("name")`
- Scattered raw strings for schema keys, rule IDs, categories, or decision reasons
- Numeric caps/slices that affect business or display policy without config ownership

## Required
- Use managed config/profile/knowledge loaders.
- Add named config only in the correct owner.
- Validate required config at the producer/normalizer boundary.
- Consumers use canonical fields directly, e.g. `signal["label"]`.
- If required data is missing, fix the producer; do not patch around it in consumers.

## Checklist
- Search for `.get(..., fallback)`.
- Search for `or "..."` fallback labels.
- Search for inline dicts mapping labels to points/weights.
- Search for numeric caps/slices that affect behaviour.
- Search for consumer-side alternate fields like `x or y`.
