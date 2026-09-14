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
  const systemHealthLabels = window.__JOB_HUNTER_SYSTEM_HEALTH_LABELS__;
  if (!systemHealthLabels) {
    throw new Error('Missing system health labels.');
  }
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
    search_default_seek_enabled: ['search_settings', 'seek_enabled'],
    search_default_linkedin_enabled: ['search_settings', 'linkedin_enabled'],
    search_default_apsjobs_enabled: ['search_settings', 'apsjobs_enabled'],
    search_default_linkedin_hours_old: ['search_settings', 'linkedin_hours_old'],
    search_default_linkedin_results_per_search: ['search_settings', 'linkedin_results_per_search'],
    search_default_linkedin_jobspy_stall_timeout_seconds: ['search_settings', 'linkedin_jobspy_stall_timeout_seconds'],
    search_default_linkedin_parallel_search_workers: ['search_settings', 'linkedin_parallel_search_workers'],
    search_default_linkedin_parallel_review_workers: ['search_settings', 'linkedin_parallel_review_workers'],
    search_default_job_market_map_parallel_workers: ['search_settings', 'job_market_map_parallel_workers'],
    search_default_sort_newest_first: ['search_settings', 'sort_newest_first'],
    search_default_linkedin_easy_apply_only: ['search_settings', 'linkedin_easy_apply_only'],
    default_country_suffix: ['default_country_suffix', null],
    playwright_headless: ['playwright_settings', 'headless'],
    playwright_browser_mode: ['playwright_settings', 'playwright_browser_mode'],
    seek_assisted_verification_enabled: ['playwright_settings', 'seek_assisted_verification_enabled'],
    seek_manual_verification_timeout_ms: ['playwright_settings', 'seek_manual_verification_timeout_ms'],
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
    search_limit_linkedin_jobspy_stall_timeout_seconds_min: ['limits.search', 'linkedin_jobspy_stall_timeout_seconds'],
    search_limit_linkedin_jobspy_stall_timeout_seconds_max: ['limits.search', 'linkedin_jobspy_stall_timeout_seconds'],
    search_limit_linkedin_parallel_search_workers_min: ['limits.search', 'linkedin_parallel_search_workers'],
    search_limit_linkedin_parallel_search_workers_max: ['limits.search', 'linkedin_parallel_search_workers'],
    search_limit_linkedin_parallel_review_workers_min: ['limits.search', 'linkedin_parallel_review_workers'],
    search_limit_linkedin_parallel_review_workers_max: ['limits.search', 'linkedin_parallel_review_workers'],
    search_limit_job_market_map_parallel_workers_min: ['limits.search', 'job_market_map_parallel_workers'],
    search_limit_job_market_map_parallel_workers_max: ['limits.search', 'job_market_map_parallel_workers'],
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
    history_potential_retention_days: ['history_settings', 'potential_retention_days'],
    history_hidden_retention_days: ['history_settings', 'hidden_retention_days'],
    history_applied_retention_days: ['history_settings', 'applied_retention_days'],
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
    cache_source_discovery_cache_max_entries: ['cache_settings', 'source_discovery_cache_max_entries'],
    cache_source_discovery_cache_max_age_minutes: ['cache_settings', 'source_discovery_cache_max_age_minutes'],
    cache_search_plan_max_age_minutes: ['cache_settings', 'search_plan_max_age_minutes'],
    cache_linkedin_failure_backoff_minutes: ['cache_settings', 'linkedin_failure_backoff_minutes'],
    cache_search_plan_min_corroboration_samples: ['cache_settings', 'search_plan_min_corroboration_samples'],
    cache_linkedin_stale_fallback_max_age_minutes: ['cache_settings', 'linkedin_stale_fallback_max_age_minutes'],
    cache_linkedin_max_consecutive_target_failures: ['cache_settings', 'linkedin_max_consecutive_target_failures'],
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
    setToggleChecked('search_default_seek_enabled', searchDefaults.seek_enabled !== false);
    setToggleChecked('search_default_linkedin_enabled', searchDefaults.linkedin_enabled !== false);
    setToggleChecked('search_default_apsjobs_enabled', searchDefaults.apsjobs_enabled !== false);
    setChoiceGroupValue('seek_max_pages', searchDefaults.seek_max_pages);
    setFieldValue('search_default_linkedin_hours_old', searchDefaults.linkedin_hours_old);
    setFieldValue('search_default_linkedin_results_per_search', searchDefaults.linkedin_results_per_search);
    setFieldValue('search_default_linkedin_jobspy_stall_timeout_seconds', searchDefaults.linkedin_jobspy_stall_timeout_seconds);
    setFieldValue('search_default_linkedin_parallel_search_workers', searchDefaults.linkedin_parallel_search_workers);
    setFieldValue('search_default_linkedin_parallel_review_workers', searchDefaults.linkedin_parallel_review_workers);
    setFieldValue('search_default_job_market_map_parallel_workers', searchDefaults.job_market_map_parallel_workers);
    setToggleChecked('search_default_sort_newest_first', searchDefaults.sort_newest_first !== false);
    const liEasyApply = searchDefaults[LINKEDIN_EASY_APPLY_ONLY];
    setFieldValue('search_default_' + LINKEDIN_EASY_APPLY_ONLY, (liEasyApply === null || liEasyApply === undefined) ? '' : liEasyApply);
    setBounds('search_default_date_range_days', searchLimits.date_range_days);
    setBounds('search_default_linkedin_hours_old', searchLimits.linkedin_hours_old);
    setBounds('search_default_linkedin_results_per_search', searchLimits.linkedin_results_per_search);
    setBounds('search_default_linkedin_jobspy_stall_timeout_seconds', searchLimits.linkedin_jobspy_stall_timeout_seconds);
    setBounds('search_default_linkedin_parallel_search_workers', searchLimits.linkedin_parallel_search_workers);
    setBounds('search_default_linkedin_parallel_review_workers', searchLimits.linkedin_parallel_review_workers);
    setBounds('search_default_job_market_map_parallel_workers', searchLimits.job_market_map_parallel_workers);
    setFieldValue('default_country_suffix', defaultCountrySuffix);
    setFieldValue('session_max_age_days', playwrightSettings.session_max_age_days);
    requireElement('playwright_headless').checked = playwrightSettings.headless !== false;
    setFieldValue(
      'playwright_browser_mode',
      playwrightSettings.playwright_browser_mode || 'persistent',
    );
    requireElement('seek_assisted_verification_enabled').checked = playwrightSettings.seek_assisted_verification_enabled === true;
    setFieldValue(
      'seek_manual_verification_timeout_ms',
      playwrightSettings.seek_manual_verification_timeout_ms === undefined
        ? ''
        : Number(playwrightSettings.seek_manual_verification_timeout_ms) / PLAYWRIGHT_TIMEOUT_MS_PER_SECOND,
    );
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
    setOptionalFieldText('search_default_linkedin_jobspy_stall_timeout_seconds_bounds', rangeText(searchLimits.linkedin_jobspy_stall_timeout_seconds));
    setOptionalFieldText('search_default_linkedin_parallel_search_workers_bounds', rangeText(searchLimits.linkedin_parallel_search_workers));
    setOptionalFieldText('search_default_linkedin_parallel_review_workers_bounds', rangeText(searchLimits.linkedin_parallel_review_workers));
    setOptionalFieldText('search_default_job_market_map_parallel_workers_bounds', rangeText(searchLimits.job_market_map_parallel_workers));

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
    setFieldValue('cache_source_discovery_cache_max_entries', cacheSettings.source_discovery_cache_max_entries);
    setFieldValue('cache_source_discovery_cache_max_age_minutes', cacheSettings.source_discovery_cache_max_age_minutes);
    setFieldValue('cache_search_plan_max_age_minutes', cacheSettings.search_plan_max_age_minutes);
    setFieldValue('cache_linkedin_failure_backoff_minutes', cacheSettings.linkedin_failure_backoff_minutes);
    setFieldValue('cache_search_plan_min_corroboration_samples', cacheSettings.search_plan_min_corroboration_samples);
    setFieldValue('cache_linkedin_stale_fallback_max_age_minutes', cacheSettings.linkedin_stale_fallback_max_age_minutes);
    setFieldValue('cache_linkedin_max_consecutive_target_failures', cacheSettings.linkedin_max_consecutive_target_failures);
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
    setFieldValue('llm_temperature', llmSettings.temperature);
    setFieldValue('llm_pricing_per_1m', JSON.stringify(llmSettings.pricing_per_1m || {}, null, 2));
    const promptTemplates = llmSettings.llm_prompt_settings?.match_preference_templates || {};
    requireElement('llm_prompt_fit_review_debug_match_diagnostics_enabled').checked =
      llmSettings.llm_prompt_settings?.fit_review_debug_match_diagnostics_enabled === true;
    for (const [templateKey, fieldId] of PROMPT_TEMPLATE_FIELDS) {
      setFieldValue(fieldId, promptTemplates[templateKey]);
    }

    setFieldValue('history_potential_retention_days', historySettings.potential_retention_days);
    setFieldValue('history_hidden_retention_days', historySettings.hidden_retention_days);
    setFieldValue('history_applied_retention_days', historySettings.applied_retention_days);
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
    setFieldValue('search_limit_linkedin_jobspy_stall_timeout_seconds_min', searchLimits.linkedin_jobspy_stall_timeout_seconds?.min);
    setFieldValue('search_limit_linkedin_jobspy_stall_timeout_seconds_max', searchLimits.linkedin_jobspy_stall_timeout_seconds?.max);
    setFieldValue('search_limit_linkedin_parallel_search_workers_min', searchLimits.linkedin_parallel_search_workers?.min);
    setFieldValue('search_limit_linkedin_parallel_search_workers_max', searchLimits.linkedin_parallel_search_workers?.max);
    setFieldValue('search_limit_linkedin_parallel_review_workers_min', searchLimits.linkedin_parallel_review_workers?.min);
    setFieldValue('search_limit_linkedin_parallel_review_workers_max', searchLimits.linkedin_parallel_review_workers?.max);
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
        seek_enabled: Boolean(document.getElementById('search_default_seek_enabled')?.checked),
        linkedin_enabled: Boolean(document.getElementById('search_default_linkedin_enabled')?.checked),
        apsjobs_enabled: Boolean(document.getElementById('search_default_apsjobs_enabled')?.checked),
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
        linkedin_jobspy_stall_timeout_seconds: readNumber('search_default_linkedin_jobspy_stall_timeout_seconds', currentSearch.linkedin_jobspy_stall_timeout_seconds),
        linkedin_parallel_search_workers: readNumber('search_default_linkedin_parallel_search_workers', currentSearch.linkedin_parallel_search_workers),
        linkedin_parallel_review_workers: readNumber('search_default_linkedin_parallel_review_workers', currentSearch.linkedin_parallel_review_workers),
        job_market_map_parallel_workers: readNumber('search_default_job_market_map_parallel_workers', currentSearch.job_market_map_parallel_workers),
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
          linkedin_jobspy_stall_timeout_seconds: {
            min: readNumber('search_limit_linkedin_jobspy_stall_timeout_seconds_min', currentSearchLimits.linkedin_jobspy_stall_timeout_seconds?.min),
            max: readNumber('search_limit_linkedin_jobspy_stall_timeout_seconds_max', currentSearchLimits.linkedin_jobspy_stall_timeout_seconds?.max),
          },
          linkedin_parallel_search_workers: {
            min: readNumber('search_limit_linkedin_parallel_search_workers_min', currentSearchLimits.linkedin_parallel_search_workers?.min),
            max: readNumber('search_limit_linkedin_parallel_search_workers_max', currentSearchLimits.linkedin_parallel_search_workers?.max),
          },
          linkedin_parallel_review_workers: {
            min: readNumber('search_limit_linkedin_parallel_review_workers_min', currentSearchLimits.linkedin_parallel_review_workers?.min),
            max: readNumber('search_limit_linkedin_parallel_review_workers_max', currentSearchLimits.linkedin_parallel_review_workers?.max),
          },
          job_market_map_parallel_workers: {
            min: readNumber('search_limit_job_market_map_parallel_workers_min', currentSearchLimits.job_market_map_parallel_workers?.min),
            max: readNumber('search_limit_job_market_map_parallel_workers_max', currentSearchLimits.job_market_map_parallel_workers?.max),
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
        potential_retention_days: readNumber('history_potential_retention_days', currentHistory.potential_retention_days),
        hidden_retention_days: readNumber('history_hidden_retention_days', currentHistory.hidden_retention_days),
        applied_retention_days: readNumber('history_applied_retention_days', currentHistory.applied_retention_days),
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
        source_discovery_cache_max_entries: readNumber(
          'cache_source_discovery_cache_max_entries',
          currentCacheSettings.source_discovery_cache_max_entries,
        ),
        source_discovery_cache_max_age_minutes: readNumber(
          'cache_source_discovery_cache_max_age_minutes',
          currentCacheSettings.source_discovery_cache_max_age_minutes,
        ),
        search_plan_max_age_minutes: readNumber(
          'cache_search_plan_max_age_minutes',
          currentCacheSettings.search_plan_max_age_minutes,
        ),
        linkedin_failure_backoff_minutes: readNumber(
          'cache_linkedin_failure_backoff_minutes',
          currentCacheSettings.linkedin_failure_backoff_minutes,
        ),
        search_plan_min_corroboration_samples: readNumber(
          'cache_search_plan_min_corroboration_samples',
          currentCacheSettings.search_plan_min_corroboration_samples,
        ),
        linkedin_stale_fallback_max_age_minutes: readNumber(
          'cache_linkedin_stale_fallback_max_age_minutes',
          currentCacheSettings.linkedin_stale_fallback_max_age_minutes,
        ),
        linkedin_max_consecutive_target_failures: readNumber(
          'cache_linkedin_max_consecutive_target_failures',
          currentCacheSettings.linkedin_max_consecutive_target_failures,
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
        temperature: readNumber('llm_temperature', currentLlmSettings.temperature),
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
        seek_manual_verification_timeout_ms: readSecondsAsMilliseconds(
          'seek_manual_verification_timeout_ms',
          currentPlaywright.seek_manual_verification_timeout_ms,
        ),
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

  function systemWarningSeverityClass(severity) {
    const level = String(severity || '').trim().toLowerCase();
    if (level === 'critical') return 'system-warning-pill--critical';
    if (level === 'error') return 'system-warning-pill--error';
    if (level === 'warning') return 'system-warning-pill--warning';
    return 'system-warning-pill--info';
  }

  function systemWarningLabel(value) {
    const label = String(value || '').replace(/_/g, ' ').trim();
    if (!label) {
      throw new Error(systemHealthLabels.system_health_load_error);
    }
    return label;
  }

  function systemHealthCountText(template, count) {
    return String(template).replace('{count}', String(count));
  }

  function systemWarningContextHtml(context) {
    if (!context || (typeof context === 'object' && Object.keys(context).length === 0)) {
      return '';
    }
    const contextText = typeof context === 'string' ? context : JSON.stringify(context, null, 2);
    return `
      <details class="system-warning-context">
        <summary>${escapeHtml(systemHealthLabels.system_health_technical_context_label)}</summary>
        <pre>${escapeHtml(contextText)}</pre>
      </details>
    `;
  }

  function renderSystemWarningCard(warning) {
    if (warning?.classification !== 'operational') {
      throw new Error(systemHealthLabels.system_health_load_error);
    }

    const severity = systemWarningLabel(warning.severity);
    const category = systemWarningLabel(warning.category);
    const source = String(warning.source || '').trim();
    const message = String(warning.message || '').trim();
    const jobKey = String(warning.job_key || '').trim();
    const runId = String(warning.run_id || '').trim();
    const lastSeen = String(warning.last_seen_at || '').trim();
    const count = Number(warning.count);
    const context = warning.context;
    const operatorGuidance = String(warning.operator_guidance || '').trim();
    const operatorAction = warning.operator_action;
    const operatorActionType = String(operatorAction?.type || '').trim();
    const operatorActionLabel = String(operatorAction?.label || '').trim();
    const operatorActionHtml = operatorActionType && operatorActionLabel
      ? `<button type="button" class="jh-button jh-button--secondary jh-button--compact" data-system-warning-action="${escapeHtml(operatorActionType)}" data-warning-id="${escapeHtml(String(warning.id))}">${escapeHtml(operatorActionLabel)}</button>`
      : '';

    if (!source || !message || !lastSeen || !operatorGuidance || !Number.isFinite(count)) {
      throw new Error(systemHealthLabels.system_health_load_error);
    }

    return `
      <article class="system-warning-card" data-warning-id="${escapeHtml(String(warning.id))}">
        <div class="system-warning-card__head">
          <div class="system-warning-card__copy">
            <h3 class="system-warning-card__title">${escapeHtml(message)}</h3>
            <div class="system-warning-card__message">${escapeHtml(category)} · ${escapeHtml(source)}</div>
            <div class="system-warning-card__meta">
              <span><strong>${escapeHtml(systemHealthLabels.system_health_occurrences_label)}:</strong> ${count}</span>
              ${jobKey ? `<span><strong>${escapeHtml(systemHealthLabels.system_health_job_label)}:</strong> ${escapeHtml(jobKey)}</span>` : ''}
              ${runId ? `<span><strong>${escapeHtml(systemHealthLabels.system_health_run_label)}:</strong> ${escapeHtml(runId)}</span>` : ''}
              <span><strong>${escapeHtml(systemHealthLabels.system_health_last_seen_label)}:</strong> ${escapeHtml(lastSeen)}</span>
            </div>
          </div>
          <div class="system-warning-pill-row">
            <span class="system-warning-pill ${systemWarningSeverityClass(warning.severity)}">${escapeHtml(severity)}</span>
          </div>
        </div>
        <div class="field-help">${escapeHtml(operatorGuidance)}</div>
        ${systemWarningContextHtml(context)}
        <div class="system-warning-actions">
          ${operatorActionHtml}
          <button type="button" class="jh-button jh-button--neutral jh-button--compact" data-system-warning-action="acknowledge" data-warning-id="${escapeHtml(String(warning.id))}">${escapeHtml(systemHealthLabels.system_health_acknowledge_label)}</button>
        </div>
      </article>
    `;
  }

  function renderSystemDiagnosticGroup(group) {
    if (group?.classification !== 'diagnostic') {
      throw new Error(systemHealthLabels.system_health_load_error);
    }

    const category = systemWarningLabel(group.category);
    const source = String(group.source || '').trim();
    const recordCount = Number(group.record_count);
    const occurrenceCount = Number(group.occurrence_count);
    const lastSeen = String(group.last_seen_at || '').trim();
    const sample = group.sample && typeof group.sample === 'object' ? group.sample : null;

    if (!source || !Number.isFinite(recordCount) || !Number.isFinite(occurrenceCount) || !lastSeen || !sample) {
      throw new Error(systemHealthLabels.system_health_load_error);
    }

    const sampleMessage = String(sample.message || '').trim();
    if (!sampleMessage) {
      throw new Error(systemHealthLabels.system_health_load_error);
    }
    const samplePayload = {
      job_key: sample.job_key || null,
      run_id: sample.run_id || null,
      context: sample.context,
    };

    return `
      <article class="system-warning-card" data-system-diagnostic-group="${escapeHtml(`${group.category}|${group.source}`)}">
        <div class="system-warning-card__head">
          <div class="system-warning-card__copy">
            <h3 class="system-warning-card__title">${escapeHtml(category)} · ${escapeHtml(source)}</h3>
            <div class="system-warning-card__meta">
              <span><strong>${escapeHtml(systemHealthLabels.system_health_records_label)}:</strong> ${recordCount}</span>
              <span><strong>${escapeHtml(systemHealthLabels.system_health_occurrences_label)}:</strong> ${occurrenceCount}</span>
              <span><strong>${escapeHtml(systemHealthLabels.system_health_last_seen_label)}:</strong> ${escapeHtml(lastSeen)}</span>
            </div>
          </div>
        </div>
        <details class="system-warning-context">
          <summary>${escapeHtml(systemHealthLabels.system_health_sample_label)}</summary>
          <div class="system-warning-card__message">${escapeHtml(sampleMessage)}</div>
          <pre>${escapeHtml(JSON.stringify(samplePayload, null, 2))}</pre>
        </details>
      </article>
    `;
  }

  async function fetchSystemWarnings(includeDiagnostics = false) {
    const query = includeDiagnostics ? '?include_diagnostics=true' : '';
    const response = await window.jobHunterFetch(`/api/admin/system-warnings${query}`);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || systemHealthLabels.system_health_load_error);
    }
    return {
      warnings: Array.isArray(payload.warnings) ? payload.warnings : [],
      diagnosticGroups: Array.isArray(payload.diagnostic_groups) ? payload.diagnostic_groups : [],
      summary: payload && typeof payload.summary === 'object' && payload.summary ? payload.summary : {},
    };
  }

  async function acknowledgeSystemWarning(warningId) {
    const response = await window.jobHunterFetch(`/api/admin/system-warnings/${encodeURIComponent(warningId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'acknowledge' }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || systemHealthLabels.system_health_action_error);
    }
    return payload.warning;
  }

  async function runScraperValidation() {
    const response = await window.jobHunterFetch('/api/admin/scraper-config-validation', {
      method: 'POST',
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || systemHealthLabels.system_health_scraper_validation_error);
    }
    return payload;
  }

  function initSystemWarningsControls(showStatus) {
    const panel = document.getElementById('system_warnings_panel');
    const list = document.getElementById('system_warnings_list');
    const empty = document.getElementById('system_warnings_empty');
    const status = document.getElementById('system_warnings_status');
    const refreshButton = document.getElementById('system_warnings_refresh_button');
    const diagnosticsToggle = document.getElementById('system_diagnostics_toggle_button');
    const diagnosticsSection = document.getElementById('system_diagnostics_section');
    const diagnosticsList = document.getElementById('system_diagnostics_list');
    if (
      !panel || !list || !empty || !status || !diagnosticsToggle
      || !diagnosticsSection || !diagnosticsList
      || typeof window.jobHunterFetch !== 'function'
    ) {
      return;
    }
    if (panel.dataset.bound === 'true') {
      return;
    }
    panel.dataset.bound = 'true';
    let diagnosticsVisible = false;

    const setStatus = (message, kind) => {
      status.textContent = String(message || '');
      status.className = kind ? `field-help sync-status sync-status--${kind}` : 'field-help';
      if (typeof showStatus === 'function') {
        showStatus(message, kind);
      }
    };

    const renderWarnings = (warnings) => {
      empty.hidden = warnings.length > 0;
      list.innerHTML = warnings.map((warning) => renderSystemWarningCard(warning)).join('');
    };

    const renderDiagnostics = (groups) => {
      diagnosticsSection.hidden = !diagnosticsVisible;
      if (!diagnosticsVisible) {
        diagnosticsList.innerHTML = '';
        return;
      }
      diagnosticsList.innerHTML = groups.length
        ? groups.map((group) => renderSystemDiagnosticGroup(group)).join('')
        : `<p class="field-help">${escapeHtml(systemHealthLabels.system_health_diagnostics_empty)}</p>`;
    };

    const refresh = async ({ silent = false } = {}) => {
      if (!silent) {
        setStatus(systemHealthLabels.system_health_checking_status, 'loading');
      }
      try {
        const payload = await fetchSystemWarnings(diagnosticsVisible);
        const warnings = payload.warnings;
        const diagnosticGroups = payload.diagnosticGroups;
        const summary = payload.summary;
        const activeCount = Number(summary.active_problem_records);
        const diagnosticCount = Number(summary.diagnostic_records);

        if (!Number.isFinite(activeCount) || !Number.isFinite(diagnosticCount)) {
          throw new Error(systemHealthLabels.system_health_load_error);
        }

        renderWarnings(warnings);
        renderDiagnostics(diagnosticGroups);
        const activeText = systemHealthCountText(
          systemHealthLabels.system_health_active_count_template,
          activeCount,
        );
        const diagnosticText = systemHealthCountText(
          systemHealthLabels.system_health_diagnostic_count_template,
          diagnosticCount,
        );
        setStatus(`${activeText} ${diagnosticText}`, activeCount > 0 ? 'warning' : 'success');
      } catch (error) {
        list.innerHTML = '';
        diagnosticsList.innerHTML = '';
        empty.hidden = false;
        setStatus(error.message || systemHealthLabels.system_health_load_error, 'error');
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
      button.textContent = action === 'run_scraper_validation'
        ? systemHealthLabels.system_health_scraper_validation_running_label
        : systemHealthLabels.system_health_acknowledging_label;
      try {
        if (action === 'run_scraper_validation') {
          setStatus(systemHealthLabels.system_health_scraper_validation_running_status, 'loading');
          await runScraperValidation();
          await refresh({ silent: true });
          setStatus(systemHealthLabels.system_health_scraper_validation_completed_status, 'success');
        } else if (action === 'acknowledge') {
          await acknowledgeSystemWarning(warningId);
          await refresh({ silent: true });
          setStatus(systemHealthLabels.system_health_acknowledged_status, 'success');
        } else {
          throw new Error(systemHealthLabels.system_health_action_error);
        }
      } catch (error) {
        setStatus(error.message || systemHealthLabels.system_health_action_error, 'error');
      } finally {
        button.disabled = false;
        button.textContent = originalLabel;
      }
    });

    diagnosticsToggle.addEventListener('click', async () => {
      diagnosticsVisible = !diagnosticsVisible;
      diagnosticsToggle.setAttribute('aria-expanded', diagnosticsVisible ? 'true' : 'false');
      diagnosticsToggle.textContent = diagnosticsVisible
        ? systemHealthLabels.system_health_diagnostics_hide_label
        : systemHealthLabels.system_health_diagnostics_show_label;
      await refresh();
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
      setStatus(systemHealthLabels.system_health_scraper_validation_running_status, 'loading');
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
        setStatus(error.message || systemHealthLabels.system_health_scraper_validation_error, 'error');
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

  function initUserAccessControls(showStatus) {
    const panel = document.getElementById('user_access_management_panel');
    const list = document.getElementById('user_access_list');
    const statusEl = document.getElementById('user_access_status');
    const labels = window.__JOB_HUNTER_GLOBAL_SETTINGS_LABELS__;
    if (!panel || !list || !statusEl || !labels || typeof window.jobHunterFetch !== 'function') {
      return;
    }
    if (panel.dataset.bound === 'true') {
      return;
    }
    panel.dataset.bound = 'true';

    const statusLabels = {
      pending: labels.user_access_status_pending,
      approved: labels.user_access_status_approved,
      blocked: labels.user_access_status_blocked,
    };

    const setStatus = (message, kind) => {
      statusEl.textContent = String(message || '');
      statusEl.className = kind ? `field-help sync-status sync-status--${kind}` : 'field-help';
      if (typeof showStatus === 'function') {
        showStatus(message, kind);
      }
    };

    const formatUserDate = (value) => {
      const text = String(value || '').trim();
      return text || labels.user_access_unknown_value;
    };

    const renderUser = (user) => {
      const userId = String(user?.user_id || '').trim();
      const email = String(user?.email || '').trim();
      const displayName = String(user?.display_name || '').trim() || labels.user_access_unknown_value;
      const accessStatus = String(user?.access_status || '').trim().toLowerCase();
      if (!userId || !email || !Object.prototype.hasOwnProperty.call(statusLabels, accessStatus)) {
        throw new Error(labels.user_access_load_error);
      }
      const isAdmin = user?.is_admin === true;
      const actions = isAdmin
        ? `<span class="user-access-admin-label">${escapeHtml(labels.user_access_admin_label)}</span>`
        : `
          <button type="button" class="jh-button jh-button--primary jh-button--compact" data-user-access-status="approved" data-user-id="${escapeHtml(userId)}">${escapeHtml(labels.user_access_approve_label)}</button>
          <button type="button" class="jh-button jh-button--neutral jh-button--compact" data-user-access-status="pending" data-user-id="${escapeHtml(userId)}">${escapeHtml(labels.user_access_pending_label)}</button>
          <button type="button" class="jh-button jh-button--danger jh-button--compact" data-user-access-status="blocked" data-user-id="${escapeHtml(userId)}">${escapeHtml(labels.user_access_block_label)}</button>
        `;
      return `
        <article class="user-access-card" data-user-id="${escapeHtml(userId)}">
          <div class="user-access-card__head">
            <div>
              <h3 class="user-access-card__name">${escapeHtml(displayName)}</h3>
              <p class="user-access-card__email">${escapeHtml(email)}</p>
            </div>
            <span class="user-access-card__status user-access-card__status--${escapeHtml(accessStatus)}">${escapeHtml(statusLabels[accessStatus])}</span>
          </div>
          <div class="user-access-card__meta">
            <span><strong>${escapeHtml(labels.user_access_created_label)}:</strong> ${escapeHtml(formatUserDate(user.created_at))}</span>
            <span><strong>${escapeHtml(labels.user_access_last_activity_label)}:</strong> ${escapeHtml(formatUserDate(user.last_seen_at))}</span>
          </div>
          <div class="user-access-card__actions">${actions}</div>
        </article>
      `;
    };

    const renderUsers = (users) => {
      if (!users.length) {
        list.innerHTML = `<p class="field-help">${escapeHtml(labels.user_access_empty)}</p>`;
        return;
      }
      list.innerHTML = users.map(renderUser).join('');
    };

    const loadUsers = async () => {
      try {
        const response = await window.jobHunterFetch('/api/admin/user-access');
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(payload.error || labels.user_access_load_error);
        }
        const users = Array.isArray(payload.users) ? payload.users : null;
        if (!users) {
          throw new Error(labels.user_access_load_error);
        }
        renderUsers(users);
        const pendingCount = users.filter((user) => user?.access_status === 'pending').length;
        if (pendingCount === 1) {
          setStatus(labels.user_access_pending_summary_one, '');
        } else if (pendingCount > 1) {
          setStatus(labels.user_access_pending_summary_many.replace('{count}', String(pendingCount)), '');
        } else {
          setStatus('', '');
        }
      } catch (error) {
        list.innerHTML = '';
        setStatus(error.message || labels.user_access_load_error, 'error');
      }
    };

    list.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-user-access-status]');
      if (!button) return;
      const userId = String(button.dataset.userId || '').trim();
      const nextStatus = String(button.dataset.userAccessStatus || '').trim();
      if (!userId || !Object.prototype.hasOwnProperty.call(statusLabels, nextStatus)) return;
      const originalLabel = button.textContent;
      button.disabled = true;
      try {
        const response = await window.jobHunterFetch(`/api/admin/user-access/${encodeURIComponent(userId)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: nextStatus }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(payload.error || labels.user_access_action_error);
        }
        await loadUsers();
        setStatus(labels.user_access_updated_status, 'success');
      } catch (error) {
        setStatus(error.message || labels.user_access_action_error, 'error');
      } finally {
        button.disabled = false;
        button.textContent = originalLabel;
      }
    });

    loadUsers();
  }

  return {
    fillGlobalForm,
    collectGlobalSettings,
    loadGlobalSettingsHelp,
    applyGlobalSettingsHelp,
    initRuntimeMaintenanceControls,
    initKnowledgeSyncControls,
    initScraperValidationControls,
    initSystemWarningsControls,
    initUserAccessControls,
  };
}());
