import { formatRemoveItemLabel, renderTrashActionButton } from '../common/action-buttons.js';
import * as onboardingPage from './onboarding-page.js';
import { setSelectedLocations, hydrateSearchBasics } from './onboarding-search.js';
import * as onboardingStorage from './onboarding-storage.js';
import * as onboardingUpload from './onboarding-upload.js';
import * as onboardingSettingsUtils from '../settings/shared/settings-utils.js';
import * as onboardingCurrencyUi from '../common/currency-input.js';
import * as onboardingLocationUi from '../common/location-options.js';
import * as onboardingCapabilityUi from '../common/capability-ui.js';

const {
  applyProfileDefaults,
  CHECK_STEP,
  getReviewCapabilityPreviewCount,
  hasDraftProfileState,
  hasSearchBasicsState,
  hideStatus,
  isRebuildMode,
  isTestMode,
  onboardingSettingsPayload,
  ONBOARDING_WELCOME_KEY,
  refreshStepNavigation,
  renderLocationSelect,
  resetPrimaryCvDropZoneAppearance,
  REVIEW_STEP,
  SEARCH_STEP,
  searchPreferencesPayload,
  setMinContractMonthValue,
  setStep,
  showStatus,
  startWorkingStatus,
  STEP_COUNT,
  updateCompensationVisibility,
  validateOnboardingSettings,
  validateSearchPreferences,
  WIZARD_STATE_KEY,
  setLastLoadedProfile,
} = onboardingPage;
const {
  createProfileButton,
  primaryCvDropZone,
  primaryCvInput,
  reviewCapabilityCount: reviewCapabilityCountEl,
  stepNavButtons,
} = onboardingPage.refs;

const {
  escapeHtml,
  normalizeReviewText,
  normalizeReviewTitleLists,
  normalizeReviewCapability,
  patternToLabel,
  normalizeWorkModePreferences,
  getWorkModePreferenceValues,
  setWorkModePreferenceValues,
  setEngagementTypeValues,
  getSectorPreferenceValues,
  setSectorPreferenceValues,
  setCurrencyFieldValue,
  readCurrencyFieldValue,
} = onboardingSettingsUtils;

const onboardingDefaults = window.__JOB_HUNTER_ONBOARDING_DEFAULTS__;
if (!onboardingDefaults) {
  throw new Error('Missing onboarding defaults.');
}
const onboardingCvPageLimit = Number(onboardingDefaults.cv_max_pages);
if (!Number.isInteger(onboardingCvPageLimit) || onboardingCvPageLimit < 1) {
  throw new Error('Missing CV page limit.');
}
const onboardingFlowTitleTierLabels = window.__JOB_HUNTER_TITLE_TIER_LABELS__;
const onboardingImportSummaryLabels = window.__JOB_HUNTER_ONBOARDING_IMPORT_SUMMARY_LABELS__;
const onboardingFlowLabels = window.__JOB_HUNTER_ONBOARDING_FLOW_LABELS__;
const capabilityLabels = onboardingCapabilityUi.labels;
const capabilityIconHtml = onboardingCapabilityUi.capabilityIconHtml;
const splitCapabilityAliasesForDisplay = onboardingCapabilityUi.splitCapabilityAliasesForDisplay;
if (!onboardingFlowTitleTierLabels) {
  throw new Error('Missing title tier labels.');
}
if (!onboardingImportSummaryLabels) {
  throw new Error('Missing onboarding import summary labels.');
}
if (!onboardingFlowLabels) {
  throw new Error('Missing onboarding flow labels.');
}
if (!capabilityLabels || !capabilityLabels.onboarding_title || !capabilityLabels.help_text || !capabilityLabels.onboarding_no_match_text) {
  throw new Error('Missing capability UI labels.');
}
function normalizeReviewTitle(value) {
  return patternToLabel(value) || normalizeReviewText(value);
}

function normalizeReviewTitleKey(value) {
  return normalizeReviewTitle(value).toLowerCase();
}

function normalizeReviewAlias(value) {
  return normalizeReviewText(value).toLowerCase();
}

function formatLabel(template, values = {}) {
  return String(template || '').replace(/\{(\w+)\}/g, (_, key) => {
    if (Object.prototype.hasOwnProperty.call(values, key)) {
      return String(values[key]);
    }
    return '';
  });
}

function locationLabel(value) {
  return onboardingLocationUi.getLocationLabel ? onboardingLocationUi.getLocationLabel(value) : normalizeReviewText(value);
}

function dedupeReviewList(values) {
  const seen = new Set();
  const output = [];
  for (const value of values || []) {
    const cleaned = normalizeReviewTitle(value);
    const key = normalizeReviewTitleKey(cleaned);
    if (!cleaned || seen.has(key)) continue;
    seen.add(key);
    output.push(cleaned);
  }
  return output;
}

const flowRefs = Object.freeze({
  reviewStepRoot: document.querySelector('[data-step="2"]'),
  wizardProgressSteps: document.querySelector('.wizard-progress-steps'),
  checkTargetTitles: document.getElementById('check_target_titles'),
  checkSecondaryTitles: document.getElementById('check_secondary_titles'),
  checkCapabilities: document.getElementById('check_capabilities'),
  checkLocations: document.getElementById('check_locations'),
  checkEngagementType: document.getElementById('check_engagement_type'),
  checkMinContractMonths: document.getElementById('check_min_contract_months'),
  checkWorkModePreference: document.getElementById('check_work_mode_preference'),
  checkSectorPreference: document.getElementById('check_sector_preference'),
  checkSalaryYearly: document.getElementById('check_salary_yearly'),
  checkSalaryDaily: document.getElementById('check_salary_daily'),
  locationSearch: document.getElementById('location_search'),
  reviewMinimumSalaryYearly: document.getElementById('review_minimum_salary_yearly'),
  reviewMinimumDailyRate: document.getElementById('review_minimum_daily_rate'),
  reviewCapabilityFilter: document.getElementById('review_capability_filter'),
  reviewCapabilityCards: document.getElementById('review_capability_cards'),
  reviewTargetTitlesList: document.getElementById('review_target_titles_list'),
  reviewSecondaryTitlesList: document.getElementById('review_secondary_titles_list'),
  reviewTargetTitlesInput: document.getElementById('review_target_titles_input'),
  reviewSecondaryTitlesInput: document.getElementById('review_secondary_titles_input'),
  reviewAddTargetTitle: document.getElementById('review_add_target_title'),
  reviewAddSecondaryTitle: document.getElementById('review_add_secondary_title'),
  primaryCvInput: document.getElementById('primary_cv'),
  continueToSearchBasics: document.getElementById('continue_to_search_basics'),
  continueToCheck: document.getElementById('continue_to_check'),
  confirmReview: document.getElementById('confirm_review'),
  backToUploadFooter: document.getElementById('back_to_upload_footer'),
  backToReviewFooter: document.getElementById('back_to_review_footer'),
  backToSearchBasicsFooter: document.getElementById('back_to_search_basics_footer'),
  editDraftProfile: document.getElementById('edit_draft_profile'),
  editSearchBasics: document.getElementById('edit_search_basics'),
});

