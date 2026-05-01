const statusEl = document.getElementById('status');
const urlParams = new URLSearchParams(window.location.search);
const isRebuildMode = urlParams.get('mode') === 'rebuild';
const stepEls = Array.from(document.querySelectorAll('.wizard-step'));
const heroSectionEl = document.querySelector('.hero');
const heroTitleEl = document.getElementById('hero_title');
const heroCopyEl = document.getElementById('hero_copy');
const formTitleEl = document.getElementById('form_title');
const workflowSummaryEl = document.getElementById('workflow_summary');
const progressFillEl = document.getElementById('wizard_progress_fill');
const primaryCvInput = document.getElementById('primary_cv');
const primaryCvDropZone = document.getElementById('cv_drop_zone');
const primaryCvStatusEl = document.getElementById('primary_cv_status');
const locationInput = document.getElementById('location_search');
const addLocationButton = document.getElementById('add_location');
const locationSuggestions = document.getElementById('location_suggestions');
const locationQuickPicks = document.getElementById('location_quick_picks');
const locationSelected = document.getElementById('location_selected');
const reviewCapabilityCountEl = document.getElementById('review_capability_count');
const salaryYearlyBlock = document.getElementById('salary_yearly_block');
const salaryDailyBlock = document.getElementById('salary_daily_block');
const createProfileButton = document.getElementById('create_profile');
const stepNavButtons = Array.from(document.querySelectorAll('[data-step-nav]'));
const onbTestPanel = document.getElementById('onb_test_panel');
const onbTestTrigger = document.getElementById('onb_test_trigger');
const onbTestMenu = document.getElementById('onb_test_menu');
const onbResetUserBtn = document.getElementById('onb_reset_user_btn');
const onbResetLearningBtn = document.getElementById('onb_reset_learning_btn');
const STEP_COUNT = 4;
const REVIEW_STEP = 2;
const SEARCH_STEP = 3;
const CHECK_STEP = 4;
const COMMON_LOCATION_OPTIONS = [];
const WIZARD_STATE_KEY = 'jobHunter.onboardingWizard';
const ONBOARDING_WELCOME_KEY = 'jobHunter.onboardingWelcome';
const ONBOARDING_WELCOME_OPT_OUT_KEY = 'jobHunter.onboardingWelcomeOptOut';
const INITIAL_CAPABILITY_VISIBLE_COUNT = 12;
const CAPABILITY_VISIBLE_INCREMENT = 24;
const isTestMode = document.body.dataset.testMode === 'true';

let currentStep = 1;
let workingStatusTimer = null;
let preservedPrimaryCvFile = null;
let lastImportPayload = null;
let reviewTargetTitles = [];
let reviewSecondaryTitles = [];
let reviewCapabilityRules = [];
let selectedLocations = [];
let selectedReviewCapabilityIndexes = new Set();
let reviewCapabilityVisibleCount = INITIAL_CAPABILITY_VISIBLE_COUNT;
let maxUnlockedStep = 1;

function hasDraftProfileState() {
  return Boolean(
    lastImportPayload
    || reviewTargetTitles.length
    || reviewSecondaryTitles.length
    || reviewCapabilityRules.length
  );
}

function hasSearchBasicsState() {
  return Boolean(
    hasDraftProfileState()
    && (
      selectedLocations.length
      || String(document.getElementById('review_search_keywords')?.value || '').trim()
    )
  );
}

function refreshStepNavigation() {
  const unlockedStep = Math.max(
    1,
    maxUnlockedStep,
    hasDraftProfileState() ? REVIEW_STEP : 1,
    hasSearchBasicsState() ? SEARCH_STEP : 1,
  );
  maxUnlockedStep = Math.min(STEP_COUNT, unlockedStep);
  stepNavButtons.forEach((button) => {
    const step = Number(button.dataset.stepNav || 0);
    button.disabled = !step || step > maxUnlockedStep;
    button.setAttribute('aria-current', step === currentStep ? 'step' : 'false');
  });
}

function setTestMenuOpen(open) {
  if (!onbTestMenu || !onbTestTrigger) {
    return;
  }
  onbTestMenu.classList.toggle('is-open', Boolean(open));
  onbTestTrigger.setAttribute('aria-expanded', open ? 'true' : 'false');
}

function clearOnboardingBrowserState() {
  try {
    window.sessionStorage.removeItem(WIZARD_STATE_KEY);
    window.sessionStorage.removeItem(ONBOARDING_WELCOME_KEY);
  } catch {}
  try {
    window.localStorage.removeItem(ONBOARDING_WELCOME_OPT_OUT_KEY);
  } catch {}
}

async function postTestAction(path) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || 'Request failed');
  }
  return payload;
}

function resetOnboardingWizardState() {
  lastImportPayload = null;
  reviewTargetTitles = [];
  reviewSecondaryTitles = [];
  reviewCapabilityRules = [];
  selectedReviewCapabilityIndexes.clear();
  reviewCapabilityVisibleCount = INITIAL_CAPABILITY_VISIBLE_COUNT;
  maxUnlockedStep = 1;
  window.sessionStorage.removeItem(WIZARD_STATE_KEY);
  const filterInput = document.getElementById('review_capability_filter');
  if (filterInput) filterInput.value = '';
  const reviewCards = document.getElementById('review_capability_cards');
  if (reviewCards) reviewCards.innerHTML = '';
  refreshStepNavigation();
}

function saveWizardState() {
  if (currentStep < 2 && !hasDraftProfileState()) {
    window.sessionStorage.removeItem(WIZARD_STATE_KEY);
    return;
  }
  const engagementInput = document.querySelector('input[name="engagement_pref"]:checked');
  window.sessionStorage.setItem(WIZARD_STATE_KEY, JSON.stringify({
    step: currentStep,
    maxUnlockedStep,
    reviewTargetTitles,
    reviewSecondaryTitles,
    reviewCapabilityRules,
    reviewCapabilityVisibleCount,
    selectedLocations,
    searchKeywords: document.getElementById('review_search_keywords')?.value || '',
    minimumSalaryYearly: document.getElementById('review_minimum_salary_yearly')?.value || '',
    minimumDailyRate: document.getElementById('review_minimum_daily_rate')?.value || '',
    engagementType: engagementInput?.value || 'both',
  }));
}

