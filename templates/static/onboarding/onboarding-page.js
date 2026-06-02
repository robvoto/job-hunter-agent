import * as onboardingSettingsUtils from '../settings/shared/settings-utils.js';
import * as onboardingCurrencyUi from '../common/currency-input.js';
import * as onboardingLocationUi from '../common/location-options.js';
import * as onboardingCapabilityUi from '../common/capability-ui.js';
import { createController as createMessageBannerController } from '../common/message-banner.js';
import * as onboardingUpload from './onboarding-upload.js';

const urlParams = new URLSearchParams(window.location.search);
export const isRebuildMode = urlParams.get('mode') === 'rebuild';
export const refs = Object.freeze({
  status: document.getElementById('status'),
  stepEls: Array.from(document.querySelectorAll('.wizard-step')),
  wizardProgressSteps: Array.from(document.querySelectorAll('.wizard-progress-step')),
  workflowSummary: document.getElementById('workflow_summary'),
  progressFill: document.getElementById('wizard_progress_fill'),
  primaryCvInput: document.getElementById('primary_cv'),
  primaryCvDropZone: document.getElementById('cv_drop_zone'),
  cvDropZoneContent: document.getElementById('cv_drop_zone_content'),
  locationSelect: document.getElementById('location_search'),
  workModePreferences: Array.from(document.querySelectorAll('input[name="work_mode_preference"]')),
  sectorPreferenceSelect: document.getElementById('sector_preference'),
  sectorPreferenceSummary: document.getElementById('sector_preference_summary'),
  engagementTypeSummary: document.getElementById('engagement_type_summary'),
  workModePreferenceSummary: document.getElementById('work_mode_preference_summary'),
  reviewCapabilityCount: document.getElementById('review_capability_count'),
  salaryYearlyBlock: document.getElementById('salary_yearly_block'),
  salaryDailyBlock: document.getElementById('salary_daily_block'),
  createProfileButton: document.getElementById('create_profile'),
  continueToReview: document.getElementById('continue_to_review'),
  stepNavButtons: Array.from(document.querySelectorAll('[data-step-nav]')),
  capabilityStrengthPreset: document.getElementById('os_capability_strength_preset'),
  reviewSearchKeywords: document.getElementById('review_search_keywords'),
  minContractMonths: document.getElementById('min_contract_months'),
  reviewMinimumSalaryYearly: document.getElementById('review_minimum_salary_yearly'),
  reviewMinimumDailyRate: document.getElementById('review_minimum_daily_rate'),
  reviewCapabilityFilter: document.getElementById('review_capability_filter'),
  reviewCapabilityCards: document.getElementById('review_capability_cards'),
  reviewCapabilityTitle: document.getElementById('review_capability_title'),
  reviewCapabilityHelp: document.getElementById('review_capability_help'),
  reviewCapabilityHelper: document.getElementById('review_capability_helper'),
});
const {
  status: statusEl,
  stepEls,
  wizardProgressSteps,
  workflowSummary: workflowSummaryEl,
  progressFill: progressFillEl,
  primaryCvInput,
  primaryCvDropZone,
  cvDropZoneContent: primaryCvDropZoneContentEl,
  locationSelect,
  sectorPreferenceSelect,
  sectorPreferenceSummary,
  engagementTypeSummary,
  workModePreferenceSummary,
  reviewCapabilityCount: reviewCapabilityCountEl,
  salaryYearlyBlock,
  salaryDailyBlock,
  createProfileButton,
  continueToReview: continueToReviewEl,
  stepNavButtons,
  capabilityStrengthPreset: capabilityStrengthPresetEl,
  reviewSearchKeywords: reviewSearchKeywordsEl,
  reviewMinimumSalaryYearly: reviewMinimumSalaryYearlyEl,
  reviewMinimumDailyRate: reviewMinimumDailyRateEl,
  reviewCapabilityFilter: reviewCapabilityFilterEl,
  reviewCapabilityCards: reviewCapabilityCardsEl,
  reviewCapabilityTitle: reviewCapabilityTitleEl,
  reviewCapabilityHelp: reviewCapabilityHelpEl,
  reviewCapabilityHelper: reviewCapabilityHelperEl,
} = refs;
const statusUi = createMessageBannerController(statusEl);
export const STEP_COUNT = 4;
export const REVIEW_STEP = 2;
export const SEARCH_STEP = 3;
export const CHECK_STEP = 4;
const capabilityLabels = onboardingCapabilityUi.labels;
const escapeHtml = onboardingSettingsUtils.escapeHtml;
const onboardingFlowLabels = window.__JOB_HUNTER_ONBOARDING_FLOW_LABELS__;
const ONBOARDING_CV_PAGE_LIMIT = Number(window.__JOB_HUNTER_ONBOARDING_DEFAULTS__.cv_max_pages);
const salaryLimits = window.__JOB_HUNTER_SALARY_LIMITS__;
const minContractMonthOptions = window.__JOB_HUNTER_MIN_CONTRACT_MONTH_OPTIONS__;
const minContractMonthValues = new Set(minContractMonthOptions.map((option) => String(option.value).trim()));
const minContractMonthNoneLabel = String(window.__JOB_HUNTER_MIN_CONTRACT_MONTH_NONE_LABEL__).trim();
const onboardingPageTitleTierLabels = window.__JOB_HUNTER_TITLE_TIER_LABELS__;
if (!onboardingPageTitleTierLabels) {
  throw new Error('Missing title tier labels.');
}
if (!capabilityLabels || !capabilityLabels.onboarding_title || !capabilityLabels.help_text || !capabilityLabels.filter_placeholder) {
  throw new Error('Missing capability UI labels.');
}
if (!onboardingFlowLabels || !onboardingFlowLabels.review_capability_helper_copy) {
  throw new Error('Missing onboarding flow labels.');
}
if (typeof escapeHtml !== 'function') {
  throw new Error('Missing HTML escaping helper.');
}

