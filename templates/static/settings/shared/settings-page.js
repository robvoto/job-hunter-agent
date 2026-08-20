import { JobHunterChipEditor as chipEditor } from './settings-chip-editor.js';
import { JobHunterCapabilityEditor as capabilityEditor } from './settings-capability-editor.js';
import { JobHunterClearanceEditor as clearanceEditor } from './settings-clearance-editor.js';
import { JobHunterEligibilityEditor as eligibilityEditor } from './settings-eligibility-editor.js';
import { JobHunterQualificationEditor as qualificationEditor } from './settings-qualification-editor.js';
import { JobHunterAdminSettings as adminSettings } from '../global/settings-admin.js';
import { JobHunterAlertsSettings as alertsSettings } from '../standard/settings-alerts.js';
import * as capabilityUi from '../../common/capability-ui.js';
import * as locationUi from '../../common/location-options.js';
import { createController as createMessageBannerController } from '../../common/message-banner.js';
import { bindSelectedChoicePopover, createAnchoredPopover } from '../../common/anchored-popover.js';
import {
  escapeHtml,
  toLines,
  rulesToText,
  textToRules,
  settingsField,
  bindCurrencyFields,
  getEngagementTypeValues,
  setEngagementTypeValues,
  getSectorPreferenceValues,
  setSectorPreferenceValues,
  setCurrencyFieldValue,
  readCurrencyFieldValue,
  getWorkModePreferenceValues,
  setWorkModePreferenceValues,
  setToggleChecked,
  getToggleChecked,
  syncSourcePanelDisabledState,
  setChoiceGroupValue,
  getChoiceGroupValue,
  LINKEDIN_EASY_APPLY_ONLY,
  SECTOR_PREFERENCE_DEFAULT,
  ensureAtLeastOneChoiceSelected,
} from './settings-utils.js';

const statusEl = document.getElementById('status');
const statusUi = createMessageBannerController(statusEl);
const isTestMode = document.body?.dataset.testMode === 'true';
const capabilityLabels = capabilityUi.labels || {};
const sharedUiLabels = window.__JOB_HUNTER_SHARED_UI_LABELS__;
const roleHistoryLabels = window.__JOB_HUNTER_ROLE_HISTORY_LABELS__;
if (!sharedUiLabels) {
  throw new Error('Missing shared UI labels.');
}
if (!roleHistoryLabels) {
  throw new Error('Missing role history labels.');
}

const capabilityMatrixNav = document.getElementById('settings_capability_matrix_nav');
if (capabilityMatrixNav && capabilityLabels.matching_nav_label) {
  capabilityMatrixNav.textContent = capabilityLabels.matching_nav_label;
}

function applyRoleHistoryUiLabels() {
  const title = document.getElementById('role_history_title');
  const help = document.getElementById('role_history_help');
  const refreshBtn = document.getElementById('refresh_role_history_from_saved_cv');
  if (title) title.textContent = roleHistoryLabels.settings_title;
  if (help) help.textContent = roleHistoryLabels.help_text;
  if (refreshBtn) refreshBtn.textContent = roleHistoryLabels.refresh_button_label;
}
applyRoleHistoryUiLabels();
const fillUserSettings = (s) => alertsSettings.fillUserSettings(s);
const collectUserSettings = () => alertsSettings.collectUserSettings(loadedUserSettings);

const sectorPreferenceDefault = String(SECTOR_PREFERENCE_DEFAULT || 'any').trim().toLowerCase();
function readOnboardingWelcomeSearchKeywords() {
  try {
    const raw = window.localStorage.getItem('jobHunter.onboardingWelcome');
    if (!raw) return '';
    const parsed = JSON.parse(raw);
    return String(parsed?.search_keywords || '').trim();
  } catch {
    return '';
  }
}

function validateSearchKeywords(keyword) {
  const text = String(keyword || '').trim();
  if (!text) {
    return;
  }
  if (text.length < 2 || text.length > 120) {
    throw new Error('Please keep the search keyword between 2 and 120 characters.');
  }
  if (text.split(/\s+/).filter(Boolean).length < 2) {
    throw new Error('Please use at least two words for the search title, or leave it blank.');
  }
}

let loadedUserSettings = null;
const SEEK_QUICK_APPLY_ONLY = 'seek_quick_apply_only';

let loadedProfile = null;
let loadedGlobalSettings = null;
let loadedSourceMaterials = null;
let suppressDirtyTracking = true;
const pageMode = document.body?.dataset.pageMode === 'admin' ? 'admin' : 'settings';
const isAdminPage = pageMode === 'admin';
const isUserAdmin = isAdminPage || !!document.querySelector('.sidebar-nav .nav-item-admin');
const bootstrapGlobalSettings = window.__JOB_HUNTER_GLOBAL_SETTINGS__ || null;

document.querySelectorAll('[data-test-only]').forEach((element) => { element.hidden = !isTestMode; });
document.querySelectorAll('[data-debug-only]').forEach((element) => { element.hidden = !isTestMode; });
document.querySelectorAll('[data-admin-only]').forEach((element) => { element.hidden = !isUserAdmin; });
document.querySelectorAll('[data-screen]').forEach((element) => {
  element.hidden = element.dataset.screen !== pageMode;
});

if (isAdminPage && bootstrapGlobalSettings) {
  loadedGlobalSettings = bootstrapGlobalSettings;
  adminSettings.fillGlobalForm(bootstrapGlobalSettings);
  adminSettings.loadGlobalSettingsHelp?.();
  adminSettings.initRuntimeMaintenanceControls?.(showStatus);
  adminSettings.initKnowledgeSyncControls?.(showStatus);
  adminSettings.initRejectionHistorySyncControls?.(showStatus);
  adminSettings.initSystemWarningsControls?.(showStatus);
  renderLlmModelOptions();
}

const ruleTextAreas = [
  ['reject_title_rules', 'pattern'],
  ['reject_description_phrase_rules', 'phrase'],
];

function formatRoleExperienceDuration(months) {
  const totalMonths = Number.isFinite(Number(months)) ? Number(months) : 0;
  if (totalMonths <= 0) return '0 months';
  const years = Math.floor(totalMonths / 12);
  const remainderMonths = totalMonths % 12;
  const parts = [];
  if (years > 0) parts.push(`${years} year${years === 1 ? '' : 's'}`);
  if (remainderMonths > 0) parts.push(`${remainderMonths} month${remainderMonths === 1 ? '' : 's'}`);
  return parts.join(' ');
}

