import * as onboardingSettingsUtils from '../settings/shared/settings-utils.js';
import * as onboardingCurrencyUi from '../common/currency-input.js';
import * as onboardingLocationUi from '../common/location-options.js';
import * as onboardingCapabilityUi from '../common/capability-ui.js';
import * as onboardingUpload from './onboarding-upload.js';

const urlParams = new URLSearchParams(window.location.search);
const isRebuildMode = urlParams.get('mode') === 'rebuild';
export const refs = Object.freeze({
  status: document.getElementById('status'),
  onboardingImportHelper: document.getElementById('onboarding_import_helper'),
  onboardingImportHelperCopy: document.getElementById('onboarding_import_helper_copy'),
  dismissOnboardingImportHelperButton: document.getElementById('dismiss_onboarding_import_helper'),
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
});
const {
  status: statusEl,
  onboardingImportHelper: onboardingImportHelperEl,
  onboardingImportHelperCopy: onboardingImportHelperCopyEl,
  dismissOnboardingImportHelperButton: dismissOnboardingImportHelperButtonEl,
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
} = refs;
const STEP_COUNT = 4;
const REVIEW_STEP = 2;
const SEARCH_STEP = 3;
const CHECK_STEP = 4;
const capabilityLabels = onboardingCapabilityUi.labels || {};
const escapeHtml = onboardingSettingsUtils.escapeHtml;
const ONBOARDING_DEFAULTS = window.__JOB_HUNTER_ONBOARDING_DEFAULTS__ || {};
const ONBOARDING_CV_PAGE_LIMIT = Number(ONBOARDING_DEFAULTS.cv_max_pages || 0);
const salaryLimits = window.__JOB_HUNTER_SALARY_LIMITS__ || {};
const minContractMonthOptions = Array.isArray(window.__JOB_HUNTER_MIN_CONTRACT_MONTH_OPTIONS__)
  ? window.__JOB_HUNTER_MIN_CONTRACT_MONTH_OPTIONS__
  : [];
