# Skill: Dashboard UI

Use before editing FastAPI routes, templates, dashboard data, settings UI, or score/highlight display.

## Rules
- Dashboard UI displays canonical data; it must not recreate filtering, scoring, or preference logic.
- Keep admin/user display policy configurable when it is tunable behaviour.
- Do not hardcode display counts, labels, thresholds, or fallback text in templates or feature code.
- Settings UI must save/load through the same profile/settings normalisers as runtime code.
- Missing required settings or labels should fail clearly, not be invented in UI code.
- Route aliases such as `/dashboard`, `/workspace`, and `/` must stay intentional and documented.

## Owners
- `routes/`: HTTP routes.
- `templates/`: page rendering.
- `dashboard_data.py`: dashboard data transformation.
- `history.py`: viewed/applied/hidden state.
- `profile_store.py`: profile/settings normalisation.
- `data/parsing_rules.json`: display labels where already owned there.

## Checklist
- Is this display logic, not business judgement?
- Does UI consume canonical data from the owner module?
- Can admin/user-tunable display policy be changed without code?
- Are labels/settings validated before use?
- Did you run the smallest relevant server/template check?