function renderRoleExperienceReadonly(profile) {
  const container = document.getElementById('role_experience_readonly');
  if (!container) return;
  const rows = Array.isArray(profile?.role_experience) ? profile.role_experience : [];
  if (!rows.length) {
    container.innerHTML = `<p class="panel-copy">${escapeHtml(roleHistoryLabels.empty_text)}</p>`;
    return;
  }
  container.innerHTML = rows.map((row) => {
    const title = escapeHtml(String(row?.normalized_title || '').trim() || 'Untitled role');
    const totalMonths = Number(row?.total_duration_months || 0);
    const endYear = Number(row?.most_recent_end_year || 0);
    const variants = Array.isArray(row?.title_variants) ? row.title_variants : [];
    const variantHtml = variants.length
      ? `<div class="capability-card-meta">${
          variants.map((variant) => {
            const variantTitle = escapeHtml(String(variant?.normalized_title || '').trim() || 'untitled');
            const variantMonths = formatRoleExperienceDuration(Number(variant?.total_duration_months || 0));
            const variantEndYear = Number(variant?.most_recent_end_year || 0);
            const variantSuffix = variantEndYear > 0 ? ` · most recent end year ${variantEndYear}` : '';
            return `<div>${variantTitle}: ${escapeHtml(variantMonths)}${escapeHtml(variantSuffix)}</div>`;
          }).join('')
        }</div>`
      : '';
    const summary = `${formatRoleExperienceDuration(totalMonths)} total`;
    const endYearCopy = endYear > 0 ? `Most recent end year ${endYear}` : 'Most recent end year unknown';
    return `
      <article class="capability-card">
        <div class="capability-card-main">
          <div class="capability-card-head">
            <strong class="capability-group-title">${title}</strong>
          </div>
          <div class="capability-card-meta">
            <div>${escapeHtml(summary)}</div>
            <div>${escapeHtml(endYearCopy)}</div>
          </div>
          ${variantHtml}
        </div>
      </article>
    `;
  }).join('');
}

function buildCapturedCvText(sourceMaterials) {
  const profileSources = Array.isArray(sourceMaterials?.profile_sources)
    ? sourceMaterials.profile_sources
    : [];
  if (profileSources.length !== 1) {
    return '';
  }
  return String(profileSources[0]?.content || '').trim();
}

function renderCapturedCvText(sourceMaterials) {
  const field = document.getElementById('cv_text_debug');
  if (!field) return;
  field.value = buildCapturedCvText(sourceMaterials);
}

export function hideStatus() {
  statusUi.hide();
}

export function showStatus(message, kind, options = {}) {
  statusUi.show(message, kind, options);
}

export function showInlineStatus(element, message, kind) {
  if (!element) return;
  element.textContent = message;
  element.className = `inline-status ${kind}`;
}

function normalizeSummaryWhitespace(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function normalizeSummaryList(values) {
  if (!Array.isArray(values)) return [];
  return values
    .map((value) => normalizeSummaryWhitespace(value))
    .filter(Boolean);
}

function fieldLabelText(fieldId) {
  const field = document.getElementById(fieldId);
  const label = document.querySelector(`label[for="${fieldId}"]`);
  const labelText = label ? normalizeSummaryWhitespace(label.textContent) : '';
  const sourceTitle = field?.closest('.search-source-panel')
    ?.querySelector('.search-source-title');
  const sourceText = normalizeSummaryWhitespace(sourceTitle?.textContent || '');
  return sourceText && labelText ? `${sourceText} ${labelText}` : labelText;
}

function formatSummaryBoolean(value) {
  return value ? sharedUiLabels.settings_value_on : sharedUiLabels.settings_value_off;
}

function formatSummaryText(value) {
  const text = normalizeSummaryWhitespace(value);
  return text || sharedUiLabels.settings_value_blank;
}

function formatSummaryList(values) {
  const normalized = normalizeSummaryList(values);
  return normalized.length ? normalized.join(', ') : sharedUiLabels.settings_value_none;
}

function formatSummaryCurrency(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount) || amount <= 0) {
    return sharedUiLabels.settings_value_not_set;
  }
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: 'AUD',
    maximumFractionDigits: 0,
  }).format(amount);
}

function formatSummarySelect(fieldId, value) {
  const select = document.getElementById(fieldId);
  if (!select) return formatSummaryText(value);
  const match = Array.from(select.options).find((option) => String(option.value) === String(value));
  const text = normalizeSummaryWhitespace(match?.textContent || '');
  return text || formatSummaryText(value);
}

function formatSummaryTime(value) {
  const text = normalizeSummaryWhitespace(value);
  return text || sharedUiLabels.settings_value_not_set;
}

function captureCandidateSettingsSnapshot(profile, userSettings) {
  const normalizedProfile = profile || {};
  const normalizedUserSettings = userSettings || {};
  const enabledSources = Array.isArray(normalizedProfile.enabled_sources)
    ? normalizedProfile.enabled_sources.map((value) => String(value || '').trim().toLowerCase())
    : [];
  return {
    searchKeyword: normalizedProfile.search_settings?.keywords || '',
    locations: normalizedProfile.search_settings?.locations || [],
    searchDateWindow: normalizedProfile.search_settings?.date_range_days ?? '',
    seekMaxPages: normalizedProfile.search_settings?.seek_max_pages ?? '',
    seekQuickApplyOnly: normalizedProfile.search_settings?.seek_quick_apply_only ?? '',
    linkedinResultsPerSearch: normalizedProfile.search_settings?.linkedin_results_per_search ?? '',
    linkedinEasyApplyOnly: normalizedProfile.search_settings?.linkedin_easy_apply_only ?? '',
    apsjobsResultsPerSearch: normalizedProfile.search_settings?.apsjobs_results_per_search ?? '',
    minimumSalaryYearly: normalizedProfile.salary_preferences?.minimum_salary_yearly ?? 0,
    minimumDailyRate: normalizedProfile.salary_preferences?.minimum_daily_rate ?? 0,
    targetRoles: normalizedProfile.target_roles || [],
    alsoConsiderRoles: normalizedProfile.also_consider_roles || [],
    mustNotRequireSkills: normalizedProfile.must_not_require_skills || [],
    engagementType: normalizedProfile.match_preferences?.engagement_type || [],
    workModePreference: normalizedProfile.match_preferences?.work_mode_preference || [],
    sectorPreference: normalizedProfile.match_preferences?.prefer_sector || '',
    minContractMonths: normalizedProfile.match_preferences?.min_contract_months ?? '',
    preferenceWeights: normalizedProfile.preference_weights || {},
    seekEnabled: enabledSources.includes('seek'),
    linkedinEnabled: enabledSources.includes('linkedin'),
    apsjobsEnabled: enabledSources.includes('apsjobs'),
    scheduleEnabled: Boolean(normalizedUserSettings.schedule?.enabled),
    scheduleTimeLocal: normalizedUserSettings.schedule?.daily_time_local || '',
    telegramEnabled: Boolean(normalizedUserSettings.telegram?.enabled),
    telegramBotUsername: normalizedUserSettings.telegram?.bot_username || '',
    telegramDisableLinkPreview: Boolean(normalizedUserSettings.telegram?.disable_link_preview),
    llmModel: normalizedUserSettings.llm?.model || '',
  };
}

