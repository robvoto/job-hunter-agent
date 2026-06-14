import * as onboardingPage from './onboarding-page.js';
import * as onboardingSettingsUtils from '../settings/shared/settings-utils.js';
import * as onboardingLocationUi from '../common/location-options.js';
const {
  reviewSearchKeywords: reviewSearchKeywordsEl,
  reviewMinimumSalaryYearly: reviewMinimumSalaryYearlyEl,
  reviewMinimumDailyRate: reviewMinimumDailyRateEl,
} = onboardingPage.refs;

function getSectorPreferenceValues() {
  return onboardingSettingsUtils.getSectorPreferenceValues();
}

function setSectorPreferenceValues(values) {
  onboardingSettingsUtils.setSectorPreferenceValues(values);
}

function getWorkModePreferenceValues() {
  return onboardingSettingsUtils.getWorkModePreferenceValues();
}

function setWorkModePreferenceValues(values) {
  onboardingSettingsUtils.setWorkModePreferenceValues(values);
}

function setEngagementTypeValues(values) {
  onboardingSettingsUtils.setEngagementTypeValues(values);
}

export function setSelectedLocations(locations) {
  const select = onboardingPage.refs.locationSelect;
  const value = String(Array.isArray(locations) && locations.length ? locations[0] : '').trim();
  const current = String(select?.value || onboardingPage.selectedLocations[0] || '').trim();
  const next = value || current;
  const resolved = onboardingLocationUi.resolveLocationValue ? onboardingLocationUi.resolveLocationValue(next) : next;
  onboardingPage.setSelectedLocations(resolved ? [resolved] : []);
  if (select) select.value = resolved;
  onboardingPage.renderLocationSelect();
}

export function hydrateSearchBasics(profile) {
  const searchSettings = profile?.search_settings || {};
  const matchPreferences = profile?.match_preferences || {};
  const salaryPreferences = profile?.salary_preferences || {};
  const currentKeywords = String(reviewSearchKeywordsEl?.value || '').trim();
  const savedKeywords = String(searchSettings.keywords || '').trim();
  const profileTargetRoles = Array.isArray(profile?.target_roles) ? profile.target_roles : [];
  const fallbackKeyword = profileTargetRoles.length ? onboardingPage.defaultSearchKeywordFromTargetRoles(profile) : '';
  reviewSearchKeywordsEl.value = currentKeywords || savedKeywords || fallbackKeyword;
  onboardingPage.setMinContractMonthValue(matchPreferences.min_contract_months ?? '');
  const currentSalaryYearly = String(reviewMinimumSalaryYearlyEl.value || '').trim();
  const currentSalaryDaily = String(reviewMinimumDailyRateEl.value || '').trim();
  if (!currentSalaryYearly) {
    onboardingSettingsUtils.setCurrencyFieldValue(reviewMinimumSalaryYearlyEl, salaryPreferences.minimum_salary_yearly ?? 0);
  }
  if (!currentSalaryDaily) {
    onboardingSettingsUtils.setCurrencyFieldValue(reviewMinimumDailyRateEl, salaryPreferences.minimum_daily_rate ?? 0);
  }
  setSelectedLocations(searchSettings.locations || []);
  const engagementType = Array.isArray(matchPreferences.engagement_type) ? matchPreferences.engagement_type : [];
  setEngagementTypeValues(engagementType);
  setWorkModePreferenceValues(matchPreferences.work_mode_preference || []);
  if (!document.querySelectorAll('input[name="prefer_sector"]:checked').length) {
    setSectorPreferenceValues(matchPreferences.prefer_sector || []);
  }
  onboardingPage.updateCompensationVisibility();
}
