const urlParams = new URLSearchParams(window.location.search);
const isRebuildMode = urlParams.get('mode') === 'rebuild';
const refs = Object.freeze({
  status: document.getElementById('status'),
  stepEls: Array.from(document.querySelectorAll('.wizard-step')),
  wizardProgressSteps: Array.from(document.querySelectorAll('.wizard-progress-step')),
  heroSection: document.querySelector('.hero'),
  heroTitle: document.getElementById('hero_title'),
  heroCopy: document.getElementById('hero_copy'),
  formTitle: document.getElementById('form_title'),
  workflowSummary: document.getElementById('workflow_summary'),
  workflowStep2: document.getElementById('workflow_step_2'),
  progressFill: document.getElementById('wizard_progress_fill'),
  primaryCvInput: document.getElementById('primary_cv'),
  primaryCvDropZone: document.getElementById('cv_drop_zone'),
  primaryCvStatus: document.getElementById('primary_cv_status'),
  cvDropZoneContent: document.getElementById('cv_drop_zone_content'),
  locationSelect: document.getElementById('location_search'),
  locationSelected: document.getElementById('location_selected'),
  workModePreferences: Array.from(document.querySelectorAll('input[name="work_mode_preference"]')),
  governmentPreferenceSelect: document.getElementById('government_preference'),
  reviewCapabilityCount: document.getElementById('review_capability_count'),
  salaryYearlyBlock: document.getElementById('salary_yearly_block'),
  salaryDailyBlock: document.getElementById('salary_daily_block'),
  createProfileButton: document.getElementById('create_profile'),
  stepNavButtons: Array.from(document.querySelectorAll('[data-step-nav]')),
  onbTestPanel: document.getElementById('onb_test_panel'),
  onbTestTrigger: document.getElementById('onb_test_trigger'),
  onbTestMenu: document.getElementById('onb_test_menu'),
  onbResetUserBtn: document.getElementById('onb_reset_user_btn'),
  onbResetLearningBtn: document.getElementById('onb_reset_learning_btn'),
  capabilityStrengthPreset: document.getElementById('os_capability_strength_preset'),
  reviewSearchKeywords: document.getElementById('review_search_keywords'),
  reviewMinimumSalaryYearly: document.getElementById('review_minimum_salary_yearly'),
  reviewMinimumDailyRate: document.getElementById('review_minimum_daily_rate'),
  reviewCapabilityFilter: document.getElementById('review_capability_filter'),
  reviewCapabilityCards: document.getElementById('review_capability_cards'),
  reviewCapabilityHelp: document.getElementById('review_capability_help'),
  primaryCvLimitHelp: document.getElementById('primary_cv_limit_help'),
  engagementInputs: Array.from(document.querySelectorAll('input[name="engagement_pref"]')),
});
const {
  status: statusEl,
  stepEls,
  wizardProgressSteps,
  heroSection: heroSectionEl,
  heroTitle: heroTitleEl,
  heroCopy: heroCopyEl,
  formTitle: formTitleEl,
  workflowSummary: workflowSummaryEl,
  workflowStep2: workflowStep2El,
  progressFill: progressFillEl,
  primaryCvInput,
  primaryCvDropZone,
  primaryCvStatus: primaryCvStatusEl,
  cvDropZoneContent: primaryCvDropZoneContentEl,
  locationSelect,
  locationSelected,
  governmentPreferenceSelect,
  reviewCapabilityCount: reviewCapabilityCountEl,
  salaryYearlyBlock,
  salaryDailyBlock,
  createProfileButton,
  stepNavButtons,
  onbTestPanel,
  onbTestTrigger,
  onbTestMenu,
  onbResetUserBtn,
  onbResetLearningBtn,
  capabilityStrengthPreset: capabilityStrengthPresetEl,
  reviewSearchKeywords: reviewSearchKeywordsEl,
  reviewMinimumSalaryYearly: reviewMinimumSalaryYearlyEl,
  reviewMinimumDailyRate: reviewMinimumDailyRateEl,
  reviewCapabilityFilter: reviewCapabilityFilterEl,
  reviewCapabilityCards: reviewCapabilityCardsEl,
  reviewCapabilityHelp: reviewCapabilityHelpEl,
  primaryCvLimitHelp: primaryCvLimitHelpEl,
} = refs;
const STEP_COUNT = 4;
const REVIEW_STEP = 2;
const SEARCH_STEP = 3;
const CHECK_STEP = 4;
const locationUi = window.JobHunterLocationUi || {};
const onboardingCurrencyUi = window.JobHunterCurrencyUi || {};
const capabilityUi = window.JobHunterCapabilityUi || {};
const capabilityReviewCopy = capabilityUi.reviewCopy || {};
const ONBOARDING_DEFAULTS = window.__JOB_HUNTER_ONBOARDING_DEFAULTS__ || {};
const ONBOARDING_CV_PAGE_LIMIT = Number(ONBOARDING_DEFAULTS.cv_max_pages || 0);
const salaryLimits = window.__JOB_HUNTER_SALARY_LIMITS__ || {};
const ENGAGEMENT_TYPE_OPTIONS = Array.isArray(window.__JOB_HUNTER_ENGAGEMENT_TYPE_OPTIONS__)
  ? window.__JOB_HUNTER_ENGAGEMENT_TYPE_OPTIONS__
  : [];