const candidateSettingsSummaryFields = [
  { key: 'searchKeyword', path: 'search_settings.keywords', fieldId: 'keywords', format: formatSummaryText },
  { key: 'locations', path: 'search_settings.locations', fieldId: 'locations', format: formatSummaryList },
  { key: 'searchDateWindow', path: 'search_settings.date_range_days', fieldId: 'search_date_window', format: (value) => formatSummarySelect('search_date_window', value) },
  { key: 'seekMaxPages', path: 'search_settings.seek_max_pages', fieldId: 'seek_max_pages', format: formatSummaryText },
  { key: 'seekQuickApplyOnly', path: 'search_settings.seek_quick_apply_only', fieldId: 'seek_quick_apply_only', format: formatSummaryText },
  { key: 'linkedinResultsPerSearch', path: 'search_settings.linkedin_results_per_search', fieldId: 'linkedin_results_per_search', format: formatSummaryText },
  { key: 'linkedinEasyApplyOnly', path: 'search_settings.linkedin_easy_apply_only', fieldId: 'linkedin_easy_apply_only', format: formatSummaryText },
  { key: 'apsjobsResultsPerSearch', path: 'search_settings.apsjobs_results_per_search', fieldId: 'apsjobs_results_per_search', format: formatSummaryText },
  { key: 'minimumSalaryYearly', path: 'salary_preferences.minimum_salary_yearly', fieldId: 'minimum_salary_yearly', format: formatSummaryCurrency },
  { key: 'minimumDailyRate', path: 'salary_preferences.minimum_daily_rate', fieldId: 'minimum_daily_rate', format: formatSummaryCurrency },
  { key: 'targetRoles', path: 'target_roles', fieldId: 'target_roles', format: formatSummaryList },
  { key: 'alsoConsiderRoles', path: 'also_consider_roles', fieldId: 'also_consider_roles', format: formatSummaryList },
  { key: 'mustNotRequireSkills', path: 'must_not_require_skills', fieldId: 'must_not_require_skills', format: formatSummaryList },
  { key: 'engagementType', path: 'match_preferences.engagement_type', fieldId: 'engagement_type_label', format: formatSummaryList },
  { key: 'workModePreference', path: 'match_preferences.work_mode_preference', fieldId: 'work_mode_preference_label', format: formatSummaryList },
  { key: 'sectorPreference', path: 'match_preferences.prefer_sector', fieldId: 'sector_preference_label', format: formatSummaryText },
  { key: 'minContractMonths', path: 'match_preferences.min_contract_months', fieldId: 'min_contract_months', format: formatSummaryText },
  { key: 'seekEnabled', path: 'enabled_sources', fieldId: 'seek_enabled', format: formatSummaryBoolean },
  { key: 'linkedinEnabled', path: 'enabled_sources', fieldId: 'linkedin_enabled', format: formatSummaryBoolean },
  { key: 'apsjobsEnabled', path: 'enabled_sources', fieldId: 'apsjobs_enabled', format: formatSummaryBoolean },
  { key: 'scheduleEnabled', path: 'schedule.enabled', fieldId: 'schedule_enabled', format: formatSummaryBoolean, scope: 'user_settings' },
  { key: 'scheduleTimeLocal', path: 'schedule.daily_time_local', fieldId: 'schedule_daily_time_local', format: formatSummaryTime, scope: 'user_settings' },
  { key: 'telegramEnabled', path: 'telegram.enabled', fieldId: 'telegram_enabled', format: formatSummaryBoolean, scope: 'user_settings' },
  { key: 'telegramBotUsername', path: 'telegram.bot_username', fieldId: 'telegram_bot_username', format: formatSummaryText, scope: 'user_settings' },
  { key: 'telegramDisableLinkPreview', path: 'telegram.disable_link_preview', fieldId: 'telegram_disable_link_preview', format: formatSummaryBoolean, scope: 'user_settings' },
  { key: 'llmModel', path: 'llm.model', fieldId: 'llm_model', format: formatSummaryText, scope: 'user_settings' },
];

function collectSettingsDiffs(before, after, path = [], diffs = []) {
  if (before && typeof before === 'object' && !Array.isArray(before)
      && after && typeof after === 'object' && !Array.isArray(after)) {
    const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
    [...keys].sort().forEach((key) => {
      collectSettingsDiffs(before[key], after[key], [...path, key], diffs);
    });
    return diffs;
  }
  if (JSON.stringify(before) !== JSON.stringify(after)) {
    diffs.push({ path: path.join('.'), before, after });
  }
  return diffs;
}

