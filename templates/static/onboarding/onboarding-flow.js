const { escapeHtml, normalizeReviewText, patternToLabel, normalizeWorkModePreferences, getWorkModePreferenceValues, setWorkModePreferenceValues, setEngagementTypeValues, setCurrencyFieldValue, readCurrencyFieldValue } = window.JobHunterSettingsUtils;

const onboardingFlowCurrencyUi = window.JobHunterCurrencyUi || {};
const onboardingDefaults = window.__JOB_HUNTER_ONBOARDING_DEFAULTS__ || {};
const onboardingCvPageLimit = Number(onboardingDefaults.cv_max_pages || 0);

function normalizeReviewTitle(value) {
  return patternToLabel(value) || normalizeReviewText(value);
}

function normalizeReviewTitleKey(value) {
  return normalizeReviewTitle(value).toLowerCase();
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
    const key = normalizeReviewTitleKey(cleaned);
    if (!cleaned || seen.has(key)) continue;
    seen.add(key);
    output.push(cleaned);
  }
  return output;
}

function normalizeReviewTitleLists(primaryValues, secondaryValues) {
  const primary = dedupeReviewList(primaryValues);
  const primarySeen = new Set(primary.map(normalizeReviewTitleKey));
  const secondary = [];
  const seenSecondary = new Set();
  for (const value of dedupeReviewList(secondaryValues)) {
    const key = normalizeReviewTitleKey(value);
    if (!key || primarySeen.has(key) || seenSecondary.has(key)) continue;
    seenSecondary.add(key);
    secondary.push(value);
  }
  return { primary, secondary };
}