function clearOnboardingBrowserState() {
  try {
    window.localStorage.removeItem(ONBOARDING_WELCOME_KEY);
    window.localStorage.removeItem(WIZARD_STATE_KEY);
  } catch (error) {
    console.warn('Could not clear onboarding browser state.', error);
  }
}

const engagementTypeOptions = Array.isArray(window.__JOB_HUNTER_ENGAGEMENT_TYPE_OPTIONS__)
  ? window.__JOB_HUNTER_ENGAGEMENT_TYPE_OPTIONS__
  : [];
const engagementTypeLabels = Object.fromEntries(
  engagementTypeOptions
    .map((option) => [String(option.value || '').trim().toLowerCase(), String(option.label || '').trim()])
    .filter(([value]) => Boolean(value))
);
const engagementTypeDefaultValues = Array.isArray(window.__JOB_HUNTER_ENGAGEMENT_TYPE_DEFAULT_VALUES__)
  ? window.__JOB_HUNTER_ENGAGEMENT_TYPE_DEFAULT_VALUES__
  : engagementTypeOptions.map((option) => option.value);
const engagementTypeDefaultLabel = engagementTypeDefaultValues
  .map((value) => engagementTypeLabels[String(value || '').trim().toLowerCase()] || String(value || '').trim())
  .filter(Boolean)
  .join(' | ');
const minContractMonthOptions = Array.isArray(window.__JOB_HUNTER_MIN_CONTRACT_MONTH_OPTIONS__)
  ? window.__JOB_HUNTER_MIN_CONTRACT_MONTH_OPTIONS__
  : [];
const minContractMonthNoneLabel = String(window.__JOB_HUNTER_MIN_CONTRACT_MONTH_NONE_LABEL__ || 'All').trim();
const sectorPreferenceOptions = Array.isArray(window.__JOB_HUNTER_SECTOR_PREFERENCE_OPTIONS__)
  ? window.__JOB_HUNTER_SECTOR_PREFERENCE_OPTIONS__
  : [];
const sectorPreferenceDefault = String(
  window.__JOB_HUNTER_SECTOR_PREFERENCE_DEFAULT__
  || sectorPreferenceOptions?.[0]?.value
  || 'any'
).trim().toLowerCase();
const sectorPreferenceDefaultLabel = String(
  window.__JOB_HUNTER_SECTOR_PREFERENCE_DEFAULT_LABEL__
  || ''
).trim();
const sectorPreferenceLabels = Object.fromEntries(
  sectorPreferenceOptions
    .map((option) => [String(option.value || '').trim().toLowerCase(), String(option.label || '').trim()])
    .filter(([value]) => Boolean(value))
);
const workModePreferenceOptions = Array.isArray(window.__JOB_HUNTER_WORK_MODE_PREFERENCE_OPTIONS__)
  ? window.__JOB_HUNTER_WORK_MODE_PREFERENCE_OPTIONS__
  : [];
const workModePreferenceLabels = Object.fromEntries(
  workModePreferenceOptions
    .map((option) => [String(option.value || '').trim().toLowerCase(), String(option.label || '').trim()])
    .filter(([value]) => Boolean(value))
);
const workModePreferenceNoneLabel = String(
  window.__JOB_HUNTER_WORK_MODE_PREFERENCE_NONE_LABEL__
  || 'No preference'
).trim();

function engagementTypeLabel(values) {
  const selected = Array.isArray(values) ? values : [values];
  const labels = selected
    .map((value) => engagementTypeLabels[String(value || '').trim().toLowerCase()] || String(value || '').trim())
    .filter(Boolean);
  return labels.length ? labels.join(' | ') : engagementTypeDefaultLabel;
}

function minContractMonthText(value) {
  const selected = String(value || '').trim();
  if (!selected) {
    return minContractMonthNoneLabel;
  }
  const option = minContractMonthOptions.find((item) => String(item.value || '').trim() === selected);
  if (!option || !option.label) {
    throw new Error(`Missing contract month label for value: ${selected}`);
  }
  return String(option.label).trim();
}

function workModePreferenceLabel(values) {
  const selected = normalizeWorkModePreferences(values);
  if (!selected.length) {
    return workModePreferenceNoneLabel;
  }
  return selected.map((value) => workModePreferenceLabels[value] || value).join(' | ');
}

function sectorPreferenceLabel(value) {
  const values = Array.isArray(value)
    ? value
    : String(value || '').split(/[,\n|/]+/);
  const selected = [];
  const seen = new Set();
  for (const item of values) {
    const key = String(item || '').trim().toLowerCase();
    if (!key || seen.has(key)) continue;
    if (sectorPreferenceLabels[key]) {
      seen.add(key);
      selected.push(sectorPreferenceLabels[key]);
    }
  }
  return selected.length ? selected.join(' | ') : sectorPreferenceDefaultLabel || sectorPreferenceLabels[sectorPreferenceDefault] || '';
}

function preventFileNavigation(event) {
  event.preventDefault();
}

function moveReviewTitle(sourceList, sourceIndex, targetList) {
  const source = sourceList === 'primary' ? onboardingPage.reviewTargetTitles : onboardingPage.reviewSecondaryTitles;
  const target = targetList === 'primary' ? onboardingPage.reviewTargetTitles : onboardingPage.reviewSecondaryTitles;
  const item = source[sourceIndex];
  if (!item) return;
  const key = normalizeReviewTitleKey(item);
  const targetHas = target.some((value) => normalizeReviewTitleKey(value) === key);
  if (!targetHas) {
    target.push(item);
  }
  source.splice(sourceIndex, 1);
  const normalized = normalizeReviewTitleLists(onboardingPage.reviewTargetTitles, onboardingPage.reviewSecondaryTitles);
  onboardingPage.setReviewTargetTitles(normalized.primary);
  onboardingPage.setReviewSecondaryTitles(normalized.secondary);
  renderReviewStep();
}

function addReviewTitle(targetList, value) {
  const cleaned = normalizeReviewTitle(value);
  if (!cleaned) return;
  const key = normalizeReviewTitleKey(cleaned);
  const target = targetList === 'primary' ? onboardingPage.reviewTargetTitles : onboardingPage.reviewSecondaryTitles;
  const other = targetList === 'primary' ? onboardingPage.reviewSecondaryTitles : onboardingPage.reviewTargetTitles;
  const otherIndex = other.findIndex((item) => normalizeReviewTitleKey(item) === key);
  if (otherIndex >= 0) {
    other.splice(otherIndex, 1);
  }
  if (!target.some((item) => normalizeReviewTitleKey(item) === key)) {
    target.push(cleaned);
  }
  const normalized = normalizeReviewTitleLists(onboardingPage.reviewTargetTitles, onboardingPage.reviewSecondaryTitles);
  onboardingPage.setReviewTargetTitles(normalized.primary);
  onboardingPage.setReviewSecondaryTitles(normalized.secondary);
  renderReviewStep();
}