function formatGenericSummaryValue(value) {
  if (value === null || value === undefined || value === '') {
    return sharedUiLabels.settings_value_not_set;
  }
  if (typeof value === 'boolean') return formatSummaryBoolean(value);
  if (Array.isArray(value)) return value.length ? value.join(', ') : sharedUiLabels.settings_value_none;
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function buildCandidateSettingsSaveMessage(beforeProfile, beforeUserSettings, afterProfile, afterUserSettings) {
  const beforeSnapshot = captureCandidateSettingsSnapshot(beforeProfile, beforeUserSettings);
  const afterSnapshot = captureCandidateSettingsSnapshot(afterProfile, afterUserSettings);
  const lines = [];
  const coveredDiffs = new Set();

  candidateSettingsSummaryFields.forEach((field) => {
    const beforeValue = beforeSnapshot[field.key];
    const afterValue = afterSnapshot[field.key];
    if (JSON.stringify(beforeValue) === JSON.stringify(afterValue)) {
      return;
    }
    const label = fieldLabelText(field.fieldId);
    if (!label) {
      return;
    }
    lines.push(`${label}: ${field.format(beforeValue)} -> ${field.format(afterValue)}`);
    coveredDiffs.add(`${field.scope || 'profile'}.${field.path}`);
  });

  const genericDiffs = [
    ...collectSettingsDiffs(beforeProfile, afterProfile).map((diff) => ({ ...diff, scope: 'profile' })),
    ...collectSettingsDiffs(beforeUserSettings, afterUserSettings).map((diff) => ({ ...diff, scope: 'user_settings' })),
  ];
  genericDiffs.forEach((diff) => {
    const qualifiedPath = `${diff.scope}.${diff.path}`;
    if (coveredDiffs.has(qualifiedPath)) return;
    lines.push(`${qualifiedPath}: ${formatGenericSummaryValue(diff.before)} -> ${formatGenericSummaryValue(diff.after)}`);
  });

  if (!lines.length) {
    return [
      sharedUiLabels.settings_saved_success,
      sharedUiLabels.settings_saved_no_effective_changes,
    ].join('\n');
  }

  return [
    sharedUiLabels.settings_saved_success,
    sharedUiLabels.settings_saved_changes_heading,
    ...lines,
  ].join('\n');
}

export function markDirty() {
  if (suppressDirtyTracking) return;
  if (activeSaveButton) activeSaveButton.disabled = false;
  if (stickySaveBar) {
    stickySaveBar.hidden = false;
    stickySaveBar.dataset.dirty = 'true';
  }
}

export function clearDirty() {
  if (activeSaveButton) activeSaveButton.disabled = true;
  if (stickySaveBar) {
    stickySaveBar.hidden = true;
    delete stickySaveBar.dataset.dirty;
  }
  showInlineStatus(globalStatus, '', '');
}

function renderLlmModelOptions() {
  const select = document.getElementById('llm_model');
  if (!select) return;
  const modelOptions = loadedGlobalSettings?.llm_settings?.model_options
    ?? window.__JOB_HUNTER_LLM_MODEL_OPTIONS__;
  const options = Array.isArray(modelOptions)
    ? modelOptions.map(model => String(model || '').trim()).filter(Boolean)
    : [];
  const currentModel = String(loadedUserSettings?.llm?.model || '').trim();
  const mergedOptions = currentModel && !options.includes(currentModel)
    ? [currentModel, ...options]
    : options;
  select.innerHTML = ['<option value="">Select a model</option>']
    .concat(mergedOptions.map(model => `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`))
    .join('');
  if (currentModel) select.value = currentModel;
}


function getLocationInputs() {
  const container = document.getElementById('locations');
  if (!container) return [];
  return Array.from(container.querySelectorAll('input[type="checkbox"][data-location-value]'));
}

function getSelectedLocationValues() {
  return getLocationInputs()
    .filter((input) => input.checked)
    .map((input) => String(input.dataset.locationValue || '').trim())
    .filter(Boolean);
}

function syncLocationSelectionLimit() {
  const inputs = getLocationInputs();
  const configuredMax = loadedGlobalSettings?.limits?.search?.locations_max_selected?.max;
  const maxSelected = Number(configuredMax);
  if (!Number.isFinite(maxSelected) || maxSelected < 1) return;
  const selectedCount = inputs.filter((input) => input.checked).length;
  inputs.forEach((input) => {
    input.disabled = !input.checked && selectedCount >= maxSelected;
  });
}

function renderLocationOptions() {
  const container = document.getElementById('locations');
  if (!container || !locationUi.renderLocationOptions) return;
  const options = Array.isArray(locationUi.options)
    ? locationUi.options.filter((option) => ['state', 'territory', 'city'].includes(String(option?.kind || '').trim().toLowerCase()))
    : [];
  const savedValues = new Set(
    (loadedProfile?.search_settings?.locations || [])
      .map((value) => String(value || '').trim())
      .filter(Boolean)
  );
  const grouped = new Map();
  options.forEach((option) => {
    const group = String(option?.group || '').trim();
    if (!group) return;
    if (!grouped.has(group)) grouped.set(group, []);
    grouped.get(group).push(option);
  });
  container.innerHTML = '';
  grouped.forEach((groupOptions, group) => {
    const section = document.createElement('fieldset');
    section.className = ['checkbox-list-group', 'location-checkbox-group', groupOptions.length > 6 ? 'checkbox-list-group--dense' : ''].filter(Boolean).join(' ');
    const legend = document.createElement('legend');
    legend.textContent = group;
    section.appendChild(legend);
    const optionsWrap = document.createElement('div');
    optionsWrap.className = 'checkbox-list-options location-checkbox-options';
    groupOptions.forEach((option) => {
      const value = String(option?.value || '').trim();
      const label = String(option?.label || '').trim();
      if (!value || !label) return;
      const item = document.createElement('label');
      item.className = 'checkbox-list-option location-checkbox-option';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.className = 'jh-checkbox';
      input.dataset.locationValue = value;
      input.checked = savedValues.has(value);
      input.addEventListener('change', () => {
        syncLocationSelectionLimit();
        markDirty();
      });
      const text = document.createElement('span');
      text.textContent = label;
      item.append(input, text);
      optionsWrap.appendChild(item);
    });
    section.appendChild(optionsWrap);
    container.appendChild(section);
  });
  syncLocationSelectionLimit();
}

function buildSettingsHelpDrawer(bodyHtml, extraClass = '') {
  const drawer = document.createElement('details');
  drawer.className = ['field-info-drawer', 'settings-help-drawer', extraClass].filter(Boolean).join(' ');

  const summary = document.createElement('summary');
  summary.className = 'field-info';
  summary.setAttribute('aria-label', 'Help');
  summary.textContent = 'i';

  const panel = document.createElement('div');
  panel.className = 'field-info-panel';
  panel.innerHTML = bodyHtml;

  drawer.append(summary, panel);
  return drawer;
}

function findFieldLabelForHelp(node) {
  let cursor = node.previousElementSibling;
  while (cursor) {
    if (cursor.matches('label')) {
      return cursor;
    }
    if (cursor.matches('.field-label-row')) {
      return null;
    }
    cursor = cursor.previousElementSibling;
  }
  return null;
}

function upgradeSettingsHelpBlocks() {
  const scope = document.querySelector('.settings-main') || document;

  scope.querySelectorAll('.settings-group .field-help').forEach((node) => {
    if (node.closest('details.help-drawer, details.field-info-drawer')) return;
    const bodyHtml = node.innerHTML.trim();
    if (!bodyHtml) return;
    const label = findFieldLabelForHelp(node);
    if (!label || label.closest('.field-label-row')) return;
    const row = document.createElement('div');
    row.className = 'field-label-row';
    label.parentNode.insertBefore(row, label);
    row.appendChild(label);
    row.appendChild(buildSettingsHelpDrawer(bodyHtml));
    node.remove();
  });
}

function initFieldInfoDrawers() {
  const drawers = Array.from(document.querySelectorAll('details.field-info-drawer'));
  if (!drawers.length) return;
  const closeAll = (exceptDrawer = null) => {
    drawers.forEach((drawer) => {
      if (drawer !== exceptDrawer) {
        drawer.open = false;
      }
    });
  };
  drawers.forEach((drawer) => {
    drawer.addEventListener('toggle', () => {
      if (drawer.open) closeAll(drawer);
    });
  });
  document.addEventListener('click', (event) => {
    if (event.target.closest('details.field-info-drawer')) return;
    closeAll();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeAll();
  });
}

upgradeSettingsHelpBlocks();
initFieldInfoDrawers();

function collectProfile() {
  chipEditor.flushChipEditorInputs();
  const searchDateWindow = Number(document.getElementById('search_date_window')?.value || '3');
  const hoursMap = { 0: 720, 1: 24, 3: 72, 7: 168, 15: 360, 30: 720 };
  const seekQuickApplyRaw = document.getElementById(SEEK_QUICK_APPLY_ONLY)?.value;
  const linkedinEasyApplyRaw = document.getElementById(LINKEDIN_EASY_APPLY_ONLY)?.value;
  const sectorPreferenceValues = getSectorPreferenceValues();
  const seekMaxPages = Number(getChoiceGroupValue('seek_max_pages'));
  if (!Number.isFinite(seekMaxPages)) {
    throw new Error('Please choose a valid SEEK page limit.');
  }
  validateSearchKeywords(settingsField('keywords').value);
  const engagementTypeValues = getEngagementTypeValues();
  const contractEnabled = engagementTypeValues.includes('contract') || engagementTypeValues.includes('full_time_contract');
  const minContractEl = document.getElementById('min_contract_months');
  return {
    search_settings: {
      keywords: String(settingsField('keywords').value || '').trim(),
      locations: getSelectedLocationValues(),
      classification_ids: toLines(document.getElementById('classification_ids').value),
      date_range_days: searchDateWindow === 0 ? 30 : searchDateWindow,
      linkedin_hours_old: hoursMap[searchDateWindow] ?? 72,
      seek_max_pages: seekMaxPages,
      [SEEK_QUICK_APPLY_ONLY]: seekQuickApplyRaw === '' ? null : seekQuickApplyRaw === 'true',
      linkedin_results_per_search: Number(document.getElementById('linkedin_results_per_search').value) || 25,
      [LINKEDIN_EASY_APPLY_ONLY]: linkedinEasyApplyRaw === '' ? null : linkedinEasyApplyRaw === 'true',
      apsjobs_results_per_search: Number(document.getElementById('apsjobs_results_per_search').value) || 25,
    },
    salary_preferences: {
      minimum_salary_yearly: readCurrencyFieldValue('minimum_salary_yearly', 0),
      minimum_daily_rate: readCurrencyFieldValue('minimum_daily_rate', 0),
    },
    match_preferences: {
      engagement_type: engagementTypeValues,
      work_mode_preference: getWorkModePreferenceValues(),
      prefer_sector: sectorPreferenceValues.length === 1 ? sectorPreferenceValues[0] : sectorPreferenceDefault,
      min_contract_months: contractEnabled ? (minContractEl?.value || null) : null,
    },
    preference_weights: {
      fit: Number(document.getElementById('fit_weight').value || 1),
      salary: Number(document.getElementById('salary_weight').value || 1),
      location: Number(document.getElementById('location_weight').value || 1),
      work_mode: Number(document.getElementById('work_mode_weight').value || 1),
      contract: Number(document.getElementById('contract_weight').value || 1),
      government: Number(document.getElementById('government_weight').value || 1),
      freshness: Number(document.getElementById('freshness_weight').value || 1),
    },
    candidate_capabilities: capabilityEditor.collectCapabilityRuleState(),
    candidate_eligibility: clearanceEditor.collectClearanceRuleState(),
    candidate_eligibility_facts: eligibilityEditor.collectEligibilityFactState(),
    candidate_qualifications: qualificationEditor.collectQualificationState(),
    target_roles: toLines(settingsField('target_roles').value),
    also_consider_roles: toLines(settingsField('also_consider_roles').value),
    explore_adjacent_roles: getToggleChecked('explore_adjacent_roles'),
    must_not_require_skills: toLines(settingsField('must_not_require_skills').value),
    reject_title_rules: textToRules(settingsField('reject_title_rules').value, 'pattern'),
    reject_description_phrase_rules: textToRules(settingsField('reject_description_phrase_rules').value, 'phrase'),
    enabled_sources: [
      ...(getToggleChecked('seek_enabled') ? ['seek'] : []),
      ...(getToggleChecked('linkedin_enabled') ? ['linkedin'] : []),
      ...(getToggleChecked('apsjobs_enabled') ? ['apsjobs'] : []),
    ],
  };
}

function fillForm(profile) {
  const savedKeywords = String(profile.search_settings?.keywords || '').trim();
  const onboardingKeywords = savedKeywords ? '' : readOnboardingWelcomeSearchKeywords();
  settingsField('keywords').value = savedKeywords || onboardingKeywords || '';
  renderLocationOptions();
  document.getElementById('classification_ids').value = (profile.search_settings?.classification_ids || []).join('\n');
  setChoiceGroupValue('seek_max_pages', profile.search_settings?.seek_max_pages);
  const _seekQuickApply = profile.search_settings?.[SEEK_QUICK_APPLY_ONLY];
  document.getElementById(SEEK_QUICK_APPLY_ONLY).value = (_seekQuickApply === null || _seekQuickApply === undefined) ? '' : String(_seekQuickApply);
  document.getElementById('linkedin_results_per_search').value = String(profile.search_settings?.linkedin_results_per_search);
  document.getElementById('apsjobs_results_per_search').value = String(profile.search_settings?.apsjobs_results_per_search);
  const _dateWindowEl = document.getElementById('search_date_window');
  if (_dateWindowEl) {
    const _savedDays = profile.search_settings?.date_range_days;
    const _windowValues = [1, 3, 7, 15, 30];
    const _closest = _windowValues.includes(_savedDays) ? _savedDays
      : _windowValues.reduce((p, c) => Math.abs(c - _savedDays) < Math.abs(p - _savedDays) ? c : p);
    _dateWindowEl.value = String(_closest);
  }
  const _liEasyApply = profile.search_settings?.[LINKEDIN_EASY_APPLY_ONLY];
  document.getElementById(LINKEDIN_EASY_APPLY_ONLY).value = (_liEasyApply === null || _liEasyApply === undefined) ? '' : String(_liEasyApply);
  const _enabledSources = profile.enabled_sources || ['seek', 'linkedin'];
  setToggleChecked('seek_enabled', _enabledSources.includes('seek'));
  setToggleChecked('linkedin_enabled', _enabledSources.includes('linkedin'));
  setToggleChecked('apsjobs_enabled', _enabledSources.includes('apsjobs'));
  setToggleChecked('explore_adjacent_roles', Boolean(profile.explore_adjacent_roles));
  ['seek_enabled', 'linkedin_enabled', 'apsjobs_enabled'].forEach(syncSourcePanelDisabledState);
  setEngagementTypeValues(profile.match_preferences?.engagement_type);
  setWorkModePreferenceValues(profile.match_preferences?.work_mode_preference || []);
  setSectorPreferenceValues(profile.match_preferences?.prefer_sector || sectorPreferenceDefault);
  const _minContractEl = document.getElementById('min_contract_months');
  if (_minContractEl) {
    _minContractEl.value = String(profile.match_preferences?.min_contract_months ?? '');
    const _engagementTypeValues = getEngagementTypeValues();
    _minContractEl.disabled = !(_engagementTypeValues.includes('contract') || _engagementTypeValues.includes('full_time_contract'));
  }
  syncContractDurationState();
  setCurrencyFieldValue('minimum_salary_yearly', profile.salary_preferences?.minimum_salary_yearly ?? 0);
  setCurrencyFieldValue('minimum_daily_rate', profile.salary_preferences?.minimum_daily_rate ?? 0);
  document.getElementById('fit_weight').value = String(profile.preference_weights?.fit);
  document.getElementById('salary_weight').value = String(profile.preference_weights?.salary);
  document.getElementById('location_weight').value = String(profile.preference_weights?.location);
  document.getElementById('work_mode_weight').value = String(profile.preference_weights?.work_mode);
  document.getElementById('contract_weight').value = String(profile.preference_weights?.contract);
  document.getElementById('government_weight').value = String(profile.preference_weights?.government);
  document.getElementById('freshness_weight').value = String(profile.preference_weights?.freshness);
  capabilityEditor.setCapabilityRuleState(profile.candidate_capabilities || []);
  clearanceEditor.setClearanceRuleState(profile.candidate_eligibility || []);
  eligibilityEditor.setEligibilityFactState(profile.candidate_eligibility_facts || []);
  qualificationEditor.setQualificationState(profile.candidate_qualifications || []);
  renderCapturedCvText(loadedSourceMaterials);
  renderRoleExperienceReadonly(profile);
  for (const id of ['target_roles', 'also_consider_roles', 'must_not_require_skills']) {
    settingsField(id).value = (profile[id] || []).join('\n');
  }
  for (const [id, key] of ruleTextAreas) {
    settingsField(id).value = rulesToText(profile[id], key);
  }
  chipEditor.renderGlobalChipEditors();
}

async function loadProfile() {
  const response = await jobHunterFetch('/api/profile');
  if (!response.ok) throw new Error('Could not load profile');
  const profile = await response.json();
  loadedProfile = profile;
  fillForm(profile);
  showStatus('Profile loaded.', 'success', { autoHideMs: 2600 });
}

async function loadSourceMaterials() {
  const response = await jobHunterFetch('/api/source-materials');
  if (!response.ok) throw new Error('Could not load source materials');
  const materials = await response.json();
  loadedSourceMaterials = materials;
  renderCapturedCvText(materials);
}

async function loadGlobalSettings() {
  const response = await jobHunterFetch('/api/global-settings');
  if (!response.ok) throw new Error('Could not load global settings');
  const settings = await response.json();
  loadedGlobalSettings = settings;
  adminSettings.fillGlobalForm(settings);
  adminSettings.loadGlobalSettingsHelp?.();
  renderLlmModelOptions();
}

async function loadUserSettings() {
  const response = await jobHunterFetch('/api/user-settings');
  if (!response.ok) throw new Error('Could not load alert settings');
  const settings = await response.json();
  loadedUserSettings = settings;
  alertsSettings.fillUserSettings(settings);
  renderLlmModelOptions();
}

function setSettingsHashWithoutScroll(sectionId) {
  if (!sectionId) return;
  const nextUrl = `${window.location.pathname}${window.location.search}#${sectionId}`;
  window.history.replaceState(null, '', nextUrl);
}

function scrollSettingsToTop() {
  window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
}

function normalizeSettingsSearchText(value) {
  return String(value || '').trim().toLowerCase();
}

function getSettingsSectionNavItems() {
  return Array.from(document.querySelectorAll(`.nav-item[data-section][data-screen="${pageMode}"]`));
}

function setActiveSettingsSection(sectionId, options = {}) {
  if (!sectionId) return;
  const activeButton = document.querySelector(`.nav-item[data-section="${sectionId}"][data-screen="${pageMode}"]`);
  document.querySelectorAll('.settings-group').forEach(group => {
    group.classList.toggle('is-active', group.id === sectionId);
  });
  document.querySelectorAll('.nav-item[data-section]').forEach(item => {
    item.classList.toggle('is-active', item === activeButton);
  });
  setSettingsHashWithoutScroll(sectionId);
  if (options.scrollToTop) {
    scrollSettingsToTop();
  }
}

function settingsSectionSearchHaystack(button) {
  const section = document.getElementById(button.dataset.section || '');
  return normalizeSettingsSearchText(`${button.textContent || ''} ${section?.textContent || ''}`);
}

function applySettingsSectionSearch(query) {
  const searchText = normalizeSettingsSearchText(query);
  const navItems = getSettingsSectionNavItems();
  const matchedSectionIds = new Set();

  navItems.forEach((button) => {
    const isMatch = !searchText || settingsSectionSearchHaystack(button).includes(searchText);
    button.hidden = !isMatch;
    button.classList.toggle('is-search-match', Boolean(searchText && isMatch));
    if (isMatch && button.dataset.section) {
      matchedSectionIds.add(button.dataset.section);
    }
  });

  if (!searchText) {
    document.querySelectorAll(`.settings-group[data-screen="${pageMode}"]`).forEach((group) => {
      group.classList.remove('is-search-result');
    });
    const hashSection = window.location.hash.replace('#', '');
    const target = navItems.find((button) => button.dataset.section === hashSection) || navItems[0];
    if (target) setActiveSettingsSection(target.dataset.section);
    return;
  }

  document.querySelectorAll(`.settings-group[data-screen="${pageMode}"]`).forEach((group) => {
    group.classList.remove('is-active');
    group.classList.toggle('is-search-result', matchedSectionIds.has(group.id));
  });

  const firstMatch = navItems.find((button) => !button.hidden);
  document.querySelectorAll('.nav-item[data-section]').forEach(item => {
    item.classList.toggle('is-active', item === firstMatch);
  });
  if (firstMatch?.dataset.section) {
    setSettingsHashWithoutScroll(firstMatch.dataset.section);
  }
}

const settingsSectionSearch = document.getElementById('settings_section_search');
settingsSectionSearch?.addEventListener('input', () => {
  applySettingsSectionSearch(settingsSectionSearch.value);
});
// -- Navigation --------------------------------------------
document.querySelectorAll('.nav-item[data-section]').forEach(btn => {
  btn.addEventListener('click', () => {
    if (settingsSectionSearch) {
      settingsSectionSearch.value = '';
      applySettingsSectionSearch('');
    }
    setActiveSettingsSection(btn.dataset.section, { scrollToTop: true });
  });
});

if (window.location.hash) {
  const target = document.querySelector(`.nav-item[data-section="${window.location.hash.replace('#', '')}"]`);
  if (target && !target.hidden) target.click();
}
if (!document.querySelector(`.settings-group.is-active[data-screen="${pageMode}"]`)) {
  const firstVisibleSection = document.querySelector(`.settings-group[data-screen="${pageMode}"]`);
  const firstVisibleNav = document.querySelector(`.nav-item[data-screen="${pageMode}"][data-section="${firstVisibleSection?.id || ''}"]`);
  document.querySelectorAll('.settings-group').forEach(group => {
    group.classList.toggle('is-active', group === firstVisibleSection);
  });
  document.querySelectorAll('.nav-item[data-section]').forEach(item => {
    item.classList.toggle('is-active', item === firstVisibleNav);
  });
  if (firstVisibleSection) setSettingsHashWithoutScroll(firstVisibleSection.id);
}

// -- Sliders -----------------------------------------------
function updateSliderLabel(slider) {
  const label = document.getElementById(slider.id + '_label');
  if (!label) return;
  const val = parseFloat(slider.value);
  const map = { 0: 'Ignore', 0.5: 'Light', 1: 'Normal', 1.5: 'High', 2: 'Very high' };
  label.textContent = map[val] || val;
}

document.querySelectorAll('[data-weight-slider]').forEach(slider => {
  slider.addEventListener('input', () => { updateSliderLabel(slider); markDirty(); });
});

function initSliders() {
  document.querySelectorAll('[data-weight-slider]').forEach(updateSliderLabel);
}

// -- Save Management ---------------------------------------
const stickySaveBar = document.getElementById('sticky_save_bar');
const activeSaveButton = isAdminPage ? document.getElementById('save_admin_btn') : document.getElementById('save_settings_btn');
const activeDiscardButton = isAdminPage ? document.getElementById('discard_admin_changes_btn') : document.getElementById('discard_changes_btn');
const globalStatus = document.getElementById('global_save_status');

if (activeSaveButton) activeSaveButton.disabled = true;

bindCurrencyFields(['minimum_salary_yearly', 'minimum_daily_rate', 'salary_limit_minimum_salary_yearly_max', 'salary_limit_minimum_daily_rate_max']);

document.querySelectorAll('input, select, textarea').forEach(el => {
  if (
    el.id === 'capability_matrix_filter'
    || el.id === 'settings_section_search'
    || el.classList.contains('is-readonly')
    || el.type === 'hidden'
  ) return;
  el.addEventListener('change', markDirty);
  if (el.tagName === 'TEXTAREA' || ['text', 'time', 'number', 'password', 'search'].includes(el.type)) {
    el.addEventListener('input', markDirty);
  }
});

['seek_enabled', 'linkedin_enabled', 'apsjobs_enabled'].forEach((toggleId) => {
  document.getElementById(toggleId)?.addEventListener('change', () => syncSourcePanelDisabledState(toggleId));
});

const pageLabels = window.__JOB_HUNTER_ONBOARDING_PAGE_LABELS__;
if (!pageLabels) {
  throw new Error('Missing onboarding page labels.');
}

function minContractMonthSummaryText(value) {
  const selected = String(value).trim();
  if (!selected) {
    return pageLabels.summary_any_length_label;
  }
  const option = Array.from(document.querySelectorAll('#min_contract_months option'))
    .find((item) => String(item.value).trim() === selected);
  if (!option || !option.textContent) {
    throw new Error(`Missing contract month label for value: ${selected}`);
  }
  return String(option.textContent).trim();
}

const contractDurationRow = document.getElementById('contract_duration_row');
const contractTypeInput = document.querySelector('input[name="engagement_type"][value="contract"]');
const contractTypeChip = contractTypeInput?.closest('label');
const contractDurationPopover = contractDurationRow && contractTypeChip
  ? createAnchoredPopover({ popover: contractDurationRow, anchor: contractTypeChip })
  : null;
if (contractDurationPopover && contractTypeChip && contractTypeInput) {
  bindSelectedChoicePopover({
    controller: contractDurationPopover,
    anchor: contractTypeChip,
    input: contractTypeInput,
  });
}
const minContractMonthNoneLabel = String(window.__JOB_HUNTER_MIN_CONTRACT_MONTH_NONE_LABEL__ || '').trim();
if (!minContractMonthNoneLabel) {
  throw new Error('Missing minimum contract month none label.');
}

function updateContractChipLabel() {
  const chipSpan = contractTypeChip?.querySelector('span');
  if (!chipSpan || !contractTypeInput) return;
  if (!chipSpan.dataset.baseLabel) {
    chipSpan.dataset.baseLabel = String(chipSpan.textContent || '').trim();
  }
  if (!contractTypeInput.checked) {
    chipSpan.textContent = chipSpan.dataset.baseLabel;
    return;
  }
  const value = String(document.getElementById('min_contract_months')?.value || '').trim();
  const detail = value ? `${value}+` : minContractMonthNoneLabel.toLocaleLowerCase();
  chipSpan.textContent = `${chipSpan.dataset.baseLabel} (${detail})`;
}

function syncContractDurationState({ showPopover = false } = {}) {
  const minContractEl = document.getElementById('min_contract_months');
  if (!minContractEl) return;
  const selectedTypes = getEngagementTypeValues();
  const contractSelected =
    selectedTypes.includes('contract') ||
    selectedTypes.includes('full_time_contract');

  minContractEl.disabled = !contractSelected;

  if (!contractSelected) {
    minContractEl.value = '';
    contractDurationPopover?.hide();
  } else if (showPopover) {
    contractDurationPopover?.show();
  }

  updateContractChipLabel();
  updateSearchPreferenceSummaries();
}

function updateSearchPreferenceSummaries() {
  const allChecked = (name) => {
    const inputs = Array.from(document.querySelectorAll(`input[name="${name}"]`));
    return inputs.length > 0 && inputs.every((i) => i.checked);
  };
  const set = (id, text) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.hidden = !text;
  };
  const contractMonths = String(document.getElementById('min_contract_months')?.value || '').trim();
  set(
    'engagement_type_summary',
    allChecked('engagement_type')
      ? `${pageLabels.work_type_summary_all_label} \u00b7 ${pageLabels.work_type_summary_contract_length_label}: ${contractMonths ? minContractMonthSummaryText(contractMonths) : pageLabels.summary_any_length_label}`
      : '',
  );
  set('work_mode_preference_summary', allChecked('work_mode_preference') ? pageLabels.work_mode_summary_all_label : '');
  set('sector_preference_summary', allChecked('prefer_sector') ? pageLabels.sector_preference_summary_all_label : '');
}

