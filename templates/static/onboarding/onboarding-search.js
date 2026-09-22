import * as onboardingPage from './onboarding-page.js';
import * as onboardingSettingsUtils from '../settings/shared/settings-utils.js';
import * as onboardingLocationUi from '../common/location-options.js';
const {
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
  const source = Array.isArray(locations) ? locations : [locations];
  const resolved = source
    .map((value) => onboardingLocationUi.resolveLocationValue ? onboardingLocationUi.resolveLocationValue(value) : String(value || '').trim())
    .filter(Boolean);
  onboardingPage.setSelectedLocations(resolved);
  onboardingPage.renderLocationSelect();
}

export function hydrateSearchBasics(profile) {
  const searchSettings = profile?.search_settings || {};
  const matchPreferences = profile?.match_preferences || {};
  const salaryPreferences = profile?.salary_preferences || {};
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
  setSectorPreferenceValues(matchPreferences.prefer_sector || []);
  onboardingPage.updateCompensationVisibility();
}
