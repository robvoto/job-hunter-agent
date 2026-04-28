    const statusEl = document.getElementById('status');
    const summaryBox = document.getElementById('summary_box');
    const summaryHeading = document.getElementById('summary_heading');
    const summaryText = document.getElementById('summary_text');
    const patternsText = document.getElementById('patterns_text');
    const locationInput = document.getElementById('location_search');
    const addLocationButton = document.getElementById('add_location');
    const locationSuggestions = document.getElementById('location_suggestions');
    const locationQuickPicks = document.getElementById('location_quick_picks');
    const locationSelected = document.getElementById('location_selected');
    const reviewBox = document.getElementById('review_box');
    const urlParams = new URLSearchParams(window.location.search);
    const isRebuildMode = urlParams.get('mode') === 'rebuild';
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
      'Northern Territory'
    ];
    let selectedLocations = [];
    let reviewTargetTitles = [];
    let reviewAdjacentTitles = [];
    let reviewCapabilityRules = [];
    let lastImportPayload = null;
    const reviewCapabilityLevelMeta = {
      strong: { label: 'Strong', summary: 'Proven strength that should count heavily when a role depends on it.' },
      working: { label: 'Working', summary: 'Solid evidence, but not one of your main headline strengths.' },
      basic: { label: 'Minor exposure', summary: 'Real exposure, but this should stay a light signal rather than a driver.' },
    };
    const reviewCapabilityPriorityMeta = {
      core: { label: 'Primary', summary: 'This should actively pull matching roles up.' },
      supporting: { label: 'Secondary', summary: 'Relevant and positive, but secondary to your core pitch.' },
      contextual: { label: 'Background', summary: 'Useful context only. It should not drive matching on its own.' },
    };
    const reviewCapabilityPriorityOrder = ['core', 'supporting', 'contextual'];

    function showStatus(message, kind) {
      statusEl.textContent = message;
      statusEl.className = message ? `status ${kind}` : 'status';
    }

    function normalizeLocationValue(value) {
      return String(value || '').replace(/\s+/g, ' ').trim();
    }

    function locationKey(value) {
      return normalizeLocationValue(value).toLowerCase();
    }

    function renderLocationSuggestions() {
      locationSuggestions.innerHTML = COMMON_LOCATION_OPTIONS
        .map(value => `<option value="${value}"></option>`)
        .join('');

      locationQuickPicks.innerHTML = COMMON_LOCATION_OPTIONS.slice(0, 8)
        .map(value => {
          const activeClass = selectedLocations.some(item => locationKey(item) === locationKey(value)) ? ' is-active' : '';
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
        .map(value => (
          `<span class="location-chip">${value}<button type="button" data-remove-location="${value}" aria-label="Remove ${value}">×</button></span>`
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
      if (selectedLocations.some(item => locationKey(item) === locationKey(normalized))) {
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
      selectedLocations = selectedLocations.filter(item => locationKey(item) !== key);
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
      return {
        extraction_lookback_years: lookbackYears ? Number(lookbackYears) : undefined,
        title_extraction_min_months: minMonths ? Number(minMonths) : undefined,
      };
    }

    function searchPreferencesPayload() {
      return {
        keywords: document.getElementById('search_keywords').value.trim(),
        locations: selectedLocations,
        engagement_type: document.querySelector('input[name="engagement_pref"]:checked').value
      };
    }

    function validateOnboardingSettings(settings) {
      const lookback = Number(settings.extraction_lookback_years);
      const minMonths = Number(settings.title_extraction_min_months);

      if (!Number.isInteger(lookback) || lookback < 1 || lookback > 20) {
        throw new Error('Please enter a lookback between 1 and 20 years.');
      }
      if (!Number.isInteger(minMonths) || minMonths < 1 || minMonths > 24) {
        throw new Error('Please enter a short-role threshold between 1 and 24 months.');
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
    }

    function validatePrimaryFile(file) {
      if (!file) {
        throw new Error('Choose your detailed CV first.');
      }
      const name = String(file.name || '').toLowerCase();
      if (!name.endsWith('.docx') && !name.endsWith('.md') && !name.endsWith('.txt')) {
        throw new Error('Please upload a .docx, .md, or .txt CV file.');
      }
    }

    function applyProfileDefaults(profile) {
      const onboarding = profile?.onboarding_settings || {};
      document.getElementById('os_lookback_years').value = String(onboarding.extraction_lookback_years ?? onboarding.title_extraction_lookback_years ?? '');
      document.getElementById('os_min_months').value = String(onboarding.title_extraction_min_months ?? '');

      const search = profile?.search_settings || {};
      document.getElementById('search_keywords').value = search.keywords || '';
      setSelectedLocations(search.locations || []);
    }

    function renderProfileSnapshot(profile) {
      summaryHeading.textContent = isRebuildMode ? 'Updated Profile Preview' : 'Profile Preview';
      summaryText.textContent = profile.candidate_summary || (isRebuildMode ? 'Profile refreshed.' : 'Profile built.');
      const targets = (profile.target_title_patterns || []).slice(0, 3);
      patternsText.textContent = targets.length ? `Target titles: ${targets.join(' | ')}` : 'Target titles will appear here after extraction.';
      summaryBox.classList.add('visible');
    }

    function normalizeReviewText(value) {
      return String(value || '').replace(/\s+/g, ' ').trim();
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
      return normalizeReviewText(value);
    }

    function normalizeReviewAlias(value) {
      return normalizeReviewText(value).toLowerCase();
    }

    function normalizeReviewCapability(rule) {
      const name = normalizeReviewText(rule?.name || '');
      const rawLevel = String(rule?.level || 'working').trim().toLowerCase();
      const rawFit = String(rule?.fit || 'supporting').trim().toLowerCase();
      const level = rawLevel === 'strong' ? 'strong' : rawLevel === 'working' ? 'working' : 'basic';
      const fit = rawFit === 'core' ? 'core' : rawFit === 'supporting' ? 'supporting' : 'contextual';
      const aliases = [];
      const seen = new Set();
      for (const alias of Array.isArray(rule?.aliases) ? rule.aliases : []) {
        const cleaned = normalizeReviewAlias(alias);
        if (!cleaned || cleaned === name.toLowerCase() || seen.has(cleaned)) continue;
        seen.add(cleaned);
        aliases.push(cleaned);
      }
      return { name, level, fit, aliases };
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
          <button type="button" ${removeAttribute}="${index}" aria-label="Remove ${escapeHtml(value)}">×</button>
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
      const groups = reviewCapabilityPriorityOrder.map(priority => {
        const rules = reviewCapabilityRules
          .map((rule, index) => ({ rule, index }))
          .filter(item => item.rule.fit === priority)
          .filter(item => {
            if (!filterTerm) return true;
            return item.rule.name.toLowerCase().includes(filterTerm)
              || item.rule.aliases.some(alias => alias.includes(filterTerm));
          });
        return { priority, rules };
      });
      container.innerHTML = groups.map(group => {
        const priorityMeta = reviewCapabilityPriorityMeta[group.priority];
        const rowsHtml = group.rules.length ? group.rules.map(({ rule, index }) => `
          <article class="review-capability-row" data-review-capability-index="${index}">
            <div class="review-capability-fields">
              <div>
                <label for="review_capability_name_${index}">Capability</label>
                <input id="review_capability_name_${index}" type="text" data-review-capability-field="name" value="${escapeHtml(rule.name)}">
              </div>
              <div>
                <label for="review_capability_level_${index}">Strength</label>
                <select id="review_capability_level_${index}" data-review-capability-field="level">
                  <option value="strong"${rule.level === 'strong' ? ' selected' : ''}>Strong</option>
                  <option value="working"${rule.level === 'working' ? ' selected' : ''}>Working</option>
                  <option value="basic"${rule.level === 'basic' ? ' selected' : ''}>Minor exposure</option>
                </select>
              </div>
              <div>
                <label for="review_capability_fit_${index}">Priority</label>
                <select id="review_capability_fit_${index}" data-review-capability-field="fit">
                  <option value="core"${rule.fit === 'core' ? ' selected' : ''}>Primary</option>
                  <option value="supporting"${rule.fit === 'supporting' ? ' selected' : ''}>Secondary</option>
                  <option value="contextual"${rule.fit === 'contextual' ? ' selected' : ''}>Background</option>
                </select>
              </div>
              <div class="review-capability-actions">
                <button class="secondary" type="button" data-remove-review-capability="${index}">Remove</button>
              </div>
            </div>
            <p class="review-capability-copy">${escapeHtml(reviewCapabilityLevelMeta[rule.level]?.summary || '')}</p>
            <details>
              <summary>Job ad keywords (${rule.aliases.length})</summary>
              <p class="help">Short words or phrases the app looks for in job descriptions. Use JD language like <code>agile</code> or <code>uat</code>, not CV sentence fragments.</p>
              <div class="chip-list" style="margin-top:10px;">
                ${rule.aliases.length ? rule.aliases.map((alias, aliasIndex) => `
                  <span class="chip-item">
                    <span>${escapeHtml(alias)}</span>
                    <button type="button" data-remove-review-alias="${index}" data-review-alias-index="${aliasIndex}" aria-label="Remove ${escapeHtml(alias)}">×</button>
                  </span>
                `).join('') : '<span class="chip-empty">No job ad keywords yet.</span>'}
              </div>
              <div class="chip-editor-row">
                <input type="text" data-review-alias-input="${index}" placeholder="Add a short job-ad keyword">
                <button class="secondary" type="button" data-add-review-alias="${index}">Add</button>
              </div>
            </details>
          </article>
        `).join('') : '<div class="chip-empty">No matching capabilities in this group.</div>';
        return `
          <section class="review-capability-group">
            <div class="review-capability-group-head">
              <h5>${escapeHtml(priorityMeta.label)} capabilities</h5>
              <span class="chip-item">${escapeHtml(String(group.rules.length))} shown</span>
            </div>
            <p class="review-capability-group-copy">${escapeHtml(priorityMeta.summary)}</p>
            <div class="review-capability-row-list">${rowsHtml}</div>
          </section>
        `;
      }).join('');
    }

    function renderReviewStep() {
      renderReviewChipList('review_target_titles_list', reviewTargetTitles, 'No target titles extracted yet.', 'data-remove-review-target');
      renderReviewChipList('review_adjacent_titles_list', reviewAdjacentTitles, 'No secondary titles extracted yet.', 'data-remove-review-adjacent');
      renderReviewCapabilities();
      reviewBox.hidden = false;
      reviewBox.classList.add('visible');
    }

    function hydrateReviewStep(profile, fallbackSearchPrefs) {
      const searchSettings = profile?.search_settings || {};
      reviewTargetTitles = dedupeReviewList(profile?.target_title_patterns || []);
      reviewAdjacentTitles = dedupeReviewList(profile?.adjacent_title_patterns || []);
      reviewCapabilityRules = (profile?.capability_profile_rules || []).map(normalizeReviewCapability).filter(rule => rule.name);
      document.getElementById('review_search_keywords').value = String(searchSettings.keywords || fallbackSearchPrefs?.keywords || '').trim();
      renderReviewStep();
    }

    function buildCompletionRedirectState(payload, searchPrefs) {
      const profile = payload?.profile || {};
      const targets = Array.isArray(profile.target_title_patterns)
        ? profile.target_title_patterns.slice(0, 4).map(value => String(value || '').trim()).filter(Boolean)
        : [];
      const locations = Array.isArray(searchPrefs?.locations)
        ? searchPrefs.locations.map(value => String(value || '').trim()).filter(Boolean)
        : [];
      return {
        kind: isRebuildMode ? 'profile-refresh' : 'onboarding-complete',
        title: isRebuildMode ? 'Profile refreshed' : 'Profile built',
        message: payload?.message || (isRebuildMode ? 'Your profile was refreshed from the uploaded CV.' : 'Your profile was built from the uploaded CV.'),
        summary: String(profile.candidate_summary || '').trim(),
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

    async function confirmReview() {
      const keyword = document.getElementById('review_search_keywords').value.trim();
      if (!reviewTargetTitles.length) {
        throw new Error('Please keep at least one target title before continuing.');
      }
      const response = await fetch('/api/onboarding/confirm-profile-signals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          search_keyword: keyword,
          target_title_patterns: reviewTargetTitles,
          adjacent_title_patterns: reviewAdjacentTitles,
          capability_profile_rules: reviewCapabilityRules.map(normalizeReviewCapability).filter(rule => rule.name),
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.error || 'Could not save onboarding review');
      }
      const finalSearchPrefs = {
        ...(lastImportPayload?.profile?.search_settings || {}),
        keywords: keyword || String(payload?.profile?.search_settings?.keywords || '').trim(),
        locations: selectedLocations,
      };
      renderProfileSnapshot(payload.profile || {});
      storeCompletionRedirectState(payload, finalSearchPrefs);
      showStatus(payload.message || 'Onboarding targeting saved.', 'ok');
      setTimeout(() => {
        window.location.href = '/';
      }, 800);
    }

    async function createProfile() {
      const primary = document.getElementById('primary_cv').files[0];
      const searchPrefs = searchPreferencesPayload();
      const onboardingSettings = onboardingSettingsPayload();

      validatePrimaryFile(primary);
      validateOnboardingSettings(onboardingSettings);
      validateSearchPreferences(searchPrefs);

      if (isRebuildMode) {
        const confirmed = window.confirm(
          "Refresh your profile using this CV?\n\n" +
          "We will replace the extracted profile content from your current CV, including summaries, capability rules, title patterns, and evidence tiers.\n\n" +
          "Other workspace settings stay in place."
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
          search_preferences: searchPrefs,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.error || 'Could not create profile');
      }
      lastImportPayload = payload;
      renderProfileSnapshot(payload.profile || {});
      hydrateReviewStep(payload.profile || {}, searchPrefs);
      showStatus('Profile extracted. Review the generated targeting below, then continue.', 'ok');
    }

    async function loadProfileDefaults() {
      const response = await fetch('/api/profile');
      if (!response.ok) {
        return;
      }
      const profile = await response.json().catch(() => ({}));
      applyProfileDefaults(profile || {});
    }

    if (isRebuildMode) {
      document.title = 'Refresh Your Profile | Job Hunter';
      document.getElementById('hero_title').textContent = 'Refresh Your Profile';
      document.getElementById('hero_copy').textContent = 'Upload an updated CV and we will refresh the extracted profile content while keeping your wider workspace configuration in place.';
      document.getElementById('form_title').textContent = 'Step 1. Refresh Basics';
      document.getElementById('create_profile').textContent = 'Refresh Profile';
      document.getElementById('workflow_title').textContent = 'How refresh works';
      document.getElementById('workflow_intro').textContent = 'Refreshing replaces the profile content generated from your CV, not your wider workspace setup.';
      document.getElementById('workflow_step_1').textContent = 'You upload an updated CV and keep your search basics in place.';
      document.getElementById('workflow_step_2').textContent = 'We re-extract summaries, titles, capability rules, and evidence tiers.';
      document.getElementById('workflow_step_3').textContent = 'You review the refreshed targeting before it replaces the current profile output.';
      document.getElementById('workflow_note').textContent = 'Rules, alerts, schedules, and the rest of the workspace stay in place.';
      summaryHeading.textContent = 'Updated Profile Preview';
    }

    document.getElementById('create_profile').addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      const originalLabel = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Building Profile...';
      try {
        await createProfile();
      } catch (error) {
        showStatus(error.message, 'error');
      } finally {
        btn.disabled = false;
        btn.textContent = originalLabel;
      }
    });

    document.getElementById('review_add_target_title').addEventListener('click', () => {
      const input = document.getElementById('review_target_titles_input');
      const cleaned = normalizeReviewTitle(input.value);
      if (!cleaned) return;
      reviewTargetTitles = dedupeReviewList([...reviewTargetTitles, cleaned]);
      input.value = '';
      renderReviewStep();
    });

    document.getElementById('review_add_adjacent_title').addEventListener('click', () => {
      const input = document.getElementById('review_adjacent_titles_input');
      const cleaned = normalizeReviewTitle(input.value);
      if (!cleaned) return;
      reviewAdjacentTitles = dedupeReviewList([...reviewAdjacentTitles, cleaned]);
      input.value = '';
      renderReviewStep();
    });

    document.getElementById('review_add_capability').addEventListener('click', () => {
      reviewCapabilityRules = [...reviewCapabilityRules, { name: '', level: 'working', fit: 'supporting', aliases: [] }];
      renderReviewStep();
    });

    document.getElementById('review_capability_filter').addEventListener('input', () => {
      renderReviewCapabilities();
    });

    document.getElementById('confirm_review').addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      const originalLabel = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Saving Targeting...';
      try {
        await confirmReview();
      } catch (error) {
        showStatus(error.message, 'error');
      } finally {
        btn.disabled = false;
        btn.textContent = originalLabel;
      }
    });

    reviewBox.addEventListener('click', (event) => {
      const removeTarget = event.target.closest('[data-remove-review-target]');
      if (removeTarget) {
        reviewTargetTitles.splice(Number(removeTarget.dataset.removeReviewTarget), 1);
        renderReviewStep();
        return;
      }
      const removeAdjacent = event.target.closest('[data-remove-review-adjacent]');
      if (removeAdjacent) {
        reviewAdjacentTitles.splice(Number(removeAdjacent.dataset.removeReviewAdjacent), 1);
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
      const input = reviewBox.querySelector(`[data-review-alias-input="${ruleIndex}"]`);
      const cleaned = normalizeReviewAlias(input?.value || '');
      if (!cleaned) return;
      const aliases = [...(reviewCapabilityRules[ruleIndex]?.aliases || [])];
      if (!aliases.includes(cleaned)) aliases.push(cleaned);
      reviewCapabilityRules[ruleIndex] = { ...reviewCapabilityRules[ruleIndex], aliases };
      renderReviewStep();
    });

    reviewBox.addEventListener('input', (event) => {
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

    reviewBox.addEventListener('change', (event) => {
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

    reviewBox.addEventListener('keydown', (event) => {
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
      if (event.key === 'Enter' && event.target.id === 'review_adjacent_titles_input') {
        event.preventDefault();
        document.getElementById('review_add_adjacent_title').click();
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

    renderLocationSuggestions();
    loadProfileDefaults().catch(() => {});