const ENGAGEMENT_TYPE_DEFAULT = String(
  window.__JOB_HUNTER_ENGAGEMENT_TYPE_DEFAULT__
  || window.__JOB_HUNTER_ENGAGEMENT_TYPE_OPTIONS__?.[0]?.value
  || ''
).trim().toLowerCase();
const ENGAGEMENT_TYPE_VALUES = new Set(ENGAGEMENT_TYPE_OPTIONS.map((option) => String(option.value || '').trim().toLowerCase()).filter(Boolean));
const GOVERNMENT_PREFERENCE_OPTIONS = Array.isArray(window.__JOB_HUNTER_GOVERNMENT_PREFERENCE_OPTIONS__)
  ? window.__JOB_HUNTER_GOVERNMENT_PREFERENCE_OPTIONS__
  : [];
const GOVERNMENT_PREFERENCE_DEFAULT = String(
  window.__JOB_HUNTER_GOVERNMENT_PREFERENCE_DEFAULT__
  || GOVERNMENT_PREFERENCE_OPTIONS?.[0]?.value
  || 'any'
).trim().toLowerCase();
const GOVERNMENT_PREFERENCE_LABELS = Object.fromEntries(
  GOVERNMENT_PREFERENCE_OPTIONS
    .map((option) => [String(option.value || '').trim().toLowerCase(), String(option.label || '').trim()])
    .filter(([value]) => Boolean(value))
);
const WORK_MODE_PREFERENCE_OPTIONS = Array.isArray(window.__JOB_HUNTER_WORK_MODE_PREFERENCE_OPTIONS__)
  ? window.__JOB_HUNTER_WORK_MODE_PREFERENCE_OPTIONS__
  : [];
const WORK_MODE_PREFERENCE_VALUES = new Set(
  WORK_MODE_PREFERENCE_OPTIONS
    .map((option) => String(option.value || '').trim().toLowerCase())
    .filter((value) => Boolean(value))
);

if (reviewCapabilityHelpEl) {
  reviewCapabilityHelpEl.textContent = capabilityReviewCopy.onboardingHelp || reviewCapabilityHelpEl.textContent;
}
if (primaryCvLimitHelpEl) {
  primaryCvLimitHelpEl.textContent = Number.isFinite(ONBOARDING_CV_PAGE_LIMIT) && ONBOARDING_CV_PAGE_LIMIT > 0
    ? `We read the first ${ONBOARDING_CV_PAGE_LIMIT} pages of your CV. Longer files are truncated and flagged during onboarding.`
    : 'We read only a limited slice of your CV. Longer files are truncated and flagged during onboarding.';
}
if (workflowStep2El) {
  workflowStep2El.textContent = Number.isFinite(ONBOARDING_CV_PAGE_LIMIT) && ONBOARDING_CV_PAGE_LIMIT > 0
    ? `We extract likely job titles, capabilities, and a starter search direction from the first ${ONBOARDING_CV_PAGE_LIMIT} pages of your CV.`
    : 'We extract likely job titles, capabilities, and a starter search direction from your CV.';
}
const PRIMARY_CV_COPY = {
  emptyTitle: 'Drop your CV here or click to browse',
  emptyHint: 'Formats: .docx, .pdf, .md, .txt',
  loadedHint: 'Drop another file or click to replace',
};
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
let searchBasicsPersistTimer = null;

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
      || String(reviewSearchKeywordsEl?.value || '').trim()
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