const CHIP_MOVE_ICON = '<svg viewBox="0 0 16 14" width="13" height="11" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M1 4h14M11 1l4 3-4 3"/><path d="M15 10H1M5 7l-4 3 4 3"/></svg>';

function renderReviewChipList(containerKey, values, emptyLabel, removeAttribute, moveAttribute, moveAriaPrefix) {
  const container = document.getElementById(containerKey);
  if (!container) return;
  if (!values.length) {
    container.innerHTML = `<span class="chip-empty">${emptyLabel}</span>`;
    return;
  }
  container.innerHTML = values.map((value, index) => `
    <span class="chip-item">
      <span>${escapeHtml(value)}</span>
      <button type="button" ${moveAttribute}="${index}" aria-label="${escapeHtml(formatLabel(moveAriaPrefix, { name: value }))}" title="${escapeHtml(formatLabel(moveAriaPrefix, { name: value }))}">${CHIP_MOVE_ICON}</button>
      <button type="button" ${removeAttribute}="${index}" aria-label="${escapeHtml(formatRemoveItemLabel(value))}">&#215;</button>
    </span>
  `).join('');
}

function formatCurrencySummaryValue(value) {
  const raw = String(value ?? '').trim();
  if (!raw) return onboardingFlowLabels.not_provided_label;
  const formatted = onboardingCurrencyUi.formatCurrencyValue?.(raw) || '0';
  return `$${formatted}`;
}

function updateCheckStep() {
  const searchPrefs = searchPreferencesPayload();
  flowRefs.checkTargetTitles.textContent = onboardingPage.reviewTargetTitles.length ? onboardingPage.reviewTargetTitles.join(' | ') : onboardingFlowLabels.not_provided_label;
  flowRefs.checkSecondaryTitles.textContent = onboardingPage.reviewSecondaryTitles.length ? onboardingPage.reviewSecondaryTitles.join(' | ') : onboardingFlowLabels.not_provided_label;
  flowRefs.checkCapabilities.textContent = onboardingPage.reviewCapabilityRules.length
    ? (onboardingPage.reviewCapabilityRules.length === 1
      ? onboardingFlowLabels.capability_rows_label_one
      : formatLabel(onboardingFlowLabels.capability_rows_label_many, { count: onboardingPage.reviewCapabilityRules.length }))
    : onboardingFlowLabels.capabilities_none_label;
  flowRefs.checkLocations.textContent = searchPrefs.locations.length
    ? searchPrefs.locations.map(locationLabel).join(' | ')
    : onboardingFlowLabels.not_provided_label;
  flowRefs.checkEngagementType.textContent = engagementTypeLabel(searchPrefs.engagement_type);
  flowRefs.checkMinContractMonths.textContent = minContractMonthText(searchPrefs.min_contract_months);
  flowRefs.checkWorkModePreference.textContent = workModePreferenceLabel(searchPrefs.work_mode_preference);
  flowRefs.checkSectorPreference.textContent = sectorPreferenceLabel(searchPrefs.prefer_sector);
  flowRefs.checkSalaryYearly.textContent = formatCurrencySummaryValue(searchPrefs.minimum_salary_yearly);
  flowRefs.checkSalaryDaily.textContent = formatCurrencySummaryValue(searchPrefs.minimum_daily_rate);
  if (flowRefs.confirmReview) {
    const canFinish = onboardingPage.reviewTargetTitles.length > 0 && onboardingPage.reviewCapabilityRules.length > 0;
    flowRefs.confirmReview.setAttribute('aria-disabled', canFinish ? 'false' : 'true');
  }
}

function removeReviewCapability(index) {
  onboardingPage.reviewCapabilityRules.splice(index, 1);
  onboardingPage.setSelectedReviewCapabilityIndexes(
    new Set(
      [...onboardingPage.selectedReviewCapabilityIndexes]
        .filter((value) => value !== index)
        .map((value) => (value > index ? value - 1 : value))
    )
  );
  onboardingPage.setReviewCapabilityVisibleCount(Math.max(onboardingPage.reviewCapabilityVisibleCount - 1, getReviewCapabilityPreviewCount()));
}

function removeReviewCapabilityAlias(index, aliasValue) {
  const rule = onboardingPage.reviewCapabilityRules[index];
  if (!rule) return;
  const cleanedAlias = normalizeReviewAlias(aliasValue);
  onboardingPage.reviewCapabilityRules[index] = normalizeReviewCapability({
    ...rule,
    aliases: (rule.aliases || []).filter((alias) => alias !== cleanedAlias),
  });
  renderReviewCapabilities();
  onboardingStorage.saveWizardState();
}

function applyReviewCapabilityAction(index, action) {
  if (!onboardingPage.reviewCapabilityRules[index]) return;
  if (action === 'remove') {
    removeReviewCapability(index);
  }
  renderReviewStep();
  onboardingStorage.saveWizardState();
}

function applyBulkReviewCapabilityAction(action) {
  const selectedIndexes = [...onboardingPage.selectedReviewCapabilityIndexes].sort((left, right) => right - left);
  if (!selectedIndexes.length) return;
  for (const index of selectedIndexes) {
    if (action !== 'remove') continue;
    removeReviewCapability(index);
  }
  if (action === 'remove') {
    onboardingPage.selectedReviewCapabilityIndexes.clear();
  }
  renderReviewStep();
  onboardingStorage.saveWizardState();
}

function selectVisibleReviewCapabilities() {
  const filterTerm = String(flowRefs.reviewCapabilityFilter?.value || '').trim().toLowerCase();
  const orderedRules = onboardingPage.reviewCapabilityRules
    .map((rule, index) => ({ rule, index }))
    .sort((left, right) => left.rule.name.localeCompare(right.rule.name))
    .filter((item) => !filterTerm || item.rule.name.toLowerCase().includes(filterTerm)
      || item.rule.aliases.some((alias) => (patternToLabel(alias) || alias).toLowerCase().includes(filterTerm)));
  const visibleRules = filterTerm ? orderedRules : orderedRules.slice(0, onboardingPage.reviewCapabilityVisibleCount);
  visibleRules.forEach(({ index }) => onboardingPage.selectedReviewCapabilityIndexes.add(index));
  renderReviewCapabilities();
}

function clearSelectedReviewCapabilities() {
  onboardingPage.selectedReviewCapabilityIndexes.clear();
  renderReviewCapabilities();
}

