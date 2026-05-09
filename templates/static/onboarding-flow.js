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

function renderReviewChipList(elementId, values, emptyLabel, removeAttribute, moveAttribute, moveLabel) {
  const container = document.getElementById(elementId);
  if (!container) return;
  if (!values.length) {
    container.innerHTML = `<span class="chip-empty">${emptyLabel}</span>`;
    return;
  }
  container.innerHTML = values.map((value, index) => `
    <span class="chip-item">
      <span>${escapeHtml(value)}</span>
      <button type="button" ${moveAttribute}="${index}" aria-label="${escapeHtml(moveLabel)} ${escapeHtml(value)}">${escapeHtml(moveLabel)}</button>
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

      const response = await jobHunterFetch('/api/onboarding/confirm-profile-signals', {
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
  addReviewTitle('primary', input.value);
  input.value = '';
});

document.getElementById('review_add_secondary_title').addEventListener('click', () => {
  const input = document.getElementById('review_secondary_titles_input');
  addReviewTitle('secondary', input.value);
  input.value = '';
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

renderLocationSuggestions();
loadProfileDefaults().catch(() => {});
if (!restoreWizardState()) {
  setStep(1, { scroll: false });
}
refreshStepNavigation();
updatePrimaryCvStatus(primaryCvInput?.files?.[0] || preservedPrimaryCvFile || null);
updateCreateProfileAvailability();
updateCompensationVisibility();

if (primaryCvDropZone && primaryCvInput) {
  resetPrimaryCvDropZoneAppearance();
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