function dedupeSearchTitles(values) {
  const seen = new Set();
  const output = [];
  for (const value of values) {
    const cleaned = String(value).trim();
    if (!cleaned) continue;
    const key = cleaned.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(cleaned);
  }
  return output;
}

export function defaultSearchKeywordFromTargetRoles(profile) {
  if (!profile || !Array.isArray(profile.target_roles)) {
    throw new Error('Missing target roles.');
  }
  const allTitles = dedupeSearchTitles(reviewTargetTitles.concat(profile.target_roles));
  if (!allTitles.length) {
    throw new Error('Missing target role keywords.');
  }
  return allTitles[0];
}
const {
  WORK_MODE_PREFERENCE_VALUES: ONBOARDING_WORK_MODE_PREFERENCE_VALUES,
  ENGAGEMENT_TYPE_VALUES,
  getEngagementTypeValues: getOnboardingEngagementTypeValues,
  setEngagementTypeValues: setOnboardingEngagementTypeValues,
} = onboardingSettingsUtils;
const {
  getWorkModePreferenceValues: getOnboardingWorkModePreferenceValues,
  setWorkModePreferenceValues: setOnboardingWorkModePreferenceValues,
  getSectorPreferenceValues: getOnboardingSectorPreferenceValues,
  setSectorPreferenceValues: setOnboardingSectorPreferenceValues,
  parseCurrencyValue: onboardingParseCurrencyValue,
  setCurrencyFieldValue: onboardingSetCurrencyFieldValue,
  normalizeReviewTitleLists,
  normalizeReviewCapability,
} = onboardingSettingsUtils;
if (reviewCapabilityTitleEl) {
  reviewCapabilityTitleEl.textContent = capabilityLabels.onboarding_title;
}
const checkCapabilitiesLabelEl = document.getElementById('check_capabilities_label');
if (checkCapabilitiesLabelEl) {
  checkCapabilitiesLabelEl.textContent = capabilityLabels.onboarding_title;
}
if (reviewCapabilityHelpEl) {
  reviewCapabilityHelpEl.textContent = capabilityLabels.help_text;
}
if (reviewCapabilityHelperEl) {
  reviewCapabilityHelperEl.textContent = onboardingFlowLabels.review_capability_helper_copy;
}
if (reviewCapabilityFilterEl) {
  reviewCapabilityFilterEl.placeholder = capabilityLabels.filter_placeholder;
  reviewCapabilityFilterEl.setAttribute('aria-label', capabilityLabels.filter_placeholder);
}
const onboardingPageLabels = window.__JOB_HUNTER_ONBOARDING_PAGE_LABELS__;
if (!onboardingPageLabels) {
  throw new Error('Missing onboarding page labels.');
}
export const PRIMARY_CV_COPY = Object.freeze({
  emptyTitle: onboardingPageLabels.cv_drop_zone_empty_title,
  emptyHint: onboardingPageLabels.cv_drop_zone_empty_hint,
  loadedHint: onboardingPageLabels.cv_drop_zone_loaded_hint,
});
onboardingUpload.configureOnboardingUpload({
  refs,
  primaryCvCopy: PRIMARY_CV_COPY,
  getPreservedPrimaryCvFile: () => preservedPrimaryCvFile,
  setPreservedPrimaryCvFile,
  getDraftBuiltExplicitly: () => draftBuiltExplicitly,
  hideStatus,
  showStatus,
  refreshStepNavigation,
});
const ONBOARDING_USER_ID = String(window.__JOB_HUNTER_USER_ID__ || '').trim();
if (!ONBOARDING_USER_ID) {
  throw new Error('Missing user id.');
}
function buildScopedStorageKey(baseKey) {
  return `${baseKey}:${ONBOARDING_USER_ID}`;
}
export const WIZARD_STATE_KEY = buildScopedStorageKey('jobHunter.onboardingWizard');
export const ONBOARDING_WELCOME_KEY = buildScopedStorageKey('jobHunter.onboardingWelcome');
const ONBOARDING_WELCOME_OPT_OUT_KEY = buildScopedStorageKey('jobHunter.onboardingWelcomeOptOut');
const ONBOARDING_IMPORT_HELPER_DISMISSED_KEY = buildScopedStorageKey('jobHunter.onboardingImportHelperDismissed');
const REVIEW_CAPABILITY_PREVIEW_ROWS = window.__JOB_HUNTER_ONBOARDING_IMPORT_SUMMARY_LABELS__.capability_preview_rows;
if (!Number.isInteger(REVIEW_CAPABILITY_PREVIEW_ROWS) || REVIEW_CAPABILITY_PREVIEW_ROWS < 1) {
  throw new Error('Missing review capability preview row count.');
}
export const isTestMode = document.body.dataset.testMode === 'true';