function toggleSelectedReviewCapability(index, checked) {
  if (checked) {
    onboardingPage.selectedReviewCapabilityIndexes.add(index);
  } else {
    onboardingPage.selectedReviewCapabilityIndexes.delete(index);
  }
  renderReviewCapabilities();
}

function renderReviewCapabilities() {
  const container = flowRefs.reviewCapabilityCards;
  if (!container) return;
  if (!onboardingPage.reviewCapabilityRules.length) {
    if (reviewCapabilityCountEl) {
      reviewCapabilityCountEl.textContent = onboardingFlowLabels.capabilities_none_label;
      reviewCapabilityCountEl.classList.remove('is-selected');
    }
    container.innerHTML = `<div class="chip-empty">${escapeHtml(capabilityLabels.onboarding_empty_text)}</div>`;
    return;
  }
  const filterTerm = String(flowRefs.reviewCapabilityFilter?.value || '').trim().toLowerCase();
  const orderedRules = onboardingPage.reviewCapabilityRules
    .map((rule, index) => ({ rule, index }))
    .sort((left, right) => left.rule.name.localeCompare(right.rule.name))
    .filter((item) => {
      if (!filterTerm) return true;
      return item.rule.name.toLowerCase().includes(filterTerm)
        || item.rule.aliases.some((alias) => (patternToLabel(alias) || alias).toLowerCase().includes(filterTerm));
    });
  const visibleRules = filterTerm ? orderedRules : orderedRules.slice(0, onboardingPage.reviewCapabilityVisibleCount);
  const hiddenCount = Math.max(orderedRules.length - visibleRules.length, 0);
  const previewCount = getReviewCapabilityPreviewCount();
  const isExpanded = !filterTerm && orderedRules.length > previewCount && onboardingPage.reviewCapabilityVisibleCount >= orderedRules.length;
  const selectedVisibleCount = visibleRules.filter(({ index }) => onboardingPage.selectedReviewCapabilityIndexes.has(index)).length;
  if (reviewCapabilityCountEl) {
    reviewCapabilityCountEl.textContent = filterTerm
      ? formatLabel(onboardingFlowLabels.capability_shown_of_label, { shown: visibleRules.length, total: orderedRules.length })
      : (onboardingPage.selectedReviewCapabilityIndexes.size
        ? formatLabel(onboardingFlowLabels.capability_count_with_selection_label, { total: orderedRules.length, selected: onboardingPage.selectedReviewCapabilityIndexes.size })
        : formatLabel(onboardingFlowLabels.capability_count_label, { total: orderedRules.length }));
    reviewCapabilityCountEl.classList.toggle('is-selected', onboardingPage.selectedReviewCapabilityIndexes.size > 0);
  }
  const rowsHtml = visibleRules.length ? visibleRules.map(({ rule, index }) => {
    const titleCaseName = rule.name.toLowerCase().split(' ').map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
    const displayName = titleCaseName || onboardingFlowLabels.capability_untitled_label;
    const { preview: previewAliases, remaining: remainingAliases } = splitCapabilityAliasesForDisplay(rule.aliases);
    const aliasPreviewHtml = previewAliases.length ? `
      <div class="capability-alias-preview" aria-label="${escapeHtml(capabilityLabels.related_skills_label)}">
        ${previewAliases.map((alias) =>
          `<span class="cap-alias-chip cap-alias-chip--preview" title="${escapeHtml(patternToLabel(alias) || alias)}">
            <span class="cap-alias-chip-label">${escapeHtml(patternToLabel(alias) || alias)}</span>
          </span>`
        ).join('')}
      </div>
    ` : '';
    const aliasHtml = (() => {
      if (!rule.aliases.length) return '';
      const aliasChips = remainingAliases.map((alias) =>
        `<span class="cap-alias-chip" title="${escapeHtml(patternToLabel(alias) || alias)}">
          <span class="cap-alias-chip-label">${escapeHtml(patternToLabel(alias) || alias)}</span>
          <button class="cap-alias-chip-remove" type="button" data-review-remove-capability-alias="${index}" data-review-capability-alias="${escapeHtml(alias)}" aria-label="${escapeHtml(capabilityLabels.remove_related_skill_aria_label)}" title="${escapeHtml(capabilityLabels.remove_related_skill_aria_label)}">&times;</button>
        </span>`
      ).join('');
      if (!remainingAliases.length) {
        return '';
      }
      return `
        <details class="capability-alias-drawer">
          <summary class="cap-alias-summary">
            <span class="capability-summary-label capability-summary-label--closed">${escapeHtml(formatLabel(capabilityLabels.related_skills_show_more, { count: remainingAliases.length }))}</span>
            <span class="capability-summary-label capability-summary-label--open">${escapeHtml(capabilityLabels.related_skills_show_less)}</span>
          </summary>
          <div class="cap-alias-chips" aria-label="${escapeHtml(capabilityLabels.related_skills_label)}">${aliasChips}</div>
        </details>
      `;
    })();
    const selectedClass = onboardingPage.selectedReviewCapabilityIndexes.has(index) ? ' is-selected' : '';
    return `
      <article class="capability-card${selectedClass}" data-review-capability-index="${index}">
        <div class="review-capability-main">
          <span class="review-capability-head">
            <span class="review-capability-title-row">
              ${capabilityIconHtml(rule.icon_key, displayName)}
              <strong class="review-capability-title">${escapeHtml(displayName)}</strong>
            </span>
          </span>
          ${aliasPreviewHtml}
          ${aliasHtml}
        </div>
        <div class="review-capability-actions" role="group" aria-label="${escapeHtml(formatLabel(onboardingFlowLabels.capability_actions_for_label, { name: displayName }))}">
          ${renderTrashActionButton({
            itemName: displayName,
            dataAttributes: {
              'data-review-capability-action': 'remove',
              'data-review-capability-index': index,
            },
          })}
        </div>
      </article>
    `;
    }).join('') : `<div class="chip-empty">${escapeHtml(capabilityLabels.onboarding_no_match_text)}</div>`;
  const bulkDisabled = onboardingPage.selectedReviewCapabilityIndexes.size ? '' : ' disabled';
  const footerHtml = (!filterTerm && orderedRules.length > previewCount) ? `
    <div class="review-capability-footer">
      <button class="btn-icon review-capability-footer-action review-capability-footer-action--text" type="button" data-review-toggle-capabilities="true" aria-label="${escapeHtml(isExpanded ? onboardingFlowLabels.capability_show_fewer_label : formatLabel(onboardingFlowLabels.capability_show_more_label, { count: hiddenCount }))}" title="${escapeHtml(isExpanded ? onboardingFlowLabels.capability_show_fewer_label : formatLabel(onboardingFlowLabels.capability_show_more_label, { count: hiddenCount }))}">
        <span class="review-capability-footer-label">${escapeHtml(isExpanded ? onboardingFlowLabels.capability_show_fewer_label : formatLabel(onboardingFlowLabels.capability_show_more_label, { count: hiddenCount }))}</span>
      </button>
    </div>
  ` : '';
  const toolbarHtml = onboardingPage.selectedReviewCapabilityIndexes.size ? `
    <div class="review-capability-toolbar">
      <div class="review-capability-toolbar-main">
        <span class="review-capability-toolbar-copy">${escapeHtml(formatLabel(onboardingFlowLabels.capability_selected_copy, { count: selectedVisibleCount }))}</span>
        <div class="review-capability-bulk-actions">
          <button class="jh-button jh-button--secondary jh-button--compact" type="button" data-review-select-visible="true">${escapeHtml(onboardingFlowLabels.capability_select_shown_label)}</button>
          <button class="jh-button jh-button--secondary jh-button--compact" type="button" data-review-clear-selection="true"${bulkDisabled}>${escapeHtml(onboardingFlowLabels.capability_clear_selection_label)}</button>
          <button class="jh-button jh-button--danger jh-button--compact" type="button" data-review-bulk-action="remove"${bulkDisabled}>${escapeHtml(onboardingFlowLabels.capability_remove_selected_label)}</button>
        </div>
      </div>
    </div>
  ` : '';
  container.innerHTML = `
    <div class="review-capability-group">
      <div class="review-capability-row-list">${rowsHtml}</div>
      ${footerHtml}
      ${toolbarHtml}
    </div>
  `;
}

