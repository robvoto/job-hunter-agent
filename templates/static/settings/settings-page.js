var LINKEDIN_EASY_APPLY_ONLY = window.LINKEDIN_EASY_APPLY_ONLY || 'linkedin_easy_apply_only';
window.LINKEDIN_EASY_APPLY_ONLY = LINKEDIN_EASY_APPLY_ONLY;

const statusEl = document.getElementById('status');
const isTestMode = document.body?.dataset.testMode === 'true';
const runNowButton = document.getElementById('run_now');
const rebuildProfileButton = document.getElementById('rebuild_profile');
const capabilityUi = window.JobHunterCapabilityUi || {};

// Module references
const chipEditor = window.JobHunterChipEditor;
const capabilityEditor = window.JobHunterCapabilityEditor;
const adminSettings = window.JobHunterAdminSettings;
const alertsSettings = window.JobHunterAlertsSettings;
const { escapeHtml, toLines, rulesToText, textToRules, settingsField, bindCurrencyFields, setCurrencyFieldValue, readCurrencyFieldValue } = window.JobHunterSettingsUtils;

// Aliases kept in scope for settings-review-panel.js which reads these by name
const capabilityStrengthMeta = capabilityEditor.capabilityStrengthMeta;
const collectCapabilityRuleState = capabilityEditor.collectCapabilityRuleState;
const flushChipEditorInputs = chipEditor.flushChipEditorInputs;
const fillUserSettings = (s) => alertsSettings.fillUserSettings(s);
const collectUserSettings = () => alertsSettings.collectUserSettings(loadedUserSettings);

const governmentPreferenceOptions = Array.isArray(window.__JOB_HUNTER_GOVERNMENT_PREFERENCE_OPTIONS__)
  ? window.__JOB_HUNTER_GOVERNMENT_PREFERENCE_OPTIONS__
  : [];
const governmentPreferenceDefault = String(
  window.__JOB_HUNTER_GOVERNMENT_PREFERENCE_DEFAULT__
  || governmentPreferenceOptions?.[0]?.value
  || 'any'
).trim().toLowerCase();
const workModePreferenceOptions = Array.isArray(window.__JOB_HUNTER_WORK_MODE_PREFERENCE_OPTIONS__)
  ? window.__JOB_HUNTER_WORK_MODE_PREFERENCE_OPTIONS__
  : [];

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

function getWorkModePreferenceValues() {
  return normalizeWorkModePreferences(
    Array.from(document.querySelectorAll('input[name="work_mode_preference"]:checked')).map((input) => input.value)
  );
}

function setWorkModePreferenceValues(values) {
  const selected = new Set(normalizeWorkModePreferences(values));
  document.querySelectorAll('input[name="work_mode_preference"]').forEach((input) => {
    input.checked = selected.size === 0 || selected.has(String(input.value || '').trim().toLowerCase());
  });
}