const minContractMonthValues = new Set(minContractMonthOptions.map((option) => String(option.value || '').trim()));
const minContractMonthNoneLabel = String(window.__JOB_HUNTER_MIN_CONTRACT_MONTH_NONE_LABEL__ || 'All').trim();
const onboardingPageTitleTierLabels = window.__JOB_HUNTER_TITLE_TIER_LABELS__;
export const PRIMARY_CV_COPY = Object.freeze({
  emptyTitle: 'Drop your CV here',
  emptyHint: 'Drop, click, or paste a CV file to start onboarding.',
  loadedHint: 'You can keep going or replace it with another file.',
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

if (!onboardingPageTitleTierLabels) {
  throw new Error('Missing title tier labels.');
}
if (!capabilityLabels.onboarding_title || !capabilityLabels.help_text) {
  throw new Error('Missing capability UI labels.');
}
if (typeof escapeHtml !== 'function') {
  throw new Error('Missing HTML escaping helper.');
}

export function defaultSearchKeywordFromTargetRoles(profile) {
  const reviewedTitles = Array.isArray(reviewTargetTitles) ? reviewTargetTitles : [];
  const profileTitles = Array.isArray(profile?.target_roles) ? profile.target_roles : [];
  const allTitles = reviewedTitles.concat(profileTitles).filter(Boolean);
  return allTitles.length ? allTitles[0] : '';
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
if (reviewCapabilityFilterEl) {
  reviewCapabilityFilterEl.placeholder = capabilityLabels.filter_placeholder;
  reviewCapabilityFilterEl.setAttribute('aria-label', capabilityLabels.filter_placeholder);
}
const onboardingPageLabels = window.__JOB_HUNTER_ONBOARDING_PAGE_LABELS__;
if (!onboardingPageLabels) {
  throw new Error('Missing onboarding page labels.');
}
const PRIMARY_CV_COPY = {
  emptyTitle: onboardingPageLabels.cv_drop_zone_empty_title,
  emptyHint: onboardingPageLabels.cv_drop_zone_empty_hint,
  loadedHint: onboardingPageLabels.cv_drop_zone_loaded_hint,
};
const ONBOARDING_USER_ID = String(window.__JOB_HUNTER_USER_ID__ || '').trim();
if (!ONBOARDING_USER_ID) {
  throw new Error('Missing user id.');
}
function buildScopedStorageKey(baseKey) {
  return `${baseKey}:${ONBOARDING_USER_ID}`;
}
const WIZARD_STATE_KEY = buildScopedStorageKey('jobHunter.onboardingWizard');
const ONBOARDING_WELCOME_KEY = buildScopedStorageKey('jobHunter.onboardingWelcome');
const ONBOARDING_WELCOME_OPT_OUT_KEY = buildScopedStorageKey('jobHunter.onboardingWelcomeOptOut');
const ONBOARDING_IMPORT_HELPER_DISMISSED_KEY = buildScopedStorageKey('jobHunter.onboardingImportHelperDismissed');
const SOURCE_PACK_DATA_PREFIX = '/data/';
const ROOT_DATA_PREFIX = 'data/';
const REVIEW_CAPABILITY_PREVIEW_ROWS = (window.__JOB_HUNTER_ONBOARDING_IMPORT_SUMMARY_LABELS__ || {}).capability_preview_rows || 1;
const isTestMode = document.body.dataset.testMode === 'true';

export let currentStep = 1;
export let workingStatusTimer = null;
export let preservedPrimaryCvFile = null;
export let lastImportPayload = null;
export let reviewTargetTitles = [];
export let reviewSecondaryTitles = [];
export let reviewCapabilityRules = [];
export let selectedLocations = [];
export let selectedReviewCapabilityIndexes = new Set();
export let reviewCapabilityVisibleCount = REVIEW_CAPABILITY_PREVIEW_ROWS;
export let maxUnlockedStep = 1;
export let draftBuiltExplicitly = false;
export let searchBasicsPersistTimer = null;
export let savedPrimaryCvSourcePath = '';
export let savedPrimaryCvFileName = '';
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

export function setSavedPrimaryCvSourcePath(value) {
  savedPrimaryCvSourcePath = String(value || '');
}

export function setSavedPrimaryCvFileName(value) {
  savedPrimaryCvFileName = String(value || '');
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

function onboardingImportHelperDismissed() {
  try {
    return window.localStorage.getItem(ONBOARDING_IMPORT_HELPER_DISMISSED_KEY) === '1';
  } catch {
    return false;
  }
}

function showOnboardingImportHelper(message) {
  if (!onboardingImportHelperEl || !onboardingImportHelperCopyEl) {
    return;
  }
  onboardingImportHelperCopyEl.textContent = String(message || '').trim();
  onboardingImportHelperEl.hidden = false;
}

function hideOnboardingImportHelper(markDismissed = false) {
  if (onboardingImportHelperEl) {
    onboardingImportHelperEl.hidden = true;
  }
  if (!markDismissed) {
    return;
  }
  try {
    window.localStorage.setItem(ONBOARDING_IMPORT_HELPER_DISMISSED_KEY, '1');
  } catch {
  }
}

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
  return String(refs.minContractMonths?.value || '').trim();
}

export function setMinContractMonthValue(value) {
  if (refs.minContractMonths) {
    refs.minContractMonths.value = String(value || '').trim();
  }
}

export function getResolvedMinContractMonthValue() {
  const current = getMinContractMonthValue();
  if (minContractMonthValues.has(current)) return current;
  const defaultOption = minContractMonthOptions.find((option) => Boolean(String(option.value || '').trim()));
  return String(defaultOption?.value || '').trim();
}

function minContractMonthSummaryText(value) {
  const selected = String(value || '').trim();
  if (!selected) {
    return minContractMonthNoneLabel;
  }
  const option = minContractMonthOptions.find((item) => String(item.value || '').trim() === selected);
  return String(option?.label || selected).trim();
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
    if (allSelected) {
      refs.engagementTypeSummary.textContent = `${onboardingPageLabels.work_type_summary_all_label} · ${onboardingPageLabels.work_type_summary_contract_length_label}: ${contractMonths ? minContractMonthSummaryText(contractMonths) : onboardingPageLabels.summary_any_length_label}`;
    }
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
  if (!contractEnabled) {
    span.textContent = span.dataset.baseLabel || span.textContent;
    return;
  }
  if (!span.dataset.baseLabel) span.dataset.baseLabel = span.textContent;
  const months = String(refs.minContractMonths?.value || '').trim();
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
  const max = Number(salaryLimits?.[key]?.max);
  return Number.isFinite(max) && max >= 0 ? max : Infinity;
};

export function saveWizardState() {
  if (currentStep < 2 && !hasDraftProfileState()) {
    window.localStorage.removeItem(WIZARD_STATE_KEY);
    return;
  }
  const primaryCvSource = String(
    lastImportPayload?.materials?.profile_sources?.[0]?.path
    || savedPrimaryCvSourcePath
    || ''
  ).trim();
  const primaryCvFileName = String(
    preservedPrimaryCvFile?.name
    || primaryCvInput?.files?.[0]?.name
    || savedPrimaryCvFileName
    || ''
  ).trim();
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
    primaryCvSourcePath: primaryCvSource,
    primaryCvFileName,
  }));
}