function renderReviewStep() {
  if (typeof hideStatus === 'function') {
    hideStatus();
  }
  onboardingPage.setSelectedReviewCapabilityIndexes(
    new Set([...onboardingPage.selectedReviewCapabilityIndexes].filter((index) => index >= 0 && index < onboardingPage.reviewCapabilityRules.length))
  );
  renderReviewChipList(
    'review_target_titles_list',
    onboardingPage.reviewTargetTitles,
    onboardingFlowTitleTierLabels.target_roles_empty_text,
    'data-remove-review-target',
    'data-move-review-target',
    onboardingFlowTitleTierLabels.move_to_also_consider_label,
  );
  renderReviewChipList(
    'review_secondary_titles_list',
    onboardingPage.reviewSecondaryTitles,
    onboardingFlowTitleTierLabels.also_consider_roles_empty_text,
    'data-remove-review-secondary',
    'data-move-review-secondary',
    onboardingFlowTitleTierLabels.move_to_target_roles_label,
  );
  renderReviewCapabilities();
  onboardingStorage.saveWizardState();
}

function getSearchBasicsHydrationProfile() {
  const importedSuggestions = onboardingPage.lastImportPayload?.role_suggestions || {};
  const reviewTitles = onboardingPage.reviewTargetTitles.length
    ? onboardingPage.reviewTargetTitles
    : (Array.isArray(importedSuggestions.target_roles)
      ? importedSuggestions.target_roles
      : []);
  return {
    ...(onboardingPage.lastLoadedProfile || {}),
    ...((onboardingPage.lastImportPayload || {}).profile || {}),
    target_roles: reviewTitles,
  };
}

function hydrateDraftStep(profile, roleSuggestions = {}) {
  const reviewSource = {
    ...(profile || {}),
    ...(roleSuggestions || {}),
  };
  const normalizedTitles = normalizeReviewTitleLists(
    reviewSource.target_roles || [],
    reviewSource.also_consider_roles || [],
  );
  onboardingPage.setReviewTargetTitles(normalizedTitles.primary);
  onboardingPage.setReviewSecondaryTitles(normalizedTitles.secondary);
  onboardingPage.setReviewCapabilityRules((profile?.candidate_capabilities || []).map(normalizeReviewCapability).filter((rule) => rule.name));
  onboardingPage.selectedReviewCapabilityIndexes.clear();
  onboardingPage.setReviewCapabilityVisibleCount(getReviewCapabilityPreviewCount());
  renderReviewStep();
}

function buildCompletionRedirectState(payload, searchPrefs) {
  const profile = payload?.profile || {};
  const targets = Array.isArray(profile.target_roles)
    ? profile.target_roles.slice(0, 4).map((value) => String(value || '').trim()).filter(Boolean)
    : [];
  const locations = Array.isArray(searchPrefs?.locations)
    ? searchPrefs.locations.map((value) => locationLabel(value)).filter(Boolean)
    : [];
  return {
    kind: isRebuildMode ? 'profile-refresh' : 'onboarding-complete',
    title: isRebuildMode ? 'Profile refreshed' : 'Profile built',
    message: payload?.message || (isRebuildMode ? 'Your profile was refreshed from the uploaded CV.' : 'Your profile was built from the uploaded CV.'),
    target_titles: targets,
    search_locations: locations,
    min_contract_months: searchPrefs?.min_contract_months ?? null,
    created_at: new Date().toISOString(),
  };
}

function storeCompletionRedirectState(payload, searchPrefs) {
  try {
    const redirectState = buildCompletionRedirectState(payload, searchPrefs);
    window.localStorage.setItem(ONBOARDING_WELCOME_KEY, JSON.stringify(redirectState));
  } catch (error) {
    console.warn('Could not store onboarding redirect state.', error);
  }
}

function formatExtractionSummary(counts) {
  const primary = Number(counts.target_titles || 0);
  const secondary = Number(counts.secondary_titles || 0);
  const capabilities = Number(counts.capabilities || 0);
  const formatCount = (count, singular, plural) => `${count} ${count === 1 ? singular : plural}`;
  const parts = [];
  if (primary > 0) {
    parts.push(formatCount(primary, onboardingImportSummaryLabels.target_roles_singular, onboardingImportSummaryLabels.target_roles_plural));
  }
  if (secondary > 0) {
    parts.push(formatCount(secondary, onboardingImportSummaryLabels.secondary_roles_singular, onboardingImportSummaryLabels.secondary_roles_plural));
  }
  if (capabilities > 0) {
    parts.push(formatCount(capabilities, onboardingImportSummaryLabels.capabilities_singular, onboardingImportSummaryLabels.capabilities_plural));
  }
  if (!parts.length) {
    return '';
  }
  const joined = parts.length === 1
    ? parts[0]
    : `${parts.slice(0, -1).join(', ')}, and ${parts[parts.length - 1]}`;
  return `${onboardingImportSummaryLabels.lead_in} ${joined} ${onboardingImportSummaryLabels.source_suffix}`;
}

function formatImportSuccessSummary() {
  return onboardingFlowLabels.create_profile_ready_message;
}