export let currentStep = 1;
export let workingStatusTimer = null;
export let preservedPrimaryCvFile = null;
export let lastImportPayload = null;
export let lastLoadedProfile = null;
export let reviewTargetTitles = [];
export let reviewSecondaryTitles = [];
export let reviewCapabilityRules = [];
export let selectedLocations = [];
export let selectedReviewCapabilityIndexes = new Set();
export let reviewCapabilityVisibleCount = REVIEW_CAPABILITY_PREVIEW_ROWS;
export let maxUnlockedStep = 1;
export let draftBuiltExplicitly = false;
export let searchBasicsPersistTimer = null;
export let reviewCapabilityResizeObserver = null;

export function setCurrentStep(value) {
  currentStep = Number(value) || 1;
}

export function setWorkingStatusTimer(value) {
  workingStatusTimer = value;
}

export function setPreservedPrimaryCvFile(value) {
  preservedPrimaryCvFile = value;
}

export function setLastImportPayload(value) {
  lastImportPayload = value;
}

export function setLastLoadedProfile(value) {
  lastLoadedProfile = value;
}

export function setReviewTargetTitles(value) {
  reviewTargetTitles = Array.isArray(value) ? value : [];
}

export function setReviewSecondaryTitles(value) {
  reviewSecondaryTitles = Array.isArray(value) ? value : [];
}

export function setReviewCapabilityRules(value) {
  reviewCapabilityRules = Array.isArray(value) ? value : [];
}

export function setSelectedLocations(value) {
  selectedLocations = Array.isArray(value) ? value : [];
}

export function setSelectedReviewCapabilityIndexes(value) {
  selectedReviewCapabilityIndexes = value instanceof Set ? value : new Set();
}

export function setReviewCapabilityVisibleCount(value) {
  reviewCapabilityVisibleCount = Number(value) || 0;
}

export function setMaxUnlockedStep(value) {
  maxUnlockedStep = Number(value) || 1;
}

export function setDraftBuiltExplicitly(value) {
  draftBuiltExplicitly = Boolean(value);
}