function restoreWizardState() {
  try {
    const raw = window.sessionStorage.getItem(WIZARD_STATE_KEY);
    if (!raw) return false;
    const state = JSON.parse(raw);
    const savedTargets = Array.isArray(state?.reviewTargetTitles) ? state.reviewTargetTitles : [];
    const savedSecondary = Array.isArray(state?.reviewSecondaryTitles) ? state.reviewSecondaryTitles : [];
    const savedCapabilities = Array.isArray(state?.reviewCapabilityRules) ? state.reviewCapabilityRules : [];
    const hasSavedDraft = Boolean(savedTargets.length || savedSecondary.length || savedCapabilities.length);
    if (!state || (!hasSavedDraft && state.step < 2)) return false;
    reviewTargetTitles = state.reviewTargetTitles || [];
    reviewSecondaryTitles = state.reviewSecondaryTitles || [];
    reviewCapabilityRules = state.reviewCapabilityRules || [];
    maxUnlockedStep = Math.max(1, Math.min(STEP_COUNT, Number(state.maxUnlockedStep) || 1));
    reviewCapabilityVisibleCount = Number(state.reviewCapabilityVisibleCount) > 0
      ? Number(state.reviewCapabilityVisibleCount)
      : INITIAL_CAPABILITY_VISIBLE_COUNT;
    setStep(state.step, { scroll: false, persist: false });
    setSelectedLocations(state.selectedLocations || []);
    renderReviewStep();
    const kwEl = document.getElementById('review_search_keywords');
    if (kwEl) kwEl.value = state.searchKeywords || '';
    const salaryEl = document.getElementById('review_minimum_salary_yearly');
    if (salaryEl) salaryEl.value = state.minimumSalaryYearly || '';
    const dailyEl = document.getElementById('review_minimum_daily_rate');
    if (dailyEl) dailyEl.value = state.minimumDailyRate || '';
    const engEl = document.querySelector(`input[name="engagement_pref"][value="${state.engagementType || 'both'}"]`)
      || document.querySelector('input[name="engagement_pref"][value="both"]');
    if (engEl) engEl.checked = true;
    updateCompensationVisibility();
    if (state.step >= CHECK_STEP) {
      updateCheckStep();
    }
    saveWizardState();
    return true;
  } catch {
    return false;
  }
}

function formatExtractionSummary(counts) {
  const targetTitles = Number(counts?.target_titles || 0);
  const secondaryTitles = Number(counts?.secondary_titles || 0);
  const capabilities = Number(counts?.capabilities || 0);
  return `Fresh onboarding run started. Extracted ${targetTitles} primary title${targetTitles === 1 ? '' : 's'}, ${secondaryTitles} secondary title${secondaryTitles === 1 ? '' : 's'}, and ${capabilities} capabilit${capabilities === 1 ? 'y' : 'ies'} from the current run only.`;
}

const stepMeta = {
  1: {
    title: () => isRebuildMode ? 'Upload Updated CV' : 'Upload Your CV',
    heroTitle: () => isRebuildMode ? 'Refresh Your Profile' : 'Set Up Your Job Hunting Profile',
    heroCopy: () => isRebuildMode
      ? 'Upload an updated CV. Job Hunter will refresh your profile, let you review the draft, and keep your wider settings in place until you confirm the new version.'
      : 'Upload one detailed CV. Job Hunter will build a draft profile, let you review the job titles and capabilities it found, and then ask for the minimum search basics before matching starts.',
  },
  2: {
    title: () => 'Review Draft Profile',
    heroTitle: () => isRebuildMode ? 'Review Refreshed Draft' : 'Review Your Draft Profile',
    heroCopy: () => 'Check the job titles and capabilities Job Hunter learned from your CV before you lock in the search direction.',
  },
  3: {
    title: () => 'Set Search Basics',
    heroTitle: () => 'Set Your Search Basics',
    heroCopy: () => 'Add the minimum search constraints Job Hunter needs before it starts matching roles.',
  },
  4: {
    title: () => 'Check Your Setup',
    heroTitle: () => isRebuildMode ? 'Confirm Profile Refresh' : 'Confirm Your Setup',
    heroCopy: () => 'Review the draft profile and search basics together before finishing setup.',
  },
};

function showStatus(message, kind) {
  if (workingStatusTimer && kind !== 'loading') {
    window.clearInterval(workingStatusTimer);
    workingStatusTimer = null;
  }
  statusEl.textContent = message;
  statusEl.className = message ? `status ${kind}` : 'status';
}

function startWorkingStatus(messages, stepMs = 1400) {
  const items = Array.isArray(messages) ? messages.filter(Boolean) : [];
  if (!items.length) return;
  if (workingStatusTimer) {
    window.clearInterval(workingStatusTimer);
    workingStatusTimer = null;
  }
  let index = 0;
  showStatus(items[0], 'loading');
  if (items.length === 1) return;
  workingStatusTimer = window.setInterval(() => {
    index = (index + 1) % items.length;
    statusEl.textContent = items[index];
    statusEl.className = 'status loading';
  }, stepMs);
}

function updatePrimaryCvStatus(file) {
  const dropZoneContent = document.getElementById('cv_drop_zone_content');
  if (!primaryCvStatusEl || !dropZoneContent) return;

  if (!file) {
    primaryCvStatusEl.textContent = 'No file selected yet.';
    primaryCvStatusEl.classList.remove('is-selected');
    primaryCvDropZone?.classList.remove('has-file');
    dropZoneContent.innerHTML = `
      <div class="drop-zone-content-shell">
        <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="upload-icon" style="margin-bottom: 16px;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
        <p style="margin: 0; font-size: 1.1rem; font-weight: 500;">Drag & drop your CV here, or click to browse</p>
        <p class="drop-zone-hint" style="margin-top: 8px;">Supported formats: .docx, .pdf, .md, .txt</p>
      </div>
    `;
    resetPrimaryCvDropZoneAppearance();
    return;
  }

  primaryCvStatusEl.textContent = `Selected file: ${file.name}`;
  primaryCvStatusEl.classList.add('is-selected');
  primaryCvDropZone?.classList.add('has-file');
  resetPrimaryCvDropZoneAppearance();

  dropZoneContent.innerHTML = `
    <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="upload-icon"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
    <p class="file-loaded-label">File Loaded: ${file.name}</p>
    <p class="drop-zone-hint">Click or drag another file to replace</p>
  `;
}

function resetPrimaryCvDropZoneAppearance() {
  if (!primaryCvDropZone) return;
  primaryCvDropZone.classList.remove('is-dragover');
  primaryCvDropZone.style.backgroundColor = '';
  primaryCvDropZone.style.border = '';
  primaryCvDropZone.style.boxShadow = 'none';
}

function updateCreateProfileAvailability() {
  if (!createProfileButton) return;
  createProfileButton.disabled = !primaryCvInput?.files?.[0];
}

