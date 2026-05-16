window.JobHunterAdminSettings = (function () {
  const { escapeHtml, toLines, setCurrencyFieldValue, readCurrencyFieldValue } = window.JobHunterSettingsUtils;

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
    const descriptionTrustSettings = settings.description_trust_settings || {};
    const sourceDocumentSettings = settings.source_document_settings || {};
    const defaultCountrySuffix = settings.default_country_suffix || '';
    const salaryLimits = limits.salary || {};
    const onboarding = settings.onboarding_settings || {};
    const llmSettings = settings.llm_settings || {};
    const playwrightSettings = settings.playwright_settings || {};
    const LINKEDIN_EASY_APPLY_ONLY = window.LINKEDIN_EASY_APPLY_ONLY || 'linkedin_easy_apply_only';

    const setBounds = (id, bounds) => {
      const input = document.getElementById(id);
      if (!input || !bounds) return;
      if (bounds.min !== undefined) input.min = String(bounds.min);
      if (bounds.max !== undefined) input.max = String(bounds.max);
    };

    document.getElementById('highlight_strong_capability_count').value = String(fitHl.strong_capability_count ?? '');
    document.getElementById('highlight_working_capability_count').value = String(fitHl.working_capability_count ?? '');
    document.getElementById('highlight_basic_capability_count').value = String(fitHl.basic_capability_count ?? '');
    document.getElementById('highlight_reviewed_signal_count').value = String(fitHl.reviewed_signal_count ?? '');
    document.getElementById('highlight_max_highlights').value = String(fitHl.max_highlights ?? '');

    document.getElementById('search_default_date_range_days').value = String(searchDefaults.date_range_days ?? '');
    document.getElementById('search_default_seek_max_pages').value = String(searchDefaults.seek_max_pages ?? '');
    document.getElementById('search_default_linkedin_hours_old').value = String(searchDefaults.linkedin_hours_old ?? '');
    document.getElementById('search_default_linkedin_results_per_search').value = String(searchDefaults.linkedin_results_per_search ?? '');
    document.getElementById('search_default_enforce_posted_age_limit').value = searchDefaults.enforce_posted_age_limit === false ? 'false' : 'true';
    document.getElementById('search_default_sort_newest_first').value = searchDefaults.sort_newest_first === false ? 'false' : 'true';
    const liEasyApply = searchDefaults[LINKEDIN_EASY_APPLY_ONLY];
    document.getElementById('search_default_' + LINKEDIN_EASY_APPLY_ONLY).value = (liEasyApply === null || liEasyApply === undefined) ? '' : String(liEasyApply);
    setBounds('search_default_date_range_days', searchLimits.date_range_days);
    setBounds('search_default_seek_max_pages', searchLimits.seek_max_pages);
    setBounds('search_default_linkedin_hours_old', searchLimits.linkedin_hours_old);
    setBounds('search_default_linkedin_results_per_search', searchLimits.linkedin_results_per_search);
    document.getElementById('default_country_suffix').value = defaultCountrySuffix;
    document.getElementById('playwright_viewport_width').value = String(playwrightSettings.playwright_viewport_width ?? '');
    document.getElementById('playwright_viewport_height').value = String(playwrightSettings.playwright_viewport_height ?? '');
    document.getElementById('playwright_selector_timeout').value = String(playwrightSettings.playwright_selector_timeout ?? '');

    const rangeText = (value) => value?.min !== undefined && value?.max !== undefined ? `${value.min} to ${value.max}` : 'managed by the server';
    document.getElementById('search_default_date_range_days_bounds').textContent = rangeText(searchLimits.date_range_days);
    document.getElementById('search_default_seek_max_pages_bounds').textContent = rangeText(searchLimits.seek_max_pages);
    document.getElementById('search_default_linkedin_hours_old_bounds').textContent = rangeText(searchLimits.linkedin_hours_old);
    document.getElementById('search_default_linkedin_results_per_search_bounds').textContent = rangeText(searchLimits.linkedin_results_per_search);

    document.getElementById('evidence_primary_weight').value = String(evidenceWeights.primary_candidate_profile_context ?? '');
    document.getElementById('evidence_secondary_weight').value = String(evidenceWeights.secondary_candidate_profile_context ?? '');
    document.getElementById('evidence_supplementary_weight').value = String(evidenceWeights.supplementary_candidate_profile_context ?? '');

    document.getElementById('preference_fit_weight').value = String(preferenceWeights.fit ?? '');
    document.getElementById('preference_salary_weight').value = String(preferenceWeights.salary ?? '');
    document.getElementById('preference_location_weight').value = String(preferenceWeights.location ?? '');
    document.getElementById('preference_work_mode_weight').value = String(preferenceWeights.work_mode ?? '');
    document.getElementById('preference_contract_weight').value = String(preferenceWeights.contract ?? '');
    document.getElementById('preference_government_weight').value = String(preferenceWeights.government ?? '');
    document.getElementById('preference_freshness_weight').value = String(preferenceWeights.freshness ?? '');

    document.getElementById('history_max_history_sightings').value = String(historySettings.max_history_sightings ?? '');
    document.getElementById('history_repeated_listing_min_times_seen').value = String(historySettings.repeated_listing_min_times_seen ?? '');
    document.getElementById('history_repeated_listing_min_span_days').value = String(historySettings.repeated_listing_min_span_days ?? '');
    document.getElementById('history_multi_listing_red_flag_min_listings').value = String(historySettings.multi_listing_red_flag_min_listings ?? '');
    document.getElementById('history_multi_listing_red_flag_min_span_days').value = String(historySettings.multi_listing_red_flag_min_span_days ?? '');
    document.getElementById('onboarding_extraction_lookback_years').value = String(onboarding.extraction_lookback_years ?? '');
    document.getElementById('onboarding_title_extraction_min_months').value = String(onboarding.title_extraction_min_months ?? '');
    document.getElementById('onboarding_max_target_patterns').value = String(onboarding.max_target_patterns ?? '');
    document.getElementById('onboarding_max_secondary_patterns').value = String(onboarding.max_secondary_patterns ?? '');
    document.getElementById('onboarding_capability_alias_limit').value = String(onboarding.capability_alias_limit ?? '');
    document.getElementById('onboarding_signal_cluster_min_alias_hits').value = String(onboarding.signal_cluster_min_alias_hits ?? '');
    document.getElementById('onboarding_signal_cluster_min_snippet_hits').value = String(onboarding.signal_cluster_min_snippet_hits ?? '');
    document.getElementById('onboarding_signal_cluster_dense_snippet_alias_hits').value = String(onboarding.signal_cluster_dense_snippet_alias_hits ?? '');
    document.getElementById('onboarding_capability_strength_preset').value = onboarding.capability_strength_preset || '';
    document.getElementById('llm_model_options').value = (llmSettings.model_options || []).join('\n');
    setBounds('llm_max_llm_chars', llmSettings.max_llm_chars_limits);
    document.getElementById('llm_max_llm_chars').value = String(llmSettings.max_llm_chars ?? '');
    document.getElementById('llm_pricing_per_1m').value = JSON.stringify(llmSettings.pricing_per_1m || {}, null, 2);
    document.getElementById('llm_prompt_settings').value = JSON.stringify(llmSettings.llm_prompt_settings || {}, null, 2);

    document.getElementById('history_archive_stale_after_days').value = String(historySettings.archive_stale_after_days ?? '');
    document.getElementById('history_hidden_review_days').value = String(historySettings.hidden_review_days ?? '');
    document.getElementById('description_trust_min_trusted_description_length').value = String(descriptionTrustSettings.min_trusted_description_length ?? '');
    document.getElementById('source_document_allowed_suffixes').value = (sourceDocumentSettings.allowed_suffixes || []).join('\n');
    document.getElementById('source_document_allowed_suffixes').setAttribute('readonly', 'readonly');

    document.getElementById('search_limit_date_range_days_min').value = String(searchLimits.date_range_days?.min ?? '');
    document.getElementById('search_limit_date_range_days_max').value = String(searchLimits.date_range_days?.max ?? '');
    document.getElementById('search_limit_seek_max_pages_min').value = String(searchLimits.seek_max_pages?.min ?? '');
    document.getElementById('search_limit_seek_max_pages_max').value = String(searchLimits.seek_max_pages?.max ?? '');
    document.getElementById('search_limit_linkedin_hours_old_min').value = String(searchLimits.linkedin_hours_old?.min ?? '');
    document.getElementById('search_limit_linkedin_hours_old_max').value = String(searchLimits.linkedin_hours_old?.max ?? '');
    document.getElementById('search_limit_linkedin_results_per_search_min').value = String(searchLimits.linkedin_results_per_search?.min ?? '');
    document.getElementById('search_limit_linkedin_results_per_search_max').value = String(searchLimits.linkedin_results_per_search?.max ?? '');
    setCurrencyFieldValue('salary_limit_minimum_salary_yearly_max', salaryLimits.minimum_salary_yearly?.max ?? '');
    setCurrencyFieldValue('salary_limit_minimum_daily_rate_max', salaryLimits.minimum_daily_rate?.max ?? '');

    const presetPanel = document.getElementById('capability_strength_presets_panel');
    const presetTable = onboarding.capability_strength_presets || {};
    if (presetPanel) {
      const presetRows = Object.entries(presetTable).map(([presetName, presetValues]) => `
        <tr>
          <th scope="row">${escapeHtml(presetName)}</th>
          <td>${escapeHtml(Object.entries(presetValues || {}).map(([key, value]) => `${key}: ${value}`).join(' | ') || 'No values')}</td>
        </tr>
      `).join('');
      presetPanel.innerHTML = `
        <table class="settings-table">
          <thead><tr><th>Preset</th><th>Values</th></tr></thead>
          <tbody>${presetRows || '<tr><td colspan="2">No capability presets loaded.</td></tr>'}</tbody>
        </table>
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
    const currentDescriptionTrust = current.description_trust_settings || {};
    const currentSourceDocuments = current.source_document_settings || {};
    const currentEvidenceWeights = current.candidate_profile_tier_weights || {};
    const currentReviewSettings = current.review_settings || {};
    const currentPlaywright = current.playwright_settings || {};
    const currentOnboarding = current.onboarding_settings || {};
    const LINKEDIN_EASY_APPLY_ONLY = window.LINKEDIN_EASY_APPLY_ONLY || 'linkedin_easy_apply_only';

    const readNumber = (id, fallback) => {
      const raw = Number(document.getElementById(id).value);
      return Number.isNaN(raw) ? fallback : raw;
    };
    const readBoolean = (id, fallback) => {
      const raw = document.getElementById(id).value;
      if (raw === 'true') return true;
      if (raw === 'false') return false;
      return fallback;
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
        seek_max_pages: readNumber('search_default_seek_max_pages', currentSearch.seek_max_pages),
        linkedin_hours_old: readNumber('search_default_linkedin_hours_old', currentSearch.linkedin_hours_old),
        linkedin_results_per_search: readNumber('search_default_linkedin_results_per_search', currentSearch.linkedin_results_per_search),
        enforce_posted_age_limit: readBoolean('search_default_enforce_posted_age_limit', currentSearch.enforce_posted_age_limit),
        sort_newest_first: readBoolean('search_default_sort_newest_first', currentSearch.sort_newest_first),
        [LINKEDIN_EASY_APPLY_ONLY]: (() => {
          const raw = document.getElementById('search_default_' + LINKEDIN_EASY_APPLY_ONLY).value;
          if (raw === '') return null;
          return raw === 'true';
        })(),
      },
      default_country_suffix: document.getElementById('default_country_suffix').value.trim(),
      limits: {
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
        candidate_profile_tier_weights: {
          ...currentEvidenceWeights,
          primary_candidate_profile_context: readNumber('evidence_primary_weight', currentEvidenceWeights.primary_candidate_profile_context),
          secondary_candidate_profile_context: readNumber('evidence_secondary_weight', currentEvidenceWeights.secondary_candidate_profile_context),
          supplementary_candidate_profile_context: readNumber('evidence_supplementary_weight', currentEvidenceWeights.supplementary_candidate_profile_context),
        },
        history_settings: {
          ...currentHistory,
          archive_stale_after_days: readNumber('history_archive_stale_after_days', currentHistory.archive_stale_after_days),
          hidden_review_days: readNumber('history_hidden_review_days', currentHistory.hidden_review_days),
          max_history_sightings: readNumber('history_max_history_sightings', currentHistory.max_history_sightings),
          repeated_listing_min_times_seen: readNumber('history_repeated_listing_min_times_seen', currentHistory.repeated_listing_min_times_seen),
          repeated_listing_min_span_days: readNumber('history_repeated_listing_min_span_days', currentHistory.repeated_listing_min_span_days),
          multi_listing_red_flag_min_listings: readNumber('history_multi_listing_red_flag_min_listings', currentHistory.multi_listing_red_flag_min_listings),
          multi_listing_red_flag_min_span_days: readNumber('history_multi_listing_red_flag_min_span_days', currentHistory.multi_listing_red_flag_min_span_days),
        },
        description_trust_settings: {
          ...currentDescriptionTrust,
          min_trusted_description_length: readNumber(
            'description_trust_min_trusted_description_length',
            currentDescriptionTrust.min_trusted_description_length,
          ),
        },
        source_document_settings: { ...currentSourceDocuments },
        onboarding_settings: {
          ...currentOnboarding,
          extraction_lookback_years: readNumber('onboarding_extraction_lookback_years', currentOnboarding.extraction_lookback_years),
          title_extraction_min_months: readNumber('onboarding_title_extraction_min_months', currentOnboarding.title_extraction_min_months),
          max_target_patterns: readNumber('onboarding_max_target_patterns', currentOnboarding.max_target_patterns),
          max_secondary_patterns: readNumber('onboarding_max_secondary_patterns', currentOnboarding.max_secondary_patterns),
          capability_alias_limit: readNumber('onboarding_capability_alias_limit', currentOnboarding.capability_alias_limit),
          signal_cluster_min_alias_hits: readNumber('onboarding_signal_cluster_min_alias_hits', currentOnboarding.signal_cluster_min_alias_hits),
          signal_cluster_min_snippet_hits: readNumber('onboarding_signal_cluster_min_snippet_hits', currentOnboarding.signal_cluster_min_snippet_hits),
          signal_cluster_dense_snippet_alias_hits: readNumber('onboarding_signal_cluster_dense_snippet_alias_hits', currentOnboarding.signal_cluster_dense_snippet_alias_hits),
          capability_strength_preset: document.getElementById('onboarding_capability_strength_preset').value || currentOnboarding.capability_strength_preset,
        },
        llm_settings: {
          ...current.llm_settings,
          model_options: toLines(document.getElementById('llm_model_options').value),
          max_llm_chars: readNumber('llm_max_llm_chars', current.llm_settings?.max_llm_chars),
          pricing_per_1m: JSON.parse(document.getElementById('llm_pricing_per_1m').value.trim() || '{}'),
          llm_prompt_settings: JSON.parse(document.getElementById('llm_prompt_settings').value.trim() || '{}'),
        },
        review_settings: { ...currentReviewSettings },
        playwright_settings: {
          ...currentPlaywright,
          playwright_viewport_width: readNumber('playwright_viewport_width', currentPlaywright.playwright_viewport_width),
          playwright_viewport_height: readNumber('playwright_viewport_height', currentPlaywright.playwright_viewport_height),
          playwright_selector_timeout: readNumber('playwright_selector_timeout', currentPlaywright.playwright_selector_timeout),
        },
      },
    };
  }

  return { fillGlobalForm, collectGlobalSettings };
}());
