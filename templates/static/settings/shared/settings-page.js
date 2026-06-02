import { JobHunterChipEditor as chipEditor } from './settings-chip-editor.js';
import { JobHunterCapabilityEditor as capabilityEditor } from './settings-capability-editor.js';
import { JobHunterAdminSettings as adminSettings } from '../global/settings-admin.js';
import { JobHunterAlertsSettings as alertsSettings } from '../standard/settings-alerts.js';
import * as capabilityUi from '../../common/capability-ui.js';
import * as locationUi from '../../common/location-options.js';
import { createController as createMessageBannerController } from '../../common/message-banner.js';
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

const capabilityMatrixNav = document.getElementById('settings_capability_matrix_nav');
if (capabilityMatrixNav && capabilityLabels.settings_title) {
  capabilityMatrixNav.textContent = capabilityLabels.settings_title;
}
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

let loadedUserSettings = null;
let loadedProfile = null;
let loadedGlobalSettings = null;
let suppressDirtyTracking = true;
const pageMode = document.body?.dataset.pageMode === 'admin' ? 'admin' : 'settings';
const isAdminPage = pageMode === 'admin';
const isUserAdmin = isAdminPage || !!document.querySelector('.sidebar-brand-actions .nav-item-admin') || !!document.querySelector('.sidebar-brand-actions a[href*="admin"]');
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
  renderLlmModelOptions();
}

const ruleTextAreas = [
  ['reject_title_rules', 'pattern'],
  ['reject_description_phrase_rules', 'phrase'],
];

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


