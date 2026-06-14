# UI Component Map

Quick reference for every interactive widget pattern in settings and onboarding. Before adding a new control, find the closest match here and reuse the pattern.

---

## Design standards and token rationale

These rules exist for accessibility and visual-hierarchy reasons. Do not change token values without understanding the rationale below.

### Touch target minimums

| Token | Value | Applies to |
|---|---|---|
| `--control-height-lg` | 40px | All interactive form controls: inputs, selects, textareas, and choice-strip chips |

**40px is the chosen standard for all form-context interactive controls.** Chips and inputs that appear in the same form row share the same height — this follows the Atlassian design system pattern where filter chips, dropdowns, and inputs align on a single baseline. WCAG 2.5.8 (Level AA) requires only 24px; 40px is well above that. Do not reduce below 36px without re-checking accessibility.

### Chip height is intentionally smaller than form controls

Chips (~34px) are always shorter than inputs/selects (~44px). This is correct and follows every major design system — Material Design chips are 32dp vs 56dp inputs (a 24dp gap). The difference signals visual hierarchy: chips are compact selection tokens; inputs and dropdowns are primary form controls. Do not attempt to equalise them.

### Typography scale

| Token | Resolved value | Used on |
|---|---|---|
| `--control-font-size` → `--text-role-control-label-font-size` | 0.92rem | All inputs, selects, textareas |
| `--field-label-font-size` | 0.92rem | Field labels — intentionally matches control text |
| `--text-role-chip-font-size` | 0.82rem | Chip labels — intentionally smaller than controls |
| `--help-copy-font-size` | 0.8rem | Help text / summary lines |

Chip text is smaller by design. Do not raise `--text-role-chip-font-size` to match controls — it would make chips visually indistinguishable from inputs.

### Token ownership chain

```
themes.tokens.css        ← primitive values only (sizes, colours, spacing)
       ↓
themes.widgets.css       ← component rules (min-height, font-size, padding on inputs/selects/chips)
       ↓
page CSS (settings-page.css, onboarding-page.css)
                         ← page-scoped layout exceptions only
```

**Cascade rule:** same specificity = later file wins. A rule in `themes.widgets.css` that is overridden by `settings-page.css` must be re-declared in `settings-page.css` after the conflicting rule, not in `themes.widgets.css` where it will lose.

**Reusable component styles always go in `themes.widgets.css`.** Page CSS only adds layout exceptions that are genuinely scoped to one page.

### Key spacing tokens

| Token | Value | Used for |
|---|---|---|
| `--field-label-control-gap` | 12px | Row-gap inside each field (label → control) |
| `--field-body-gap` | 18px | Gap between fields in `.settings-form-grid` |
| `--field-summary-gap` | 8px | Gap between control and summary/help line below chips |
| `--surface-gap-md` | 12px | Panel padding and subpanel field spacing |

`--field-label-control-gap` is also the grid row-gap inside every `.settings-form-field` and `.onb-field`. A `.summary-line` as a direct grid child receives this gap from above — compensate with `calc(var(--field-summary-gap) - var(--field-label-control-gap))` margin-top to achieve the intended gap.

---

## Choice strip (styled toggle buttons)

Used for: Work mode, Engagement type, Sector preference (settings)

**CSS class:** `choice-card--work-mode` — applies orange-on-dark button styling. This is the only styled card class. Do not invent new ones.

**Server render:**
```python
render_choice_strip(name=..., options=[{"value":..., "label":...}], selected_values=..., input_type="checkbox"|"radio", group_id=..., label_id=..., card_class="choice-card--work-mode")
```

**Specific helpers:**
| Control | Render function | Template token |
|---|---|---|
| Engagement type | `render_engagement_type_choices()` | `__JOB_HUNTER_ENGAGEMENT_TYPE_CHOICES__` |
| Work mode | `render_work_mode_preference_choices()` | `__JOB_HUNTER_WORK_MODE_PREFERENCE_CHOICES__` |
| Sector (settings) | `render_sector_preference_choices()` | `__JOB_HUNTER_SECTOR_PREFERENCE_CHOICES__` |

**JS (settings-utils.js exports):**
- `getEngagementTypeValues()` / `setEngagementTypeValues(value)`
- `getWorkModePreferenceValues()` / `setWorkModePreferenceValues(values)`
- `getSectorPreferenceValues()` / `setSectorPreferenceValues(value)`

---

## Toggle switch

Used for: Enable SEEK, Enable LinkedIn, Sort newest first (admin)

**HTML pattern:**
```html
<label class="toggle-switch" for="my_id">
  <span class="toggle-switch-copy">
    <span class="toggle-switch-title">Label</span>
    <span class="toggle-switch-state" id="my_id_state">Enabled</span>
  </span>
  <span class="toggle-switch-control">
    <input id="my_id" type="checkbox" role="switch" checked>
    <span class="toggle-switch-ui"></span>
  </span>
</label>
```

**JS (settings-utils.js exports):** `getToggleChecked(id)` / `setToggleChecked(id, bool)` / `setToggleStateText(stateId, bool, checkedLabel, uncheckedLabel)`