document.getElementById('min_contract_months')?.addEventListener('change', () => {
  updateContractChipLabel();
  updateSearchPreferenceSummaries();
});

document.querySelectorAll('input[name="engagement_type"]').forEach((cb) => {
  cb.addEventListener('change', () => {
    if (!cb.checked) {
      const anyChecked = document.querySelectorAll('input[name="engagement_type"]:checked').length > 0;
      if (!anyChecked) cb.checked = true;
    }
    syncContractDurationState({ showPopover: cb.value === 'contract' && cb.checked });
  });
});

document.querySelectorAll('input[name="work_mode_preference"]').forEach((cb) => {
  cb.addEventListener('change', () => {
    if (!cb.checked) {
      const anyChecked = document.querySelectorAll('input[name="work_mode_preference"]:checked').length > 0;
      if (!anyChecked) cb.checked = true;
    }
    updateSearchPreferenceSummaries();
  });
});

document.querySelectorAll('input[name="prefer_sector"]').forEach((cb) => {
  cb.addEventListener('change', () => {
    ensureAtLeastOneChoiceSelected('prefer_sector', cb);
    updateSearchPreferenceSummaries();
  });
});

activeDiscardButton?.addEventListener('click', () => { window.location.reload(); });

document.getElementById('reload')?.addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  const originalLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Reloading...';
  try {
    await Promise.all([loadProfile(), loadSourceMaterials()]);
    initSliders();
    clearDirty();
    showStatus('Profile reloaded from disk.', 'success', { autoHideMs: 2600 });
  } catch (error) {
    showStatus(error.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = originalLabel;
  }
});