function renderLocationOptions() {
  const select = document.getElementById('locations');
  if (!select || !locationUi.renderLocationOptions) return;
  locationUi.renderLocationOptions(select);
  const preferred = String(loadedProfile?.search_settings?.locations?.[0] || locationUi.defaultLocation || select.value || '').trim();
  if (preferred) select.value = preferred;
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
  const locationSelect = document.getElementById('locations');
  const searchDateWindow = Number(document.getElementById('search_date_window')?.value || '3');
  const hoursMap = { 0: 720, 1: 24, 3: 72, 7: 168, 15: 360, 30: 720 };
  const linkedinEasyApplyRaw = document.getElementById(LINKEDIN_EASY_APPLY_ONLY)?.value;
  const sectorPreferenceValues = getSectorPreferenceValues();
  const seekMaxPages = Number(getChoiceGroupValue('seek_max_pages'));
  if (!Number.isFinite(seekMaxPages)) {
    throw new Error('Please choose a valid SEEK page limit.');
  }
  const engagementTypeValues = getEngagementTypeValues();
  const contractEnabled = engagementTypeValues.includes('contract');
  const minContractEl = document.getElementById('min_contract_months');
  return {
    search_settings: {
      keywords: String(settingsField('keywords').value || '').trim(),
      locations: locationSelect && locationSelect.value.trim() ? [locationSelect.value.trim()] : [],
      classification_ids: toLines(document.getElementById('classification_ids').value),
      date_range_days: searchDateWindow === 0 ? 30 : searchDateWindow,
      linkedin_hours_old: hoursMap[searchDateWindow] ?? 72,
      seek_max_pages: seekMaxPages,
      linkedin_results_per_search: Number(document.getElementById('linkedin_results_per_search').value) || 25,
      [LINKEDIN_EASY_APPLY_ONLY]: linkedinEasyApplyRaw === '' ? null : linkedinEasyApplyRaw === 'true',
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
    llm_profile_brief_mode: 'auto',
    llm_profile_brief: '',
    candidate_capabilities: capabilityEditor.collectCapabilityRuleState(),
    target_roles: toLines(settingsField('target_roles').value),
    also_consider_roles: toLines(settingsField('also_consider_roles').value),
    must_not_require_skills: toLines(settingsField('must_not_require_skills').value),
    reject_title_rules: textToRules(settingsField('reject_title_rules').value, 'pattern'),
    reject_description_phrase_rules: textToRules(settingsField('reject_description_phrase_rules').value, 'phrase'),
    enabled_sources: [
      ...(getToggleChecked('seek_enabled') ? ['seek'] : []),
      ...(getToggleChecked('linkedin_enabled') ? ['linkedin'] : []),
    ],
  };
}

function fillForm(profile) {
  const savedKeywords = String(profile.search_settings?.keywords || '').trim();
  const onboardingKeywords = savedKeywords ? '' : readOnboardingWelcomeSearchKeywords();
  settingsField('keywords').value = savedKeywords || onboardingKeywords || '';
  renderLocationOptions();
  const locationSelect = document.getElementById('locations');
  if (locationSelect) {
    locationSelect.value = String(profile.search_settings?.locations?.[0] || locationUi.defaultLocation || locationSelect.value || '').trim();
  }
  document.getElementById('classification_ids').value = (profile.search_settings?.classification_ids || []).join('\n');
  setChoiceGroupValue('seek_max_pages', profile.search_settings?.seek_max_pages);
  document.getElementById('linkedin_results_per_search').value = String(profile.search_settings?.linkedin_results_per_search);
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
  setEngagementTypeValues(profile.match_preferences?.engagement_type);
  setWorkModePreferenceValues(profile.match_preferences?.work_mode_preference || []);
  setSectorPreferenceValues(profile.match_preferences?.prefer_sector || sectorPreferenceDefault);
  const _minContractEl = document.getElementById('min_contract_months');
  if (_minContractEl) {
    _minContractEl.value = String(profile.match_preferences?.min_contract_months ?? '');
    _minContractEl.disabled = !getEngagementTypeValues().includes('contract');
  }
  updateContractChipLabel();
  document.getElementById('llm_profile_brief').value = profile.llm_profile_brief || '';
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
  document.getElementById('cv_text_debug').value = (profile.cv_text || '').trim();
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
// -- Navigation --------------------------------------------
document.querySelectorAll('.nav-item[data-section]').forEach(btn => {
  btn.addEventListener('click', () => {
    const sectionId = btn.dataset.section;
    document.querySelectorAll('.settings-group').forEach(group => {
      group.classList.toggle('is-active', group.id === sectionId);
    });
    document.querySelectorAll('.nav-item').forEach(item => {
      item.classList.toggle('is-active', item === btn);
    });
    setSettingsHashWithoutScroll(sectionId);
    scrollSettingsToTop();
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
  if (el.id === 'capability_matrix_filter' || el.classList.contains('is-readonly') || el.type === 'hidden') return;
  el.addEventListener('change', markDirty);
  if (el.tagName === 'TEXTAREA' || ['text', 'time', 'number', 'password', 'search'].includes(el.type)) {
    el.addEventListener('input', markDirty);
  }
});

function updateContractChipLabel() {
  const chipSpan = document.querySelector('input[name="engagement_type"][value="contract"]')
    ?.closest('label')?.querySelector('span');
  if (!chipSpan) return;
  const contractEnabled = getEngagementTypeValues().includes('contract');
  const val = document.getElementById('min_contract_months')?.value || '';
  if (!contractEnabled) {
    chipSpan.textContent = 'Contract';
  } else {
    chipSpan.textContent = val ? `Contract (${val}+)` : 'Contract (All)';
  }
}

function updateSearchPreferenceSummaries() {
  const pageLabels = window.__JOB_HUNTER_ONBOARDING_PAGE_LABELS__ || {};
  const allChecked = (name) => Array.from(document.querySelectorAll(`input[name="${name}"]`)).every(i => i.checked);
  const set = (id, text) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.hidden = !text;
  };
  set('engagement_type_summary', allChecked('engagement_type') ? (pageLabels.work_type_summary_all_label || '') : '');
  set('work_mode_preference_summary', allChecked('work_mode_preference') ? (pageLabels.work_mode_summary_all_label || '') : '');
  set('sector_preference_summary', allChecked('prefer_sector') ? (pageLabels.sector_preference_summary_all_label || '') : '');
}

function updateContractDurationRow() {
  const contractEnabled = getEngagementTypeValues().includes('contract');
  const minContractEl = document.getElementById('min_contract_months');
  const contractRow = document.getElementById('contract_duration_row');
  if (!contractEnabled) {
    if (minContractEl) { minContractEl.disabled = true; minContractEl.value = ''; }
    if (contractRow) contractRow.hidden = true;
    updateContractChipLabel();
  }
}

document.getElementById('min_contract_months')?.addEventListener('change', () => {
  const contractRow = document.getElementById('contract_duration_row');
  if (contractRow) contractRow.hidden = true;
  updateContractChipLabel();
});

document.querySelectorAll('input[name="engagement_type"]').forEach((cb) => {
  cb.addEventListener('change', () => {
    if (!cb.checked) {
      const anyChecked = document.querySelectorAll('input[name="engagement_type"]:checked').length > 0;
      if (!anyChecked) cb.checked = true;
    }
    if (!getEngagementTypeValues().includes('contract')) {
      updateContractDurationRow();
    } else if (cb.value === 'contract' && cb.checked) {
      const minContractEl = document.getElementById('min_contract_months');
      const contractRow = document.getElementById('contract_duration_row');
      if (minContractEl) minContractEl.disabled = false;
      if (contractRow) contractRow.hidden = false;
    }
    updateSearchPreferenceSummaries();
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
    await loadProfile();
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

document.getElementById('sync_telegram_subscribers')?.addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  const originalLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Syncing...';
  try {
    await alertsSettings.syncTelegramSubscribers();
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
    await alertsSettings.sendTelegramTestMessage();
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
      renderLlmModelOptions();
      showInlineStatus(globalStatus, 'Global settings saved.', 'success');
      showStatus('Global settings saved successfully.', 'success');
    } else {
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
      fillForm(profilePayload);
      loadedUserSettings = userPayload;
      alertsSettings.fillUserSettings(userPayload);
      initSliders();
      showInlineStatus(globalStatus, 'Settings saved.', 'success');
      showStatus('Settings saved successfully.', 'success', { autoHideMs: 2500 });
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

// -- Init ------------------------------------------------------------------
const pageLoads = isAdminPage
  ? [loadGlobalSettings()]
  : [loadProfile(), loadUserSettings()];
Promise.all(pageLoads).then(() => {
  initSliders();
  updateSearchPreferenceSummaries();
  suppressDirtyTracking = false;
  clearDirty();
}).catch(error => showStatus(error.message, 'error'));