export function setSearchBasicsPersistTimer(value) {
  searchBasicsPersistTimer = value;
}

export function setReviewCapabilityResizeObserver(value) {
  reviewCapabilityResizeObserver = value;
}

export function getReviewCapabilityPreviewCount() {
  return REVIEW_CAPABILITY_PREVIEW_ROWS;
}

function syncReviewCapabilityVisibleCount(forceRender = false) {
  const next = getReviewCapabilityPreviewCount();
  if (!next || next <= reviewCapabilityVisibleCount) {
    return false;
  }
  reviewCapabilityVisibleCount = next;
  if (forceRender && currentStep === REVIEW_STEP) {
    renderReviewCapabilities();
  }
  return true;
}

export function hasDraftProfileState() {
  return Boolean(
    lastImportPayload
    || reviewTargetTitles.length
    || reviewSecondaryTitles.length
    || reviewCapabilityRules.length
  );
}

export function hasSearchBasicsState() {
  return Boolean(
    hasDraftProfileState()
    && (
      selectedLocations.length
      || String(reviewSearchKeywordsEl?.value || '').trim()
    )
  );
}

export function refreshStepNavigation() {
  const hasPrimaryCv = Boolean(primaryCvInput?.files?.[0] || preservedPrimaryCvFile);
  const unlockedStep = Math.max(
    1,
    maxUnlockedStep,
    hasPrimaryCv && hasDraftProfileState() ? REVIEW_STEP : 1,
    hasPrimaryCv && hasSearchBasicsState() ? SEARCH_STEP : 1,
  );
  maxUnlockedStep = Math.min(STEP_COUNT, unlockedStep);
  stepNavButtons.forEach((button) => {
    const step = Number(button.dataset.stepNav || 0);
    button.disabled = !step || step > maxUnlockedStep;
    button.setAttribute('aria-current', step === currentStep ? 'step' : 'false');
  });
}

function getSectorPreferenceValues() {
  return getOnboardingSectorPreferenceValues();
}

function setSectorPreferenceValues(values) {
  setOnboardingSectorPreferenceValues(values);
}

function getMinContractMonthValue() {
  return String(refs.minContractMonths.value).trim();
}

export function setMinContractMonthValue(value) {
  if (refs.minContractMonths) {
    refs.minContractMonths.value = String(value).trim();
  }
}

export function getResolvedMinContractMonthValue() {
  const current = getMinContractMonthValue();
  if (!current) return '';
  if (!minContractMonthValues.has(current)) {
    throw new Error(`Invalid minimum contract month value: ${current}`);
  }
  return current;
}

function minContractMonthSummaryText(value) {
  const selected = String(value).trim();
  if (!selected) {
    return minContractMonthNoneLabel;
  }
  const option = minContractMonthOptions.find((item) => String(item.value).trim() === selected);
  if (!option || !option.label) {
    throw new Error(`Missing contract month label for value: ${selected}`);
  }
  return String(option.label).trim();
}

function allChoiceValuesSelected(name) {
  const inputs = Array.from(document.querySelectorAll(`input[name="${name}"]`));
  if (!inputs.length) return false;
  return inputs.every((input) => input.checked);
}

export function updateSearchPreferenceSummaries() {
  const contractMonths = getResolvedMinContractMonthValue();
  if (refs.engagementTypeSummary) {
    const allSelected = allChoiceValuesSelected('engagement_type');
    refs.engagementTypeSummary.textContent = allSelected
      ? `${onboardingPageLabels.work_type_summary_all_label} · ${onboardingPageLabels.work_type_summary_contract_length_label}: ${contractMonths ? minContractMonthSummaryText(contractMonths) : onboardingPageLabels.summary_any_length_label}`
      : '';
    refs.engagementTypeSummary.hidden = !allSelected;
  }
  if (refs.sectorPreferenceSummary) {
    const allSelected = allChoiceValuesSelected('prefer_sector');
    refs.sectorPreferenceSummary.textContent = allSelected ? onboardingPageLabels.sector_preference_summary_all_label : '';
    refs.sectorPreferenceSummary.hidden = !allSelected;
  }
  if (refs.workModePreferenceSummary) {
    const allSelected = allChoiceValuesSelected('work_mode_preference');
    refs.workModePreferenceSummary.textContent = allSelected ? onboardingPageLabels.work_mode_summary_all_label : '';
    refs.workModePreferenceSummary.hidden = !allSelected;
  }
}

