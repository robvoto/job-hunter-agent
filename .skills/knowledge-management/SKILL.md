# Skill: Knowledge Management

Use before editing managed JSON knowledge, rule loaders, paths, or approval-backed runtime knowledge.

## Rules
- Business knowledge belongs in managed JSON/profile/config, not sealed Python constants.
- JSON knowledge must have one owner module, clear metadata, and validation.
- Do not dump arbitrary dictionaries into JSON without schema and meaning.
- Pending suggestions require approval before becoming trusted runtime knowledge.
- Feature code consumes owner loaders, not raw files.
- Consumers use canonical fields only; no alternate-key guessing.

## Owners
- `paths.py`: file paths.
- `profile_store.py`: profile, scoring, settings normalisation.
- `capability_knowledge.py`: capability knowledge.
- `hard_blocker_rules.py`: hard blocker patterns.
- `role_title_knowledge.py`: title knowledge.
- `job_quality.py`: quality-rule loaders and learnable CV-farming patterns.
- `signal_registry.py`: pending learned signals.

## Checklist
- Is this stable approved knowledge or a pending suggestion?
- Is there one owner/loader?
- Is schema validated at load/normalisation time?
- Are defaults explicit in the owner, not feature code?
- Are consumers using canonical fields only?