async function createProfile() {
  const primary = flowRefs.primaryCvInput.files[0];
  const onboardingSettings = onboardingSettingsPayload();

  onboardingUpload.validatePrimaryFile(primary);
  validateOnboardingSettings(onboardingSettings);

  if (isRebuildMode) {
    const confirmed = window.confirm([
      onboardingFlowLabels.refresh_profile_confirm_title,
      onboardingFlowLabels.refresh_profile_confirm_body_1,
      onboardingFlowLabels.refresh_profile_confirm_body_2,
    ].filter(Boolean).join('\n\n'));
    if (!confirmed) return;
  }

  const files = [await onboardingUpload.fileToPayload(primary, 'Primary CV')];
  const response = await jobHunterFetch('/api/onboarding/import', {
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
    throw new Error(payload.error || onboardingFlowLabels.create_profile_error);
  }

  onboardingPage.setLastImportPayload(payload);
  onboardingPage.setMaxUnlockedStep(Math.max(onboardingPage.maxUnlockedStep, REVIEW_STEP));
  onboardingPage.setDraftBuiltExplicitly(true);
  hydrateDraftStep(payload.profile || {}, payload.role_suggestions || {});
  setStep(REVIEW_STEP);
  const pageLimitNotice = String(payload?.page_limit_notice || '').trim();
  const extractionMessage = formatImportSuccessSummary(payload);
  if (extractionMessage) {
    showStatus(extractionMessage, 'success');
  }
  if (extractionMessage) {
    console.info('[ONBOARDING] Draft profile extraction summary:', pageLimitNotice ? `${extractionMessage} ${pageLimitNotice}` : extractionMessage);
  }
  showExtractionPreview(payload);
}

function showExtractionPreview(payload) {
  const banner = document.getElementById('extraction_preview_banner');
  const summaryEl = document.getElementById('extraction_preview_summary');
  const noteEl = document.getElementById('extraction_preview_note');
  if (!banner || !summaryEl || !noteEl) return;
  const counts = payload?.extraction_counts || {};
  const summaryText = formatExtractionSummary(counts);
  summaryEl.textContent = summaryText || '';
  const notice = String(payload?.page_limit_notice || '').trim();
  noteEl.textContent = notice;
  noteEl.hidden = !notice;
  banner.hidden = false;
}

function continueFromReview() {
  if (!onboardingPage.reviewTargetTitles.length) {
    throw new Error(onboardingFlowTitleTierLabels.keep_target_roles_continue_error);
  }
  const alreadyVisitedSearch = onboardingPage.maxUnlockedStep >= SEARCH_STEP;
  onboardingPage.setMaxUnlockedStep(Math.max(onboardingPage.maxUnlockedStep, SEARCH_STEP));
  renderReviewStep();
  if (!alreadyVisitedSearch) {
    hydrateSearchBasics(getSearchBasicsHydrationProfile());
  }
  setStep(SEARCH_STEP);
}

async function continueFromSearchBasics() {
  if (typeof flushSearchBasicsPersistence === 'function') {
    await onboardingStorage.flushSearchBasicsPersistence().catch((error) => {
      console.warn(onboardingFlowLabels.continue_search_basics_error, error);
    });
  }
  const searchPrefs = searchPreferencesPayload();
  validateSearchPreferences(searchPrefs);
  onboardingPage.setMaxUnlockedStep(Math.max(onboardingPage.maxUnlockedStep, CHECK_STEP));
  updateCheckStep();
  setStep(CHECK_STEP);
}

async function finishSetup() {
  const searchPrefs = searchPreferencesPayload();
  validateSearchPreferences(searchPrefs);
  if (!onboardingPage.reviewTargetTitles.length) {
    throw new Error(onboardingFlowTitleTierLabels.keep_target_roles_finish_error);
  }
  if (!onboardingPage.reviewCapabilityRules.length) {
    throw new Error(onboardingFlowLabels.finish_setup_incomplete_error);
  }

  const response = await jobHunterFetch('/api/onboarding/confirm-profile-signals', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_locations: searchPrefs.locations,
        min_contract_months: searchPrefs.min_contract_months,
       engagement_type: searchPrefs.engagement_type,
        work_mode_preference: searchPrefs.work_mode_preference,
        prefer_sector: searchPrefs.prefer_sector,
        minimum_salary_yearly: searchPrefs.minimum_salary_yearly,
        minimum_daily_rate: searchPrefs.minimum_daily_rate,
      target_roles: onboardingPage.reviewTargetTitles,
      also_consider_roles: onboardingPage.reviewSecondaryTitles,
      candidate_capabilities: onboardingPage.reviewCapabilityRules.map(normalizeReviewCapability).filter((rule) => rule.name),
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || onboardingFlowLabels.finish_setup_error);
  }

  const finalSearchPrefs = {
    ...(onboardingPage.lastImportPayload?.profile?.search_settings || {}),
    locations: searchPrefs.locations,
    min_contract_months: searchPrefs.min_contract_months,
    engagement_type: searchPrefs.engagement_type,
    prefer_sector: searchPrefs.prefer_sector,
  };
  storeCompletionRedirectState(payload, finalSearchPrefs);
  setTimeout(() => {
    window.location.href = '/';
  }, 700);
}

async function loadProfileDefaults() {
  const response = await jobHunterFetch('/api/profile');
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || onboardingFlowLabels.load_profile_error);
  }
  const profile = payload || {};
  console.debug('[ONBOARDING] profile loaded:', { has_onboarding_settings: !!profile.onboarding_settings, has_search_settings: !!profile.search_settings, has_match_preferences: !!profile.match_preferences, has_salary_preferences: !!profile.salary_preferences });
  applyProfileDefaults(profile);
  setLastLoadedProfile(profile);
  if (onboardingPage.currentStep >= REVIEW_STEP && (onboardingPage.reviewTargetTitles.length || onboardingPage.reviewSecondaryTitles.length)) {
    renderReviewStep();
  }
  return profile;
}

async function loadProfileStatus() {
  const response = await jobHunterFetch('/api/profile/status');
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || onboardingFlowLabels.profile_status_error);
  }
  if (
    typeof payload.has_profile !== 'boolean'
    || typeof payload.has_candidate_capabilities !== 'boolean'
    || typeof payload.candidate_capability_count !== 'number'
    || typeof payload.profile_ready_for_review !== 'boolean'
    || (payload.profile_ready_for_review === false && typeof payload.blocking_reason !== 'string')
  ) {
    throw new Error(onboardingFlowLabels.profile_status_error);
  }
  return payload;
}

async function loadProfileDefaultsIfPresent(hasProfile) {
  if (!hasProfile) {
    return null;
  }
  return loadProfileDefaults();
}

async function loadProfileDefaultsForInit(hasProfile) {
  try {
    return await loadProfileDefaultsIfPresent(hasProfile);
  } catch (error) {
    console.error('[ONBOARDING] loadProfileDefaults failed:', error);
    showStatus(error.message, 'error');
    throw error;
  }
}