export function updateContractChipLabel() {
  const span = document.querySelector('input[name="engagement_type"][value="contract"]')?.closest('label')?.querySelector('span');
  if (!span) return;
  const contractEnabled = getOnboardingEngagementTypeValues().includes('contract');
  if (!span.dataset.baseLabel) span.dataset.baseLabel = span.textContent;
  if (!contractEnabled) {
    span.textContent = span.dataset.baseLabel;
    return;
  }
  const months = String(refs.minContractMonths.value).trim();
  if (!months) {
    span.textContent = `${span.dataset.baseLabel} (all)`;
  } else {
    span.textContent = `${span.dataset.baseLabel} (${months}+)`;
  }
}

export function positionContractDurationRow() {
  const contractRow = document.getElementById('contract_duration_row');
  const contractChip = document.querySelector('input[name="engagement_type"][value="contract"]')?.closest('label');
  if (!contractRow || !contractChip) return;
  const parent = contractRow.parentElement;
  if (parent && getComputedStyle(parent).position === 'static') {
    parent.style.position = 'relative';
  }
  const chipRect = contractChip.getBoundingClientRect();
  const parentRect = parent ? parent.getBoundingClientRect() : { left: 0, top: 0 };
  contractRow.style.left = Math.round(chipRect.left - parentRect.left) + 'px';
  contractRow.style.top = Math.round(chipRect.bottom - parentRect.top + 6) + 'px';
}

export function updateMinContractMonthState({ showRow = false } = {}) {
  if (!refs.minContractMonths) return;
  const contractEnabled = getOnboardingEngagementTypeValues().includes('contract');
  refs.minContractMonths.disabled = !contractEnabled;
  const contractRow = document.getElementById('contract_duration_row');
  if (contractRow) {
    if (!contractEnabled) {
      contractRow.hidden = true;
    } else if (showRow) {
      if (!getMinContractMonthValue()) {
        setMinContractMonthValue(getResolvedMinContractMonthValue());
      }
      positionContractDurationRow();
      contractRow.hidden = false;
    }
  }
  updateContractChipLabel();
  updateSearchPreferenceSummaries();
}

export function initFieldInfoToggles() {
  document.querySelectorAll('button.field-info').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const field = btn.closest('.onb-field');
      if (!field) return;
      const isOpen = field.classList.toggle('is-help-visible');
      btn.setAttribute('aria-expanded', String(isOpen));
    });
  });
}

const getSalaryLimitMaximum = (key) => {
  if (!salaryLimits || !salaryLimits[key]) {
    throw new Error(`Missing salary limit for ${key}.`);
  }
  const max = Number(salaryLimits[key].max);
  if (!Number.isFinite(max) || max < 0) {
    throw new Error(`Invalid salary limit for ${key}.`);
  }
  return max;
};

export function saveWizardState() {
  if (currentStep < 2 && !hasDraftProfileState()) {
    window.localStorage.removeItem(WIZARD_STATE_KEY);
    return;
  }
  window.localStorage.setItem(WIZARD_STATE_KEY, JSON.stringify({
    step: currentStep,
    maxUnlockedStep,
    reviewTargetTitles,
    reviewSecondaryTitles,
    reviewCapabilityRules,
    reviewCapabilityVisibleCount,
    selectedLocations,
    workModePreference: getOnboardingWorkModePreferenceValues(),
    searchKeywords: reviewSearchKeywordsEl?.value || '',
    minContractMonths: getResolvedMinContractMonthValue(),
    minimumSalaryYearly: reviewMinimumSalaryYearlyEl?.value || '',
    minimumDailyRate: reviewMinimumDailyRateEl?.value || '',
    engagementType: getOnboardingEngagementTypeValues(),
    preferSector: getSectorPreferenceValues(),
  }));
}




export function showStatus(message, kind) {
  if (workingStatusTimer && kind !== 'loading') {
    window.clearInterval(workingStatusTimer);
    workingStatusTimer = null;
  }
  statusUi.show(message, kind);
  if (kind === 'error') {
    statusEl?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

export function hideStatus() {
  if (workingStatusTimer) {
    window.clearInterval(workingStatusTimer);
    workingStatusTimer = null;
  }
  statusUi.hide();
}

export function startWorkingStatus(messages, stepMs = 1400) {
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
    statusUi.show(items[index], 'loading');
  }, stepMs);
}