document.getElementById('refresh_role_history_from_saved_cv')?.addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  const originalLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = roleHistoryLabels.refresh_button_busy_label;
  try {
    const response = await jobHunterFetch('/api/profile/refresh-role-history-from-saved-cv', {
      method: 'POST',
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || 'Could not refresh role history from saved CV.');
    }
    const roleExperience = Array.isArray(payload?.role_experience) ? payload.role_experience : [];
    loadedProfile = { ...(loadedProfile || {}), role_experience: roleExperience };
    renderRoleExperienceReadonly(loadedProfile);
    const pageLimitNotice = String(payload?.page_limit_notice || '').trim();
    const message = pageLimitNotice
      ? `${String(payload?.message || 'Role history refreshed from saved CV.').trim()} ${pageLimitNotice}`
      : String(payload?.message || 'Role history refreshed from saved CV.').trim();
    showStatus(message, 'success', { autoHideMs: 4000 });
  } catch (error) {
    showStatus(error.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = originalLabel;
  }
});

document.getElementById('open_telegram_connect')?.addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  const originalLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Generating...';
  try {
    let link = alertsSettings.getTelegramConnectLink();
    if (!link) link = (await alertsSettings.loadTelegramConnectLink()).connect_link || '';
    if (!link) throw new Error('No Telegram connect link available yet.');
    showStatus('Opening Telegram... If it fails to open, copy the link from the panel below.', 'success', { autoHideMs: 5000 });
    window.open(link, '_blank', 'noopener');
  } catch (error) {
    showStatus(error.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = originalLabel;
  }
});

