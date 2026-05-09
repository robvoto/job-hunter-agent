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
      const response = await jobHunterFetch(path, {
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

function normalizeReviewText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function normalizeReviewTitle(value) {
  return normalizeReviewText(value);
}

function normalizeReviewTitleKey(value) {
  return normalizeReviewTitle(value).toLowerCase();
}

function normalizeReviewTitleLists(primaryValues, secondaryValues) {
  const primary = [];
  const primarySeen = new Set();
  for (const value of Array.isArray(primaryValues) ? primaryValues : []) {
    const cleaned = normalizeReviewTitle(value);
    const key = normalizeReviewTitleKey(cleaned);
    if (!cleaned || primarySeen.has(key)) continue;
    primarySeen.add(key);
    primary.push(cleaned);
  }
  const secondary = [];
  const secondarySeen = new Set();
  for (const value of Array.isArray(secondaryValues) ? secondaryValues : []) {
    const cleaned = normalizeReviewTitle(value);
    const key = normalizeReviewTitleKey(cleaned);
    if (!cleaned || primarySeen.has(key) || secondarySeen.has(key)) continue;
    secondarySeen.add(key);
    secondary.push(cleaned);
  }
  return { primary, secondary };
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
    const normalizedTitles = normalizeReviewTitleLists(state.reviewTargetTitles || [], state.reviewSecondaryTitles || []);
    reviewTargetTitles = normalizedTitles.primary;
    reviewSecondaryTitles = normalizedTitles.secondary;
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