export function resetPrimaryCvDropZoneAppearance() {
  if (!primaryCvDropZone) return;
  primaryCvDropZone.classList.remove('is-dragover');
}

export function setStep(stepNumber, options = {}) {
  const { scroll = true, persist = true } = options;
  const hasPrimaryCv = Boolean(primaryCvInput?.files?.[0] || preservedPrimaryCvFile);
  if (stepNumber > 1 && !hasPrimaryCv && !hasDraftProfileState()) {
    stepNumber = 1;
  }
  const isDetailStep = stepNumber > 1;
  currentStep = stepNumber;
  stepEls.forEach((el) => {
    const step = Number(el.dataset.step);
    const active = step === stepNumber;
    el.hidden = !active;
    el.classList.toggle('is-active', active);
  });

  if (workflowSummaryEl) {
    workflowSummaryEl.hidden = isDetailStep;
  }

  if (stepNumber === 1 && preservedPrimaryCvFile) {
    onboardingUpload.restorePrimaryCvSelection(preservedPrimaryCvFile);
    onboardingUpload.updatePrimaryCvStatus(preservedPrimaryCvFile);
  }

  if (stepNumber === SEARCH_STEP) {
    // Try to auto-detect location based on browser geolocation when entering search basics step
    tryGeolocationDefault();
  }

  const percent = STEP_COUNT > 1 ? Math.round(((stepNumber - 1) / (STEP_COUNT - 1)) * 100) : 100;
  if (progressFillEl) {
    progressFillEl.style.setProperty('--onboarding-progress-fill-width', `${percent}%`);
  }
  wizardProgressSteps.forEach((el, idx) => {
    const s = idx + 1;
    el.classList.toggle('is-active', s === stepNumber);
    el.classList.toggle('is-complete', s < stepNumber);
  });
  refreshStepNavigation();
  onboardingUpload.updateCreateProfileAvailability();

  if (persist) {
    saveWizardState();
  }
  hideStatus();
  if (stepNumber === REVIEW_STEP) {
    window.requestAnimationFrame(() => syncReviewCapabilityVisibleCount(true));
  }
  if (scroll) {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
}

export function normalizeLocationValue(value) {
  return onboardingLocationUi.resolveLocationValue
    ? onboardingLocationUi.resolveLocationValue(value)
    : String(value || '').replace(/\s+/g, ' ').trim();
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
          console.warn('Could not resolve onboarding location from geolocation.', error);
        }
      },
      () => {
        console.warn('Geolocation was denied or unavailable; using manual location selection.');
      },
      {
        timeout: 5000,
        enableHighAccuracy: false,
        maximumAge: 600000, // Cache result for 10 minutes
      }
    );
  } catch (error) {
    console.warn('Could not request onboarding geolocation.', error);
  }
}

export function renderLocationSelect() {
  if (!locationSelect) return;
  const current = normalizeLocationValue(selectedLocations[0] || '');
  if (onboardingLocationUi.renderLocationOptions) {
    onboardingLocationUi.renderLocationOptions(locationSelect);
  }
  locationSelect.value = current;
  selectedLocations = current ? [current] : [];
}

export function setSelectedLocation(value, options = {}) {
  const { persist = true } = options;
  const normalized = normalizeLocationValue(value);
  selectedLocations = normalized ? [normalized] : [];
  renderLocationSelect();
  if (persist) {
    saveWizardState();
  }
}

export function onboardingSettingsPayload() {
  const capabilityStrengthPreset = capabilityStrengthPresetEl?.value.trim() || '';
  return {
    capability_strength_preset: capabilityStrengthPreset || 'balanced',
  };
}