createProfileButton.addEventListener('click', async (event) => {
  const btn = event.currentTarget;
  const originalLabel = btn.textContent;
  btn.classList.add('is-working');
  btn.disabled = true;
  btn.textContent = isRebuildMode ? onboardingFlowLabels.create_profile_button_refreshing : onboardingFlowLabels.create_profile_button_building;
  startWorkingStatus([
    onboardingFlowLabels.create_profile_status_started,
    Number.isFinite(onboardingCvPageLimit) && onboardingCvPageLimit > 0
      ? formatLabel(onboardingFlowLabels.create_profile_status_reading_pages, { count: onboardingCvPageLimit })
      : (isRebuildMode ? onboardingFlowLabels.reading_updated_cv_label : onboardingFlowLabels.reading_cv_label),
    onboardingFlowLabels.create_profile_status_extracting,
    onboardingFlowLabels.create_profile_status_reviewing,
    onboardingFlowLabels.create_profile_status_building,
  ]);
  try {
    await createProfile();
  } catch (error) {
    console.error('[ONBOARDING] createProfile failed:', error);
    showStatus(error.message, 'error');
  } finally {
    btn.classList.remove('is-working');
    onboardingUpload.updateCreateProfileAvailability();
    btn.textContent = originalLabel;
  }
});

flowRefs.continueToSearchBasics.addEventListener('click', () => {
  try {
    continueFromReview();
  } catch (error) {
    showStatus(error.message, 'error');
  }
});

flowRefs.continueToCheck.addEventListener('click', () => {
  continueFromSearchBasics().catch((error) => {
    showStatus(error.message, 'error');
  });
});

flowRefs.confirmReview.addEventListener('click', async (event) => {
  const btn = event.currentTarget;
  const originalLabel = btn.textContent;
  btn.classList.add('is-working');
  btn.disabled = true;
  btn.textContent = isRebuildMode ? onboardingFlowLabels.finish_review_button_saving : onboardingFlowLabels.finish_review_button_finishing;
  startWorkingStatus([
    onboardingFlowLabels.finish_review_status_saving,
    onboardingFlowLabels.finish_review_status_applying,
    onboardingFlowLabels.finish_review_status_finalising,
  ]);
  try {
    await finishSetup();
  } catch (error) {
    console.error('[ONBOARDING] finishSetup failed:', error);
    showStatus(error.message, 'error');
  } finally {
    btn.classList.remove('is-working');
    btn.disabled = false;
    btn.textContent = originalLabel;
  }
});

flowRefs.backToUploadFooter.addEventListener('click', () => setStep(1));
flowRefs.backToReviewFooter.addEventListener('click', () => setStep(REVIEW_STEP));
flowRefs.backToSearchBasicsFooter.addEventListener('click', () => setStep(SEARCH_STEP));
flowRefs.editDraftProfile.addEventListener('click', () => setStep(REVIEW_STEP));
flowRefs.editSearchBasics.addEventListener('click', () => setStep(SEARCH_STEP));
stepNavButtons.forEach((button) => {
  button.addEventListener('click', () => {
    if (button.disabled) return;
    const targetStep = Number(button.dataset.stepNav || 0);
    if (!targetStep || targetStep === onboardingPage.currentStep) return;
    setStep(targetStep);
  });
});
flowRefs.wizardProgressSteps?.addEventListener('click', (event) => {
  const trigger = event.target.closest('[data-step-nav]');
  if (!trigger || trigger.disabled) return;
  const targetStep = Number(trigger.dataset.stepNav || 0);
  if (!targetStep || targetStep === onboardingPage.currentStep) return;
  setStep(targetStep);
});

flowRefs.reviewAddTargetTitle.addEventListener('click', () => {
  const input = flowRefs.reviewTargetTitlesInput;
  addReviewTitle('primary', input.value);
  input.value = '';
});

flowRefs.reviewAddSecondaryTitle.addEventListener('click', () => {
  const input = flowRefs.reviewSecondaryTitlesInput;
  addReviewTitle('secondary', input.value);
  input.value = '';
});

flowRefs.reviewCapabilityFilter.addEventListener('input', () => {
  hideStatus();
  renderReviewCapabilities();
  onboardingStorage.saveWizardState();
});

flowRefs.reviewStepRoot.addEventListener('click', (event) => {
  const removeTarget = event.target.closest('[data-remove-review-target]');
  if (removeTarget) {
    onboardingPage.reviewTargetTitles.splice(Number(removeTarget.dataset.removeReviewTarget), 1);
    renderReviewStep();
    return;
  }
  const moveTarget = event.target.closest('[data-move-review-target]');
  if (moveTarget) {
    moveReviewTitle('primary', Number(moveTarget.dataset.moveReviewTarget), 'secondary');
    return;
  }
  const removeSecondary = event.target.closest('[data-remove-review-secondary]');
  if (removeSecondary) {
    onboardingPage.reviewSecondaryTitles.splice(Number(removeSecondary.dataset.removeReviewSecondary), 1);
    renderReviewStep();
    return;
  }
  const moveSecondary = event.target.closest('[data-move-review-secondary]');
  if (moveSecondary) {
    moveReviewTitle('secondary', Number(moveSecondary.dataset.moveReviewSecondary), 'primary');
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
  const aliasRemove = event.target.closest('[data-review-remove-capability-alias]');
  if (aliasRemove) {
    const aliasRow = aliasRemove.closest('[data-review-capability-index]');
    if (aliasRow) {
      removeReviewCapabilityAlias(
        Number(aliasRow.dataset.reviewCapabilityIndex),
        aliasRemove.dataset.reviewCapabilityAlias,
      );
    }
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
  if (event.target.closest('[data-review-toggle-capabilities]')) {
    const previewCount = getReviewCapabilityPreviewCount();
    onboardingPage.setReviewCapabilityVisibleCount(
      onboardingPage.reviewCapabilityVisibleCount >= onboardingPage.reviewCapabilityRules.length
        ? previewCount
        : onboardingPage.reviewCapabilityRules.length
    );
    renderReviewCapabilities();
    onboardingStorage.saveWizardState();
    return;
  }
    const capabilityRow = event.target.closest('[data-review-capability-index]');
    if (
      capabilityRow
      && !event.target.closest('.capability-alias-drawer')
      && !event.target.closest('button')
    ) {
    const index = Number(capabilityRow.dataset.reviewCapabilityIndex);
    const nextChecked = !onboardingPage.selectedReviewCapabilityIndexes.has(index);
    toggleSelectedReviewCapability(index, nextChecked);
  }
});

[
  flowRefs.reviewMinimumSalaryYearly,
  flowRefs.reviewMinimumDailyRate,
  ...document.querySelectorAll('input[name="engagement_type"]'),
].filter(Boolean).forEach((input) => {
  input.addEventListener('input', () => {
    hideStatus();
    onboardingStorage.saveWizardState();
    if (typeof scheduleSearchBasicsPersistence === 'function') {
      onboardingStorage.scheduleSearchBasicsPersistence();
    }
  });
  input.addEventListener('change', () => {
    hideStatus();
    onboardingStorage.saveWizardState();
    if (typeof scheduleSearchBasicsPersistence === 'function') {
      onboardingStorage.scheduleSearchBasicsPersistence();
    }
  });
});

document.querySelectorAll('input[name="engagement_type"]').forEach((input) => {
  input.addEventListener('change', () => {
    if (!input.checked) {
      const anyChecked = document.querySelectorAll('input[name="engagement_type"]:checked').length > 0;
      if (!anyChecked) input.checked = true;
    }
    hideStatus();
    updateCompensationVisibility();
  });
});

flowRefs.reviewStepRoot.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && event.target.id === 'review_target_titles_input') {
    event.preventDefault();
    flowRefs.reviewAddTargetTitle.click();
  }
  if (event.key === 'Enter' && event.target.id === 'review_secondary_titles_input') {
    event.preventDefault();
    flowRefs.reviewAddSecondaryTitle.click();
  }
});

