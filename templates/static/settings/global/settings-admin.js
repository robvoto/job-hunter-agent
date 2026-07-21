import {
  escapeHtml,
  toLines,
  setCurrencyFieldValue,
  readCurrencyFieldValue,
  setToggleChecked,
  setChoiceGroupValue,
  getChoiceGroupValue,
  LINKEDIN_EASY_APPLY_ONLY,
} from '../shared/settings-utils.js';

export const JobHunterAdminSettings = (function () {
  const PLAYWRIGHT_TIMEOUT_MS_PER_SECOND = 1000;
  const PROMPT_TEMPLATE_FIELDS = [
    ['compensation_target_yearly', 'llm_prompt_compensation_target_yearly'],
    ['compensation_target_daily', 'llm_prompt_compensation_target_daily'],
    ['home_location', 'llm_prompt_home_location'],
    ['prefer_permanent', 'llm_prompt_prefer_permanent'],
  ];

  const HELP_BY_CONTROL_ID = {
    highlight_strong_capability_count: ['fit_highlights', 'strong_capability_count'],
    highlight_working_capability_count: ['fit_highlights', 'working_capability_count'],
    highlight_basic_capability_count: ['fit_highlights', 'basic_capability_count'],
    highlight_reviewed_signal_count: ['fit_highlights', 'reviewed_signal_count'],
    highlight_max_highlights: ['fit_highlights', 'max_highlights'],
    search_default_date_range_days: ['search_settings', 'date_range_days'],
    search_default_linkedin_hours_old: ['search_settings', 'linkedin_hours_old'],
    search_default_linkedin_results_per_search: ['search_settings', 'linkedin_results_per_search'],
    search_default_sort_newest_first: ['search_settings', 'sort_newest_first'],
    search_default_linkedin_easy_apply_only: ['search_settings', 'linkedin_easy_apply_only'],
    default_country_suffix: ['default_country_suffix', null],
    playwright_headless: ['playwright_settings', 'headless'],
    playwright_browser_mode: ['playwright_settings', 'playwright_browser_mode'],
    seek_assisted_verification_enabled: ['playwright_settings', 'seek_assisted_verification_enabled'],
    playwright_viewport_width: ['playwright_settings', 'playwright_viewport_width'],
    playwright_viewport_height: ['playwright_settings', 'playwright_viewport_height'],
    playwright_selector_timeout: ['playwright_settings', 'playwright_selector_timeout'],
    session_max_age_days: ['playwright_settings', 'session_max_age_days'],
    search_limit_date_range_days_min: ['limits.search', 'date_range_days'],
    search_limit_date_range_days_max: ['limits.search', 'date_range_days'],
    search_limit_seek_max_pages_min: ['limits.search', 'seek_max_pages'],
    search_limit_seek_max_pages_max: ['limits.search', 'seek_max_pages'],
    search_limit_linkedin_hours_old_min: ['limits.search', 'linkedin_hours_old'],
    search_limit_linkedin_hours_old_max: ['limits.search', 'linkedin_hours_old'],
    search_limit_linkedin_results_per_search_min: ['limits.search', 'linkedin_results_per_search'],
    search_limit_linkedin_results_per_search_max: ['limits.search', 'linkedin_results_per_search'],
    salary_limit_minimum_salary_yearly_max: ['limits.salary', 'minimum_salary_yearly'],
    salary_limit_minimum_daily_rate_max: ['limits.salary', 'minimum_daily_rate'],
    evidence_primary_weight: ['candidate_profile_tier_weights', 'primary_candidate_profile_context'],
    evidence_secondary_weight: ['candidate_profile_tier_weights', 'secondary_candidate_profile_context'],
    evidence_supplementary_weight: ['candidate_profile_tier_weights', 'supplementary_candidate_profile_context'],
    preference_fit_weight: ['preference_weights', 'fit'],
    preference_salary_weight: ['preference_weights', 'salary'],
    preference_location_weight: ['preference_weights', 'location'],
    preference_freshness_weight: ['preference_weights', 'freshness'],
    history_job_history_max_entries: ['history_settings', 'job_history_max_entries'],
    history_job_history_max_age_days: ['history_settings', 'job_history_max_age_days'],
    history_archive_stale_after_days: ['history_settings', 'archive_stale_after_days'],
    history_hidden_review_days: ['history_settings', 'hidden_review_days'],
    history_repeated_listing_min_times_seen: ['history_settings', 'repeated_listing_min_times_seen'],
    history_repeated_listing_min_span_days: ['history_settings', 'repeated_listing_min_span_days'],
    history_multi_listing_red_flag_min_listings: ['history_settings', 'multi_listing_red_flag_min_listings'],
    history_multi_listing_red_flag_min_span_days: ['history_settings', 'multi_listing_red_flag_min_span_days'],
    cache_llm_cache_max_entries: ['cache_settings', 'llm_cache_max_entries'],
    cache_llm_cache_max_age_days: ['cache_settings', 'llm_cache_max_age_days'],
    cache_cv_extraction_cache_max_entries: ['cache_settings', 'cv_extraction_cache_max_entries'],
    cache_cv_extraction_cache_max_age_days: ['cache_settings', 'cv_extraction_cache_max_age_days'],
    cache_candidate_application_history_cache_max_entries: ['cache_settings', 'candidate_application_history_cache_max_entries'],
    cache_candidate_application_history_cache_max_age_days: ['cache_settings', 'candidate_application_history_cache_max_age_days'],
    cache_occupation_title_cache_max_entries: ['cache_settings', 'occupation_title_cache_max_entries'],
    cache_occupation_title_cache_max_age_days: ['cache_settings', 'occupation_title_cache_max_age_days'],
    description_trust_min_trusted_description_length: ['description_trust_settings', 'min_trusted_description_length'],
    source_document_allowed_suffixes: ['source_document_settings', 'allowed_suffixes'],
    onboarding_extraction_lookback_years: ['onboarding_settings', 'extraction_lookback_years'],
    onboarding_title_extraction_min_months: ['onboarding_settings', 'title_extraction_min_months'],
    onboarding_max_target_patterns: ['onboarding_settings', 'max_target_patterns'],
    onboarding_max_secondary_patterns: ['onboarding_settings', 'max_secondary_patterns'],
    onboarding_cv_max_pages: ['onboarding_settings', 'cv_max_pages'],
    onboarding_capability_alias_limit: ['onboarding_settings', 'capability_alias_limit'],
    onboarding_signal_cluster_min_alias_hits: ['onboarding_settings', 'signal_cluster_min_alias_hits'],
    onboarding_signal_cluster_min_snippet_hits: ['onboarding_settings', 'signal_cluster_min_snippet_hits'],
    onboarding_signal_cluster_dense_snippet_alias_hits: ['onboarding_settings', 'signal_cluster_dense_snippet_alias_hits'],
    onboarding_capability_strength_preset: ['onboarding_settings', 'capability_strength_preset'],
    llm_model_options: ['llm_settings', 'model_options'],
    llm_max_llm_chars: ['llm_settings', 'max_llm_chars'],
    llm_pricing_per_1m: ['llm_settings', 'pricing_per_1m'],
    llm_prompt_fit_review_debug_match_diagnostics_enabled: ['llm_settings.llm_prompt_settings', 'fit_review_debug_match_diagnostics_enabled'],
  };

  let globalSettingsHelp = null;
  let globalSettingsHelpPromise = null;

  function helpTextFor(groupKey, fieldKey) {
    const group = globalSettingsHelp?.groups?.[groupKey];
    if (!group) return '';
    if (fieldKey) return String(group.fields?.[fieldKey] || group.description || '').trim();
    return String(group.description || '').trim();
  }

  function findLabelForControl(controlId) {
    return document.querySelector(`label[for="${CSS.escape(controlId)}"]`);
  }

  function requireElement(controlId) {
    const element = document.getElementById(controlId);
    if (!element) {
      throw new Error(`Missing global settings element: ${controlId}`);
    }
    return element;
  }

  function setFieldValue(controlId, value) {
    const element = requireElement(controlId);
    element.value = String(value ?? '');
  }

  function setFieldText(controlId, value) {
    const element = requireElement(controlId);
    element.textContent = String(value ?? '');
  }

  function setOptionalFieldText(controlId, value) {
    const element = document.getElementById(controlId);
    if (!element) return;
    element.textContent = String(value ?? '');
  }

  function ensureHelpPanelForControl(controlId) {
    const label = findLabelForControl(controlId);
    if (!label) {
      throw new Error(`Missing global settings label: ${controlId}`);
    }
    const existingRow = label.closest('.field-label-row');
    let drawer = existingRow?.querySelector('details.field-info-drawer');
    if (!drawer) {
      const row = document.createElement('div');
      row.className = 'field-label-row';
      label.parentNode.insertBefore(row, label);
      row.appendChild(label);
      drawer = document.createElement('details');
      drawer.className = 'field-info-drawer settings-help-drawer';
      const summary = document.createElement('summary');
      summary.className = 'field-info';
      summary.setAttribute('aria-label', 'Help');
      summary.textContent = 'i';
      const panel = document.createElement('div');
      panel.className = 'field-info-panel';
      drawer.append(summary, panel);
      row.appendChild(drawer);
    }
    const panel = drawer.querySelector('.field-info-panel');
    if (!panel) {
      throw new Error(`Missing global settings help panel: ${controlId}`);
    }
    return panel;
  }

  function applyGlobalSettingsHelp() {
    if (!globalSettingsHelp?.groups) return;
    for (const [controlId, [groupKey, fieldKey]] of Object.entries(HELP_BY_CONTROL_ID)) {
      const panel = ensureHelpPanelForControl(controlId);
      if (!panel) continue;
      const text = helpTextFor(groupKey, fieldKey);
      if (!text) continue;
      panel.textContent = text;
    }
  }

  async function loadGlobalSettingsHelp() {
    if (globalSettingsHelpPromise) return globalSettingsHelpPromise;
    globalSettingsHelpPromise = fetch('/data/config/global_settings_help.json', { cache: 'no-store' })
      .then((response) => {
        if (!response.ok) throw new Error('Could not load global settings help');
        return response.json();
      })
      .then((payload) => {
        globalSettingsHelp = payload;
        applyGlobalSettingsHelp();
        return payload;
      })
      .catch((error) => {
        console.warn('[GLOBAL_SETTINGS_HELP] failed to load', error);
        return null;
      });
    return globalSettingsHelpPromise;
  }


  // Fills the admin/global-settings form. Caller is responsible for storing settings
  // in loadedGlobalSettings and calling renderLlmModelOptions() afterwards.
  function fillGlobalForm(settings) {
    const fitHl = settings.fit_highlights || {};
    const searchDefaults = settings.search_settings || {};
    const limits = settings.limits || {};
    const searchLimits = limits.search || {};
    const evidenceWeights = settings.candidate_profile_tier_weights || {};
    const preferenceWeights = settings.preference_weights || {};
    const historySettings = settings.history_settings || {};
    const cacheSettings = settings.cache_settings || {};
    const descriptionTrustSettings = settings.description_trust_settings || {};
    const descriptionCompactionSettings = settings.description_compaction_settings || {};
    const sourceDocumentSettings = settings.source_document_settings || {};
    const defaultCountrySuffix = settings.default_country_suffix || '';
    const salaryLimits = limits.salary || {};
    const onboarding = settings.onboarding_settings || {};
    const llmSettings = settings.llm_settings || {};
    const playwrightSettings = settings.playwright_settings || {};
    const setBounds = (id, bounds) => {
      const input = document.getElementById(id);
      if (!input || !bounds) return;
      if (bounds.min !== undefined) input.min = String(bounds.min);
      if (bounds.max !== undefined) input.max = String(bounds.max);
    };

    setFieldValue('highlight_strong_capability_count', fitHl.strong_capability_count);
    setFieldValue('highlight_working_capability_count', fitHl.working_capability_count);
    setFieldValue('highlight_basic_capability_count', fitHl.basic_capability_count);
    setFieldValue('highlight_reviewed_signal_count', fitHl.reviewed_signal_count);
    setFieldValue('highlight_max_highlights', fitHl.max_highlights);

    setFieldValue('search_default_date_range_days', searchDefaults.date_range_days);
    setChoiceGroupValue('seek_max_pages', searchDefaults.seek_max_pages);
    setFieldValue('search_default_linkedin_hours_old', searchDefaults.linkedin_hours_old);
    setFieldValue('search_default_linkedin_results_per_search', searchDefaults.linkedin_results_per_search);
    setToggleChecked('search_default_sort_newest_first', searchDefaults.sort_newest_first !== false);
    const liEasyApply = searchDefaults[LINKEDIN_EASY_APPLY_ONLY];
    setFieldValue('search_default_' + LINKEDIN_EASY_APPLY_ONLY, (liEasyApply === null || liEasyApply === undefined) ? '' : liEasyApply);
    setBounds('search_default_date_range_days', searchLimits.date_range_days);
    setBounds('search_default_linkedin_hours_old', searchLimits.linkedin_hours_old);
    setBounds('search_default_linkedin_results_per_search', searchLimits.linkedin_results_per_search);
    setFieldValue('default_country_suffix', defaultCountrySuffix);
    setFieldValue('session_max_age_days', playwrightSettings.session_max_age_days);
    requireElement('playwright_headless').checked = playwrightSettings.headless !== false;
    setFieldValue(
      'playwright_browser_mode',
      playwrightSettings.playwright_browser_mode || 'ephemeral',
    );
    requireElement('seek_assisted_verification_enabled').checked = playwrightSettings.seek_assisted_verification_enabled === true;
    setFieldValue('playwright_viewport_width', playwrightSettings.playwright_viewport_width);
    setFieldValue('playwright_viewport_height', playwrightSettings.playwright_viewport_height);
    setFieldValue(
      'playwright_selector_timeout',
      playwrightSettings.playwright_selector_timeout === undefined
        ? ''
        : Number(playwrightSettings.playwright_selector_timeout) / PLAYWRIGHT_TIMEOUT_MS_PER_SECOND,
    );

    const rangeText = (value) => value?.min !== undefined && value?.max !== undefined ? `${value.min} to ${value.max}` : 'managed by the server';
    setOptionalFieldText('search_default_date_range_days_bounds', rangeText(searchLimits.date_range_days));
    setOptionalFieldText('search_default_seek_max_pages_bounds', rangeText(searchLimits.seek_max_pages));
    setOptionalFieldText('search_default_linkedin_hours_old_bounds', rangeText(searchLimits.linkedin_hours_old));
    setOptionalFieldText('search_default_linkedin_results_per_search_bounds', rangeText(searchLimits.linkedin_results_per_search));

    setFieldValue('evidence_primary_weight', evidenceWeights.primary_candidate_profile_context);
    setFieldValue('evidence_secondary_weight', evidenceWeights.secondary_candidate_profile_context);
    setFieldValue('evidence_supplementary_weight', evidenceWeights.supplementary_candidate_profile_context);

    setFieldValue('preference_fit_weight', preferenceWeights.fit);
    setFieldValue('preference_salary_weight', preferenceWeights.salary);
    setFieldValue('preference_location_weight', preferenceWeights.location);
    setFieldValue('preference_freshness_weight', preferenceWeights.freshness);

    setFieldValue('history_job_history_max_entries', historySettings.job_history_max_entries);
    setFieldValue('history_job_history_max_age_days', historySettings.job_history_max_age_days);
    setFieldValue('history_repeated_listing_min_times_seen', historySettings.repeated_listing_min_times_seen);
    setFieldValue('history_repeated_listing_min_span_days', historySettings.repeated_listing_min_span_days);
    setFieldValue('history_multi_listing_red_flag_min_listings', historySettings.multi_listing_red_flag_min_listings);
    setFieldValue('history_multi_listing_red_flag_min_span_days', historySettings.multi_listing_red_flag_min_span_days);
    setFieldValue('cache_llm_cache_max_entries', cacheSettings.llm_cache_max_entries);
    setFieldValue('cache_llm_cache_max_age_days', cacheSettings.llm_cache_max_age_days);
    setFieldValue('cache_cv_extraction_cache_max_entries', cacheSettings.cv_extraction_cache_max_entries);
    setFieldValue('cache_cv_extraction_cache_max_age_days', cacheSettings.cv_extraction_cache_max_age_days);
    setFieldValue('cache_candidate_application_history_cache_max_entries', cacheSettings.candidate_application_history_cache_max_entries);
    setFieldValue('cache_candidate_application_history_cache_max_age_days', cacheSettings.candidate_application_history_cache_max_age_days);
    setFieldValue('cache_occupation_title_cache_max_entries', cacheSettings.occupation_title_cache_max_entries);
    setFieldValue('cache_occupation_title_cache_max_age_days', cacheSettings.occupation_title_cache_max_age_days);
    setFieldValue('onboarding_extraction_lookback_years', onboarding.extraction_lookback_years);
    setFieldValue('onboarding_title_extraction_min_months', onboarding.title_extraction_min_months);
    setFieldValue('onboarding_max_target_patterns', onboarding.max_target_patterns);
    setFieldValue('onboarding_max_secondary_patterns', onboarding.max_secondary_patterns);
    setFieldValue('onboarding_cv_max_pages', onboarding.cv_max_pages);
    setFieldValue('onboarding_capability_alias_limit', onboarding.capability_alias_limit);
    setFieldValue('onboarding_signal_cluster_min_alias_hits', onboarding.signal_cluster_min_alias_hits);
    setFieldValue('onboarding_signal_cluster_min_snippet_hits', onboarding.signal_cluster_min_snippet_hits);
    setFieldValue('onboarding_signal_cluster_dense_snippet_alias_hits', onboarding.signal_cluster_dense_snippet_alias_hits);
    setFieldValue('onboarding_capability_strength_preset', onboarding.capability_strength_preset || '');
    setFieldValue('llm_model_options', (llmSettings.model_options || []).join('\n'));
    setBounds('llm_max_llm_chars', llmSettings.max_llm_chars_limits);
    setFieldValue('llm_max_llm_chars', llmSettings.max_llm_chars);
    setFieldValue('llm_pricing_per_1m', JSON.stringify(llmSettings.pricing_per_1m || {}, null, 2));
    const promptTemplates = llmSettings.llm_prompt_settings?.match_preference_templates || {};
    requireElement('llm_prompt_fit_review_debug_match_diagnostics_enabled').checked =
      llmSettings.llm_prompt_settings?.fit_review_debug_match_diagnostics_enabled === true;
    for (const [templateKey, fieldId] of PROMPT_TEMPLATE_FIELDS) {
      setFieldValue(fieldId, promptTemplates[templateKey]);
    }

    setFieldValue('history_archive_stale_after_days', historySettings.archive_stale_after_days);
    setFieldValue('history_hidden_review_days', historySettings.hidden_review_days);
    setFieldValue('description_trust_min_trusted_description_length', descriptionTrustSettings.min_trusted_description_length);
    requireElement('description_compaction_enabled').checked = !!descriptionCompactionSettings.enabled;
    setFieldValue('description_compaction_min_chars', descriptionCompactionSettings.default_min_compacted_chars);
    setFieldValue('description_compaction_min_retention', descriptionCompactionSettings.min_retention_ratio);
    setFieldValue('source_document_allowed_suffixes', (sourceDocumentSettings.allowed_suffixes || []).join('\n'));
    requireElement('source_document_allowed_suffixes').setAttribute('readonly', 'readonly');

    setFieldValue('search_limit_date_range_days_min', searchLimits.date_range_days?.min);
    setFieldValue('search_limit_date_range_days_max', searchLimits.date_range_days?.max);
    setFieldValue('search_limit_seek_max_pages_min', searchLimits.seek_max_pages?.min);
    setFieldValue('search_limit_seek_max_pages_max', searchLimits.seek_max_pages?.max);
    setFieldValue('search_limit_linkedin_hours_old_min', searchLimits.linkedin_hours_old?.min);
    setFieldValue('search_limit_linkedin_hours_old_max', searchLimits.linkedin_hours_old?.max);
    setFieldValue('search_limit_linkedin_results_per_search_min', searchLimits.linkedin_results_per_search?.min);
    setFieldValue('search_limit_linkedin_results_per_search_max', searchLimits.linkedin_results_per_search?.max);
    setCurrencyFieldValue('salary_limit_minimum_salary_yearly_max', salaryLimits.minimum_salary_yearly?.max ?? '');
    setCurrencyFieldValue('salary_limit_minimum_daily_rate_max', salaryLimits.minimum_daily_rate?.max ?? '');

    const presetPanel = document.getElementById('capability_strength_presets_panel');
    const presetTable = onboarding.capability_strength_presets || {};
    if (presetPanel) {
      const presetRows = Object.entries(presetTable).map(([presetName, presetValues]) => {
        const valueRows = Object.entries(presetValues || {}).map(([key, value]) => `
          <div class="capability-preset-value-row">
            <span class="capability-preset-key">${escapeHtml(key)}</span>
            <span class="capability-preset-value">${escapeHtml(String(value))}</span>
          </div>
        `).join('');

        return `
          <article class="capability-preset-card">
            <h3>${escapeHtml(presetName)}</h3>
            <div class="capability-preset-values">
              ${valueRows || '<span class="help">No values</span>'}
            </div>
          </article>
        `;
      }).join('');
      presetPanel.innerHTML = `
        <div class="capability-preset-grid">
          ${presetRows || '<p class="help">No capability presets loaded.</p>'}
        </div>
      `;
    }
  }

  // Collects admin form values. Takes the previously loaded global settings as a
  // baseline so unedited keys are preserved.
  function collectGlobalSettings(current) {
    current = current || {};
    const currentSearch = current.search_settings || {};
    const currentLimitsGroup = current.limits || {};
    const currentSearchLimits = currentLimitsGroup.search || {};
    const currentSalaryLimits = currentLimitsGroup.salary || {};
    const currentHistory = current.history_settings || {};
    const currentCacheSettings = current.cache_settings || {};
    const currentDescriptionTrust = current.description_trust_settings || {};
    const currentCompaction = current.description_compaction_settings || {};
    const currentSourceDocuments = current.source_document_settings || {};
    const currentPreferenceWeights = current.preference_weights || {};
    const currentEvidenceWeights = current.candidate_profile_tier_weights || {};
    const currentReviewSettings = current.review_settings || {};
    const currentPlaywright = current.playwright_settings || {};
    const currentOnboarding = current.onboarding_settings || {};
    const currentLlmSettings = current.llm_settings || {};
    const currentLlmPromptSettings = currentLlmSettings.llm_prompt_settings || {};
    const readNumber = (id, fallback) => {
      const raw = Number(document.getElementById(id).value);
      return Number.isNaN(raw) ? fallback : raw;
    };
    const readSecondsAsMilliseconds = (id, fallbackMilliseconds) => {
      const fallbackSeconds = fallbackMilliseconds === undefined
        ? undefined
        : fallbackMilliseconds / PLAYWRIGHT_TIMEOUT_MS_PER_SECOND;
      const secondsValue = readNumber(id, fallbackSeconds);
      return secondsValue === undefined
        ? fallbackMilliseconds
        : secondsValue * PLAYWRIGHT_TIMEOUT_MS_PER_SECOND;
    };
    return {
      fit_highlights: {
        strong_capability_count: readNumber('highlight_strong_capability_count', current.fit_highlights?.strong_capability_count),
        working_capability_count: readNumber('highlight_working_capability_count', current.fit_highlights?.working_capability_count),
        basic_capability_count: readNumber('highlight_basic_capability_count', current.fit_highlights?.basic_capability_count),
        reviewed_signal_count: readNumber('highlight_reviewed_signal_count', current.fit_highlights?.reviewed_signal_count),
        max_highlights: readNumber('highlight_max_highlights', current.fit_highlights?.max_highlights),
      },
      search_settings: {
        ...currentSearch,
        date_range_days: readNumber('search_default_date_range_days', currentSearch.date_range_days),
        seek_max_pages: (() => {
          const value = Number(getChoiceGroupValue('seek_max_pages'));
          if (!Number.isFinite(value)) {
            throw new Error('Invalid SEEK page default.');
          }
          return value;
        })(),
        linkedin_hours_old: readNumber('search_default_linkedin_hours_old', currentSearch.linkedin_hours_old),
        linkedin_results_per_search: readNumber('search_default_linkedin_results_per_search', currentSearch.linkedin_results_per_search),
        sort_newest_first: Boolean(document.getElementById('search_default_sort_newest_first')?.checked),
        [LINKEDIN_EASY_APPLY_ONLY]: (() => {
          const raw = document.getElementById('search_default_' + LINKEDIN_EASY_APPLY_ONLY).value;
          if (raw === '') return null;
          return raw === 'true';
        })(),
      },
      default_country_suffix: document.getElementById('default_country_suffix').value.trim(),
      limits: {
        ...currentLimitsGroup,
        search: {
          ...currentSearchLimits,
          date_range_days: {
            min: readNumber('search_limit_date_range_days_min', currentSearchLimits.date_range_days?.min),
            max: readNumber('search_limit_date_range_days_max', currentSearchLimits.date_range_days?.max),
          },
          seek_max_pages: {
            min: readNumber('search_limit_seek_max_pages_min', currentSearchLimits.seek_max_pages?.min),
            max: readNumber('search_limit_seek_max_pages_max', currentSearchLimits.seek_max_pages?.max),
          },
          linkedin_hours_old: {
            min: readNumber('search_limit_linkedin_hours_old_min', currentSearchLimits.linkedin_hours_old?.min),
            max: readNumber('search_limit_linkedin_hours_old_max', currentSearchLimits.linkedin_hours_old?.max),
          },
          linkedin_results_per_search: {
            min: readNumber('search_limit_linkedin_results_per_search_min', currentSearchLimits.linkedin_results_per_search?.min),
            max: readNumber('search_limit_linkedin_results_per_search_max', currentSearchLimits.linkedin_results_per_search?.max),
          },
        },
        salary: {
          ...currentSalaryLimits,
          minimum_salary_yearly: {
            min: currentSalaryLimits.minimum_salary_yearly?.min ?? 0,
            max: readCurrencyFieldValue('salary_limit_minimum_salary_yearly_max', currentSalaryLimits.minimum_salary_yearly?.max),
          },
          minimum_daily_rate: {
            min: currentSalaryLimits.minimum_daily_rate?.min ?? 0,
            max: readCurrencyFieldValue('salary_limit_minimum_daily_rate_max', currentSalaryLimits.minimum_daily_rate?.max),
          },
        },
      },
      preference_weights: {
        ...currentPreferenceWeights,
        fit: readNumber('preference_fit_weight', currentPreferenceWeights.fit),
        salary: readNumber('preference_salary_weight', currentPreferenceWeights.salary),
        location: readNumber('preference_location_weight', currentPreferenceWeights.location),
        freshness: readNumber('preference_freshness_weight', currentPreferenceWeights.freshness),
      },
      candidate_profile_tier_weights: {
        ...currentEvidenceWeights,
        primary_candidate_profile_context: readNumber('evidence_primary_weight', currentEvidenceWeights.primary_candidate_profile_context),
        secondary_candidate_profile_context: readNumber('evidence_secondary_weight', currentEvidenceWeights.secondary_candidate_profile_context),
        supplementary_candidate_profile_context: readNumber('evidence_supplementary_weight', currentEvidenceWeights.supplementary_candidate_profile_context),
      },
      history_settings: {
        ...currentHistory,
        job_history_max_entries: readNumber('history_job_history_max_entries', currentHistory.job_history_max_entries),
        job_history_max_age_days: readNumber('history_job_history_max_age_days', currentHistory.job_history_max_age_days),
        archive_stale_after_days: readNumber('history_archive_stale_after_days', currentHistory.archive_stale_after_days),
        hidden_review_days: readNumber('history_hidden_review_days', currentHistory.hidden_review_days),
        repeated_listing_min_times_seen: readNumber('history_repeated_listing_min_times_seen', currentHistory.repeated_listing_min_times_seen),
        repeated_listing_min_span_days: readNumber('history_repeated_listing_min_span_days', currentHistory.repeated_listing_min_span_days),
        multi_listing_red_flag_min_listings: readNumber('history_multi_listing_red_flag_min_listings', currentHistory.multi_listing_red_flag_min_listings),
        multi_listing_red_flag_min_span_days: readNumber('history_multi_listing_red_flag_min_span_days', currentHistory.multi_listing_red_flag_min_span_days),
      },
      cache_settings: {
        ...currentCacheSettings,
        llm_cache_max_entries: readNumber('cache_llm_cache_max_entries', currentCacheSettings.llm_cache_max_entries),
        llm_cache_max_age_days: readNumber('cache_llm_cache_max_age_days', currentCacheSettings.llm_cache_max_age_days),
        cv_extraction_cache_max_entries: readNumber('cache_cv_extraction_cache_max_entries', currentCacheSettings.cv_extraction_cache_max_entries),
        cv_extraction_cache_max_age_days: readNumber(
          'cache_cv_extraction_cache_max_age_days',
          currentCacheSettings.cv_extraction_cache_max_age_days,
        ),
        candidate_application_history_cache_max_entries: readNumber(
          'cache_candidate_application_history_cache_max_entries',
          currentCacheSettings.candidate_application_history_cache_max_entries,
        ),
        candidate_application_history_cache_max_age_days: readNumber(
          'cache_candidate_application_history_cache_max_age_days',
          currentCacheSettings.candidate_application_history_cache_max_age_days,
        ),
        occupation_title_cache_max_entries: readNumber(
          'cache_occupation_title_cache_max_entries',
          currentCacheSettings.occupation_title_cache_max_entries,
        ),
        occupation_title_cache_max_age_days: readNumber(
          'cache_occupation_title_cache_max_age_days',
          currentCacheSettings.occupation_title_cache_max_age_days,
        ),
      },
      description_trust_settings: {
        ...currentDescriptionTrust,
        min_trusted_description_length: readNumber(
          'description_trust_min_trusted_description_length',
          currentDescriptionTrust.min_trusted_description_length,
        ),
      },
      description_compaction_settings: {
        ...currentCompaction,
        enabled: document.getElementById('description_compaction_enabled').checked,
        default_min_compacted_chars: readNumber('description_compaction_min_chars', currentCompaction.default_min_compacted_chars),
        min_retention_ratio: readNumber('description_compaction_min_retention', currentCompaction.min_retention_ratio),
      },
      source_document_settings: { ...currentSourceDocuments },
      onboarding_settings: {
        ...currentOnboarding,
        extraction_lookback_years: readNumber('onboarding_extraction_lookback_years', currentOnboarding.extraction_lookback_years),
        title_extraction_min_months: readNumber('onboarding_title_extraction_min_months', currentOnboarding.title_extraction_min_months),
        max_target_patterns: readNumber('onboarding_max_target_patterns', currentOnboarding.max_target_patterns),
        max_secondary_patterns: readNumber('onboarding_max_secondary_patterns', currentOnboarding.max_secondary_patterns),
        cv_max_pages: readNumber('onboarding_cv_max_pages', currentOnboarding.cv_max_pages),
        capability_alias_limit: readNumber('onboarding_capability_alias_limit', currentOnboarding.capability_alias_limit),
        signal_cluster_min_alias_hits: readNumber('onboarding_signal_cluster_min_alias_hits', currentOnboarding.signal_cluster_min_alias_hits),
        signal_cluster_min_snippet_hits: readNumber('onboarding_signal_cluster_min_snippet_hits', currentOnboarding.signal_cluster_min_snippet_hits),
        signal_cluster_dense_snippet_alias_hits: readNumber('onboarding_signal_cluster_dense_snippet_alias_hits', currentOnboarding.signal_cluster_dense_snippet_alias_hits),
        capability_strength_preset: document.getElementById('onboarding_capability_strength_preset').value || currentOnboarding.capability_strength_preset,
      },
      llm_settings: {
        ...currentLlmSettings,
        model_options: toLines(document.getElementById('llm_model_options').value),
        max_llm_chars: readNumber('llm_max_llm_chars', currentLlmSettings.max_llm_chars),
        pricing_per_1m: JSON.parse(document.getElementById('llm_pricing_per_1m').value.trim() || '{}'),
        llm_prompt_settings: {
          ...currentLlmPromptSettings,
          fit_review_debug_match_diagnostics_enabled: Boolean(
            document.getElementById('llm_prompt_fit_review_debug_match_diagnostics_enabled')?.checked,
          ),
          match_preference_templates: Object.fromEntries(
            PROMPT_TEMPLATE_FIELDS.map(([templateKey, fieldId]) => [
              templateKey,
              document.getElementById(fieldId).value.trim(),
            ]),
          ),
        },
      },
      review_settings: { ...currentReviewSettings },
      playwright_settings: {
        ...currentPlaywright,
        headless: document.getElementById('playwright_headless').checked,
        playwright_browser_mode:
          document.getElementById('playwright_browser_mode').value || currentPlaywright.playwright_browser_mode,
        seek_assisted_verification_enabled: document.getElementById('seek_assisted_verification_enabled').checked,
        playwright_viewport_width: readNumber('playwright_viewport_width', currentPlaywright.playwright_viewport_width),
        playwright_viewport_height: readNumber('playwright_viewport_height', currentPlaywright.playwright_viewport_height),
        playwright_selector_timeout: readSecondsAsMilliseconds(
          'playwright_selector_timeout',
          currentPlaywright.playwright_selector_timeout,
        ),
        session_max_age_days: readNumber('session_max_age_days', currentPlaywright.session_max_age_days),
      },
    };
  }

  function initKnowledgeSyncControls(showStatus) {
    const button = document.getElementById('knowledge_sync_button');
    const status = document.getElementById('knowledge_sync_status');
    if (!button || !status || typeof window.jobHunterFetch !== 'function') {
      return;
    }
    if (button.dataset.syncBound === 'true') {
      return;
    }
    button.dataset.syncBound = 'true';

    const setStatus = (message, kind) => {
      status.textContent = String(message || '');
      status.className = kind ? `field-help sync-status sync-status--${kind}` : 'field-help';
      if (typeof showStatus === 'function') {
        showStatus(message, kind);
      }
    };

    button.addEventListener('click', async () => {
      const originalLabel = button.textContent;
      button.disabled = true;
      button.textContent = 'Syncing...';
      setStatus('Syncing approved knowledge with AWS...', 'loading');

      try {
        const response = await window.jobHunterFetch('/api/admin/knowledge-sync', {
          method: 'POST',
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          throw new Error(payload.error || 'Could not sync knowledge.');
        }
        setStatus('Synced approved knowledge with AWS.', 'success');
      } catch (error) {
        setStatus(error.message || 'Could not sync knowledge.', 'error');
      } finally {
        button.disabled = false;
        button.textContent = originalLabel;
      }
    });
  }

  function initRejectionHistorySyncControls(showStatus) {
    const button = document.getElementById('rejection_history_sync_button');
    const status = document.getElementById('rejection_history_sync_status');
    if (!button || !status || typeof window.jobHunterFetch !== 'function') {
      return;
    }
    if (button.dataset.syncBound === 'true') {
      return;
    }
    button.dataset.syncBound = 'true';

    const setStatus = (message, kind) => {
      status.textContent = String(message || '');
      status.className = kind ? `field-help sync-status sync-status--${kind}` : 'field-help';
      if (typeof showStatus === 'function') {
        showStatus(message, kind);
      }
    };

    button.addEventListener('click', async () => {
      const originalLabel = button.textContent;
      button.disabled = true;
      button.textContent = 'Syncing...';
      setStatus('Fetching rejection history from sheet...', 'loading');

      try {
        const response = await window.jobHunterFetch('/api/admin/rejection-history-sync', {
          method: 'POST',
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(payload.error || 'Could not sync rejection history.');
        }
        setStatus(payload.message || 'Rejection history synced.', 'success');
      } catch (error) {
        setStatus(error.message || 'Could not sync rejection history.', 'error');
      } finally {
        button.disabled = false;
        button.textContent = originalLabel;
      }
    });
  }

  function systemWarningSeverityClass(severity) {
    const level = String(severity || '').trim().toLowerCase();
    if (level === 'critical') return 'system-warning-pill--critical';
    if (level === 'error') return 'system-warning-pill--error';
    if (level === 'warning') return 'system-warning-pill--warning';
    return 'system-warning-pill--info';
  }

  function systemWarningLabel(value) {
    return String(value || '').replace(/_/g, ' ').trim() || 'unknown';
  }

  function systemWarningContextHtml(context) {
    if (!context || (typeof context === 'object' && Object.keys(context).length === 0)) {
      return '';
    }
    const contextText = typeof context === 'string' ? context : JSON.stringify(context, null, 2);
    return `
      <details class="system-warning-context">
        <summary>Context</summary>
        <pre>${escapeHtml(contextText)}</pre>
      </details>
    `;
  }

  function renderSystemWarningCard(warning) {
    const severity = systemWarningLabel(warning?.severity);
    const category = systemWarningLabel(warning?.category);
    const status = systemWarningLabel(warning?.status);
    const source = String(warning?.source || '').trim() || 'unknown';
    const message = String(warning?.message || '').trim() || 'No message';
    const jobKey = String(warning?.job_key || '').trim();
    const runId = String(warning?.run_id || '').trim();
    const lastSeen = String(warning?.last_seen_at || '').trim();
    const count = Number(warning?.count || 0);
    const context = warning?.context;

    return `
      <article class="system-warning-card" data-warning-id="${escapeHtml(String(warning?.id || ''))}">
        <div class="system-warning-card__head">
          <div class="system-warning-card__copy">
            <h3 class="system-warning-card__title">${escapeHtml(message)}</h3>
            <div class="system-warning-card__message">
              ${escapeHtml(category)} · ${escapeHtml(source)}
            </div>
            <div class="system-warning-card__meta">
              <span><strong>Status:</strong> ${escapeHtml(status)}</span>
              <span><strong>Count:</strong> ${Number.isFinite(count) ? count : 0}</span>
              ${jobKey ? `<span><strong>Job:</strong> ${escapeHtml(jobKey)}</span>` : ''}
              ${runId ? `<span><strong>Run:</strong> ${escapeHtml(runId)}</span>` : ''}
              ${lastSeen ? `<span><strong>Last seen:</strong> ${escapeHtml(lastSeen)}</span>` : ''}
            </div>
          </div>
          <div class="system-warning-pill-row">
            <span class="system-warning-pill ${systemWarningSeverityClass(warning?.severity)}">${escapeHtml(severity)}</span>
            <span class="system-warning-pill system-warning-pill--info">${escapeHtml(status)}</span>
          </div>
        </div>
        ${systemWarningContextHtml(context)}
        <div class="system-warning-actions">
          <button type="button" class="btn btn-secondary" data-system-warning-action="review" data-warning-id="${escapeHtml(String(warning?.id || ''))}">Review</button>
          <button type="button" class="btn btn-secondary" data-system-warning-action="dismiss" data-warning-id="${escapeHtml(String(warning?.id || ''))}">Dismiss</button>
        </div>
      </article>
    `;
  }

  async function fetchSystemWarnings() {
    const response = await window.jobHunterFetch('/api/admin/system-warnings');
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || 'Could not load system warnings.');
    }
    return Array.isArray(payload.warnings) ? payload.warnings : [];
  }

  async function updateSystemWarningStatus(warningId, status) {
    const response = await window.jobHunterFetch(`/api/admin/system-warnings/${encodeURIComponent(warningId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || 'Could not update system warning.');
    }
    return payload.warning;
  }

  async function runScraperValidation() {
    const response = await window.jobHunterFetch('/api/admin/scraper-config-validation', {
      method: 'POST',
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || 'Could not run scraper validation.');
    }
    return payload;
  }

  function initSystemWarningsControls(showStatus) {
    const panel = document.getElementById('system_warnings_panel');
    const list = document.getElementById('system_warnings_list');
    const empty = document.getElementById('system_warnings_empty');
    const status = document.getElementById('system_warnings_status');
    const refreshButton = document.getElementById('system_warnings_refresh_button');
    if (!panel || !list || !empty || !status || typeof window.jobHunterFetch !== 'function') {
      return;
    }
    if (panel.dataset.bound === 'true') {
      return;
    }
    panel.dataset.bound = 'true';

    const setStatus = (message, kind) => {
      status.textContent = String(message || '');
      status.className = kind ? `field-help sync-status sync-status--${kind}` : 'field-help';
      if (typeof showStatus === 'function') {
        showStatus(message, kind);
      }
    };

    const renderWarnings = (warnings) => {
      if (!warnings.length) {
        list.innerHTML = '';
        empty.hidden = false;
        return;
      }
      empty.hidden = true;
      list.innerHTML = warnings.map(renderSystemWarningCard).join('');
    };

    const refresh = async ({ silent = false } = {}) => {
      if (!silent) {
        setStatus('Loading unresolved warnings...', 'loading');
      }
      try {
        const warnings = await fetchSystemWarnings();
        renderWarnings(warnings);
        setStatus(
          warnings.length
            ? `${warnings.length} unresolved warning${warnings.length === 1 ? '' : 's'}.`
            : 'No unresolved system warnings.',
          'success',
        );
      } catch (error) {
        list.innerHTML = '';
        empty.hidden = false;
        setStatus(error.message || 'Could not load system warnings.', 'error');
      }
    };

    list.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-system-warning-action]');
      if (!button) return;
      const warningId = button.dataset.warningId;
      const action = button.dataset.systemWarningAction;
      if (!warningId || !action) return;
      const originalLabel = button.textContent;
      button.disabled = true;
      button.textContent = 'Saving...';
      setStatus('Updating system warning...', 'loading');
      try {
        const statusValue = action === 'review' ? 'reviewed' : 'dismissed';
        await updateSystemWarningStatus(warningId, statusValue);
        await refresh({ silent: true });
        setStatus('System warning updated.', 'success');
      } catch (error) {
        setStatus(error.message || 'Could not update system warning.', 'error');
      } finally {
        button.disabled = false;
        button.textContent = originalLabel;
      }
    });

    if (refreshButton) {
      refreshButton.addEventListener('click', () => {
        refresh();
      });
    }

    refresh();
  }

  function initScraperValidationControls(showStatus) {
    const button = document.getElementById('scraper_validation_button');
    const status = document.getElementById('scraper_validation_status');
    const results = document.getElementById('scraper_validation_results');
    if (!button || !status || !results || typeof window.jobHunterFetch !== 'function') {
      return;
    }
    if (button.dataset.bound === 'true') {
      return;
    }
    button.dataset.bound = 'true';

    const setStatus = (message, kind) => {
      status.textContent = String(message || '');
      status.className = kind ? `field-help sync-status sync-status--${kind}` : 'field-help';
      if (typeof showStatus === 'function') {
        showStatus(message, kind);
      }
    };

    const renderResults = (payload) => {
      const checks = Array.isArray(payload?.results) ? payload.results : [];
      if (!checks.length) {
        results.textContent = '';
        return;
      }
      results.innerHTML = checks
        .map((item) => {
          const source = escapeHtml(String(item?.source || 'unknown'));
          const summary = escapeHtml(String(item?.summary || ''));
          const issues = Array.isArray(item?.issues) ? item.issues : [];
          const issueHtml = issues.length
            ? `<ul>${issues.map((issue) => `<li>${escapeHtml(String(issue || ''))}</li>`).join('')}</ul>`
            : '';
          return `<div class="scraper-validation-result"><strong>${source}</strong>: ${summary}${issueHtml}</div>`;
        })
        .join('');
    };

    button.addEventListener('click', async () => {
      const originalLabel = button.textContent;
      button.disabled = true;
      button.textContent = 'Running...';
      setStatus('Running scraper validation...', 'loading');
      results.textContent = '';
      try {
        const payload = await runScraperValidation();
        renderResults(payload);
        setStatus(
          payload.summary || 'Scraper validation finished.',
          payload.ok ? 'success' : 'error',
        );
      } catch (error) {
        results.textContent = '';
        setStatus(error.message || 'Could not run scraper validation.', 'error');
      } finally {
        button.disabled = false;
        button.textContent = originalLabel;
      }
    });
  }

  function initRuntimeMaintenanceControls(showStatus) {
    const clearCachesButton = document.getElementById('clear_runtime_caches_button');
    const clearCachesStatus = document.getElementById('clear_runtime_caches_status');
    const clearSearchStateButton = document.getElementById('clear_current_user_search_state_button');
    const clearSearchStateStatus = document.getElementById('clear_current_user_search_state_status');
    if (
      !clearCachesButton
      || !clearCachesStatus
      || !clearSearchStateButton
      || !clearSearchStateStatus
      || typeof window.jobHunterFetch !== 'function'
    ) {
      return;
    }
    if (clearCachesButton.dataset.bound === 'true' && clearSearchStateButton.dataset.bound === 'true') {
      return;
    }

    const bindAction = (button, status, endpoint, loadingMessage, fallbackSuccessMessage) => {
      button.dataset.bound = 'true';
      const setStatus = (message, kind) => {
        status.textContent = String(message || '');
        status.className = kind ? `field-help sync-status sync-status--${kind}` : 'field-help';
        if (typeof showStatus === 'function') {
          showStatus(message, kind);
        }
      };

      button.addEventListener('click', async () => {
        const originalLabel = button.textContent;
        button.disabled = true;
        button.textContent = 'Working...';
        setStatus(loadingMessage, 'loading');
        try {
          const response = await window.jobHunterFetch(endpoint, { method: 'POST' });
          const payload = await response.json().catch(() => ({}));
          if (!response.ok) {
            throw new Error(payload.error || 'Could not complete admin action.');
          }
          setStatus(payload.message || fallbackSuccessMessage, 'success');
        } catch (error) {
          setStatus(error.message || 'Could not complete admin action.', 'error');
        } finally {
          button.disabled = false;
          button.textContent = originalLabel;
        }
      });
    };

    bindAction(
      clearCachesButton,
      clearCachesStatus,
      '/api/admin/clear-runtime-caches',
      'Clearing shared runtime caches...',
      'Runtime caches cleared.',
    );
    bindAction(
      clearSearchStateButton,
      clearSearchStateStatus,
      '/api/admin/clear-current-user-search-state',
      'Clearing current user search state...',
      'Current user search state cleared.',
    );
  }

  return {
    fillGlobalForm,
    collectGlobalSettings,
    loadGlobalSettingsHelp,
    applyGlobalSettingsHelp,
    initRuntimeMaintenanceControls,
    initKnowledgeSyncControls,
    initRejectionHistorySyncControls,
    initScraperValidationControls,
    initSystemWarningsControls,
  };
}());