export function searchPreferencesPayload() {
  const engagementType = getOnboardingEngagementTypeValues();
  return {
    keywords: reviewSearchKeywordsEl?.value.trim() || '',
    locations: selectedLocations.length ? [selectedLocations[0]] : [],
    engagement_type: engagementType,
    min_contract_months: engagementType.includes('contract') ? (getResolvedMinContractMonthValue() || null) : null,
    work_mode_preference: getOnboardingWorkModePreferenceValues(),
    prefer_sector: getSectorPreferenceValues(),
    minimum_salary_yearly: reviewMinimumSalaryYearlyEl?.value.trim() || '',
    minimum_daily_rate: reviewMinimumDailyRateEl?.value.trim() || '',
  };
}

export function updateCompensationVisibility() {
  const engagementType = new Set(getOnboardingEngagementTypeValues());
  if (salaryYearlyBlock) salaryYearlyBlock.hidden = engagementType.size === 1 && engagementType.has('contract');
  if (salaryDailyBlock) salaryDailyBlock.hidden = engagementType.size === 1 && engagementType.has('permanent');
}

export function validateOnboardingSettings(settings) {
  const preset = String(settings.capability_strength_preset).trim();
  if (!['recent_focus', 'balanced', 'include_older_experience'].includes(preset)) {
    throw new Error('Please choose how older experience should be treated.');
  }
}