**Critical:** Never read a toggle's value with `.value === 'true'` — a checkbox `.value` is always `"on"`. Always use `.checked` via `getToggleChecked`.

---

## Select (dropdown)

Used for: Easy Apply filter, search date window, workspace minimum score, sector preference (onboarding)

Standard `<select id="...">` with hardcoded `<option>` elements or server-rendered via a render function.

**Sector options (onboarding only):** `render_sector_preference_select_options(selected_value=...)` replaces `__JOB_HUNTER_SECTOR_PREFERENCE_OPTIONS__`.

---

## Onboarding component map

Used for: onboarding wizard screens and their module owners.

| Component | Owned by | Notes |
|---|---|---|
| CV import drop zone | `templates/static/onboarding/onboarding-upload.js` | File validation, drop handling, and create-profile availability. |
| Wizard step shell / progress | `templates/static/onboarding/onboarding-page.js` and `templates/static/onboarding/onboarding-flow.js` | Step orchestration and navigation. |
| Search basics fields | `templates/static/onboarding/onboarding-storage.js` (event wiring) + `templates/static/onboarding/onboarding-search.js` (step-transition hydration) | Event handlers wired in storage.js; field hydration from DB profile in search.js. |
| Wizard state persistence | `templates/static/onboarding/onboarding-storage.js` | Save/restore wizard draft (user-scoped localStorage key) and search-basics DB persistence. |
| Review draft capability UI | `templates/static/onboarding/onboarding-flow.js` | Review rendering, filtering, and action buttons. |
| Import helper copy | `templates/static/onboarding/onboarding-page.js` and `templates/static/onboarding/onboarding-flow.js` | Page-level wiring plus action flow messages. |
| Location selector | `templates/static/onboarding/onboarding-storage.js` (change event) + `templates/static/onboarding/onboarding-search.js` (hydration) | Change event wired in storage.js; hydrated from DB profile by search.js. |
| Salary inputs | `templates/static/onboarding/onboarding-search.js` and `templates/static/settings/shared/settings-utils.js` | Shared currency helper, page-specific hydration from DB profile. |
| Continue / create buttons | `templates/static/onboarding/onboarding-upload.js` and `templates/static/onboarding/onboarding-flow.js` | Enabled state and step transitions. |

---

## Badge/chip editor

Used for: Search keywords, title patterns, must-not-require skills

```html
<div class="badge-editor" data-chip-editor="field_name">
  <div id="field_name_chips" class="badge-editor-list" aria-live="polite"></div>
  <div class="badge-editor-form">
    <input id="field_name_add" type="text" data-chip-input="field_name">
    <button type="button" data-add-chip="field_name">Add</button>
  </div>
</div>
<textarea id="field_name" class="technical-rule-source" aria-hidden="true" tabindex="-1"></textarea>
```

JS: `chipEditor.renderChipEditor('field_name')`, `chipEditor.flushChipEditorInputs()`.

---

## Currency input

Used for: Minimum salary, minimum daily rate

```html
<div class="currency-input-wrap">
  <span class="currency-prefix">$</span>
  <input id="my_field" type="text" inputmode="numeric" autocomplete="off" value="0">
</div>
```

JS: `setCurrencyFieldValue(id, value)` / `readCurrencyFieldValue(id, fallback)`. Bind with `bindCurrencyFields([id])`. Accepts element OR string ID.

---

## Bootstrap globals (all injected by `build_bootstrap_script`)

| Global | Used by |
|---|---|
| `__JOB_HUNTER_ENGAGEMENT_TYPE_OPTIONS__` | onboarding-flow.js, settings-utils.js |
| `__JOB_HUNTER_ENGAGEMENT_TYPE_DEFAULT_VALUES__` | settings-utils.js |
| `__JOB_HUNTER_WORK_MODE_PREFERENCE_OPTIONS__` | settings-utils.js |
| `__JOB_HUNTER_WORK_MODE_PREFERENCE_DEFAULT__` | settings-utils.js |
| `__JOB_HUNTER_WORK_MODE_PREFERENCE_NONE_LABEL__` | settings-utils.js |
| `__JOB_HUNTER_ONBOARDING_FLOW_LABELS__` | onboarding-flow.js |
| `__JOB_HUNTER_ONBOARDING_PAGE_LABELS__` | onboarding-page.js, settings-page.js (choice-strip summary labels) |
| `__JOB_HUNTER_ONBOARDING_IMPORT_SUMMARY_LABELS__` | onboarding-page.js, onboarding-flow.js |
| `__JOB_HUNTER_SECTOR_PREFERENCE_OPTIONS__` | onboarding-flow.js, onboarding-page.js |
| `__JOB_HUNTER_SECTOR_PREFERENCE_DEFAULT__` | settings-utils.js, onboarding-flow.js |
| `__JOB_HUNTER_TITLE_TIER_LABELS__` | onboarding-flow.js, onboarding-page.js |
| `__JOB_HUNTER_LLM_MODEL_OPTIONS__` | settings-page.js (LLM model dropdown fallback on non-admin page) |
| `__JOB_HUNTER_SALARY_LIMITS__` | currency UI |
| `__JOB_HUNTER_LOCATION_OPTIONS__` | location UI |
| `__JOB_HUNTER_CSRF_TOKEN__` | fetch helpers |