const flowRefs = Object.freeze({
  reviewStepRoot: document.querySelector('[data-step="2"]'),
  wizardProgressSteps: document.querySelector('.wizard-progress-steps'),
  checkTargetTitles: document.getElementById('check_target_titles'),
  checkSecondaryTitles: document.getElementById('check_secondary_titles'),
  checkCapabilities: document.getElementById('check_capabilities'),
  checkSearchTitle: document.getElementById('check_search_title'),
  checkLocations: document.getElementById('check_locations'),
  checkEngagementType: document.getElementById('check_engagement_type'),
  checkWorkModePreference: document.getElementById('check_work_mode_preference'),
  checkGovernmentPreference: document.getElementById('check_government_preference'),
  checkSalaryYearly: document.getElementById('check_salary_yearly'),
  checkSalaryDaily: document.getElementById('check_salary_daily'),
  locationSearch: document.getElementById('location_search'),
  reviewSearchKeywords: document.getElementById('review_search_keywords'),
  reviewMinimumSalaryYearly: document.getElementById('review_minimum_salary_yearly'),
  reviewMinimumDailyRate: document.getElementById('review_minimum_daily_rate'),
  governmentPreference: document.getElementById('government_preference'),
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
const governmentPreferenceOptions = Array.isArray(window.__JOB_HUNTER_GOVERNMENT_PREFERENCE_OPTIONS__)
  ? window.__JOB_HUNTER_GOVERNMENT_PREFERENCE_OPTIONS__
  : [];
const governmentPreferenceDefault = String(
  window.__JOB_HUNTER_GOVERNMENT_PREFERENCE_DEFAULT__
  || governmentPreferenceOptions?.[0]?.value
  || 'any'
).trim().toLowerCase();
const governmentPreferenceDefaultLabel = String(
  window.__JOB_HUNTER_GOVERNMENT_PREFERENCE_DEFAULT_LABEL__
  || ''
).trim();
const governmentPreferenceLabels = Object.fromEntries(
  governmentPreferenceOptions
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

function workModePreferenceLabel(values) {
  const selected = normalizeWorkModePreferences(values);
  if (!selected.length) {
    return workModePreferenceNoneLabel;
  }
  return selected.map((value) => workModePreferenceLabels[value] || value).join(', ');
}

function governmentPreferenceLabel(value) {
  const key = String(value || '').trim().toLowerCase();
  return governmentPreferenceLabels[key] || governmentPreferenceDefaultLabel || governmentPreferenceLabels[governmentPreferenceDefault] || '';
}

function preventFileNavigation(event) {
  event.preventDefault();
}

function moveReviewTitle(sourceList, sourceIndex, targetList) {
  const source = sourceList === 'primary' ? reviewTargetTitles : reviewSecondaryTitles;
  const target = targetList === 'primary' ? reviewTargetTitles : reviewSecondaryTitles;
  const item = source[sourceIndex];
  if (!item) return;
  const key = normalizeReviewTitleKey(item);
  const targetHas = target.some((value) => normalizeReviewTitleKey(value) === key);
  if (!targetHas) {
    target.push(item);
  }
  source.splice(sourceIndex, 1);
  const normalized = normalizeReviewTitleLists(reviewTargetTitles, reviewSecondaryTitles);
  reviewTargetTitles = normalized.primary;
  reviewSecondaryTitles = normalized.secondary;
  renderReviewStep();
}

function addReviewTitle(targetList, value) {
  const cleaned = normalizeReviewTitle(value);
  if (!cleaned) return;
  const key = normalizeReviewTitleKey(cleaned);
  const target = targetList === 'primary' ? reviewTargetTitles : reviewSecondaryTitles;
  const other = targetList === 'primary' ? reviewSecondaryTitles : reviewTargetTitles;
  const otherIndex = other.findIndex((item) => normalizeReviewTitleKey(item) === key);
  if (otherIndex >= 0) {
    other.splice(otherIndex, 1);
  }
  if (!target.some((item) => normalizeReviewTitleKey(item) === key)) {
    target.push(cleaned);
  }
  const normalized = normalizeReviewTitleLists(reviewTargetTitles, reviewSecondaryTitles);
  reviewTargetTitles = normalized.primary;
  reviewSecondaryTitles = normalized.secondary;
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
      <button type="button" ${moveAttribute}="${index}" aria-label="${escapeHtml(moveAriaPrefix)} ${escapeHtml(value)}" title="${escapeHtml(moveAriaPrefix)}">${CHIP_MOVE_ICON}</button>
      <button type="button" ${removeAttribute}="${index}" aria-label="Remove ${escapeHtml(value)}">&#215;</button>
    </span>
  `).join('');
}

function formatCurrencySummaryValue(value) {
  const raw = String(value ?? '').trim();
  if (!raw) return 'Not provided';
  const formatted = onboardingFlowCurrencyUi.formatCurrencyValue?.(raw) || '0';
  return `$${formatted}`;
}

function updateCheckStep() {
  const searchPrefs = searchPreferencesPayload();
  flowRefs.checkTargetTitles.textContent = reviewTargetTitles.length ? reviewTargetTitles.join(' | ') : 'Not provided';
  flowRefs.checkSecondaryTitles.textContent = reviewSecondaryTitles.length ? reviewSecondaryTitles.join(' | ') : 'Not provided';
  flowRefs.checkCapabilities.textContent = reviewCapabilityRules.length
    ? `${reviewCapabilityRules.length} capability row${reviewCapabilityRules.length === 1 ? '' : 's'}`
    : 'None';
  flowRefs.checkSearchTitle.textContent = searchPrefs.keywords || 'Not provided';
  flowRefs.checkLocations.textContent = searchPrefs.locations.length ? searchPrefs.locations.join(' | ') : 'Not provided';
  flowRefs.checkEngagementType.textContent = engagementTypeLabel(searchPrefs.engagement_type);
  flowRefs.checkWorkModePreference.textContent = workModePreferenceLabel(searchPrefs.work_mode_preference);
  flowRefs.checkGovernmentPreference.textContent = governmentPreferenceLabel(searchPrefs.prefer_government);
  flowRefs.checkSalaryYearly.textContent = formatCurrencySummaryValue(searchPrefs.minimum_salary_yearly);
  flowRefs.checkSalaryDaily.textContent = formatCurrencySummaryValue(searchPrefs.minimum_daily_rate);
}

function setSelectedLocations(locations) {
  const select = flowRefs.locationSearch;
  const value = String(Array.isArray(locations) && locations.length ? locations[0] : '').trim();
  const current = String(select?.value || selectedLocations[0] || '').trim();
  const next = value || current;
  selectedLocations = next ? [next] : [];
  if (select) select.value = next;
  renderSelectedLocation();
}

function defaultSearchKeywordsFromReviewedTitles(profile) {
  const reviewedTitles = Array.isArray(reviewTargetTitles) ? reviewTargetTitles : [];
  const profileTitles = Array.isArray(profile?.primary_job_title_pattern) ? profile.primary_job_title_pattern : [];
  return dedupeReviewList([...reviewedTitles, ...profileTitles]).join(', ');
}

function hydrateSearchBasics(profile) {
  const searchSettings = profile?.search_settings || {};
  const matchPreferences = profile?.match_preferences || {};
  const salaryPreferences = profile?.salary_preferences || {};
  const currentKeywords = String(flowRefs.reviewSearchKeywords.value || '').trim();
  const savedKeywords = String(searchSettings.keywords || '').trim();
  flowRefs.reviewSearchKeywords.value = currentKeywords || savedKeywords || defaultSearchKeywordsFromReviewedTitles(profile);
  const currentSalaryYearly = String(flowRefs.reviewMinimumSalaryYearly.value || '').trim();
  const currentSalaryDaily = String(flowRefs.reviewMinimumDailyRate.value || '').trim();
  if (!currentSalaryYearly) {
    setCurrencyFieldValue(flowRefs.reviewMinimumSalaryYearly, salaryPreferences.minimum_salary_yearly ?? 0);
  }
  if (!currentSalaryDaily) {
    setCurrencyFieldValue(flowRefs.reviewMinimumDailyRate, salaryPreferences.minimum_daily_rate ?? 0);
  }
  setSelectedLocations(searchSettings.locations || []);
  const engagementType = Array.isArray(matchPreferences.engagement_type)
    ? matchPreferences.engagement_type
    : [];
  setEngagementTypeValues(engagementType);
  if (!getWorkModePreferenceValues().length) {
    setWorkModePreferenceValues(matchPreferences.work_mode_preference || []);
  }
  if (flowRefs.governmentPreference && !String(flowRefs.governmentPreference.value || '').trim()) {
    flowRefs.governmentPreference.value = String(matchPreferences.prefer_government || governmentPreferenceDefault).trim().toLowerCase();
  }
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
  const filterTerm = String(flowRefs.reviewCapabilityFilter?.value || '').trim().toLowerCase();
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
  const container = flowRefs.reviewCapabilityCards;
  if (!container) return;
  if (!reviewCapabilityRules.length) {
    if (reviewCapabilityCountEl) {
      reviewCapabilityCountEl.textContent = '0 capability rows';
      reviewCapabilityCountEl.classList.remove('is-selected');
    }
    container.innerHTML = '<div class="chip-empty">No capabilities found yet.</div>';
    return;
  }
  const filterTerm = String(flowRefs.reviewCapabilityFilter?.value || '').trim().toLowerCase();
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
    reviewCapabilityCountEl.textContent = `${visibleRules.length} capability row${visibleRules.length === 1 ? '' : 's'}${hiddenCount ? ` of ${orderedRules.length}` : ''}`;
    reviewCapabilityCountEl.classList.toggle('is-selected', selectedReviewCapabilityIndexes.size > 0);
  }
  const rowsHtml = visibleRules.length ? visibleRules.map(({ rule, index }) => {
    const titleCaseName = rule.name.toLowerCase().split(' ').map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
    const aliasHtml = (() => {
      if (!rule.aliases.length) return '';
      const aliasChips = rule.aliases.map((alias) =>
        `<span class="review-capability-alias">${escapeHtml(patternToLabel(alias) || alias)}</span>`
      ).join('');
      return `
        <details class="review-capability-alias-drawer">
          <summary>Aliases (${rule.aliases.length})</summary>
          <div class="review-capability-aliases" aria-label="Aliases">${aliasChips}</div>
        </details>
      `;
    })();
    const selectedClass = selectedReviewCapabilityIndexes.has(index) ? ' is-selected' : '';
    return `
      <article class="review-capability-row${selectedClass}" data-review-capability-index="${index}">
        <div class="review-capability-main">
          <span class="review-capability-head">
            <strong class="review-capability-title">${escapeHtml(titleCaseName || 'Untitled capability')}</strong>
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
      <button class="btn btn-secondary" type="button" data-review-show-more="true">Show ${escapeHtml(String(Math.min(CAPABILITY_VISIBLE_INCREMENT, hiddenCount)))} more</button>
      <button class="btn btn-secondary review-capability-footer-link" type="button" data-review-show-all="true">Show all ${escapeHtml(String(orderedRules.length))}</button>
    </div>
  ` : '';
  const toolbarHtml = selectedReviewCapabilityIndexes.size ? `
    <div class="review-capability-toolbar">
      <div class="review-capability-toolbar-main">
        <span class="review-capability-toolbar-copy">${selectedVisibleCount} shown selected</span>
        <div class="review-capability-bulk-actions">
          <button class="btn btn-secondary" type="button" data-review-select-visible="true">Select shown</button>
          <button class="btn btn-secondary" type="button" data-review-clear-selection="true"${bulkDisabled}>Clear selection</button>
          <button class="btn btn-secondary" type="button" data-review-bulk-action="remove"${bulkDisabled}>Remove selected</button>
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
  renderReviewChipList(
    'review_target_titles_list',
    reviewTargetTitles,
    'No primary job titles extracted yet.',
    'data-remove-review-target',
    'data-move-review-target',
    'Move to secondary',
  );
  renderReviewChipList(
    'review_secondary_titles_list',
    reviewSecondaryTitles,
    'No secondary titles extracted yet.',
    'data-remove-review-secondary',
    'data-move-review-secondary',
    'Move to primary',
  );
  renderReviewCapabilities();
  saveWizardState();
}

function hydrateDraftStep(profile) {
  const normalizedTitles = normalizeReviewTitleLists(
    profile?.primary_job_title_pattern || [],
    profile?.secondary_title_patterns || [],
  );
  reviewTargetTitles = normalizedTitles.primary;
  reviewSecondaryTitles = normalizedTitles.secondary;
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

function formatExtractionSummary(counts) {
  const primary = Number(counts.target_titles || 0);
  const secondary = Number(counts.secondary_titles || 0);
  const capabilities = Number(counts.capabilities || 0);
  return `Extracted ${primary} primary title(s), ${secondary} secondary title(s), and ${capabilities} capability row(s) from your CV.`;
}

async function createProfile() {
  const primary = flowRefs.primaryCvInput.files[0];
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
    throw new Error(payload.error || 'Could not create profile');
  }

  lastImportPayload = payload;
  maxUnlockedStep = Math.max(maxUnlockedStep, REVIEW_STEP);
  hydrateDraftStep(payload.profile || {});
  setStep(REVIEW_STEP);
  const pageLimitNotice = String(payload?.page_limit_notice || '').trim();
  const extractionMessage = payload?.fresh_onboarding_run_started
    ? formatExtractionSummary(payload.extraction_counts || {})
    : 'Your draft profile is ready. Review the role direction before you continue.';
  showStatus(
    pageLimitNotice ? `${extractionMessage} ${pageLimitNotice}` : extractionMessage,
    pageLimitNotice ? 'warning' : 'ok',
  );
}

function continueFromReview() {
  if (!reviewTargetTitles.length) {
    throw new Error('Please keep at least one primary job title before continuing.');
  }
  maxUnlockedStep = Math.max(maxUnlockedStep, SEARCH_STEP);
  renderReviewStep();
  hydrateSearchBasics((lastImportPayload || {}).profile || {});
  setStep(SEARCH_STEP);
  showStatus('', '');
}

async function continueFromSearchBasics() {
  if (typeof flushSearchBasicsPersistence === 'function') {
    await flushSearchBasicsPersistence().catch((error) => {
      console.warn('Could not save onboarding search basics before continuing.', error);
    });
  }
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

  const response = await jobHunterFetch('/api/onboarding/confirm-profile-signals', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_keyword: searchPrefs.keywords,
        search_locations: searchPrefs.locations,
      engagement_type: searchPrefs.engagement_type,
        work_mode_preference: searchPrefs.work_mode_preference,
        prefer_government: searchPrefs.prefer_government,
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
    prefer_government: searchPrefs.prefer_government,
  };
  storeCompletionRedirectState(payload, finalSearchPrefs);
  showStatus(payload.message || 'Setup complete.', 'ok');
  setTimeout(() => {
    window.location.href = '/';
  }, 700);
}

async function loadProfileDefaults() {
  const response = await jobHunterFetch('/api/profile');
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
    Number.isFinite(onboardingCvPageLimit) && onboardingCvPageLimit > 0
      ? `Reading the first ${onboardingCvPageLimit} pages of your CV...`
      : (isRebuildMode ? 'Reading your updated CV...' : 'Reading your CV...'),
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

flowRefs.backToUploadFooter.addEventListener('click', () => setStep(1));
flowRefs.backToReviewFooter.addEventListener('click', () => setStep(REVIEW_STEP));
flowRefs.backToSearchBasicsFooter.addEventListener('click', () => setStep(SEARCH_STEP));
flowRefs.editDraftProfile.addEventListener('click', () => setStep(REVIEW_STEP));
flowRefs.editSearchBasics.addEventListener('click', () => setStep(SEARCH_STEP));
stepNavButtons.forEach((button) => {
  button.addEventListener('click', () => {
    if (button.disabled) return;
    const targetStep = Number(button.dataset.stepNav || 0);
    if (!targetStep || targetStep === currentStep) return;
    setStep(targetStep);
  });
});
flowRefs.wizardProgressSteps?.addEventListener('click', (event) => {
  const trigger = event.target.closest('[data-step-nav]');
  if (!trigger || trigger.disabled) return;
  const targetStep = Number(trigger.dataset.stepNav || 0);
  if (!targetStep || targetStep === currentStep) return;
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
  renderReviewCapabilities();
  saveWizardState();
});

flowRefs.reviewStepRoot.addEventListener('click', (event) => {
  const removeTarget = event.target.closest('[data-remove-review-target]');
  if (removeTarget) {
    reviewTargetTitles.splice(Number(removeTarget.dataset.removeReviewTarget), 1);
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
    reviewSecondaryTitles.splice(Number(removeSecondary.dataset.removeReviewSecondary), 1);
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
    && !event.target.closest('.review-capability-alias-drawer')
    && !event.target.closest('button')
  ) {
    const index = Number(capabilityRow.dataset.reviewCapabilityIndex);
    const nextChecked = !selectedReviewCapabilityIndexes.has(index);
    toggleSelectedReviewCapability(index, nextChecked);
  }
});

[
  flowRefs.reviewSearchKeywords,
  flowRefs.reviewMinimumSalaryYearly,
  flowRefs.reviewMinimumDailyRate,
  ...document.querySelectorAll('input[name="engagement_type"]'),
].filter(Boolean).forEach((input) => {
  input.addEventListener('input', () => {
    saveWizardState();
    if (typeof scheduleSearchBasicsPersistence === 'function') {
      scheduleSearchBasicsPersistence();
    }
  });
  input.addEventListener('change', () => {
    saveWizardState();
    if (typeof scheduleSearchBasicsPersistence === 'function') {
      scheduleSearchBasicsPersistence();
    }
  });
});

document.querySelectorAll('input[name="engagement_type"]').forEach((input) => {
  input.addEventListener('change', () => {
    if (!input.checked) {
      const anyChecked = document.querySelectorAll('input[name="engagement_type"]:checked').length > 0;
      if (!anyChecked) input.checked = true;
    }
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
  onboardingFlowCurrencyUi.bindCurrencyInput?.(input);
});
flowRefs.governmentPreference?.addEventListener('change', () => {
  saveWizardState();
  if (typeof scheduleSearchBasicsPersistence === 'function') {
    scheduleSearchBasicsPersistence();
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
const onboardingResumeStep = Number(window.__JOB_HUNTER_ONBOARDING_RESUME_STEP__ || 1);

async function initWizard() {
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.has('fresh')) {
    clearOnboardingBrowserState();
    history.replaceState(null, '', window.location.pathname);
    if (flowRefs.reviewSearchKeywords) flowRefs.reviewSearchKeywords.value = '';
    if (flowRefs.reviewMinimumSalaryYearly) flowRefs.reviewMinimumSalaryYearly.value = '';
    if (flowRefs.reviewMinimumDailyRate) flowRefs.reviewMinimumDailyRate.value = '';
    await loadProfileDefaults().catch(() => {});
    setStep(1, { scroll: false });
  } else if (restoreWizardState()) {
    loadProfileDefaults().catch(() => {});
  } else if (onboardingResumeStep > 1) {
    setStep(1, { scroll: false });
    try {
      const resumeResponse = await jobHunterFetch('/api/profile');
      if (resumeResponse.ok) {
        const resumeProfile = await resumeResponse.json().catch(() => ({}));
        applyProfileDefaults(resumeProfile || {});
        hydrateDraftStep(resumeProfile || {});
      }
    } catch {}
    if (hasDraftProfileState()) {
      maxUnlockedStep = Math.max(maxUnlockedStep, onboardingResumeStep);
      setStep(onboardingResumeStep, { scroll: false });
    }
  } else {
    loadProfileDefaults().catch(() => {});
    setStep(1, { scroll: false });
  }
  refreshStepNavigation();
  updatePrimaryCvStatus(primaryCvInput?.files?.[0] || preservedPrimaryCvFile || null);
  updateCreateProfileAvailability();
  updateCompensationVisibility();
}

initWizard().catch(() => {});

if (primaryCvDropZone && primaryCvInput) {
  resetPrimaryCvDropZoneAppearance();
  document.addEventListener('dragover', preventFileNavigation, true);
  document.addEventListener('drop', preventFileNavigation, true);
  primaryCvDropZone.addEventListener('click', () => primaryCvInput.click());
  primaryCvDropZone.addEventListener('dragenter', (event) => {
    event.preventDefault();
    primaryCvDropZone.classList.add('is-dragover');
    primaryCvDropZone.style.borderColor = 'var(--accent)';
    primaryCvDropZone.style.boxShadow = '0 0 12px color-mix(in srgb, var(--accent) 20%, transparent)';
  });
  primaryCvDropZone.addEventListener('dragover', (event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
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
    assignPrimaryCvFile(selectedFile);
  });
}