export function validateSearchPreferences(searchPrefs) {
  if (searchPrefs.keywords && (searchPrefs.keywords.length < 2 || searchPrefs.keywords.length > 120)) {
    throw new Error(`Please keep the ${onboardingPageTitleTierLabels.search_keyword_label.toLowerCase()} between 2 and 120 characters.`);
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
  if (!Array.isArray(searchPrefs.engagement_type) || searchPrefs.engagement_type.length === 0 || searchPrefs.engagement_type.some((value) => !ENGAGEMENT_TYPE_VALUES.has(value))) {
    throw new Error('Please choose what type of work you are open to.');
  }
  if (searchPrefs.min_contract_months !== null && searchPrefs.min_contract_months !== undefined) {
    const minContractMonths = Number(searchPrefs.min_contract_months);
    if (!Number.isInteger(minContractMonths) || !minContractMonthValues.has(String(minContractMonths))) {
      throw new Error('Please choose a valid minimum contract length.');
    }
  }
  if ((Array.isArray(searchPrefs.work_mode_preference) ? searchPrefs.work_mode_preference : []).some((mode) => !ONBOARDING_WORK_MODE_PREFERENCE_VALUES.has(mode))) {
    throw new Error('Please choose only remote, hybrid, or on-site.');
  }
  if (!searchPrefs.keywords) {
    throw new Error(`Please confirm one ${onboardingPageTitleTierLabels.search_keyword_label.toLowerCase()}.`);
  }
  if (searchPrefs.minimum_salary_yearly !== '' && searchPrefs.minimum_salary_yearly !== null && searchPrefs.minimum_salary_yearly !== undefined) {
    const yearly = onboardingParseCurrencyValue(searchPrefs.minimum_salary_yearly);
    if (yearly === '' || !Number.isFinite(yearly) || yearly < 0) {
      throw new Error('Please enter a valid minimum permanent salary excluding super.');
    }
    if (yearly > getSalaryLimitMaximum('minimum_salary_yearly')) {
      throw new Error('Minimum permanent salary is above the allowed maximum.');
    }
  }
  if (searchPrefs.minimum_daily_rate !== '' && searchPrefs.minimum_daily_rate !== null && searchPrefs.minimum_daily_rate !== undefined) {
    const daily = onboardingParseCurrencyValue(searchPrefs.minimum_daily_rate);
    if (daily === '' || !Number.isFinite(daily) || daily < 0) {
      throw new Error('Please enter a valid minimum contract daily rate excluding super.');
    }
    if (daily > getSalaryLimitMaximum('minimum_daily_rate')) {
      throw new Error('Minimum contract daily rate is above the allowed maximum.');
    }
  }
}

export function applyProfileDefaults(profile) {
  if (!profile || !profile.onboarding_settings || !profile.search_settings || !profile.match_preferences || !profile.salary_preferences) {
    throw new Error('Missing onboarding profile data.');
  }
  const onboarding = profile.onboarding_settings;
  const preset = onboarding.capability_strength_preset;
  if (!preset) {
    throw new Error('Missing capability strength preset.');
  }
  const searchSettings = profile.search_settings;
  const matchPreferences = profile.match_preferences;
  const salaryPreferences = profile.salary_preferences;

  if (capabilityStrengthPresetEl) capabilityStrengthPresetEl.value = String(preset);
  if (!reviewTargetTitles.length && !reviewSecondaryTitles.length) {
    if (!Array.isArray(profile.target_roles) || !Array.isArray(profile.also_consider_roles)) {
      throw new Error('Missing target role lists.');
    }
    const normalizedTitles = normalizeReviewTitleLists(
      profile.target_roles,
      profile.also_consider_roles,
    );
    reviewTargetTitles = normalizedTitles.primary;
    reviewSecondaryTitles = normalizedTitles.secondary;
  }
  if (reviewSearchKeywordsEl && !String(reviewSearchKeywordsEl.value || '').trim()) {
    const savedKeywords = String(searchSettings.keywords || '').trim();
    if (savedKeywords) {
      reviewSearchKeywordsEl.value = savedKeywords;
    } else if (Array.isArray(profile.target_roles) && profile.target_roles.length) {
      reviewSearchKeywordsEl.value = defaultSearchKeywordFromTargetRoles(profile);
    }
  }
  if (refs.minContractMonths && !String(refs.minContractMonths.value || '').trim()) {
    if (matchPreferences.min_contract_months === undefined) {
      throw new Error('Missing minimum contract length.');
    }
    setMinContractMonthValue(matchPreferences.min_contract_months ?? '');
  }
  updateMinContractMonthState();
  if (reviewMinimumSalaryYearlyEl && !String(reviewMinimumSalaryYearlyEl.value || '').trim()) {
    if (salaryPreferences.minimum_salary_yearly === undefined || salaryPreferences.minimum_salary_yearly === null) {
      throw new Error('Missing minimum permanent salary.');
    }
    onboardingSetCurrencyFieldValue(reviewMinimumSalaryYearlyEl, salaryPreferences.minimum_salary_yearly);
  }
  if (reviewMinimumDailyRateEl && !String(reviewMinimumDailyRateEl.value || '').trim()) {
    if (salaryPreferences.minimum_daily_rate === undefined || salaryPreferences.minimum_daily_rate === null) {
      throw new Error('Missing minimum contract daily rate.');
    }
    onboardingSetCurrencyFieldValue(reviewMinimumDailyRateEl, salaryPreferences.minimum_daily_rate);
  }
  if (!Array.isArray(matchPreferences.engagement_type)) {
    throw new Error('Missing engagement type preferences.');
  }
  setOnboardingEngagementTypeValues(matchPreferences.engagement_type);
  updateMinContractMonthState();
  if (!getOnboardingWorkModePreferenceValues().length) {
    if (!Array.isArray(matchPreferences.work_mode_preference)) {
      throw new Error('Missing work mode preferences.');
    }
    setOnboardingWorkModePreferenceValues(matchPreferences.work_mode_preference);
    updateSearchPreferenceSummaries();
  }
  if (!document.querySelectorAll('input[name="prefer_sector"]:checked').length) {
    if (!Array.isArray(matchPreferences.prefer_sector)) {
      throw new Error('Missing sector preferences.');
    }
    setSectorPreferenceValues(matchPreferences.prefer_sector);
    updateSearchPreferenceSummaries();
  }
  if (!selectedLocations.length && Array.isArray(searchSettings.locations) && searchSettings.locations.length) {
    setSelectedLocation(searchSettings.locations[0]);
  }
  refreshStepNavigation();
}

export function observeReviewCapabilityLayout() {
  if (reviewCapabilityResizeObserver || !window.ResizeObserver) {
    return;
  }
  const container = reviewCapabilityCardsEl;
  if (!container) {
    return;
  }
  reviewCapabilityResizeObserver = new ResizeObserver(() => {
    syncReviewCapabilityVisibleCount(true);
  });
  reviewCapabilityResizeObserver.observe(container);
}

if (continueToReviewEl) {
  continueToReviewEl.addEventListener('click', () => setStep(REVIEW_STEP));
}
[
  reviewMinimumSalaryYearlyEl,
  reviewMinimumDailyRateEl,
].filter(Boolean).forEach((input) => {
  onboardingCurrencyUi.bindCurrencyInput?.(input);
});
renderLocationSelect();
observeReviewCapabilityLayout();
initFieldInfoToggles();
updateSearchPreferenceSummaries();