function readOnboardingWelcomeSearchKeywords() {
  try {
    const raw = window.sessionStorage.getItem('jobHunter.onboardingWelcome');
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
let statusHideTimer = null;
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
  renderLlmModelOptions();
}

const ruleTextAreas = [
  ['reject_title_rules', 'pattern'],
  ['reject_description_phrase_rules', 'phrase'],
];

function hideStatus() {
  if (!statusEl) return;
  statusEl.className = 'status';
  statusEl.textContent = '';
}

function showStatus(message, kind, options = {}) {
  if (!statusEl) return;
  window.clearTimeout(statusHideTimer);
  statusEl.textContent = message;
  statusEl.className = `status is-visible ${kind}`;
  const autoHideMs = Number(options.autoHideMs || 0);
  if (autoHideMs > 0) {
    statusHideTimer = window.setTimeout(hideStatus, autoHideMs);
  }
}

function showInlineStatus(element, message, kind) {
  if (!element) return;
  element.textContent = message;
  element.className = `inline-status ${kind}`;
}

function markDirty() {
  if (suppressDirtyTracking) return;
  if (activeSaveButton) activeSaveButton.disabled = false;
  if (stickySaveBar) {
    stickySaveBar.hidden = false;
    stickySaveBar.dataset.dirty = 'true';
  }
}

function clearDirty() {
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
  const modelOptions = loadedGlobalSettings?.llm_settings?.model_options;
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
  const locationUi = window.JobHunterLocationUi || {};
  const select = document.getElementById('locations');
  if (!select || !locationUi.renderLocationOptions) return;
  locationUi.renderLocationOptions(select);
  const preferred = String(loadedProfile?.search_settings?.locations?.[0] || locationUi.defaultLocation || select.value || '').trim();
  if (preferred) select.value = preferred;
}

function collectProfile() {
  chipEditor.flushChipEditorInputs();
  const locationSelect = document.getElementById('locations');
  const searchDateWindow = Number(document.getElementById('search_date_window')?.value || '3');
  const hoursMap = { 0: 720, 1: 24, 3: 72, 7: 168, 15: 360, 30: 720 };
  const linkedinEasyApplyRaw = document.getElementById(LINKEDIN_EASY_APPLY_ONLY)?.value;
  return {
    search_settings: {
      keywords: toLines(settingsField('keywords').value).join(', '),
      locations: locationSelect && locationSelect.value.trim() ? [locationSelect.value.trim()] : [],
      classification_ids: toLines(document.getElementById('classification_ids').value),
      date_range_days: searchDateWindow === 0 ? 30 : searchDateWindow,
      linkedin_hours_old: hoursMap[searchDateWindow] ?? 72,
      seek_max_pages: Number(document.getElementById('seek_max_pages').value),
      enforce_posted_age_limit: document.getElementById('enforce_posted_age_limit').value === 'true',
      sort_newest_first: document.getElementById('sort_newest_first').value === 'true',
      linkedin_results_per_search: Number(document.getElementById('linkedin_results_per_search').value) || 25,
      [LINKEDIN_EASY_APPLY_ONLY]: linkedinEasyApplyRaw === '' ? null : linkedinEasyApplyRaw === 'true',
    },
    salary_preferences: {
      minimum_salary_yearly: readCurrencyFieldValue('minimum_salary_yearly', 0),
      minimum_daily_rate: readCurrencyFieldValue('minimum_daily_rate', 0),
    },
    match_preferences: {
      engagement_type: document.getElementById('engagement_type').value,
      work_mode_preference: getWorkModePreferenceValues(),
      prefer_government: String(document.getElementById('prefer_government').value || governmentPreferenceDefault).trim().toLowerCase(),
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
    capability_profile_rules: capabilityEditor.collectCapabilityRuleState(),
    primary_job_title_pattern: toLines(settingsField('primary_job_title_pattern').value),
    secondary_title_patterns: toLines(settingsField('secondary_title_patterns').value),
    must_not_require_skills: toLines(settingsField('must_not_require_skills').value),
    reject_title_rules: textToRules(settingsField('reject_title_rules').value, 'pattern'),
    reject_description_phrase_rules: textToRules(settingsField('reject_description_phrase_rules').value, 'phrase'),
  };
}

function fillForm(profile) {
  const savedKeywords = String(profile.search_settings?.keywords || '').trim();
  const onboardingKeywords = savedKeywords ? '' : readOnboardingWelcomeSearchKeywords();
  const keywordList = (savedKeywords || onboardingKeywords || '')
    .split(',')
    .map(k => k.trim())
    .filter(Boolean);
  settingsField('keywords').value = keywordList.join('\n');
  chipEditor.renderChipEditor('keywords');
  renderLocationOptions();
  const locationSelect = document.getElementById('locations');
  if (locationSelect) {
    const locationUi = window.JobHunterLocationUi || {};
    locationSelect.value = String(profile.search_settings?.locations?.[0] || locationUi.defaultLocation || locationSelect.value || '').trim();
  }
  document.getElementById('classification_ids').value = (profile.search_settings?.classification_ids || []).join('\n');
  document.getElementById('seek_max_pages').value = String(profile.search_settings?.seek_max_pages);
  document.getElementById('enforce_posted_age_limit').value = String(Boolean(profile.search_settings?.enforce_posted_age_limit));
  document.getElementById('sort_newest_first').value = String(Boolean(profile.search_settings?.sort_newest_first));
  document.getElementById('linkedin_results_per_search').value = String(profile.search_settings?.linkedin_results_per_search);
  const _dateWindowEl = document.getElementById('search_date_window');
  if (_dateWindowEl) {
    const _savedDays = profile.search_settings?.date_range_days;
    const _windowValues = [1, 3, 7, 15, 30];
    const _closest = _windowValues.includes(_savedDays) ? _savedDays
      : _windowValues.reduce((p, c) => Math.abs(c - _savedDays) < Math.abs(p - _savedDays) ? c : p);
    _dateWindowEl.value = String(_closest);
  }
  const _minScoreSelect = document.getElementById('workspace_minimum_score');
  if (_minScoreSelect) {
    const _levels = (profile.match_levels || []).slice().sort((a, b) => (a.minimum_score || 0) - (b.minimum_score || 0));
    _minScoreSelect.innerHTML = '<option value="0">All roles</option>' +
      _levels.map(l => `<option value="${l.minimum_score}">${escapeHtml(l.label)} &amp; above</option>`).join('');
    const _savedScore = loadedUserSettings?.workspace?.minimum_score;
    if (_savedScore !== undefined) _minScoreSelect.value = String(_savedScore);
  }
  const _liEasyApply = profile.search_settings?.[LINKEDIN_EASY_APPLY_ONLY];
  document.getElementById(LINKEDIN_EASY_APPLY_ONLY).value = (_liEasyApply === null || _liEasyApply === undefined) ? '' : String(_liEasyApply);
  document.getElementById('engagement_type').value = profile.match_preferences?.engagement_type || 'both';
  setWorkModePreferenceValues(profile.match_preferences?.work_mode_preference || []);
  const governmentPreference = document.getElementById('prefer_government');
  if (governmentPreference) {
    governmentPreference.value = String(profile.match_preferences?.prefer_government || governmentPreferenceDefault).trim().toLowerCase();
  }
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
  capabilityEditor.setCapabilityRuleState(profile.capability_profile_rules || []);
  document.getElementById('cv_text_debug').value = (profile.cv_text || '').trim();
  for (const id of ['primary_job_title_pattern', 'secondary_title_patterns', 'must_not_require_skills']) {
    settingsField(id).value = (profile[id] || []).join('\n');
  }
  for (const [id, key] of ruleTextAreas) {
    settingsField(id).value = rulesToText(profile[id], key);
  }
  chipEditor.renderGlobaldChipEditors();
}

async function loadProfile() {
  const response = await jobHunterFetch('/api/profile');
  if (!response.ok) throw new Error('Could not load profile');
  const profile = await response.json();
  loadedProfile = profile;
  fillForm(profile);
  showStatus('Profile loaded.', 'ok', { autoHideMs: 2600 });
}

async function loadGlobalSettings() {
  const response = await jobHunterFetch('/api/global-settings');
  if (!response.ok) throw new Error('Could not load global settings');
  const settings = await response.json();
  loadedGlobalSettings = settings;
  adminSettings.fillGlobalForm(settings);
  renderLlmModelOptions();
}

async function loadUserSettings() {
  const response = await jobHunterFetch('/api/user-settings');
  if (!response.ok) throw new Error('Could not load alert settings');
  const settings = await response.json();
  loadedUserSettings = settings;
  alertsSettings.fillUserSettings(settings);
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
    window.location.hash = sectionId;
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
  if (firstVisibleSection) window.location.hash = firstVisibleSection.id;
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

document.querySelectorAll('input[name="work_mode_preference"]').forEach((cb) => {
  cb.addEventListener('change', () => {
    if (!cb.checked) {
      const anyChecked = document.querySelectorAll('input[name="work_mode_preference"]:checked').length > 0;
      if (!anyChecked) cb.checked = true;
    }
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
    showStatus('Profile reloaded from disk.', 'ok', { autoHideMs: 2600 });
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
    showStatus('Opening Telegram... If it fails to open, copy the link from the panel below.', 'ok', { autoHideMs: 5000 });
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
      renderLlmModelOptions();
      showInlineStatus(globalStatus, 'Global settings saved.', 'ok');
      showStatus('Global settings saved successfully.', 'ok');
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
      showInlineStatus(globalStatus, 'Settings saved.', 'ok');
      showStatus('Settings saved successfully.', 'ok', { autoHideMs: 2500 });
    }
    clearDirty();
  } catch (err) {
    if (activeSaveButton) activeSaveButton.disabled = false;
    showInlineStatus(globalStatus, err?.message || 'Could not save changes.', 'error');
    showStatus(err?.message || 'Could not save changes.', 'error');
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
  suppressDirtyTracking = false;
  clearDirty();
}).catch(error => showStatus(error.message, 'error'));
