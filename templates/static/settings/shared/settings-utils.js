import {
  bindCurrencyInput,
  parseCurrencyValue as parseCurrencyInputValue,
  setCurrencyInputValue,
} from '../../common/currency-input.js';

export const LINKEDIN_EASY_APPLY_ONLY = 'linkedin_easy_apply_only';

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
function toLines(value) {
  return value.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
}

function normalizeReviewText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function patternToLabel(pattern) {
  return normalizeReviewText(
    String(pattern || '')
      .replace(/\\b/g, '')
      .replace(/\\s\+/g, ' ')
      .replace(/\\ /g, ' ')
      .replace(/\\/g, '')
  );
}

function normalizeReviewTitle(value) {
  return patternToLabel(value) || normalizeReviewText(value);
}

function normalizeReviewTitleKey(value) {
  return normalizeReviewTitle(value).toLowerCase();
}

function dedupeReviewList(values) {
  const seen = new Set();
  const output = [];
  for (const value of values || []) {
    const cleaned = normalizeReviewTitle(value);
    const key = normalizeReviewTitleKey(cleaned);
    if (!cleaned || seen.has(key)) continue;
    seen.add(key);
    output.push(cleaned);
  }
  return output;
}

function normalizeReviewTitleLists(primaryValues, secondaryValues) {
  const primary = dedupeReviewList(primaryValues);
  const primarySeen = new Set(primary.map(normalizeReviewTitleKey));
  const secondary = [];
  const seenSecondary = new Set();
  for (const value of dedupeReviewList(secondaryValues)) {
    const key = normalizeReviewTitleKey(value);
    if (!key || primarySeen.has(key) || seenSecondary.has(key)) continue;
    seenSecondary.add(key);
    secondary.push(value);
  }
  return { primary, secondary };
}

function normalizeReviewCapability(rule) {
  const name = normalizeReviewText(rule?.name || '');
  const level = normalizeReviewText(rule?.level || '').toLowerCase();
  const aliases = [];
  const seen = new Set();
  for (const alias of Array.isArray(rule?.aliases) ? rule.aliases : []) {
    const cleaned = normalizeReviewText(alias).toLowerCase();
    if (!cleaned || cleaned === name.toLowerCase() || seen.has(cleaned)) continue;
    seen.add(cleaned);
    aliases.push(cleaned);
  }
  const icon_key = normalizeReviewText(rule?.icon_key || '').toLowerCase();
  return { name, level, aliases, icon_key };
}

function rulesToText(rules, key) {
  return (rules || []).map(rule => `${rule[key] || ''} || ${rule.reason || ''}`).join('\n');
}

function textToRules(value, key) {
  return toLines(value).map(line => {
    const parts = line.split('||');
    return {
      [key]: (parts[0] || '').trim(),
      reason: (parts[1] || '').trim(),
    };
  }).filter(rule => rule[key]);
}

const workModePreferenceOptions = Array.isArray(window.__JOB_HUNTER_WORK_MODE_PREFERENCE_OPTIONS__)
  ? window.__JOB_HUNTER_WORK_MODE_PREFERENCE_OPTIONS__
  : [];
const workModePreferenceDefaultValues = Array.isArray(window.__JOB_HUNTER_WORK_MODE_PREFERENCE_DEFAULT__)
  ? window.__JOB_HUNTER_WORK_MODE_PREFERENCE_DEFAULT__.map((value) => String(value || '').trim().toLowerCase()).filter(Boolean)
  : workModePreferenceOptions.map((option) => String(option.value || '').trim().toLowerCase()).filter(Boolean);
const engagementTypeOptions = Array.isArray(window.__JOB_HUNTER_ENGAGEMENT_TYPE_OPTIONS__)
  ? window.__JOB_HUNTER_ENGAGEMENT_TYPE_OPTIONS__
  : [];
const engagementTypeDefaultValues = Array.isArray(window.__JOB_HUNTER_ENGAGEMENT_TYPE_DEFAULT_VALUES__)
  ? window.__JOB_HUNTER_ENGAGEMENT_TYPE_DEFAULT_VALUES__
  : engagementTypeOptions.map((option) => option.value);