function restorePrimaryCvSelection(file) {
  if (!primaryCvInput || !file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  primaryCvInput.files = transfer.files;
}

function setStep(stepNumber, options = {}) {
  const { scroll = true, persist = true } = options;
  currentStep = stepNumber;
  stepEls.forEach((el) => {
    const step = Number(el.dataset.step);
    const active = step === stepNumber;
    el.hidden = !active;
    el.classList.toggle('is-active', active);
  });

  const meta = stepMeta[stepNumber];
  heroTitleEl.textContent = meta.heroTitle();
  heroCopyEl.textContent = meta.heroCopy();

  const isDetailStep = stepNumber > 1;
  if (heroSectionEl) heroSectionEl.classList.toggle('is-compact', isDetailStep);
  if (workflowSummaryEl) {
    workflowSummaryEl.hidden = isDetailStep;
    workflowSummaryEl.style.display = isDetailStep ? 'none' : '';
  }

  if (stepNumber === 1 && preservedPrimaryCvFile) {
    restorePrimaryCvSelection(preservedPrimaryCvFile);
    updatePrimaryCvStatus(preservedPrimaryCvFile);
  }

  if (formTitleEl) formTitleEl.textContent = `Step ${stepNumber}. ${meta.title()}`;
  const percent = Math.round((stepNumber / STEP_COUNT) * 100);
  if (progressFillEl) {
    progressFillEl.style.width = `${percent}%`;
  }
  document.querySelectorAll('.wizard-progress-step').forEach((el, idx) => {
    const s = idx + 1;
    el.classList.toggle('is-active', s === stepNumber);
    el.classList.toggle('is-complete', s < stepNumber);
  });
  refreshStepNavigation();
  updateCreateProfileAvailability();

  if (persist) {
    saveWizardState();
  }
  if (scroll) {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
}

function normalizeLocationValue(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function locationKey(value) {
  return normalizeLocationValue(value).toLowerCase();
}

function renderLocationSuggestions() {
  locationSuggestions.innerHTML = COMMON_LOCATION_OPTIONS
    .map((value) => `<option value="${value}"></option>`)
    .join('');

  locationQuickPicks.innerHTML = COMMON_LOCATION_OPTIONS.slice(0, 8)
    .map((value) => {
      const activeClass = selectedLocations.some((item) => locationKey(item) === locationKey(value)) ? ' is-active' : '';
      return `<button class="chip-button${activeClass}" type="button" data-location="${value}">${value}</button>`;
    })
    .join('');
}

function renderSelectedLocations() {
  if (!selectedLocations.length) {
    locationSelected.innerHTML = '';
    renderLocationSuggestions();
    return;
  }

  locationSelected.innerHTML = selectedLocations
    .map((value) => (
      `<span class="location-chip">${value}<button type="button" data-remove-location="${value}" aria-label="Remove ${value}">&#215;</button></span>`
    ))
    .join('');
  renderLocationSuggestions();
}

function setSelectedLocations(values) {
  const deduped = [];
  const seen = new Set();
  for (const value of values || []) {
    const normalized = normalizeLocationValue(value);
    const key = locationKey(normalized);
    if (!normalized || seen.has(key)) continue;
    seen.add(key);
    deduped.push(normalized);
  }
  selectedLocations = deduped;
  renderSelectedLocations();
  saveWizardState();
}

function addLocation(value) {
  const normalized = normalizeLocationValue(value);
  if (!normalized) return;
  if (normalized.length < 2 || normalized.length > 80) {
    showStatus('Please use a location name between 2 and 80 characters.', 'error');
    return;
  }
  if (!/^[A-Za-z\s,'()-]+$/.test(normalized)) {
    showStatus('Locations should look like a normal city, state, or region name.', 'error');
    return;
  }
  if (selectedLocations.some((item) => locationKey(item) === locationKey(normalized))) {
    locationInput.value = '';
    return;
  }
  selectedLocations = [...selectedLocations, normalized];
  locationInput.value = '';
  showStatus('', '');
  renderSelectedLocations();
  saveWizardState();
}

function removeLocation(value) {
  const key = locationKey(value);
  selectedLocations = selectedLocations.filter((item) => locationKey(item) !== key);
  renderSelectedLocations();
  saveWizardState();
}

async function fileToPayload(file, label) {
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error(`Could not read ${file.name}`));
    reader.readAsDataURL(file);
  });
  const parts = dataUrl.split(',', 2);
  return {
    label,
    filename: file.name,
    content_base64: parts[1] || '',
  };
}

function onboardingSettingsPayload() {
  const lookbackYears = document.getElementById('os_lookback_years').value.trim();
  const minMonths = document.getElementById('os_min_months').value.trim();
  const capabilityStrengthPreset = document.getElementById('os_capability_strength_preset').value.trim();
  return {
    extraction_lookback_years: lookbackYears ? Number(lookbackYears) : undefined,
    title_extraction_min_months: minMonths ? Number(minMonths) : undefined,
    capability_strength_preset: capabilityStrengthPreset || 'balanced',
  };
}

function searchPreferencesPayload() {
  return {
    keywords: document.getElementById('review_search_keywords')?.value.trim() || '',
    locations: selectedLocations,
    engagement_type: document.querySelector('input[name="engagement_pref"]:checked').value,
    minimum_salary_yearly: document.getElementById('review_minimum_salary_yearly')?.value.trim() || '',
    minimum_daily_rate: document.getElementById('review_minimum_daily_rate')?.value.trim() || '',
  };
}

function updateCompensationVisibility() {
  const engagementType = String(document.querySelector('input[name="engagement_pref"]:checked')?.value || 'both').trim().toLowerCase();
  if (salaryYearlyBlock) salaryYearlyBlock.hidden = engagementType === 'contract';
  if (salaryDailyBlock) salaryDailyBlock.hidden = engagementType === 'permanent';
}

function normalizeOptionalNonNegativeIntegerInput(value) {
  const text = String(value ?? '').trim();
  if (!text) return '';
  const numeric = Number(text);
  if (!Number.isFinite(numeric)) return text;
  return numeric <= 0 ? '' : String(Math.trunc(numeric));
}

function validateOnboardingSettings(settings) {
  const lookback = Number(settings.extraction_lookback_years);
  const minMonths = Number(settings.title_extraction_min_months);
  const preset = String(settings.capability_strength_preset || '').trim();

  if (!Number.isInteger(lookback) || lookback < 1 || lookback > 20) {
    throw new Error('Please enter a lookback between 1 and 20 years.');
  }
  if (!Number.isInteger(minMonths) || minMonths < 1 || minMonths > 24) {
    throw new Error('Please enter a short-role threshold between 1 and 24 months.');
  }
  if (!['recent_focus', 'balanced', 'include_older_experience'].includes(preset)) {
    throw new Error('Please choose how older experience should be treated.');
  }
}

function validateSearchPreferences(searchPrefs) {
  if (searchPrefs.keywords && (searchPrefs.keywords.length < 2 || searchPrefs.keywords.length > 120)) {
    throw new Error('Please keep the primary search title between 2 and 120 characters.');
  }
  if (!searchPrefs.locations.length) {
    throw new Error('Please add at least one search location.');
  }
  if (searchPrefs.locations.length > 8) {
    throw new Error('Please keep your location list to 8 places or fewer.');
  }
  for (const location of searchPrefs.locations) {
    if (location.length < 2 || location.length > 80) {
      throw new Error('Each location should be between 2 and 80 characters.');
    }
    if (!/^[A-Za-z\s,'()-]+$/.test(location)) {
      throw new Error('Locations should look like normal city, state, or region names.');
    }
  }
  if (!['both', 'permanent', 'contract'].includes(searchPrefs.engagement_type)) {
    throw new Error('Please choose what type of work you are open to.');
  }
  if (!searchPrefs.keywords) {
    throw new Error('Please confirm one primary search title.');
  }
  if (searchPrefs.minimum_salary_yearly) {
    const yearly = Number(searchPrefs.minimum_salary_yearly);
    if (!Number.isFinite(yearly) || yearly < 0) {
      throw new Error('Please enter a valid minimum permanent salary excluding super.');
    }
  }
  if (searchPrefs.minimum_daily_rate) {
    const daily = Number(searchPrefs.minimum_daily_rate);
    if (!Number.isFinite(daily) || daily < 0) {
      throw new Error('Please enter a valid minimum contract daily rate excluding super.');
    }
  }
}

function validatePrimaryFile(file) {
  if (!file) {
    throw new Error('Choose your detailed CV first.');
  }
  const name = String(file.name || '').toLowerCase();
  if (!name.endsWith('.docx') && !name.endsWith('.pdf') && !name.endsWith('.md') && !name.endsWith('.txt')) {
    throw new Error('Please upload a .docx, .pdf, .md, or .txt CV file.');
  }
}

function assignPrimaryCvFile(file) {
  if (!primaryCvInput || !file) return;
  restorePrimaryCvSelection(file);
  preservedPrimaryCvFile = file;
  updatePrimaryCvStatus(file);
  updateCreateProfileAvailability();
  refreshStepNavigation();
}

function handlePrimaryCvDrop(event) {
  event.preventDefault();
  if (!primaryCvDropZone) return;
  primaryCvDropZone.classList.remove('is-dragover');
  const file = event.dataTransfer?.files?.[0];
  if (!file) return;
  try {
    validatePrimaryFile(file);
  } catch (error) {
    showStatus(error.message, 'error');
    updatePrimaryCvStatus(null);
    return;
  }
  assignPrimaryCvFile(file);
  showStatus('', '');
}

function applyProfileDefaults(profile) {
  const onboarding = profile?.onboarding_settings || {};
  const lookback = onboarding.extraction_lookback_years ?? 8;
  const minMonths = onboarding.title_extraction_min_months ?? 6;
  const preset = onboarding.capability_strength_preset || 'balanced';

  document.getElementById('os_lookback_years').value = String(lookback);
  document.getElementById('os_min_months').value = String(minMonths);
  document.getElementById('os_capability_strength_preset').value = String(preset);
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

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function normalizeReviewTitle(value) {
  return patternToLabel(value) || normalizeReviewText(value);
}

function normalizeReviewAlias(value) {
  return normalizeReviewText(value).toLowerCase();
}

function normalizeReviewCapability(rule) {
  const name = normalizeReviewText(rule?.name || '');
  const level = normalizeReviewText(rule?.level || '').toLowerCase();
  const aliases = [];
  const seen = new Set();
  for (const alias of Array.isArray(rule?.aliases) ? rule.aliases : []) {
    const cleaned = normalizeReviewAlias(alias);
    if (!cleaned || cleaned === name.toLowerCase() || seen.has(cleaned)) continue;
    seen.add(cleaned);
    aliases.push(cleaned);
  }
  return { name, level, aliases };
}

function dedupeReviewList(values) {
  const seen = new Set();
  const output = [];
  for (const value of values || []) {
    const cleaned = normalizeReviewTitle(value);
    const key = cleaned.toLowerCase();
    if (!cleaned || seen.has(key)) continue;
    seen.add(key);
    output.push(cleaned);
  }
  return output;
}

function renderReviewChipList(elementId, values, emptyLabel, removeAttribute) {
  const container = document.getElementById(elementId);
  if (!container) return;
  if (!values.length) {
    container.innerHTML = `<span class="chip-empty">${emptyLabel}</span>`;
    return;
  }
  container.innerHTML = values.map((value, index) => `
    <span class="chip-item">
      <span>${escapeHtml(value)}</span>
      <button type="button" ${removeAttribute}="${index}" aria-label="Remove ${escapeHtml(value)}">&#215;</button>
    </span>
  `).join('');
}


function updateCheckStep() {
  const searchPrefs = searchPreferencesPayload();
  document.getElementById('check_target_titles').textContent = reviewTargetTitles.length ? reviewTargetTitles.join(' | ') : 'Not provided';
  document.getElementById('check_secondary_titles').textContent = reviewSecondaryTitles.length ? reviewSecondaryTitles.join(' | ') : 'Not provided';
  document.getElementById('check_capabilities').textContent = reviewCapabilityRules.length
    ? `${reviewCapabilityRules.length} capability row${reviewCapabilityRules.length === 1 ? '' : 's'}`
    : 'None';
  document.getElementById('check_search_title').textContent = searchPrefs.keywords || 'Not provided';
  document.getElementById('check_locations').textContent = searchPrefs.locations.length ? searchPrefs.locations.join(' | ') : 'Not provided';
  document.getElementById('check_engagement_type').textContent = (
    searchPrefs.engagement_type === 'permanent'
      ? 'Permanent only'
      : searchPrefs.engagement_type === 'contract'
        ? 'Contract only'
        : 'Both permanent and contract'
  );
  document.getElementById('check_salary_yearly').textContent = searchPrefs.minimum_salary_yearly
    ? `$${Number(searchPrefs.minimum_salary_yearly).toLocaleString()}`
    : 'Not provided';
  document.getElementById('check_salary_daily').textContent = searchPrefs.minimum_daily_rate
    ? `$${Number(searchPrefs.minimum_daily_rate).toLocaleString()}`
    : 'Not provided';
}

function hydrateSearchBasics(profile) {
  const searchSettings = profile?.search_settings || {};
  const matchPreferences = profile?.match_preferences || {};
  const salaryPreferences = profile?.salary_preferences || {};
  document.getElementById('review_search_keywords').value = String(searchSettings.keywords || '').trim();
  document.getElementById('review_minimum_salary_yearly').value = normalizeOptionalNonNegativeIntegerInput(salaryPreferences.minimum_salary_yearly);
  document.getElementById('review_minimum_daily_rate').value = normalizeOptionalNonNegativeIntegerInput(salaryPreferences.minimum_daily_rate);
  setSelectedLocations(searchSettings.locations || []);
  const engagementType = String(matchPreferences.engagement_type || 'both').trim().toLowerCase();
  const engagementInput = document.querySelector(`input[name="engagement_pref"][value="${engagementType}"]`)
    || document.querySelector('input[name="engagement_pref"][value="both"]');
  if (engagementInput) engagementInput.checked = true;
  updateCompensationVisibility();
}

function removeReviewCapability(index) {
  reviewCapabilityRules.splice(index, 1);
  selectedReviewCapabilityIndexes = new Set(
    [...selectedReviewCapabilityIndexes]
      .filter((value) => value !== index)
      .map((value) => (value > index ? value - 1 : value))
  );
  reviewCapabilityVisibleCount = Math.max(reviewCapabilityVisibleCount - 1, INITIAL_CAPABILITY_VISIBLE_COUNT);
}

function applyReviewCapabilityAction(index, action) {
  if (!reviewCapabilityRules[index]) return;
  if (action === 'remove') {
    removeReviewCapability(index);
  }
  renderReviewStep();
}

function applyBulkReviewCapabilityAction(action) {
  const selectedIndexes = [...selectedReviewCapabilityIndexes].sort((left, right) => right - left);
  if (!selectedIndexes.length) return;
  for (const index of selectedIndexes) {
    if (action !== 'remove') continue;
    removeReviewCapability(index);
  }
  if (action === 'remove') {
    selectedReviewCapabilityIndexes.clear();
  }
  renderReviewStep();
}

function selectVisibleReviewCapabilities() {
  const filterTerm = String(document.getElementById('review_capability_filter')?.value || '').trim().toLowerCase();
  const orderedRules = reviewCapabilityRules
    .map((rule, index) => ({ rule, index }))
    .sort((left, right) => left.rule.name.localeCompare(right.rule.name))
    .filter((item) => !filterTerm || item.rule.name.toLowerCase().includes(filterTerm));
  const visibleRules = filterTerm ? orderedRules : orderedRules.slice(0, reviewCapabilityVisibleCount);
  visibleRules.forEach(({ index }) => selectedReviewCapabilityIndexes.add(index));
  renderReviewCapabilities();
}

function clearSelectedReviewCapabilities() {
  selectedReviewCapabilityIndexes.clear();
  renderReviewCapabilities();
}

function toggleSelectedReviewCapability(index, checked) {
  if (checked) {
    selectedReviewCapabilityIndexes.add(index);
  } else {
    selectedReviewCapabilityIndexes.delete(index);
  }
  renderReviewCapabilities();
}

function renderReviewCapabilities() {
  const container = document.getElementById('review_capability_cards');
  if (!container) return;
  if (!reviewCapabilityRules.length) {
    if (reviewCapabilityCountEl) {
      reviewCapabilityCountEl.textContent = '0 shown';
      reviewCapabilityCountEl.classList.remove('is-selected');
    }
    container.innerHTML = '<div class="chip-empty">No capabilities found yet.</div>';
    return;
  }
  const filterTerm = String(document.getElementById('review_capability_filter')?.value || '').trim().toLowerCase();
  const orderedRules = reviewCapabilityRules
    .map((rule, index) => ({ rule, index }))
    .sort((left, right) => left.rule.name.localeCompare(right.rule.name))
    .filter((item) => {
      if (!filterTerm) return true;
      return item.rule.name.toLowerCase().includes(filterTerm)
        || item.rule.aliases.some((alias) => alias.includes(filterTerm));
    });
  const visibleRules = filterTerm ? orderedRules : orderedRules.slice(0, reviewCapabilityVisibleCount);
  const hiddenCount = Math.max(orderedRules.length - visibleRules.length, 0);
  const selectedVisibleCount = visibleRules.filter(({ index }) => selectedReviewCapabilityIndexes.has(index)).length;
  if (reviewCapabilityCountEl) {
    reviewCapabilityCountEl.textContent = `${visibleRules.length} shown${hiddenCount ? ` of ${orderedRules.length}` : ''}`;
    reviewCapabilityCountEl.classList.toggle('is-selected', selectedReviewCapabilityIndexes.size > 0);
  }
  const rowsHtml = visibleRules.length ? visibleRules.map(({ rule, index }) => {
    const titleCaseName = rule.name.toLowerCase().split(' ').map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
    const aliasHtml = rule.aliases.length && isTestMode
      ? `
        <div class="review-capability-aliases capability-aliases test-only" aria-label="Background keywords">
          ${rule.aliases.map((alias) => `<span class="review-capability-alias alias-tag">${escapeHtml(patternToLabel(alias) || alias)}</span>`).join('')}
        </div>
      `
      : '';
    const selectedClass = selectedReviewCapabilityIndexes.has(index) ? ' is-selected' : '';
    return `
      <article class="review-capability-row${selectedClass}" data-review-capability-index="${index}">
        <div class="review-capability-main">
          <span class="review-capability-head">
            <strong class="review-capability-title">${escapeHtml(titleCaseName || 'Untitled capability')}</strong>
            <span class="review-capability-selected-badge" aria-hidden="true">Selected</span>
          </span>
          ${aliasHtml}
        </div>
        <div class="review-capability-actions" role="group" aria-label="Actions for ${escapeHtml(titleCaseName || 'capability')}">
          <button class="review-capability-action review-capability-action-danger" type="button" data-review-capability-action="remove" data-review-capability-index="${index}" aria-label="Remove ${escapeHtml(titleCaseName || 'capability')}" title="Remove ${escapeHtml(titleCaseName || 'capability')}">
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" class="review-capability-action-icon">
              <path d="M9 3h6l1 2h4v2H4V5h4l1-2Zm1 7h2v8h-2v-8Zm4 0h2v8h-2v-8ZM7 10h2v8H7v-8Zm1 11h8a2 2 0 0 0 2-2V8H6v11a2 2 0 0 0 2 2Z" fill="currentColor"/>
            </svg>
            <span class="sr-only">Remove</span>
          </button>
        </div>
      </article>
    `;
  }).join('') : '<div class="chip-empty">No matching capabilities found.</div>';
  const bulkDisabled = selectedReviewCapabilityIndexes.size ? '' : ' disabled';
  const footerHtml = hiddenCount > 0 ? `
    <div class="review-capability-footer">
      <button class="secondary" type="button" data-review-show-more="true">Show ${escapeHtml(String(Math.min(CAPABILITY_VISIBLE_INCREMENT, hiddenCount)))} more</button>
      <button class="secondary review-capability-footer-link" type="button" data-review-show-all="true">Show all ${escapeHtml(String(orderedRules.length))}</button>
    </div>
  ` : '';
  const toolbarHtml = selectedReviewCapabilityIndexes.size ? `
    <div class="review-capability-toolbar">
      <div class="review-capability-toolbar-main">
        <span class="review-capability-toolbar-copy">${selectedVisibleCount} shown selected</span>
        <div class="review-capability-bulk-actions">
          <button class="secondary" type="button" data-review-select-visible="true">Select shown</button>
          <button class="secondary" type="button" data-review-clear-selection="true"${bulkDisabled}>Clear selection</button>
          <button class="secondary" type="button" data-review-bulk-action="remove"${bulkDisabled}>Remove selected</button>
        </div>
      </div>
    </div>
  ` : '';
  container.innerHTML = `
    <section class="review-capability-group">
      <div class="review-capability-row-list">${rowsHtml}</div>
      ${footerHtml}
      ${toolbarHtml}
    </section>
  `;
}

function renderReviewStep() {
  selectedReviewCapabilityIndexes = new Set(
    [...selectedReviewCapabilityIndexes].filter((index) => index >= 0 && index < reviewCapabilityRules.length)
  );
  renderReviewChipList('review_target_titles_list', reviewTargetTitles, 'No primary job titles extracted yet.', 'data-remove-review-target');
  renderReviewChipList('review_secondary_titles_list', reviewSecondaryTitles, 'No secondary titles extracted yet.', 'data-remove-review-secondary');
  renderReviewCapabilities();
  saveWizardState();
}

function hydrateDraftStep(profile) {
  reviewTargetTitles = dedupeReviewList(profile?.primary_job_title_pattern || []);
  reviewSecondaryTitles = dedupeReviewList(profile?.secondary_title_patterns || []);
  reviewCapabilityRules = (profile?.capability_profile_rules || []).map(normalizeReviewCapability).filter((rule) => rule.name);
  selectedReviewCapabilityIndexes.clear();
  reviewCapabilityVisibleCount = INITIAL_CAPABILITY_VISIBLE_COUNT;
  renderReviewStep();
}

function buildCompletionRedirectState(payload, searchPrefs) {
  const profile = payload?.profile || {};
  const targets = Array.isArray(profile.primary_job_title_pattern)
    ? profile.primary_job_title_pattern.slice(0, 4).map((value) => String(value || '').trim()).filter(Boolean)
    : [];
  const locations = Array.isArray(searchPrefs?.locations)
    ? searchPrefs.locations.map((value) => String(value || '').trim()).filter(Boolean)
    : [];
  return {
    kind: isRebuildMode ? 'profile-refresh' : 'onboarding-complete',
    title: isRebuildMode ? 'Profile refreshed' : 'Profile built',
    message: payload?.message || (isRebuildMode ? 'Your profile was refreshed from the uploaded CV.' : 'Your profile was built from the uploaded CV.'),
    target_titles: targets,
    search_keywords: String(searchPrefs?.keywords || '').trim(),
    search_locations: locations,
    created_at: new Date().toISOString(),
  };
}

function storeCompletionRedirectState(payload, searchPrefs) {
  try {
    const redirectState = buildCompletionRedirectState(payload, searchPrefs);
    window.sessionStorage.setItem('jobHunter.onboardingWelcome', JSON.stringify(redirectState));
  } catch (error) {
    console.warn('Could not store onboarding redirect state.', error);
  }
}

async function createProfile() {
  const primary = document.getElementById('primary_cv').files[0];
  const onboardingSettings = onboardingSettingsPayload();

  validatePrimaryFile(primary);
  validateOnboardingSettings(onboardingSettings);
  resetOnboardingWizardState();

  if (isRebuildMode) {
    const confirmed = window.confirm(
      'Refresh your profile using this CV?\n\n'
      + 'This will re-extract your summaries, capability rules, and evidence tiers from the document.\n\n'
      + 'Your custom Decision Weights, Salary Preferences, and Search Settings will be preserved.'
    );
    if (!confirmed) return;
  }

  const files = [await fileToPayload(primary, 'Primary CV')];
  const response = await fetch('/api/onboarding/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      files,
      onboarding_settings: onboardingSettings,
      search_preferences: {},
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || 'Could not create profile');
  }

  lastImportPayload = payload;
  maxUnlockedStep = Math.max(maxUnlockedStep, REVIEW_STEP);
  hydrateDraftStep(payload.profile || {});
  hydrateSearchBasics(payload.profile || {});
  setStep(REVIEW_STEP);
  showStatus(
    payload?.fresh_onboarding_run_started
      ? formatExtractionSummary(payload.extraction_counts || {})
      : 'Your draft profile is ready. Review the role direction before you continue.',
    'ok',
  );
}

function continueFromReview() {
  if (!reviewTargetTitles.length) {
    throw new Error('Please keep at least one target title before continuing.');
  }
  maxUnlockedStep = Math.max(maxUnlockedStep, SEARCH_STEP);
  renderReviewStep();
  setStep(SEARCH_STEP);
  showStatus('', '');
}

function continueFromSearchBasics() {
  const searchPrefs = searchPreferencesPayload();
  validateSearchPreferences(searchPrefs);
  maxUnlockedStep = Math.max(maxUnlockedStep, CHECK_STEP);
  updateCheckStep();
  setStep(CHECK_STEP);
  showStatus('', '');
}

async function finishSetup() {
  const searchPrefs = searchPreferencesPayload();
  validateSearchPreferences(searchPrefs);
  if (!reviewTargetTitles.length) {
    throw new Error('Please keep at least one target title before finishing setup.');
  }

  const response = await fetch('/api/onboarding/confirm-profile-signals', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      search_keyword: searchPrefs.keywords,
      search_locations: searchPrefs.locations,
      engagement_type: searchPrefs.engagement_type,
      minimum_salary_yearly: searchPrefs.minimum_salary_yearly,
      minimum_daily_rate: searchPrefs.minimum_daily_rate,
      primary_job_title_pattern: reviewTargetTitles,
      secondary_title_patterns: reviewSecondaryTitles,
      capability_profile_rules: reviewCapabilityRules.map(normalizeReviewCapability).filter((rule) => rule.name),
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || 'Could not finish onboarding');
  }

  const finalSearchPrefs = {
    ...(lastImportPayload?.profile?.search_settings || {}),
    keywords: searchPrefs.keywords || String(payload?.profile?.search_settings?.keywords || '').trim(),
    locations: searchPrefs.locations,
    engagement_type: searchPrefs.engagement_type,
  };
  storeCompletionRedirectState(payload, finalSearchPrefs);
  showStatus(payload.message || 'Setup complete.', 'ok');
  setTimeout(() => {
    window.location.href = '/';
  }, 700);
}

async function loadProfileDefaults() {
  const response = await fetch('/api/profile');
  if (!response.ok) return;
  const profile = await response.json().catch(() => ({}));
  applyProfileDefaults(profile || {});
}

if (isTestMode && onbTestPanel && onbTestTrigger && onbTestMenu) {
  onbTestPanel.hidden = false;

  onbTestTrigger.addEventListener('click', () => {
    setTestMenuOpen(!onbTestMenu.classList.contains('is-open'));
  });

  document.addEventListener('click', (event) => {
    if (!onbTestPanel.contains(event.target)) {
      setTestMenuOpen(false);
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      setTestMenuOpen(false);
    }
  });

  onbResetUserBtn?.addEventListener('click', async () => {
    const confirmed = window.confirm(
      'Reset current user?\n\n'
      + 'This clears the current profile, onboarding state, uploaded CV state, local review feedback, and job history.\n\n'
      + 'Shared learned signals will be preserved.'
    );
    if (!confirmed) {
      return;
    }
    try {
      setTestMenuOpen(false);
      const payload = await postTestAction('/api/test/reset-user');
      clearOnboardingBrowserState();
      window.location.href = payload.redirect_to || '/start';
    } catch (error) {
      window.alert(error.message || 'Could not reset current user.');
    }
  });

  onbResetLearningBtn?.addEventListener('click', async () => {
    const confirmed = window.confirm(
      'Reset global learning?\n\n'
      + 'This wipes the shared learned signal memory for every test user.\n\n'
      + 'This is dangerous and cannot be undone.'
    );
    if (!confirmed) {
      return;
    }
    try {
      setTestMenuOpen(false);
      const payload = await postTestAction('/api/test/reset-learning');
      window.alert(payload.message || 'Global learning reset.');
    } catch (error) {
      window.alert(error.message || 'Could not reset global learning.');
    }
  });
}

createProfileButton.addEventListener('click', async (event) => {
  const btn = event.currentTarget;
  const originalLabel = btn.textContent;
  btn.classList.add('is-working');
  btn.disabled = true;
  btn.textContent = isRebuildMode ? 'Refreshing Draft...' : 'Building Draft...';
  startWorkingStatus([
    'Fresh onboarding run started.',
    isRebuildMode ? 'Reading your updated CV...' : 'Reading your CV...',
    'Extracting titles and capabilities...',
    'Reviewing role history and recency...',
    'Building your draft profile...',
  ]);
  try {
    await createProfile();
  } catch (error) {
    showStatus(error.message, 'error');
  } finally {
    btn.classList.remove('is-working');
    updateCreateProfileAvailability();
    btn.textContent = originalLabel;
  }
});

document.getElementById('continue_to_search_basics').addEventListener('click', () => {
  try {
    continueFromReview();
  } catch (error) {
    showStatus(error.message, 'error');
  }
});

document.getElementById('continue_to_check').addEventListener('click', () => {
  try {
    continueFromSearchBasics();
  } catch (error) {
    showStatus(error.message, 'error');
  }
});

document.getElementById('confirm_review').addEventListener('click', async (event) => {
  const btn = event.currentTarget;
  const originalLabel = btn.textContent;
  btn.classList.add('is-working');
  btn.disabled = true;
  btn.textContent = isRebuildMode ? 'Saving Refresh...' : 'Finishing Setup...';
  startWorkingStatus([
    'Saving your reviewed profile...',
    'Applying search basics...',
    'Finalising setup...',
  ]);
  try {
    await finishSetup();
  } catch (error) {
    showStatus(error.message, 'error');
  } finally {
    btn.classList.remove('is-working');
    btn.disabled = false;
    btn.textContent = originalLabel;
  }
});

document.getElementById('back_to_upload_footer').addEventListener('click', () => setStep(1));
document.getElementById('back_to_review_footer').addEventListener('click', () => setStep(REVIEW_STEP));
document.getElementById('back_to_search_basics_footer').addEventListener('click', () => setStep(SEARCH_STEP));
document.getElementById('edit_draft_profile').addEventListener('click', () => setStep(REVIEW_STEP));
document.getElementById('edit_search_basics').addEventListener('click', () => setStep(SEARCH_STEP));
stepNavButtons.forEach((button) => {
  button.addEventListener('click', () => {
    if (button.disabled) return;
    const targetStep = Number(button.dataset.stepNav || 0);
    if (!targetStep || targetStep === currentStep) return;
    setStep(targetStep);
  });
});
document.querySelector('.wizard-progress-steps')?.addEventListener('click', (event) => {
  const trigger = event.target.closest('[data-step-nav]');
  if (!trigger || trigger.disabled) return;
  const targetStep = Number(trigger.dataset.stepNav || 0);
  if (!targetStep || targetStep === currentStep) return;
  setStep(targetStep);
});

document.getElementById('review_add_target_title').addEventListener('click', () => {
  const input = document.getElementById('review_target_titles_input');
  const cleaned = normalizeReviewTitle(input.value);
  if (!cleaned) return;
  reviewTargetTitles = dedupeReviewList([...reviewTargetTitles, cleaned]);
  input.value = '';
  renderReviewStep();
});

document.getElementById('review_add_secondary_title').addEventListener('click', () => {
  const input = document.getElementById('review_secondary_titles_input');
  const cleaned = normalizeReviewTitle(input.value);
  if (!cleaned) return;
  reviewSecondaryTitles = dedupeReviewList([...reviewSecondaryTitles, cleaned]);
  input.value = '';
  renderReviewStep();
});

document.getElementById('review_capability_filter').addEventListener('input', () => {
  renderReviewCapabilities();
  saveWizardState();
});

document.querySelector('[data-step="2"]').addEventListener('click', (event) => {
  const removeTarget = event.target.closest('[data-remove-review-target]');
  if (removeTarget) {
    reviewTargetTitles.splice(Number(removeTarget.dataset.removeReviewTarget), 1);
    renderReviewStep();
    return;
  }
  const removeSecondary = event.target.closest('[data-remove-review-secondary]');
  if (removeSecondary) {
    reviewSecondaryTitles.splice(Number(removeSecondary.dataset.removeReviewSecondary), 1);
    renderReviewStep();
    return;
  }
  const capabilityAction = event.target.closest('[data-review-capability-action]');
  if (capabilityAction) {
    applyReviewCapabilityAction(
      Number(capabilityAction.dataset.reviewCapabilityIndex),
      capabilityAction.dataset.reviewCapabilityAction,
    );
    return;
  }
  const bulkAction = event.target.closest('[data-review-bulk-action]');
  if (bulkAction) {
    applyBulkReviewCapabilityAction(bulkAction.dataset.reviewBulkAction);
    return;
  }
  if (event.target.closest('[data-review-select-visible]')) {
    selectVisibleReviewCapabilities();
    return;
  }
  if (event.target.closest('[data-review-clear-selection]')) {
    clearSelectedReviewCapabilities();
    return;
  }
  if (event.target.closest('[data-review-show-all]')) {
    reviewCapabilityVisibleCount = reviewCapabilityRules.length;
    renderReviewCapabilities();
    saveWizardState();
    return;
  }
  if (event.target.closest('[data-review-show-more]')) {
    reviewCapabilityVisibleCount = Math.min(
      reviewCapabilityVisibleCount + CAPABILITY_VISIBLE_INCREMENT,
      reviewCapabilityRules.length,
    );
    renderReviewCapabilities();
    saveWizardState();
    return;
  }
  const capabilityRow = event.target.closest('[data-review-capability-index]');
  if (
    capabilityRow
    && !event.target.closest('button')
  ) {
    const index = Number(capabilityRow.dataset.reviewCapabilityIndex);
    const nextChecked = !selectedReviewCapabilityIndexes.has(index);
    toggleSelectedReviewCapability(index, nextChecked);
  }
});

document.querySelectorAll(
  '#review_search_keywords, #review_minimum_salary_yearly, #review_minimum_daily_rate, input[name="engagement_pref"]'
).forEach((input) => {
  input.addEventListener('input', saveWizardState);
  input.addEventListener('change', saveWizardState);
});

document.querySelector('[data-step="2"]').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && event.target.id === 'review_target_titles_input') {
    event.preventDefault();
    document.getElementById('review_add_target_title').click();
  }
  if (event.key === 'Enter' && event.target.id === 'review_secondary_titles_input') {
    event.preventDefault();
    document.getElementById('review_add_secondary_title').click();
  }
});

