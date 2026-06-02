import * as onboardingPage from './onboarding-page.js';
import * as onboardingSettingsUtils from '../settings/shared/settings-utils.js';

const WIZARD_STATE_KEY = onboardingPage.WIZARD_STATE_KEY;

function getSearchBasicsState() {
  return {
    keywords: onboardingPage.refs.reviewSearchKeywords?.value || '',
    minContractMonths: onboardingPage.getResolvedMinContractMonthValue?.() || '',
    minimumSalaryYearly: onboardingPage.refs.reviewMinimumSalaryYearly?.value || '',
    minimumDailyRate: onboardingPage.refs.reviewMinimumDailyRate?.value || '',
  };
}

export function buildSearchBasicsProfilePatch() {
  const location = String(onboardingPage.selectedLocations[0] || onboardingPage.refs.locationSelect?.value || '').trim();
  const searchBasics = getSearchBasicsState();
  const engagementType = onboardingSettingsUtils.getEngagementTypeValues();
  const minimumSalaryYearly = onboardingSettingsUtils.parseCurrencyValue(searchBasics.minimumSalaryYearly);
  const minimumDailyRate = onboardingSettingsUtils.parseCurrencyValue(searchBasics.minimumDailyRate);
  const minContractMonths = engagementType.includes('contract') ? (searchBasics.minContractMonths || null) : null;

  return {
    search_settings: {
      keywords: String(searchBasics.keywords || '').trim(),
      locations: location ? [location] : [],
    },
    match_preferences: {
      engagement_type: engagementType,
      min_contract_months: minContractMonths,
      work_mode_preference: onboardingSettingsUtils.getWorkModePreferenceValues(),
      prefer_sector: onboardingSettingsUtils.getSectorPreferenceValues(),
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

export function saveWizardState() {
  if (onboardingPage.currentStep < 2 && !onboardingPage.hasDraftProfileState()) {
    window.localStorage.removeItem(WIZARD_STATE_KEY);
    return;
  }
  window.localStorage.setItem(WIZARD_STATE_KEY, JSON.stringify({
    step: onboardingPage.currentStep,
    maxUnlockedStep: onboardingPage.maxUnlockedStep,
    reviewTargetTitles: onboardingPage.reviewTargetTitles,
    reviewSecondaryTitles: onboardingPage.reviewSecondaryTitles,
    reviewCapabilityRules: onboardingPage.reviewCapabilityRules,
    reviewCapabilityVisibleCount: onboardingPage.reviewCapabilityVisibleCount,
    selectedLocations: onboardingPage.selectedLocations,
    workModePreference: onboardingSettingsUtils.getWorkModePreferenceValues(),
    searchKeywords: onboardingPage.refs.reviewSearchKeywords?.value || '',
    minContractMonths: onboardingPage.getResolvedMinContractMonthValue?.() || '',
    minimumSalaryYearly: onboardingPage.refs.reviewMinimumSalaryYearly?.value || '',
    minimumDailyRate: onboardingPage.refs.reviewMinimumDailyRate?.value || '',
    engagementType: onboardingSettingsUtils.getEngagementTypeValues(),
    preferSector: onboardingSettingsUtils.getSectorPreferenceValues(),
  }));
}

export function scheduleSearchBasicsPersistence() {
  if (onboardingPage.searchBasicsPersistTimer) {
    window.clearTimeout(onboardingPage.searchBasicsPersistTimer);
  }
  onboardingPage.setSearchBasicsPersistTimer(window.setTimeout(() => {
    onboardingPage.setSearchBasicsPersistTimer(null);
    persistSearchBasicsToProfile().catch((error) => {
      console.warn('Could not persist onboarding search basics.', error);
    });
  }, 500));
}

export async function flushSearchBasicsPersistence() {
  if (onboardingPage.searchBasicsPersistTimer) {
    window.clearTimeout(onboardingPage.searchBasicsPersistTimer);
    onboardingPage.setSearchBasicsPersistTimer(null);
  }
  await persistSearchBasicsToProfile();
}

export function restoreWizardState() {
  try {
    const raw = window.localStorage.getItem(WIZARD_STATE_KEY);
    if (!raw) return false;
    const state = JSON.parse(raw);
    const savedTargets = Array.isArray(state?.reviewTargetTitles) ? state.reviewTargetTitles : [];
    const savedSecondary = Array.isArray(state?.reviewSecondaryTitles) ? state.reviewSecondaryTitles : [];
    const savedCapabilities = Array.isArray(state?.reviewCapabilityRules) ? state.reviewCapabilityRules : [];
    const hasSavedDraft = Boolean(savedTargets.length || savedSecondary.length || savedCapabilities.length);
    if (!state || (Number(state.step) >= 2 && !hasSavedDraft)) return false;
    const normalizedTitles = onboardingSettingsUtils.normalizeReviewTitleLists(state.reviewTargetTitles || [], state.reviewSecondaryTitles || []);
    onboardingPage.setReviewTargetTitles(normalizedTitles.primary);
    onboardingPage.setReviewSecondaryTitles(normalizedTitles.secondary);
    onboardingPage.setReviewCapabilityRules((Array.isArray(state.reviewCapabilityRules) ? state.reviewCapabilityRules : [])
      .map(onboardingSettingsUtils.normalizeReviewCapability)
      .filter((rule) => rule.name));
    onboardingPage.setMaxUnlockedStep(Math.max(1, Math.min(4, Number(state.maxUnlockedStep) || 1)));
    onboardingPage.setReviewCapabilityVisibleCount(Number(state.reviewCapabilityVisibleCount) > 0
      ? Number(state.reviewCapabilityVisibleCount)
      : onboardingPage.getReviewCapabilityPreviewCount());
    try {
      onboardingPage.setSelectedLocation((Array.isArray(state.selectedLocations) ? state.selectedLocations[0] : state.selectedLocations) || '', { persist: false });
    } catch (error) {
      console.warn('Could not restore onboarding location state.', error);
    }
    try {
      if (onboardingPage.refs.reviewSearchKeywords) onboardingPage.refs.reviewSearchKeywords.value = state.searchKeywords || '';
      onboardingPage.setMinContractMonthValue(state.minContractMonths || '');
      if (onboardingPage.refs.reviewMinimumSalaryYearly) onboardingSettingsUtils.setCurrencyFieldValue(onboardingPage.refs.reviewMinimumSalaryYearly, state.minimumSalaryYearly || 0);
      if (onboardingPage.refs.reviewMinimumDailyRate) onboardingSettingsUtils.setCurrencyFieldValue(onboardingPage.refs.reviewMinimumDailyRate, state.minimumDailyRate || 0);
      onboardingSettingsUtils.setEngagementTypeValues(state.engagementType);
      onboardingSettingsUtils.setWorkModePreferenceValues(state.workModePreference || []);
      onboardingSettingsUtils.setSectorPreferenceValues(state.preferSector || []);
      onboardingPage.updateSearchPreferenceSummaries();
      onboardingPage.updateCompensationVisibility();
    } catch (error) {
      console.warn('Could not restore onboarding search basics state.', error);
    }
    return Number(state.step) || 2;
  } catch (error) {
    console.warn('Could not restore onboarding wizard state.', error);
    return false;
  }
}

// Event handlers for search-basics fields that need to persist wizard state and sync to DB.
// Wired here (not in page.js) because this module owns save/persist logic.
const { locationSelect, minContractMonths: minContractMonthsEl, workModePreferences } = onboardingPage.refs;

if (locationSelect) {
  locationSelect.addEventListener('change', () => {
    onboardingPage.hideStatus();
    onboardingPage.setSelectedLocation(locationSelect.value);
    scheduleSearchBasicsPersistence();
  });
}

document.querySelectorAll('input[name="prefer_sector"]').forEach((input) => {
  input.addEventListener('change', () => {
    onboardingSettingsUtils.ensureAtLeastOneChoiceSelected?.('prefer_sector', input);
    onboardingPage.hideStatus();
    onboardingPage.updateSearchPreferenceSummaries();
    saveWizardState();
    scheduleSearchBasicsPersistence();
  });
});

if (minContractMonthsEl) {
  minContractMonthsEl.addEventListener('change', () => {
    const contractRow = document.getElementById('contract_duration_row');
    if (contractRow) contractRow.hidden = true;
    onboardingPage.updateContractChipLabel();
    onboardingPage.updateSearchPreferenceSummaries();
    onboardingPage.hideStatus();
    saveWizardState();
    scheduleSearchBasicsPersistence();
  });
  minContractMonthsEl.addEventListener('blur', () => {
    const contractRow = document.getElementById('contract_duration_row');
    if (contractRow && !String(minContractMonthsEl.value || '').trim()) {
      contractRow.hidden = true;
    }
  });
}

document.querySelectorAll('input[name="engagement_type"]').forEach((input) => {
  input.addEventListener('change', () => {
    if (!input.checked) {
      const anyChecked = document.querySelectorAll('input[name="engagement_type"]:checked').length > 0;
      if (!anyChecked) input.checked = true;
    }
    onboardingPage.hideStatus();
    onboardingPage.updateMinContractMonthState({ showRow: input.value === 'contract' && input.checked });
    onboardingPage.updateCompensationVisibility();
    saveWizardState();
    scheduleSearchBasicsPersistence();
  });
});

if (workModePreferences.length) {
  workModePreferences.forEach((element) => element.addEventListener('change', () => {
    onboardingPage.hideStatus();
    onboardingPage.updateSearchPreferenceSummaries();
    saveWizardState();
    scheduleSearchBasicsPersistence();
  }));
}