const engagementTypeValues = new Set(
  engagementTypeOptions
    .map((option) => String(option.value || '').trim().toLowerCase())
    .filter(Boolean)
);
const sectorPreferenceDefault = String(
  window.__JOB_HUNTER_SECTOR_PREFERENCE_DEFAULT__
  || 'any'
).trim().toLowerCase();
const workModePreferenceValues = new Set(
  workModePreferenceOptions
    .map((option) => String(option.value || '').trim().toLowerCase())
    .filter(Boolean)
);
function normalizeWorkModePreferences(value) {
  const values = Array.isArray(value)
    ? value
    : String(value || '').split(/[,\n|/]+/);
  const selected = [];
  const seen = new Set();
  for (const option of workModePreferenceOptions) {
    const key = String(option.value || '').trim().toLowerCase();
    if (!key) continue;
    if (values.some((item) => String(item || '').trim().toLowerCase() === key) && !seen.has(key)) {
      seen.add(key);
      selected.push(key);
    }
  }
  return selected;
}

function normalizeEngagementTypePreferences(value) {
  const values = Array.isArray(value)
    ? value
    : String(value || '').split(/[,\n|/]+/);
  const selected = [];
  const seen = new Set();
  for (const option of engagementTypeOptions) {
    const key = String(option.value || '').trim().toLowerCase();
    if (!key) continue;
    if (values.some((item) => String(item || '').trim().toLowerCase() === key) && !seen.has(key)) {
      seen.add(key);
      selected.push(key);
    }
  }
  if (selected.length) {
    return selected;
  }
  return engagementTypeDefaultValues.map((value) => String(value || '').trim().toLowerCase()).filter(Boolean);
}

function getWorkModePreferenceValues() {
  return normalizeWorkModePreferences(
    Array.from(document.querySelectorAll('input[name="work_mode_preference"]:checked')).map((input) => input.value)
  );
}

function setWorkModePreferenceValues(values) {
  const normalized = normalizeWorkModePreferences(values);
  const selected = new Set(normalized.length ? normalized : workModePreferenceDefaultValues);
  document.querySelectorAll('input[name="work_mode_preference"]').forEach((input) => {
    input.checked = selected.size === 0 || selected.has(String(input.value || '').trim().toLowerCase());
  });
}

function getEngagementTypeValues() {
  return normalizeEngagementTypePreferences(
    Array.from(document.querySelectorAll('input[name="engagement_type"]:checked')).map((input) => input.value)
  );
}

function setEngagementTypeValues(value) {
  const selected = new Set(normalizeEngagementTypePreferences(value));
  const inputs = Array.from(document.querySelectorAll('input[name="engagement_type"]'));
  inputs.forEach((input) => {
    input.checked = selected.size === 0 || selected.has(String(input.value || '').trim().toLowerCase());
  });
}

function normalizeSectorPreferenceValues(value) {
  const values = Array.isArray(value)
    ? value
    : String(value || '').split(/[,\n|/]+/);
  const inputs = Array.from(document.querySelectorAll('input[name="prefer_sector"]'));
  const selected = [];
  const seen = new Set();
  for (const input of inputs) {
    const key = String(input.value || '').trim().toLowerCase();
    if (!key) continue;
    if (values.some((item) => String(item || '').trim().toLowerCase() === key) && !seen.has(key)) {
      seen.add(key);
      selected.push(key);
    }
  }
  if (selected.length) {
    return selected;
  }
  return inputs.map((input) => String(input.value || '').trim().toLowerCase()).filter(Boolean);
}

function getSectorPreferenceValues() {
  return normalizeSectorPreferenceValues(
    Array.from(document.querySelectorAll('input[name="prefer_sector"]:checked')).map((input) => input.value)
  );
}

function setSectorPreferenceValues(value) {
  const selected = new Set(normalizeSectorPreferenceValues(value));
  document.querySelectorAll('input[name="prefer_sector"]').forEach((input) => {
    input.checked = selected.size === 0 || selected.has(String(input.value || '').trim().toLowerCase());
  });
}