addLocationButton.addEventListener('click', () => addLocation(locationInput.value));
locationInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    addLocation(locationInput.value);
  }
});
locationQuickPicks.addEventListener('click', (event) => {
  const button = event.target.closest('[data-location]');
  if (!button) return;
  addLocation(button.getAttribute('data-location'));
});
document.querySelectorAll('input[name="engagement_pref"]').forEach((input) => {
  input.addEventListener('change', updateCompensationVisibility);
});
locationSelected.addEventListener('click', (event) => {
  const button = event.target.closest('[data-remove-location]');
  if (!button) return;
  removeLocation(button.getAttribute('data-remove-location'));
});

// Function to move privacy tip into a callout box
function movePrivacyTip() {
  const privacyTipEl = document.getElementById('privacy_tip'); // Assuming an ID for the privacy tip
  if (privacyTipEl && primaryCvDropZone) {
    const calloutBox = document.createElement('div');
    calloutBox.className = 'privacy-callout'; // Add a class for styling
    calloutBox.style.backgroundColor = 'var(--state-warning-bg)';
    calloutBox.style.color = 'var(--state-warning-text)';
    calloutBox.style.border = '1px solid var(--state-warning-border)';
    calloutBox.style.padding = '12px';
    calloutBox.style.marginBottom = '20px';
    calloutBox.style.borderRadius = '8px';
    calloutBox.style.fontSize = '0.9em';

    calloutBox.innerHTML = privacyTipEl.innerHTML; // Move content
    privacyTipEl.parentNode.removeChild(privacyTipEl); // Remove original element
    primaryCvDropZone.parentNode.insertBefore(calloutBox, primaryCvDropZone);
  }
}