function getSelectedEngagementType() {
  const value = String(refs.engagementInputs.find((input) => input.checked)?.value || ENGAGEMENT_TYPE_DEFAULT || 'both').trim().toLowerCase();
  if (ENGAGEMENT_TYPE_VALUES.size > 0 && !ENGAGEMENT_TYPE_VALUES.has(value)) {
    const fallback = refs.engagementInputs[0];
    if (fallback) fallback.checked = true;
    return String(fallback?.value || ENGAGEMENT_TYPE_DEFAULT || 'both').trim().toLowerCase();
  }
  return value;
}

function setSelectedEngagementType(value) {
  const selected = String(value || ENGAGEMENT_TYPE_DEFAULT).trim().toLowerCase();
  const input = refs.engagementInputs.find((item) => item.value === selected)
    || refs.engagementInputs.find((item) => item.value === ENGAGEMENT_TYPE_DEFAULT);
  if (input) input.checked = true;
}

function getGovernmentPreferenceValue() {
  return String(governmentPreferenceSelect?.value || GOVERNMENT_PREFERENCE_DEFAULT).trim().toLowerCase();
}

function setGovernmentPreferenceValue(value) {
  const selected = String(value || GOVERNMENT_PREFERENCE_DEFAULT).trim().toLowerCase();
  if (governmentPreferenceSelect) {
    const validValue = GOVERNMENT_PREFERENCE_LABELS[selected] ? selected : GOVERNMENT_PREFERENCE_DEFAULT;
    governmentPreferenceSelect.value = validValue;
  }
}

function getSalaryLimitMaximum(key) {
  const limit = salaryLimits?.[key] || {};
  const parsed = Number(limit.max);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : Infinity;
}

function setCurrencyFieldValue(input, value) {
  if (!input) return;
  if (onboardingCurrencyUi.setCurrencyInputValue) {
    onboardingCurrencyUi.setCurrencyInputValue(input, value);
    return;
  }
  input.value = String(value ?? '');
}

function parseCurrencyFieldValue(value) {
  if (onboardingCurrencyUi.parseCurrencyValue) {
    return onboardingCurrencyUi.parseCurrencyValue(value);
  }
  const cleaned = String(value ?? '').replace(/[^\d]/g, '');
  return cleaned ? Number(cleaned) : '';
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
  if (reviewCapabilityFilterEl) reviewCapabilityFilterEl.value = '';
  if (reviewCapabilityCardsEl) reviewCapabilityCardsEl.innerHTML = '';
  refreshStepNavigation();
}

function saveWizardState() {
  if (currentStep < 2 && !hasDraftProfileState()) {
    window.sessionStorage.removeItem(WIZARD_STATE_KEY);
    return;
  }
  window.sessionStorage.setItem(WIZARD_STATE_KEY, JSON.stringify({
    step: currentStep,
    maxUnlockedStep,
    reviewTargetTitles,
    reviewSecondaryTitles,
    reviewCapabilityRules,
    reviewCapabilityVisibleCount,
    selectedLocations,
    workModePreference: getWorkModePreferenceValues(),
    searchKeywords: reviewSearchKeywordsEl?.value || '',
    minimumSalaryYearly: reviewMinimumSalaryYearlyEl?.value || '',
    minimumDailyRate: reviewMinimumDailyRateEl?.value || '',
    engagementType: getSelectedEngagementType() || ENGAGEMENT_TYPE_DEFAULT,
    preferGovernment: getGovernmentPreferenceValue(),
  }));
}

function buildSearchBasicsProfilePatch() {
  const location = String(selectedLocations[0] || locationSelect?.value || '').trim();
  const keywords = String(reviewSearchKeywordsEl?.value || '').trim();
  const minimumSalaryYearly = parseCurrencyFieldValue(reviewMinimumSalaryYearlyEl?.value || '');
  const minimumDailyRate = parseCurrencyFieldValue(reviewMinimumDailyRateEl?.value || '');
  const engagementType = getSelectedEngagementType();
  const preferGovernment = getGovernmentPreferenceValue();

  return {
    search_settings: {
      keywords,
      locations: location ? [location] : [],
    },
    match_preferences: {
      engagement_type: engagementType,
      work_mode_preference: getWorkModePreferenceValues(),
      prefer_government: preferGovernment,
    },
    salary_preferences: {
      minimum_salary_yearly: Number(minimumSalaryYearly || 0),
      minimum_daily_rate: Number(minimumDailyRate || 0),
    },
  };
}