document.getElementById('refresh_telegram_connection')?.addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  const originalLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Checking...';
  try {
    const payload = await alertsSettings.syncTelegramSubscribers();
    const totalSubscribers = Number(payload?.result?.total_subscribers || 0);
    showStatus(
      payload?.message || 'Connected Telegram account refreshed.',
      totalSubscribers > 0 ? 'success' : 'error',
    );
  } catch (error) {
    showStatus(error.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = originalLabel;
  }
});

document.getElementById('send_telegram_test')?.addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  const originalLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Sending...';
  try {
    const payload = await alertsSettings.sendTelegramTestMessage();
    showStatus(payload?.message || 'Telegram test message sent.', 'success');
  } catch (error) {
    showStatus(error.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = originalLabel;
  }
});

async function saveActivePage() {
  if (!activeSaveButton) return;
  const originalLabel = activeSaveButton.textContent;
  activeSaveButton.classList.add('is-working');
  activeSaveButton.disabled = true;
  activeSaveButton.textContent = 'Saving...';
  showInlineStatus(globalStatus, isAdminPage ? 'Saving global settings...' : 'Saving settings...', 'loading');
  try {
    if (isAdminPage) {
      const globalSettingsPayload = adminSettings.collectGlobalSettings(loadedGlobalSettings);
      const globalResponse = await jobHunterFetch('/api/global-settings', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(globalSettingsPayload),
      });
      const globalPayload = await globalResponse.json().catch(() => ({}));
      if (!globalResponse.ok) throw new Error(globalPayload.error || 'Could not save global settings.');
      loadedGlobalSettings = globalPayload;
      adminSettings.fillGlobalForm(globalPayload);
      adminSettings.applyGlobalSettingsHelp?.();
      adminSettings.initKnowledgeSyncControls?.(showStatus);
      adminSettings.initRejectionHistorySyncControls?.(showStatus);
      adminSettings.initSystemWarningsControls?.(showStatus);
      renderLlmModelOptions();
      showInlineStatus(globalStatus, 'Global settings saved.', 'success');
      showStatus(sharedUiLabels.global_settings_saved_success, 'success');
    } else {
      const previousProfile = loadedProfile;
      const previousUserSettings = loadedUserSettings;
      const profile = collectProfile();
      const userSettingsPayload = alertsSettings.collectUserSettings(loadedUserSettings);
      const profileResponse = await jobHunterFetch('/api/profile', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(profile),
      });
      const profilePayload = await profileResponse.json().catch(() => ({}));
      if (!profileResponse.ok) throw new Error(profilePayload.error || 'Could not save profile settings.');
      const userResponse = await jobHunterFetch('/api/user-settings', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(userSettingsPayload),
      });
      const userPayload = await userResponse.json().catch(() => ({}));
      if (!userResponse.ok) throw new Error(userPayload.error || 'Could not save user settings.');
      loadedProfile = profilePayload;
      fillForm(profilePayload);
      loadedUserSettings = userPayload;
      alertsSettings.fillUserSettings(userPayload);
      initSliders();
      showInlineStatus(globalStatus, 'Settings saved.', 'success');
      showStatus(
        buildCandidateSettingsSaveMessage(
          previousProfile,
          previousUserSettings,
          profilePayload,
          userPayload,
        ),
        'success',
      );
    }
    clearDirty();
  } catch (err) {
    if (activeSaveButton) activeSaveButton.disabled = false;
    showInlineStatus(globalStatus, err?.message || 'Could not save changes.', 'error');
  } finally {
    activeSaveButton.classList.remove('is-working');
    activeSaveButton.textContent = originalLabel;
  }
}

activeSaveButton?.addEventListener('click', (event) => {
  event.preventDefault();
  event.stopPropagation();
  saveActivePage();
});

// -- Module event handlers (after markDirty is defined) ---------------------
chipEditor.initEventHandlers(markDirty);
capabilityEditor.initEventHandlers(markDirty);
clearanceEditor.initEventHandlers(markDirty);
eligibilityEditor.initEventHandlers(markDirty);
qualificationEditor.initEventHandlers(markDirty);
alertsSettings.initEventHandlers();

// -- Init ------------------------------------------------------------------
const pageLoads = isAdminPage
  ? [loadGlobalSettings()]
  : [loadProfile(), loadUserSettings(), loadSourceMaterials()];
Promise.all(pageLoads).then(() => {
  initSliders();
  syncContractDurationState();
  suppressDirtyTracking = false;
  clearDirty();
}).catch(error => showStatus(error.message, 'error'));
