const statusEl = document.getElementById('status');
const isTestMode = document.body?.dataset.testMode === 'true';
const urlParams = new URLSearchParams(window.location.search);
const isRebuildMode = urlParams.get('mode') === 'rebuild';
const stepEls = Array.from(document.querySelectorAll('.wizard-step'));
const heroSectionEl = document.querySelector('.hero');
const heroStepEl = document.getElementById('hero_step');
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
const createProfileButton = document.getElementById('create_profile');
const capabilityUi = window.JobHunterCapabilityUi || {};

function renderLogo() {
  if (!heroSectionEl) return;

  const img = document.createElement('img');
  img.src = '/static/job_hunter_img.png';
  img.alt = 'Job Hunter Logo';
  img.style.height = '64px';
  img.style.position = 'absolute';
  img.style.top = '40px';
  img.style.right = '40px';

  heroSectionEl.style.position = 'relative';
  heroSectionEl.appendChild(img);
}

document.querySelectorAll('[data-test-only]').forEach((element) => {
  element.hidden = !isTestMode;
});

const COMMON_LOCATION_OPTIONS = [
  'Sydney NSW',
  'Melbourne VIC',
  'Brisbane QLD',
  'Perth WA',
  'Adelaide SA',
  'Canberra ACT',
  'Hobart TAS',
  'Darwin NT',
  'New South Wales',
  'Victoria',
  'Queensland',
  'Western Australia',
  'South Australia',
  'Tasmania',
  'Australian Capital Territory',
  'Northern Territory',
];

const REVIEW_STEP = 2;
const SEARCH_STEP = 3;
const CHECK_STEP = 4;
const STEP_COUNT = 4;

let currentStep = 1;
let selectedLocations = [];
let reviewTargetTitles = [];
let reviewSecondaryTitles = [];
let reviewCapabilityRules = [];
let lastImportPayload = null;
let preservedPrimaryCvFile = null;
let workingStatusTimer = null;

const reviewCapabilityLevelMeta = capabilityUi.capabilityLevelMeta || {};

function saveWizardState() {
  if (currentStep < 2) {
    window.sessionStorage.removeItem('jobHunter.onboardingWizard');
    return;
  }
  const engagementInput = document.querySelector('input[name="engagement_pref"]:checked');
  window.sessionStorage.setItem('jobHunter.onboardingWizard', JSON.stringify({
    step: currentStep,
    reviewTargetTitles,
    reviewSecondaryTitles,
    reviewCapabilityRules,
    selectedLocations,
    searchKeywords: document.getElementById('review_search_keywords')?.value || '',
    minimumSalaryYearly: document.getElementById('review_minimum_salary_yearly')?.value || '',
    minimumDailyRate: document.getElementById('review_minimum_daily_rate')?.value || '',
    engagementType: engagementInput?.value || 'both',
  }));
}