[
  flowRefs.reviewMinimumSalaryYearly,
  flowRefs.reviewMinimumDailyRate,
].filter(Boolean).forEach((input) => {
  onboardingCurrencyUi.bindCurrencyInput?.(input);
});
flowRefs.locationSearch?.addEventListener('change', (event) => {
  if (!event.target.matches('input[type="checkbox"][data-location-value]')) return;
  hideStatus();
  onboardingPage.syncSelectedLocationsFromSelect();
  onboardingStorage.saveWizardState();
  if (typeof scheduleSearchBasicsPersistence === 'function') {
    onboardingStorage.scheduleSearchBasicsPersistence();
  }
});

document.querySelectorAll('input[name="prefer_sector"]').forEach((input) => {
  input.addEventListener('change', () => {
    hideStatus();
    onboardingStorage.saveWizardState();
    if (typeof scheduleSearchBasicsPersistence === 'function') {
      onboardingStorage.scheduleSearchBasicsPersistence();
    }
  });
});
document.querySelectorAll('input[name="work_mode_preference"]').forEach((cb) => {
  cb.addEventListener('change', () => {
    if (!cb.checked) {
      const anyChecked = document.querySelectorAll('input[name="work_mode_preference"]:checked').length > 0;
      if (!anyChecked) cb.checked = true;
    }
    hideStatus();
  });
});
const onboardingResumeStep = Number(window.__JOB_HUNTER_ONBOARDING_RESUME_STEP__ || 1);

async function initWizard() {
  const urlParams = new URLSearchParams(window.location.search);
  let profileStatus;
  try {
    profileStatus = await loadProfileStatus();
  } catch (error) {
    showStatus(error.message, 'error');
    return;
  }
  const hasProfile = profileStatus.has_profile;
  if (urlParams.has('fresh')) {
    clearOnboardingBrowserState();
    history.replaceState(null, '', window.location.pathname);
    if (flowRefs.reviewMinimumSalaryYearly) flowRefs.reviewMinimumSalaryYearly.value = '';
    if (flowRefs.reviewMinimumDailyRate) flowRefs.reviewMinimumDailyRate.value = '';
    await loadProfileDefaultsForInit(hasProfile);
    setStep(1, { scroll: false, persist: false });
  } else {
    const restoredStep = onboardingStorage.restoreWizardState();
    if (restoredStep) {
      const stepToRestore = Math.max(1, Math.min(STEP_COUNT, restoredStep));
      const needsDraftFallback = stepToRestore >= REVIEW_STEP && !onboardingPage.hasDraftProfileState();
      const needsSearchFallback = stepToRestore >= SEARCH_STEP && !onboardingPage.hasSearchBasicsState();
      const loadedProfile = (needsDraftFallback || needsSearchFallback)
        ? await loadProfileDefaultsForInit(hasProfile)
        : null;
      if (loadedProfile) {
        if (needsDraftFallback) {
          hydrateDraftStep(loadedProfile);
        }
        if (needsSearchFallback) {
          hydrateSearchBasics(loadedProfile);
        }
      }
      setStep(stepToRestore, { scroll: false, persist: false });
      if (stepToRestore >= REVIEW_STEP) {
        renderReviewStep();
      }
      if (stepToRestore >= CHECK_STEP) {
        updateCheckStep();
      }
    } else if (onboardingResumeStep > 1) {
      setStep(1, { scroll: false, persist: false });
      const resumeProfile = await loadProfileDefaultsForInit(hasProfile);
      if (resumeProfile) {
        hydrateDraftStep(resumeProfile);
        hydrateSearchBasics(resumeProfile);
      }
      if (hasDraftProfileState()) {
        onboardingPage.setMaxUnlockedStep(Math.max(onboardingPage.maxUnlockedStep, onboardingResumeStep));
        setStep(onboardingResumeStep, { scroll: false, persist: false });
      }
    } else {
      setStep(1, { scroll: false, persist: false });
      await loadProfileDefaultsForInit(hasProfile);
    }
  }
  refreshStepNavigation();
  onboardingUpload.updatePrimaryCvStatus(primaryCvInput?.files?.[0] || onboardingPage.preservedPrimaryCvFile || null);
  onboardingUpload.updateCreateProfileAvailability();
  updateCompensationVisibility();
}

initWizard().catch((error) => { console.error('[ONBOARDING] initWizard failed:', error); });

if (primaryCvDropZone && primaryCvInput) {
  resetPrimaryCvDropZoneAppearance();
  document.addEventListener('dragover', preventFileNavigation, true);
  document.addEventListener('drop', preventFileNavigation, true);
  primaryCvDropZone.addEventListener('click', () => primaryCvInput.click());
  primaryCvDropZone.addEventListener('dragenter', (event) => {
    event.preventDefault();
    primaryCvDropZone.classList.add('is-dragover');
  });
  primaryCvDropZone.addEventListener('dragover', (event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
    primaryCvDropZone.classList.add('is-dragover');
  });
  primaryCvDropZone.addEventListener('dragleave', (event) => {
    if (event.target === primaryCvDropZone) {
      resetPrimaryCvDropZoneAppearance();
    }
  });
  primaryCvDropZone.addEventListener('drop', onboardingUpload.handlePrimaryCvDrop);
  primaryCvInput.addEventListener('change', () => {
    const selectedFile = primaryCvInput.files?.[0] || null;
    if (!selectedFile) {
      if (onboardingPage.preservedPrimaryCvFile) {
        onboardingUpload.restorePrimaryCvSelection(onboardingPage.preservedPrimaryCvFile);
        onboardingUpload.updatePrimaryCvStatus(onboardingPage.preservedPrimaryCvFile);
      } else {
        onboardingUpload.updatePrimaryCvStatus(null);
      }
      onboardingUpload.updateCreateProfileAvailability();
      return;
    }
    onboardingUpload.assignPrimaryCvFile(selectedFile);
  });
}