function setToggleChecked(id, checked) {
  const input = document.getElementById(id);
  if (input) input.checked = Boolean(checked);
}

function getToggleChecked(id) {
  return Boolean(document.getElementById(id)?.checked);
}

function syncSourcePanelDisabledState(toggleId) {
  const toggleInput = document.getElementById(toggleId);
  const panel = toggleInput?.closest('.search-source-panel');
  if (!panel) return;
  const enabled = Boolean(toggleInput.checked);
  panel.classList.toggle('is-source-disabled', !enabled);
  panel.querySelectorAll('input, select, textarea').forEach((field) => {
    if (field === toggleInput) return;
    field.disabled = !enabled;
  });
}

function setChoiceGroupValue(name, value) {
  const inputs = Array.from(document.querySelectorAll(`input[name="${name}"]`));
  if (!inputs.length) {
    throw new Error(`Missing choice group for ${name}.`);
  }
  const selectedValue = String(value ?? '').trim();
  if (!selectedValue) {
    throw new Error(`Missing value for ${name}.`);
  }
  let matched = false;
  inputs.forEach((input) => {
    const checked = String(input.value || '').trim() === selectedValue;
    input.checked = checked;
    matched = matched || checked;
  });
  if (!matched) {
    throw new Error(`Invalid value for ${name}: ${selectedValue}`);
  }
}

function getChoiceGroupValue(name) {
  const value = String(document.querySelector(`input[name="${name}"]:checked`)?.value || '').trim();
  if (!value) {
    throw new Error(`Missing choice value for ${name}.`);
  }
  return value;
}

function ensureAtLeastOneChoiceSelected(name, changedInput) {
  const inputs = Array.from(document.querySelectorAll(`input[name="${name}"]`));
  if (!inputs.length || !changedInput || changedInput.checked) {
    return;
  }
  const anyChecked = inputs.some((input) => input.checked);
  if (!anyChecked) {
    changedInput.checked = true;
  }
}

function settingsField(id) {
  return document.getElementById(id);
}

function bindCurrencyFields(ids) {
  (ids || []).forEach((id) => bindCurrencyInput(document.getElementById(id)));
}

function setCurrencyFieldValue(id, value) {
  const input = (typeof id === 'string') ? document.getElementById(id) : id;
  if (!input) return;
  setCurrencyInputValue(input, value);
}

function readCurrencyFieldValue(id, fallback) {
  if (fallback === undefined) fallback = 0;
  const input = (typeof id === 'string') ? document.getElementById(id) : id;
  if (!input) return fallback;
  const parsed = parseCurrencyInputValue(input.value);
  return Number.isFinite(parsed) && parsed !== '' ? parsed : fallback;
}

function parseCurrencyValue(value) {
  return parseCurrencyInputValue(value);
}

export {
  escapeHtml,
  toLines,
  normalizeReviewText,
  patternToLabel,
  normalizeReviewTitleLists,
  normalizeReviewCapability,
  rulesToText,
  textToRules,
  settingsField,
  bindCurrencyFields,
  normalizeWorkModePreferences,
  getWorkModePreferenceValues,
  setWorkModePreferenceValues,
  normalizeEngagementTypePreferences,
  getEngagementTypeValues,
  setEngagementTypeValues,
  normalizeSectorPreferenceValues,
  getSectorPreferenceValues,
  setSectorPreferenceValues,
  setToggleChecked,
  getToggleChecked,
  syncSourcePanelDisabledState,
  setChoiceGroupValue,
  getChoiceGroupValue,
  ensureAtLeastOneChoiceSelected,
  engagementTypeValues as ENGAGEMENT_TYPE_VALUES,
  engagementTypeDefaultValues as ENGAGEMENT_TYPE_DEFAULT_VALUES,
  workModePreferenceValues as WORK_MODE_PREFERENCE_VALUES,
  sectorPreferenceDefault as SECTOR_PREFERENCE_DEFAULT,
  parseCurrencyValue,
  setCurrencyFieldValue,
  readCurrencyFieldValue,
};