async function persistSearchBasicsToProfile() {
  const response = await jobHunterFetch('/api/profile', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(buildSearchBasicsProfilePatch()),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || 'Could not save search basics');
  }
  return response.json().catch(() => ({}));
}

function scheduleSearchBasicsPersistence() {
  if (searchBasicsPersistTimer) {
    window.clearTimeout(searchBasicsPersistTimer);
  }
  searchBasicsPersistTimer = window.setTimeout(() => {
    searchBasicsPersistTimer = null;
    persistSearchBasicsToProfile().catch((error) => {
      console.warn('Could not persist onboarding search basics.', error);
    });
  }, 500);
}

async function flushSearchBasicsPersistence() {
  if (searchBasicsPersistTimer) {
    window.clearTimeout(searchBasicsPersistTimer);
    searchBasicsPersistTimer = null;
  }
  await persistSearchBasicsToProfile();
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
    setSelectedLocation((Array.isArray(state.selectedLocations) ? state.selectedLocations[0] : state.selectedLocations) || '');
    renderReviewStep();
    const kwEl = reviewSearchKeywordsEl;
    if (kwEl) kwEl.value = state.searchKeywords || '';
    const salaryEl = reviewMinimumSalaryYearlyEl;
    if (salaryEl) setCurrencyFieldValue(salaryEl, state.minimumSalaryYearly || 0);
    const dailyEl = reviewMinimumDailyRateEl;
    if (dailyEl) setCurrencyFieldValue(dailyEl, state.minimumDailyRate || 0);
    setSelectedEngagementType(state.engagementType || ENGAGEMENT_TYPE_DEFAULT);
    setWorkModePreferenceValues(state.workModePreference || []);
    setGovernmentPreferenceValue(state.preferGovernment || GOVERNMENT_PREFERENCE_DEFAULT);
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
  if (!primaryCvStatusEl || !primaryCvDropZoneContentEl) return;

  if (!file) {
    primaryCvStatusEl.textContent = 'No file selected yet.';
    primaryCvStatusEl.classList.remove('is-selected');
    primaryCvDropZone?.classList.remove('has-file');
    primaryCvDropZoneContentEl.innerHTML = `
      <div class="drop-zone-content-shell">
        <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="upload-icon" style="margin-bottom: 16px;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
        <p style="margin: 0; font-size: 1.1rem; font-weight: 500;">${PRIMARY_CV_COPY.emptyTitle}</p>
        <p class="drop-zone-hint" style="margin-top: 8px;">${PRIMARY_CV_COPY.emptyHint}</p>
      </div>
    `;
    resetPrimaryCvDropZoneAppearance();
    return;
  }

  primaryCvStatusEl.textContent = `Selected file: ${file.name}`;
  primaryCvStatusEl.classList.add('is-selected');
  primaryCvDropZone?.classList.add('has-file');
  resetPrimaryCvDropZoneAppearance();

  primaryCvDropZoneContentEl.innerHTML = `
    <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="upload-icon"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
    <p class="file-loaded-label">File Loaded: ${file.name}</p>
    <p class="drop-zone-hint">${PRIMARY_CV_COPY.loadedHint}</p>
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

  if (stepNumber === SEARCH_STEP) {
    // Try to auto-detect location based on browser geolocation when entering search basics step
    tryGeolocationDefault();
  }

  if (formTitleEl) formTitleEl.textContent = `Step ${stepNumber}. ${meta.title()}`;
  const percent = STEP_COUNT > 1 ? Math.round(((stepNumber - 1) / (STEP_COUNT - 1)) * 100) : 100;
  if (progressFillEl) {
    progressFillEl.style.width = `${percent}%`;
  }
  wizardProgressSteps.forEach((el, idx) => {
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

async function tryGeolocationDefault() {
  /**Request browser geolocation and set location to nearest city if user grants permission.*/
  if (!navigator.geolocation) {
    // Geolocation not available, skip
    return;
  }
  
  if (selectedLocations.length > 0) {
    // Already selected, don't override
    return;
  }

  try {
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        const { latitude, longitude } = position.coords;
        try {
          const response = await jobHunterFetch('/api/onboarding/lookup-location-by-geolocation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ latitude, longitude }),
          });
          const data = await response.json().catch(() => ({}));
          if (response.ok && data.location) {
            setSelectedLocation(data.location);
          }
        } catch (error) {
          // Silently ignore geolocation API errors; user can still manually select
        }
      },
      () => {
        // User denied geolocation or error occurred; silently continue with default
      },
      {
        timeout: 5000,
        enableHighAccuracy: false,
        maximumAge: 600000, // Cache result for 10 minutes
      }
    );
  } catch (error) {
    // Silently ignore any geolocation errors
  }
}

function renderLocationSelect() {
  if (!locationSelect) return;
  const current = normalizeLocationValue(selectedLocations[0] || '');
  if (locationUi.renderLocationOptions) {
    locationUi.renderLocationOptions(locationSelect, { excludedValues: current ? [current] : [] });
  }
  locationSelect.value = current;
  selectedLocations = current ? [current] : [];
  renderSelectedLocation();
}

function renderSelectedLocation() {
  if (!locationSelected) return;
  const current = normalizeLocationValue(selectedLocations[0] || locationSelect?.value || '');
  locationSelected.innerHTML = current
    ? `<span class="location-chip">${current}</span>`
    : '';
}

function setSelectedLocation(value) {
  const normalized = normalizeLocationValue(value);
  selectedLocations = normalized ? [normalized] : [];
  renderLocationSelect();
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
  const capabilityStrengthPreset = capabilityStrengthPresetEl?.value.trim() || '';
  return {
    capability_strength_preset: capabilityStrengthPreset || 'balanced',
  };
}

function searchPreferencesPayload() {
  return {
    keywords: reviewSearchKeywordsEl?.value.trim() || '',
    locations: selectedLocations.length ? [selectedLocations[0]] : [],
    engagement_type: getSelectedEngagementType(),
    work_mode_preference: getWorkModePreferenceValues(),
    prefer_government: getGovernmentPreferenceValue(),
    minimum_salary_yearly: reviewMinimumSalaryYearlyEl?.value.trim() || '',
    minimum_daily_rate: reviewMinimumDailyRateEl?.value.trim() || '',
  };
}

function updateCompensationVisibility() {
  const engagementType = getSelectedEngagementType();
  if (salaryYearlyBlock) salaryYearlyBlock.hidden = engagementType === 'contract';
  if (salaryDailyBlock) salaryDailyBlock.hidden = engagementType === 'permanent';
}

function validateOnboardingSettings(settings) {
  const preset = String(settings.capability_strength_preset || '').trim();
  if (!['recent_focus', 'balanced', 'include_older_experience'].includes(preset)) {
    throw new Error('Please choose how older experience should be treated.');
  }
}

function validateSearchPreferences(searchPrefs) {
  if (searchPrefs.keywords && (searchPrefs.keywords.length < 2 || searchPrefs.keywords.length > 120)) {
    throw new Error('Please keep the primary search title between 2 and 120 characters.');
  }
  if (searchPrefs.locations.length !== 1) {
    throw new Error('Please choose one search location.');
  }
  const location = searchPrefs.locations[0];
  if (location.length < 2 || location.length > 80) {
    throw new Error('Location should be between 2 and 80 characters.');
  }
  if (!/^[A-Za-z\s,'()-]+$/.test(location)) {
    throw new Error('Location should look like a normal city, state, or region name.');
  }
  if (ENGAGEMENT_TYPE_VALUES.size > 0 && !ENGAGEMENT_TYPE_VALUES.has(searchPrefs.engagement_type)) {
    throw new Error('Please choose what type of work you are open to.');
  }
  if ((Array.isArray(searchPrefs.work_mode_preference) ? searchPrefs.work_mode_preference : []).some((mode) => !WORK_MODE_PREFERENCE_VALUES.has(mode))) {
    throw new Error('Please choose only remote, hybrid, or on-site.');
  }
  if (!searchPrefs.keywords) {
    throw new Error('Please confirm one primary search title.');
  }
  if (searchPrefs.minimum_salary_yearly !== '' && searchPrefs.minimum_salary_yearly !== null && searchPrefs.minimum_salary_yearly !== undefined) {
    const yearly = parseCurrencyFieldValue(searchPrefs.minimum_salary_yearly);
    if (yearly === '' || !Number.isFinite(yearly) || yearly < 0) {
      throw new Error('Please enter a valid minimum permanent salary excluding super.');
    }
    if (yearly > getSalaryLimitMaximum('minimum_salary_yearly')) {
      throw new Error('Minimum permanent salary is above the allowed maximum.');
    }
  }
  if (searchPrefs.minimum_daily_rate !== '' && searchPrefs.minimum_daily_rate !== null && searchPrefs.minimum_daily_rate !== undefined) {
    const daily = parseCurrencyFieldValue(searchPrefs.minimum_daily_rate);
    if (daily === '' || !Number.isFinite(daily) || daily < 0) {
      throw new Error('Please enter a valid minimum contract daily rate excluding super.');
    }
    if (daily > getSalaryLimitMaximum('minimum_daily_rate')) {
      throw new Error('Minimum contract daily rate is above the allowed maximum.');
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
  event.stopPropagation();
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
  const preset = onboarding.capability_strength_preset || ONBOARDING_DEFAULTS.capability_strength_preset;
  const searchSettings = profile?.search_settings || {};
  const matchPreferences = profile?.match_preferences || {};
  const salaryPreferences = profile?.salary_preferences || {};

  if (capabilityStrengthPresetEl) capabilityStrengthPresetEl.value = String(preset);
  if (!reviewTargetTitles.length && !reviewSecondaryTitles.length) {
    const normalizedTitles = normalizeReviewTitleLists(
      profile?.primary_job_title_pattern || [],
      profile?.secondary_title_patterns || [],
    );
    reviewTargetTitles = normalizedTitles.primary;
    reviewSecondaryTitles = normalizedTitles.secondary;
  }
  if (reviewSearchKeywordsEl && !String(reviewSearchKeywordsEl.value || '').trim()) {
    const savedKeywords = String(searchSettings.keywords || '').trim();
    reviewSearchKeywordsEl.value = savedKeywords || reviewTargetTitles.join(', ');
  }
  if (reviewMinimumSalaryYearlyEl && !String(reviewMinimumSalaryYearlyEl.value || '').trim()) {
    setCurrencyFieldValue(reviewMinimumSalaryYearlyEl, salaryPreferences.minimum_salary_yearly ?? 0);
  }
  if (reviewMinimumDailyRateEl && !String(reviewMinimumDailyRateEl.value || '').trim()) {
    setCurrencyFieldValue(reviewMinimumDailyRateEl, salaryPreferences.minimum_daily_rate ?? 0);
  }
  if (!getWorkModePreferenceValues().length) {
    setWorkModePreferenceValues(matchPreferences.work_mode_preference || []);
  }
  if (governmentPreferenceSelect && !String(governmentPreferenceSelect.value || '').trim()) {
    setGovernmentPreferenceValue(matchPreferences.prefer_government || GOVERNMENT_PREFERENCE_DEFAULT);
  }
  if (!selectedLocations.length) {
    setSelectedLocation((searchSettings.locations || [])[0] || '');
  }
  if (currentStep >= REVIEW_STEP && (reviewTargetTitles.length || reviewSecondaryTitles.length)) {
    renderReviewStep();
  } else {
    refreshStepNavigation();
  }
}

if (locationSelect) {
  locationSelect.addEventListener('change', () => {
    setSelectedLocation(locationSelect.value);
    scheduleSearchBasicsPersistence();
  });
}
if (governmentPreferenceSelect) {
  governmentPreferenceSelect.addEventListener('change', () => {
    saveWizardState();
    scheduleSearchBasicsPersistence();
  });
}
if (refs.workModePreferences.length) {
  refs.workModePreferences.forEach((element) => element.addEventListener('change', () => {
    saveWizardState();
    scheduleSearchBasicsPersistence();
  }));
}
[
  reviewMinimumSalaryYearlyEl,
  reviewMinimumDailyRateEl,
].filter(Boolean).forEach((input) => {
  onboardingCurrencyUi.bindCurrencyInput?.(input);
});
renderLocationSelect();
