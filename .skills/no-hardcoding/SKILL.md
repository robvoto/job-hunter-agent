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
- Do not add local fallback defaults for business values, decision labels, or display labels in feature code. If the owner does not provide the value, surface an explicit error or fix the owner.
- If the same label or copy is reused across summary, tooltip, and debug views, put it in the owning JSON/data file once and read it from there.

## Checklist
- Search for `.get(..., fallback)`.
- Search for `or "..."` fallback labels.
- Search for inline dicts mapping labels to points/weights.
- Search for numeric caps/slices that affect behaviour.
- Search for consumer-side alternate fields like `x or y`.

## Advanced settings ownership

Configurable/admin-tunable behaviour belongs in advanced settings — not feature code.

Rules:
- Global system behaviour belongs in global advanced settings.
- Advanced settings must be manageable from the Advanced Settings UI.
- Do not hardcode admin-tunable behaviour in Python/JS.
- If unsure whether a setting is global or candidate-specific, ask before implementing.
- Do not silently create candidate-specific settings.