function normalizePrimaryCvSourcePath(path) {
  const value = String(path || '').trim().replace(/\\/g, '/').replace(/^\/+/, '');
  return value.startsWith(ROOT_DATA_PREFIX) ? value.slice(ROOT_DATA_PREFIX.length) : value;
}

async function restorePrimaryCvFromSourcePath() {
  if (!primaryCvInput || primaryCvInput.files?.[0] || preservedPrimaryCvFile) {
    return false;
  }
  const state = (() => {
    try {
      const raw = window.localStorage.getItem(WIZARD_STATE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  })();
  const sourcePath = String(state?.primaryCvSourcePath || savedPrimaryCvSourcePath || '').trim();
  if (!sourcePath) {
    return false;
  }
  const dataPath = normalizePrimaryCvSourcePath(sourcePath);
  const response = await fetch(`${SOURCE_PACK_DATA_PREFIX}${encodeURI(dataPath)}`, {
    cache: 'no-store',
  });
  if (!response.ok) {
    return false;
  }
  const blob = await response.blob();
  const fileName = String(state?.primaryCvFileName || savedPrimaryCvFileName || dataPath.split('/').pop() || 'cv').trim();
  const file = new File([blob], fileName, { type: blob.type || 'application/octet-stream' });
  onboardingUpload.assignPrimaryCvFile(file);
  return true;
}

function buildSearchBasicsProfilePatch() {
  const location = String(selectedLocations[0] || locationSelect?.value || '').trim();
  const keywords = String(reviewSearchKeywordsEl?.value || '').trim();
  const minimumSalaryYearly = onboardingParseCurrencyValue(reviewMinimumSalaryYearlyEl?.value || '');
  const minimumDailyRate = onboardingParseCurrencyValue(reviewMinimumDailyRateEl?.value || '');
  const engagementType = getOnboardingEngagementTypeValues();
  const minContractMonths = engagementType.includes('contract') ? (getResolvedMinContractMonthValue() || null) : null;
  const preferSector = getSectorPreferenceValues();

  return {
    search_settings: {
      keywords,
      locations: location ? [location] : [],
    },
    match_preferences: {
      engagement_type: engagementType,
      min_contract_months: minContractMonths,
      work_mode_preference: getOnboardingWorkModePreferenceValues(),
      prefer_sector: preferSector,
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

export function scheduleSearchBasicsPersistence() {
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
  let state;
  try {
    const raw = window.localStorage.getItem(WIZARD_STATE_KEY);
    if (!raw) return false;
    state = JSON.parse(raw);
    const savedTargets = Array.isArray(state?.reviewTargetTitles) ? state.reviewTargetTitles : [];
    const savedSecondary = Array.isArray(state?.reviewSecondaryTitles) ? state.reviewSecondaryTitles : [];
    const savedCapabilities = Array.isArray(state?.reviewCapabilityRules) ? state.reviewCapabilityRules : [];
    const hasSavedDraft = Boolean(savedTargets.length || savedSecondary.length || savedCapabilities.length);
    if (!state || (Number(state.step) >= 2 && !hasSavedDraft)) return false;
    const normalizedTitles = normalizeReviewTitleLists(state.reviewTargetTitles || [], state.reviewSecondaryTitles || []);
    reviewTargetTitles = normalizedTitles.primary;
    reviewSecondaryTitles = normalizedTitles.secondary;
    reviewCapabilityRules = (Array.isArray(state.reviewCapabilityRules) ? state.reviewCapabilityRules : [])
      .map(normalizeReviewCapability)
      .filter((rule) => rule.name);
    maxUnlockedStep = Math.max(1, Math.min(STEP_COUNT, Number(state.maxUnlockedStep) || 1));
    reviewCapabilityVisibleCount = Number(state.reviewCapabilityVisibleCount) > 0
      ? Number(state.reviewCapabilityVisibleCount)
      : getReviewCapabilityPreviewCount();
    savedPrimaryCvSourcePath = String(state.primaryCvSourcePath || '').trim();
    savedPrimaryCvFileName = String(state.primaryCvFileName || '').trim();
    try {
      setSelectedLocation((Array.isArray(state.selectedLocations) ? state.selectedLocations[0] : state.selectedLocations) || '', { persist: false });
    } catch (error) {
      console.warn('Could not restore onboarding location state.', error);
    }
    try {
      const kwEl = reviewSearchKeywordsEl;
      if (kwEl) kwEl.value = state.searchKeywords || '';
      setMinContractMonthValue(state.minContractMonths || '');
      const salaryEl = reviewMinimumSalaryYearlyEl;
      if (salaryEl) onboardingSetCurrencyFieldValue(salaryEl, state.minimumSalaryYearly || 0);
      const dailyEl = reviewMinimumDailyRateEl;
      if (dailyEl) onboardingSetCurrencyFieldValue(dailyEl, state.minimumDailyRate || 0);
      setOnboardingEngagementTypeValues(state.engagementType);
      setOnboardingWorkModePreferenceValues(state.workModePreference || []);
      setSectorPreferenceValues(state.preferSector || []);
      updateSearchPreferenceSummaries();
      updateCompensationVisibility();
      if (Number(state.step) >= CHECK_STEP) {
        updateCheckStep();
      }
    } catch (error) {
      console.warn('Could not restore onboarding search basics state.', error);
    }
    return Number(state.step) || REVIEW_STEP;
  } catch (error) {
    console.warn('Could not restore onboarding wizard state.', error);
    return false;
  }
}
 

export function showStatus(message, kind) {
  if (workingStatusTimer && kind !== 'loading') {
    window.clearInterval(workingStatusTimer);
    workingStatusTimer = null;
  }
  statusEl.textContent = message;
  statusEl.className = message ? `status ${kind}` : 'status';
}

export function hideStatus() {
  if (workingStatusTimer) {
    window.clearInterval(workingStatusTimer);
    workingStatusTimer = null;
  }
  statusEl.textContent = '';
  statusEl.className = 'status';
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
    statusEl.textContent = items[index];
    statusEl.className = 'status loading';
  }, stepMs);
}

function resetPrimaryCvDropZoneAppearance() {
  if (!primaryCvDropZone) return;
  primaryCvDropZone.classList.remove('is-dragover');
}

export function setStep(stepNumber, options = {}) {
  const { scroll = true, persist = true } = options;
  const hasPrimaryCv = Boolean(primaryCvInput?.files?.[0] || preservedPrimaryCvFile);
  if (stepNumber > 1 && !hasPrimaryCv) {
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
  } else if (stepNumber === 1) {
    void restorePrimaryCvFromSourcePath();
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

function onboardingSettingsPayload() {
  const capabilityStrengthPreset = capabilityStrengthPresetEl?.value.trim() || '';
  return {
    capability_strength_preset: capabilityStrengthPreset || 'balanced',
  };
}

function searchPreferencesPayload() {
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

function validateOnboardingSettings(settings) {
  const preset = String(settings.capability_strength_preset || '').trim();
  if (!['recent_focus', 'balanced', 'include_older_experience'].includes(preset)) {
    throw new Error('Please choose how older experience should be treated.');
  }
}

function validateSearchPreferences(searchPrefs) {
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

function applyProfileDefaults(profile) {
  const onboarding = profile?.onboarding_settings || {};
  const preset = onboarding.capability_strength_preset || ONBOARDING_DEFAULTS.capability_strength_preset;
  const searchSettings = profile?.search_settings || {};
  const matchPreferences = profile?.match_preferences || {};
  const salaryPreferences = profile?.salary_preferences || {};

  if (capabilityStrengthPresetEl) capabilityStrengthPresetEl.value = String(preset);
  if (!reviewTargetTitles.length && !reviewSecondaryTitles.length) {
    const normalizedTitles = normalizeReviewTitleLists(
      profile?.target_roles || [],
      profile?.also_consider_roles || [],
    );
    reviewTargetTitles = normalizedTitles.primary;
    reviewSecondaryTitles = normalizedTitles.secondary;
  }
  if (reviewSearchKeywordsEl && !String(reviewSearchKeywordsEl.value || '').trim()) {
    const savedKeywords = String(searchSettings.keywords || '').trim();
    reviewSearchKeywordsEl.value = savedKeywords || defaultSearchKeywordFromTargetRoles(profile);
  }
  if (refs.minContractMonths && !String(refs.minContractMonths.value || '').trim()) {
    setMinContractMonthValue(matchPreferences.min_contract_months ?? '');
  }
  updateMinContractMonthState();
  if (reviewMinimumSalaryYearlyEl && !String(reviewMinimumSalaryYearlyEl.value || '').trim()) {
    onboardingSetCurrencyFieldValue(reviewMinimumSalaryYearlyEl, salaryPreferences.minimum_salary_yearly ?? 0);
  }
  if (reviewMinimumDailyRateEl && !String(reviewMinimumDailyRateEl.value || '').trim()) {
    onboardingSetCurrencyFieldValue(reviewMinimumDailyRateEl, salaryPreferences.minimum_daily_rate ?? 0);
  }
  setOnboardingEngagementTypeValues(matchPreferences.engagement_type || []);
  updateMinContractMonthState();
  if (!getOnboardingWorkModePreferenceValues().length) {
    setOnboardingWorkModePreferenceValues(matchPreferences.work_mode_preference || []);
    updateSearchPreferenceSummaries();
  }
  if (!document.querySelectorAll('input[name="prefer_sector"]:checked').length) {
    setSectorPreferenceValues(matchPreferences.prefer_sector || []);
    updateSearchPreferenceSummaries();
  }
  if (!selectedLocations.length) {
    setSelectedLocation((searchSettings.locations || [])[0] || '');
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
if (locationSelect) {
  locationSelect.addEventListener('change', () => {
    hideStatus();
    setSelectedLocation(locationSelect.value);
    scheduleSearchBasicsPersistence();
  });
}
if (dismissOnboardingImportHelperButtonEl) {
  dismissOnboardingImportHelperButtonEl.addEventListener('click', () => hideOnboardingImportHelper(true));
}
document.querySelectorAll('input[name="prefer_sector"]').forEach((input) => {
  input.addEventListener('change', () => {
    onboardingSettingsUtils.ensureAtLeastOneChoiceSelected?.('prefer_sector', input);
    hideStatus();
    updateSearchPreferenceSummaries();
    saveWizardState();
    scheduleSearchBasicsPersistence();
  });
});
if (refs.minContractMonths) {
  refs.minContractMonths.addEventListener('change', () => {
    const contractRow = document.getElementById('contract_duration_row');
    if (contractRow) contractRow.hidden = true;
    updateContractChipLabel();
    updateSearchPreferenceSummaries();
    hideStatus();
    saveWizardState();
    scheduleSearchBasicsPersistence();
  });
}
document.querySelectorAll('input[name="engagement_type"]').forEach((input) => {
  input.addEventListener('change', () => {
    if (!input.checked) {
      const anyChecked = document.querySelectorAll('input[name="engagement_type"]:checked').length > 0;
      if (!anyChecked) input.checked = true;
    }
    hideStatus();
    updateMinContractMonthState({ showRow: input.value === 'contract' && input.checked });
    updateCompensationVisibility();
    saveWizardState();
    scheduleSearchBasicsPersistence();
  });
});
  if (refs.workModePreferences.length) {
    refs.workModePreferences.forEach((element) => element.addEventListener('change', () => {
      hideStatus();
      updateSearchPreferenceSummaries();
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
observeReviewCapabilityLayout();
initFieldInfoToggles();
updateSearchPreferenceSummaries();