function restoreWizardState() {
  try {
    const raw = window.sessionStorage.getItem('jobHunter.onboardingWizard');
    if (!raw) return false;
    const state = JSON.parse(raw);
    if (!state || state.step < 2) return false;
    reviewTargetTitles = state.reviewTargetTitles || [];
    reviewSecondaryTitles = state.reviewSecondaryTitles || [];
    reviewCapabilityRules = state.reviewCapabilityRules || [];
    setSelectedLocations(state.selectedLocations || []);
    setStep(state.step);
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
    return true;
  } catch {
    return false;
  }
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
      <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="upload-icon"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
      <p>Drag & drop your CV here, or click to browse</p>
      <p class="drop-zone-hint">Supported formats: .docx, .pdf, .md, .txt</p>
    `;
    return;
  }

  primaryCvStatusEl.textContent = `Selected file: ${file.name}`;
  primaryCvStatusEl.classList.add('is-selected');
  primaryCvDropZone?.classList.add('has-file');

  dropZoneContent.innerHTML = `
    <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="upload-icon"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
    <p class="file-loaded-label">File Loaded: ${file.name}</p>
    <p class="drop-zone-hint">Click or drag another file to replace</p>
  `;
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

function setStep(stepNumber) {
  currentStep = stepNumber;
  stepEls.forEach((el) => {
    const step = Number(el.dataset.step);
    const active = step === stepNumber;
    el.hidden = !active;
    el.classList.toggle('is-active', active);
  });

  const meta = stepMeta[stepNumber];
  heroStepEl.textContent = `Step ${stepNumber} of ${STEP_COUNT}`;
  heroTitleEl.textContent = meta.heroTitle();
  heroCopyEl.textContent = meta.heroCopy();

  const isDetailStep = stepNumber > 1;
  if (heroSectionEl) heroSectionEl.classList.toggle('is-compact', isDetailStep);
  if (workflowSummaryEl) {
    workflowSummaryEl.hidden = isDetailStep;
    workflowSummaryEl.style.display = isDetailStep ? 'none' : '';
  }

  if (formTitleEl) formTitleEl.textContent = `Step 1. ${stepMeta[1].title()}`;
  const percent = Math.round((stepNumber / STEP_COUNT) * 100);
  progressFillEl.style.width = `${percent}%`;
  progressFillEl.textContent = `${percent}% Complete`;
  window.scrollTo({ top: 0, behavior: 'smooth' });
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
}

function removeLocation(value) {
  const key = locationKey(value);
  selectedLocations = selectedLocations.filter((item) => locationKey(item) !== key);
  renderSelectedLocations();
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

function normalizeReviewAlias(value) {
  return normalizeReviewText(value).toLowerCase();
}

function normalizeReviewCapability(rule) {
  const name = normalizeReviewText(rule?.name || '');
  const rawLevel = String(rule?.level || 'working').trim().toLowerCase();
  const level = rawLevel === 'strong'
    ? 'strong'
    : rawLevel === 'working'
      ? 'working'
      : rawLevel === 'low'
        ? 'low'
        : 'basic';
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
    const key = cleaned.toLowerCase();
    if (!cleaned || seen.has(key)) continue;
    seen.add(key);
    output.push(cleaned);
  }
  return output;
}

function renderReviewChipList(elementId, values, emptyLabel, removeAttribute) {
  const container = document.getElementById(elementId);
  if (!container) return;
  if (!values.length) {
    container.innerHTML = `<span class="chip-empty">${emptyLabel}</span>`;
    return;
  }
  container.innerHTML = values.map((value, index) => `
    <span class="chip-item">
      <span>${escapeHtml(value)}</span>
      <button type="button" ${removeAttribute}="${index}" aria-label="Remove ${escapeHtml(value)}">&#215;</button>
    </span>
  `).join('');
}

function renderReviewCapabilities() {
  const container = document.getElementById('review_capability_cards');
  if (!container) return;
  if (!reviewCapabilityRules.length) {
    container.innerHTML = '<div class="chip-empty">No capability rows yet. Add one if you want to tune the matrix before continuing.</div>';
    return;
  }
  const filterTerm = String(document.getElementById('review_capability_filter')?.value || '').trim().toLowerCase();
  const filteredRules = reviewCapabilityRules
    .map((rule, index) => ({ rule, index }))
    .filter((item) => {
      if (!filterTerm) return true;
      return item.rule.name.toLowerCase().includes(filterTerm)
        || item.rule.aliases.some((alias) => alias.includes(filterTerm));
    });
  const rowsHtml = filteredRules.length ? filteredRules.map(({ rule, index }) => {
      const aliasPreview = rule.aliases.slice(0, 3);
      const remainingAliasCount = Math.max(rule.aliases.length - aliasPreview.length, 0);
      return `
      <details class="review-capability-row" data-review-capability-index="${index}"${filterTerm ? ' open' : ''}>
        <summary class="review-capability-summary">
          <div class="review-capability-summary-main">
            <strong class="review-capability-title">${escapeHtml(rule.name || 'Untitled capability')}</strong>
            <div class="review-capability-preview">
              ${aliasPreview.length ? aliasPreview.map((alias) => `<span class="chip-item chip-item-subtle">${escapeHtml(alias)}</span>`).join('') : '<span class="chip-empty">No aliases yet.</span>'}
              ${remainingAliasCount ? `<span class="chip-item chip-item-subtle">+${remainingAliasCount} more</span>` : ''}
            </div>
          </div>
          <div class="review-capability-summary-meta">
            <span class="chip-item strength-chip strength-${escapeHtml(rule.level)}">${escapeHtml(reviewCapabilityLevelMeta[rule.level]?.label || 'Intermediate')}</span>
            <button class="icon-button icon-button-danger" type="button" data-remove-review-capability="${index}" aria-label="Remove ${escapeHtml(rule.name || 'capability')}" title="Remove capability">
              <span aria-hidden="true">🗑</span>
            </button>
          </div>
        </summary>
        <div class="review-capability-body">
          <div class="review-capability-column-head">
            <span>Capability</span>
            <span>Strength</span>
            <span>Action</span>
          </div>
          <div class="review-capability-fields">
            <div>
              <input id="review_capability_name_${index}" type="text" data-review-capability-field="name" aria-label="Capability name" value="${escapeHtml(rule.name)}">
            </div>
            <div>
              <select id="review_capability_level_${index}" data-review-capability-field="level" aria-label="Capability strength">
                <option value="strong"${rule.level === 'strong' ? ' selected' : ''}>Expert</option>
                <option value="working"${rule.level === 'working' ? ' selected' : ''}>Advanced</option>
                <option value="basic"${rule.level === 'basic' ? ' selected' : ''}>Intermediate</option>
                <option value="low"${rule.level === 'low' ? ' selected' : ''}>Beginner</option>
              </select>
            </div>
          </div>
          <div class="review-capability-meta">
            <span class="chip-item strength-chip strength-${escapeHtml(rule.level)}">${escapeHtml(reviewCapabilityLevelMeta[rule.level]?.label || 'Intermediate')}</span>
            <span class="chip-item">${escapeHtml(String(rule.aliases.length))} alias${rule.aliases.length === 1 ? '' : 'es'}</span>
          </div>
          <p class="review-capability-copy">${escapeHtml(reviewCapabilityLevelMeta[rule.level]?.summary || '')}</p>
          <details class="review-capability-alias-shell">
            <summary>Aliases (${rule.aliases.length})</summary>
            <p class="help">These are alternate job-ad terms Job Hunter can match to this capability. Job Hunter should usually suggest them for you. Only add one if an obvious term is missing.</p>
            <div class="chip-list chip-list-tight">
              ${rule.aliases.length ? rule.aliases.map((alias, aliasIndex) => `
                <span class="chip-item">
                  <span>${escapeHtml(alias)}</span>
                  <button type="button" data-remove-review-alias="${index}" data-review-alias-index="${aliasIndex}" aria-label="Remove ${escapeHtml(alias)}">&#215;</button>
                </span>
              `).join('') : '<span class="chip-empty">No aliases yet.</span>'}
            </div>
            <div class="chip-editor-row">
              <input type="text" data-review-alias-input="${index}" placeholder="Add an alias">
              <button class="secondary" type="button" data-add-review-alias="${index}">Add</button>
            </div>
          </details>
        </div>
      </details>
    `;
    }).join('') : '<div class="chip-empty">No matching capabilities found.</div>';
  container.innerHTML = `
    <section class="review-capability-group">
      <div class="review-capability-group-head">
        <h4>Capabilities</h4>
        <span class="chip-item">${escapeHtml(String(filteredRules.length))} shown</span>
      </div>
      <p class="review-capability-group-copy">Keep current strengths only. Remove old or weak capabilities you do not want driving matching.</p>
      <div class="review-capability-row-list">${rowsHtml}</div>
    </section>
  `;
}

function renderReviewStep() {
  renderReviewChipList('review_target_titles_list', reviewTargetTitles, 'No target titles extracted yet.', 'data-remove-review-target');
  renderReviewChipList('review_secondary_titles_list', reviewSecondaryTitles, 'No secondary titles extracted yet.', 'data-remove-review-secondary');
  renderReviewCapabilities();
  saveWizardState();
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

function hydrateDraftStep(profile) {
  reviewTargetTitles = dedupeReviewList(profile?.target_title_patterns || []);
  reviewSecondaryTitles = dedupeReviewList(profile?.secondary_title_patterns || []);
  reviewCapabilityRules = (profile?.capability_profile_rules || []).map(normalizeReviewCapability).filter((rule) => rule.name);
  renderReviewStep();
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
}

function buildCompletionRedirectState(payload, searchPrefs) {
  const profile = payload?.profile || {};
  const targets = Array.isArray(profile.target_title_patterns)
    ? profile.target_title_patterns.slice(0, 4).map((value) => String(value || '').trim()).filter(Boolean)
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

  if (isRebuildMode) {
    const confirmed = window.confirm(
      'Refresh your profile using this CV?\n\n'
      + 'This will re-extract your summaries, capability rules, and evidence tiers from the document.\n\n'
      + 'Your custom Decision Weights, Salary Preferences, and Search Settings will be preserved.'
    );
    if (!confirmed) return;
  }

  const files = [await fileToPayload(primary, 'Primary CV')];
  const response = await fetch('/api/onboarding/import', {
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
  hydrateDraftStep(payload.profile || {});
  hydrateSearchBasics(payload.profile || {});
  setStep(REVIEW_STEP);
  showStatus('Your draft profile is ready. Review the role direction before you continue.', 'ok');
}

function continueFromReview() {
  if (!reviewTargetTitles.length) {
    throw new Error('Please keep at least one target title before continuing.');
  }
  renderReviewStep();
  setStep(SEARCH_STEP);
  showStatus('', '');
}

function continueFromSearchBasics() {
  const searchPrefs = searchPreferencesPayload();
  validateSearchPreferences(searchPrefs);
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

  const response = await fetch('/api/onboarding/confirm-profile-signals', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      search_keyword: searchPrefs.keywords,
      search_locations: searchPrefs.locations,
      engagement_type: searchPrefs.engagement_type,
      minimum_salary_yearly: searchPrefs.minimum_salary_yearly,
      minimum_daily_rate: searchPrefs.minimum_daily_rate,
      target_title_patterns: reviewTargetTitles,
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
  const response = await fetch('/api/profile');
  if (!response.ok) return;
  const profile = await response.json().catch(() => ({}));
  applyProfileDefaults(profile || {});
}

createProfileButton.addEventListener('click', async (event) => {
  const btn = event.currentTarget;
  const originalLabel = btn.textContent;
  btn.classList.add('is-working');
  btn.disabled = true;
  btn.textContent = isRebuildMode ? 'Refreshing Draft...' : 'Building Draft...';
  startWorkingStatus([
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

document.getElementById('back_to_upload').addEventListener('click', () => setStep(1));
document.getElementById('back_to_review').addEventListener('click', () => setStep(REVIEW_STEP));
document.getElementById('back_to_review_footer').addEventListener('click', () => setStep(REVIEW_STEP));
document.getElementById('back_to_search_basics').addEventListener('click', () => setStep(SEARCH_STEP));
document.getElementById('back_to_search_basics_footer').addEventListener('click', () => setStep(SEARCH_STEP));
document.getElementById('edit_draft_profile').addEventListener('click', () => setStep(REVIEW_STEP));
document.getElementById('edit_search_basics').addEventListener('click', () => setStep(SEARCH_STEP));

document.getElementById('review_add_target_title').addEventListener('click', () => {
  const input = document.getElementById('review_target_titles_input');
  const cleaned = normalizeReviewTitle(input.value);
  if (!cleaned) return;
  reviewTargetTitles = dedupeReviewList([...reviewTargetTitles, cleaned]);
  input.value = '';
  renderReviewStep();
});

document.getElementById('review_add_secondary_title').addEventListener('click', () => {
  const input = document.getElementById('review_secondary_titles_input');
  const cleaned = normalizeReviewTitle(input.value);
  if (!cleaned) return;
  reviewSecondaryTitles = dedupeReviewList([...reviewSecondaryTitles, cleaned]);
  input.value = '';
  renderReviewStep();
});

document.getElementById('review_add_capability').addEventListener('click', () => {
  reviewCapabilityRules = [...reviewCapabilityRules, { name: '', level: 'working', aliases: [] }];
  renderReviewStep();
});

document.getElementById('review_capability_filter').addEventListener('input', () => {
  renderReviewCapabilities();
});

document.querySelector('[data-step="2"]').addEventListener('click', (event) => {
  const removeTarget = event.target.closest('[data-remove-review-target]');
  if (removeTarget) {
    reviewTargetTitles.splice(Number(removeTarget.dataset.removeReviewTarget), 1);
    renderReviewStep();
    return;
  }
  const removeSecondary = event.target.closest('[data-remove-review-secondary]');
  if (removeSecondary) {
    reviewSecondaryTitles.splice(Number(removeSecondary.dataset.removeReviewSecondary), 1);
    renderReviewStep();
    return;
  }
  const removeCapability = event.target.closest('[data-remove-review-capability]');
  if (removeCapability) {
    reviewCapabilityRules.splice(Number(removeCapability.dataset.removeReviewCapability), 1);
    renderReviewStep();
    return;
  }
  const removeAlias = event.target.closest('[data-remove-review-alias]');
  if (removeAlias) {
    const ruleIndex = Number(removeAlias.dataset.removeReviewAlias);
    const aliasIndex = Number(removeAlias.dataset.reviewAliasIndex);
    const aliases = [...(reviewCapabilityRules[ruleIndex]?.aliases || [])];
    aliases.splice(aliasIndex, 1);
    reviewCapabilityRules[ruleIndex] = { ...reviewCapabilityRules[ruleIndex], aliases };
    renderReviewStep();
    return;
  }
  const addAlias = event.target.closest('[data-add-review-alias]');
  if (!addAlias) return;
  const ruleIndex = Number(addAlias.dataset.addReviewAlias);
  const input = document.querySelector(`[data-review-alias-input="${ruleIndex}"]`);
  const cleaned = normalizeReviewAlias(input?.value || '');
  if (!cleaned) return;
  const aliases = [...(reviewCapabilityRules[ruleIndex]?.aliases || [])];
  if (!aliases.includes(cleaned)) aliases.push(cleaned);
  reviewCapabilityRules[ruleIndex] = { ...reviewCapabilityRules[ruleIndex], aliases };
  renderReviewStep();
});

document.querySelector('[data-step="2"]').addEventListener('input', (event) => {
  const field = event.target.closest('[data-review-capability-field]');
  if (!field) return;
  const card = field.closest('[data-review-capability-index]');
  if (!card) return;
  const index = Number(card.dataset.reviewCapabilityIndex);
  const key = field.dataset.reviewCapabilityField;
  reviewCapabilityRules[index] = {
    ...reviewCapabilityRules[index],
    [key]: key === 'name' ? normalizeReviewText(field.value) : String(field.value || '').trim().toLowerCase(),
  };
});

document.querySelector('[data-step="2"]').addEventListener('change', (event) => {
  const field = event.target.closest('[data-review-capability-field]');
  if (!field) return;
  const card = field.closest('[data-review-capability-index]');
  if (!card) return;
  const index = Number(card.dataset.reviewCapabilityIndex);
  const key = field.dataset.reviewCapabilityField;
  reviewCapabilityRules[index] = {
    ...reviewCapabilityRules[index],
    [key]: key === 'name' ? normalizeReviewText(field.value) : String(field.value || '').trim().toLowerCase(),
  };
  renderReviewStep();
});

document.querySelector('[data-step="2"]').addEventListener('keydown', (event) => {
  const aliasInput = event.target.closest('[data-review-alias-input]');
  if (aliasInput && event.key === 'Enter') {
    event.preventDefault();
    const ruleIndex = Number(aliasInput.dataset.reviewAliasInput);
    const cleaned = normalizeReviewAlias(aliasInput.value || '');
    if (!cleaned) return;
    const aliases = [...(reviewCapabilityRules[ruleIndex]?.aliases || [])];
    if (!aliases.includes(cleaned)) aliases.push(cleaned);
    reviewCapabilityRules[ruleIndex] = { ...reviewCapabilityRules[ruleIndex], aliases };
    renderReviewStep();
    return;
  }
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
locationSelected.addEventListener('click', (event) => {
  const button = event.target.closest('[data-remove-location]');
  if (!button) return;
  removeLocation(button.getAttribute('data-remove-location'));
});

renderLogo();
renderLocationSuggestions();
loadProfileDefaults().catch(() => {});
setStep(1);
updateCreateProfileAvailability();

if (primaryCvDropZone && primaryCvInput) {
  primaryCvDropZone.addEventListener('click', () => primaryCvInput.click());
  primaryCvDropZone.addEventListener('dragenter', (event) => {
    event.preventDefault();
    primaryCvDropZone.classList.add('is-dragover');
  });
  primaryCvDropZone.addEventListener('dragover', (event) => {
    event.preventDefault();
    primaryCvDropZone.classList.add('is-dragover');
  });
  primaryCvDropZone.addEventListener('dragleave', (event) => {
    if (event.target === primaryCvDropZone) {
      primaryCvDropZone.classList.remove('is-dragover');
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