---

## Settings page: server-side template tokens

All resolved in `pages.py → _render_template_with_locations()`.

| Token | Replaced with |
|---|---|
| `__JOB_HUNTER_ENGAGEMENT_TYPE_CHOICES__` | `render_engagement_type_choices()` |
| `__JOB_HUNTER_WORK_MODE_PREFERENCE_CHOICES__` | `render_work_mode_preference_choices()` |
| `__JOB_HUNTER_WORK_MODE_PREFERENCE_HELP__` | `WORK_MODE_PREFERENCE_HELP_TEXT` |
| `__JOB_HUNTER_SECTOR_PREFERENCE_CHOICES__` | `render_sector_preference_choices()` |
| `__JOB_HUNTER_SECTOR_PREFERENCE_HELP__` | `SECTOR_PREFERENCE_HELP_TEXT` |
| `__JOB_HUNTER_SECTOR_PREFERENCE_OPTIONS__` | `render_sector_preference_select_options()` (onboarding select) |
| `__JOB_HUNTER_TITLE_TIER_TARGET_ROLES_LABEL__` | `title_tier_labels.target_roles_label` |
| `__JOB_HUNTER_TITLE_TIER_TARGET_ROLES_HELP__` | `title_tier_labels.target_roles_help` |
| `__JOB_HUNTER_TITLE_TIER_TARGET_ROLES_PLACEHOLDER__` | `title_tier_labels.target_roles_input_placeholder` |
| `__JOB_HUNTER_TITLE_TIER_TARGET_ROLES_EMPTY_TEXT__` | `title_tier_labels.target_roles_empty_text` |
| `__JOB_HUNTER_TITLE_TIER_MOVE_TO_TARGET_ROLES_LABEL__` | `title_tier_labels.move_to_target_roles_label` |
| `__JOB_HUNTER_TITLE_TIER_KEEP_TARGET_ROLES_CONTINUE_ERROR__` | `title_tier_labels.keep_target_roles_continue_error` |
| `__JOB_HUNTER_TITLE_TIER_KEEP_TARGET_ROLES_FINISH_ERROR__` | `title_tier_labels.keep_target_roles_finish_error` |
| `__JOB_HUNTER_TITLE_TIER_ALSO_CONSIDER_ROLES_LABEL__` | `title_tier_labels.also_consider_roles_label` |
| `__JOB_HUNTER_TITLE_TIER_ALSO_CONSIDER_ROLES_HELP__` | `title_tier_labels.also_consider_roles_help` |
| `__JOB_HUNTER_TITLE_TIER_ALSO_CONSIDER_ROLES_PLACEHOLDER__` | `title_tier_labels.also_consider_roles_input_placeholder` |
| `__JOB_HUNTER_TITLE_TIER_ALSO_CONSIDER_ROLES_EMPTY_TEXT__` | `title_tier_labels.also_consider_roles_empty_text` |
| `__JOB_HUNTER_TITLE_TIER_MOVE_TO_ALSO_CONSIDER_LABEL__` | `title_tier_labels.move_to_also_consider_label` |
| `__JOB_HUNTER_TITLE_TIER_SEARCH_KEYWORD_LABEL__` | `title_tier_labels.search_keyword_label` |
| `__JOB_HUNTER_TITLE_TIER_SEARCH_KEYWORD_HELP__` | `title_tier_labels.search_keyword_help` |
| `__JOB_HUNTER_TITLE_TIER_SEARCH_KEYWORD_EXAMPLE__` | `title_tier_labels.search_keyword_example` |
| `__JOB_HUNTER_SALARY_MIN_ANNUAL_LABEL__` | `SALARY_MIN_ANNUAL_LABEL` |
| `__JOB_HUNTER_SALARY_MIN_DAILY_LABEL__` | `SALARY_MIN_DAILY_LABEL` |
| `__JOB_HUNTER_SETTINGS_SALARY_ANNUAL_HELP__` | `SETTINGS_SALARY_ANNUAL_HELP_TEXT` |
| `__JOB_HUNTER_SETTINGS_SALARY_DAILY_HELP__` | `SETTINGS_SALARY_DAILY_HELP_TEXT` |

---

## Owners

| Layer | File |
|---|---|
| Server render helpers | `job_hunter_agent/server_helpers.py` |
| Template wiring | `job_hunter_agent/routes/pages.py` |
| Settings JS utils | `templates/static/settings/shared/settings-utils.js` |
| Settings page JS | `templates/static/settings/shared/settings-page.js` |
| CSS tokens/primitives | `templates/static/themes/` |
| Settings HTML partials | `templates/partials/settings/standard/` |
| Onboarding HTML | `templates/onboarding.html` |