// Function to add small info icons to salary fields to explain "Excluding super"
function addSalaryInfoIcons() {
  const salaryFields = [
    'review_minimum_salary_yearly',
    'review_minimum_daily_rate'
  ];

  salaryFields.forEach(id => {
    const input = document.getElementById(id);
    if (input) {
      const infoIcon = document.createElement('span');
      infoIcon.innerHTML = '&#9432;'; // Info icon character (i)
      infoIcon.title = 'Excluding super';
      infoIcon.style.marginLeft = '8px';
      infoIcon.style.cursor = 'help';
      infoIcon.style.color = 'var(--muted)';
      infoIcon.style.fontSize = '1rem';
      infoIcon.style.verticalAlign = 'middle';
      input.parentNode.insertBefore(infoIcon, input.nextSibling);
    }
  });
}

renderLocationSuggestions();
loadProfileDefaults().catch(() => {});
if (!restoreWizardState()) {
  setStep(1, { scroll: false });
}
refreshStepNavigation();
updatePrimaryCvStatus(primaryCvInput?.files?.[0] || preservedPrimaryCvFile || null);
updateCreateProfileAvailability();
updateCompensationVisibility();
addSalaryInfoIcons();

if (primaryCvDropZone && primaryCvInput) {
  resetPrimaryCvDropZoneAppearance();

  movePrivacyTip(); // Call the privacy tip function here to ensure it runs after DOM is ready and elements are defined

  // Existing event listeners for primaryCvDropZone
  primaryCvDropZone.addEventListener('click', () => primaryCvInput.click());
  primaryCvDropZone.addEventListener('dragenter', (event) => {
    event.preventDefault();
    primaryCvDropZone.classList.add('is-dragover');
    primaryCvDropZone.style.borderColor = 'var(--accent)';
    primaryCvDropZone.style.boxShadow = '0 0 12px color-mix(in srgb, var(--accent) 20%, transparent)';
  });
  primaryCvDropZone.addEventListener('dragover', (event) => {
    event.preventDefault();
    primaryCvDropZone.classList.add('is-dragover');
    primaryCvDropZone.style.borderColor = 'var(--accent)';
    primaryCvDropZone.style.boxShadow = '0 0 12px color-mix(in srgb, var(--accent) 20%, transparent)';
  });
  primaryCvDropZone.addEventListener('dragleave', (event) => {
    if (event.target === primaryCvDropZone) {
      resetPrimaryCvDropZoneAppearance();
    }
  });
  primaryCvDropZone.addEventListener('drop', handlePrimaryCvDrop);
  primaryCvInput.addEventListener('change', () => {
    const selectedFile = primaryCvInput.files?.[0] || null;
    if (!selectedFile) {
      if (preservedPrimaryCvFile) {
        restorePrimaryCvSelection(preservedPrimaryCvFile);
        updatePrimaryCvStatus(preservedPrimaryCvFile);
      } else {
        updatePrimaryCvStatus(null);
      }
      updateCreateProfileAvailability();
      return;
    }
    preservedPrimaryCvFile = selectedFile;
    updatePrimaryCvStatus(selectedFile);
    updateCreateProfileAvailability();
  });
}
