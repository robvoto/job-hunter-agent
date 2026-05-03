    function getReviewChoiceMeta(choice) {
      if (!choice) return { label: 'Choose a strength' };
      return capabilityStrengthMeta(choice) || { label: 'Choose a strength' };
    }

    function renderReviewChoiceGuide(choice) {
      const meta = getReviewChoiceMeta(choice);
      return `
        <strong>${escapeHtml(meta.label)}</strong>
        <p>This sets the capability strength used during matching.</p>
      `;
    }

    function reviewOptionMarkup(selectedValue) {
      const options = [
        ['', 'Choose a strength'],
        ['strong', capabilityStrengthMeta('strong')?.label || 'Expert'],
        ['working', capabilityStrengthMeta('working')?.label || 'Intermediate'],
        ['basic', capabilityStrengthMeta('basic')?.label || 'Basic'],
      ];
      return options.map(([value, label]) => {
        const selected = value === selectedValue ? ' selected' : '';
        return `<option value="${escapeHtml(value)}"${selected}>${escapeHtml(label)}</option>`;
      }).join('');
    }

    function suggestionExamplesMarkup(items, emptyLabel) {
      if (!items || !items.length) return `<p>${escapeHtml(emptyLabel)}</p>`;
      return `<ul>${items.map(item => `
        <li>
          <a href="${escapeHtml(item.url || '#')}" target="_blank" rel="noreferrer">${escapeHtml(item.title || 'Untitled role')}</a>
          ${item.company ? ` - ${escapeHtml(item.company)}` : ''}
          ${item.search_location ? ` (${escapeHtml(item.search_location)})` : ''}
        </li>
      `).join('')}</ul>`;
    }

    function renderSuggestedTuning(suggestions) {
      const panel = document.getElementById('tuning_suggestions_panel');
      const capabilitySuggestions = suggestions.capability_suggestions || [];
      const ruleSuggestions = suggestions.rule_suggestions || [];
      const summary = suggestions.summary || {};
      if (!capabilitySuggestions.length && !ruleSuggestions.length) {
        panel.innerHTML = '<p>No suggested tuning yet. After a scrape run, repeated useful capability signals and repeat junk-role patterns will show up here for confirmation.</p>';
        return;
      }
      const capabilityHtml = capabilitySuggestions.length ? `
        <div class="tuning-group">
          <h3>Capability signals from viable roles</h3>
          <p class="tuning-group-copy">Repeated skills from kept roles that need a decision before the engine can learn how to classify them consistently.</p>
          <div class="review-list">
            ${capabilitySuggestions.map(item => `
              <div class="review-card">
                <h3>${escapeHtml(item.skill || 'Capability signal')}</h3>
                <p>Seen in ${escapeHtml(String(item.count || 0))} kept role(s).</p>
                <div class="suggestion-meta"><span class="suggestion-chip">Suggested: ${escapeHtml(item.recommended_label || 'Review')}</span></div>
                <label>${escapeHtml(capabilityUi.reviewStrengthPromptLabel || 'How strong is this capability for you?')}</label>
                <select class="skill-choice" data-skill="${escapeHtml(item.skill || '')}">${reviewOptionMarkup(item.recommended_choice || '')}</select>
                <details class="review-choice-guide">
                  <summary>What this choice means</summary>
                  <div class="review-choice-guide-body">${renderReviewChoiceGuide(item.recommended_choice || '')}</div>
                </details>
                <details class="review-examples">
                  <summary>Examples from kept roles</summary>
                  <div class="review-examples-body">${suggestionExamplesMarkup(item.examples || [], 'No example roles saved for this signal yet.')}</div>
                </details>
                <div class="card-actions" style="margin-top:10px;">
                  <button class="primary confirm-skill-btn" data-skill="${escapeHtml(item.skill || '')}" style="font-size:0.9rem;padding:8px 16px;">Confirm</button>
                </div>
              </div>
            `).join('')}
          </div>
        </div>
      ` : '';

      const actionableRules = ruleSuggestions.filter(item => !(item.reason || '').startsWith('TITLE_NOT_TARGET') && !(item.reason || '').startsWith('TITLE_BAD_KEYWORD'));
      const workingFilters = ruleSuggestions.filter(item => (item.reason || '').startsWith('TITLE_BAD_KEYWORD'));

      function ruleCardMarkup(item) {
        return `
          <div class="review-card">
            <h3>${escapeHtml(item.headline || item.reason || 'Rule signal')}</h3>
            <p>${escapeHtml(item.detail || '')}</p>
            <div class="suggestion-meta">
              <span class="suggestion-chip">Target: ${escapeHtml(item.target || 'Matching rules')}</span>
              <span class="suggestion-chip">Count: ${escapeHtml(String(item.count || 0))}</span>
            </div>
            <p><strong>Suggested action:</strong> ${escapeHtml(item.recommendation || 'Review this signal and decide whether the matching rules need refinement.')}</p>
            <p>Examples:</p>
            ${suggestionExamplesMarkup(item.samples || [], 'No sample roles saved for this signal yet.')}
            ${(item.reason || '').startsWith('DESC_CAPABILITY_LOW') ? `
            <div class="card-actions" style="margin-top:10px;">
              <button class="secondary add-phrase-exclusion-btn" data-reason="${escapeHtml(item.reason || '')}" style="font-size:0.9rem;padding:8px 16px;border-color:var(--state-error-border);color:var(--state-error-text);background:var(--state-error-bg);">Add to exclusions</button>
            </div>` : ''}
            ${(item.reason || '').startsWith('TITLE_BAD_KEYWORD') ? `
            <div class="card-actions" style="margin-top:10px;">
              <button class="secondary dismiss-rule-card-btn" style="font-size:0.9rem;padding:8px 16px;">Dismiss</button>
            </div>` : ''}
          </div>`;
      }

      const ruleHtml = (actionableRules.length || workingFilters.length) ? `
        <div class="tuning-group">
          <h3>Repeated junk-role signals</h3>
          <p class="tuning-group-copy">Patterns from rejects that are worth keeping, strengthening, or watching before you touch search keywords.</p>
          ${actionableRules.length ? `<div class="review-list">${actionableRules.map(ruleCardMarkup).join('')}</div>` : ''}
          ${workingFilters.length ? `
          <details style="margin-top:14px;">
            <summary style="cursor:pointer;color:var(--muted);font-size:0.88rem;">Filters already working correctly (${workingFilters.length})</summary>
            <div class="review-list" style="margin-top:10px;">${workingFilters.map(ruleCardMarkup).join('')}</div>
          </details>` : ''}
        </div>
      ` : '';

      panel.innerHTML = `
        <div class="tuning-summary">
          <div class="tuning-summary-card"><strong>${escapeHtml(String(summary.capability_count || capabilitySuggestions.length || 0))}</strong><span>Capability suggestions</span></div>
          <div class="tuning-summary-card"><strong>${escapeHtml(String(summary.rule_count || ruleSuggestions.length || 0))}</strong><span>Rule signals to review</span></div>
        </div>
        ${capabilityHtml}
        ${ruleHtml}
      `;
    }

    async function loadReviewData() {
      const response = await fetch('/api/review-data');
      if (!response.ok) { renderSuggestedTuning({ capability_suggestions: [], rule_suggestions: [], summary: {} }); return; }
      const payload = await response.json();
      renderSuggestedTuning(payload.suggested_tuning || { capability_suggestions: [], rule_suggestions: [], summary: {} });
    }

    function collectProfile() {
      flushChipEditorInputs();
      return {
        search_settings: {
          keywords: document.getElementById('keywords').value.trim(),
          locations: toLines(document.getElementById('locations').value),
          classification_ids: toLines(document.getElementById('classification_ids').value),
          date_range_days: Number(document.getElementById('date_range_days').value),
          seek_max_pages: Number(document.getElementById('seek_max_pages').value),
          enforce_posted_age_limit: document.getElementById('enforce_posted_age_limit').value === 'true',
          sort_newest_first: document.getElementById('sort_newest_first').value === 'true',
          linkedin_hours_old: Number(document.getElementById('linkedin_hours_old').value) || 24,
          linkedin_results_per_search: Number(document.getElementById('linkedin_results_per_search').value) || 25,
          linkedin_easy_apply_only: (() => { const v = document.getElementById('linkedin_easy_apply_only').value; return v === '' ? null : v === 'true'; })(),
        },
        salary_preferences: {
          minimum_salary_yearly: Number(document.getElementById('minimum_salary_yearly').value || 0),
          minimum_daily_rate: Number(document.getElementById('minimum_daily_rate').value || 0),
        },
        preference_weights: {
          fit: Number(document.getElementById('fit_weight').value || 1),
          salary: Number(document.getElementById('salary_weight').value || 1),
          location: Number(document.getElementById('location_weight').value || 1),
          work_mode: Number(document.getElementById('work_mode_weight').value || 1),
          contract: Number(document.getElementById('contract_weight').value || 1),
          government: Number(document.getElementById('government_weight').value || 1),
          freshness: Number(document.getElementById('freshness_weight').value || 1),
        },
        llm_profile_brief_mode: 'auto',
        llm_profile_brief: '',
        capability_profile_rules: collectCapabilityRuleState(),
        primary_job_title_pattern: toLines(settingsField('primary_job_title_pattern').value),
        secondary_title_patterns: toLines(settingsField('secondary_title_patterns').value),
        must_not_require_skills: toLines(settingsField('must_not_require_skills').value),
        reject_title_rules: textToRules(settingsField('reject_title_rules').value, 'pattern'),
        reject_description_phrase_rules: textToRules(settingsField('reject_description_phrase_rules').value, 'phrase'),
      };
    }

    async function patchProfile(payload, successMessage) {
      const response = await fetch('/api/profile', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const errorPayload = await response.json().catch(() => ({}));
        throw new Error(errorPayload.error || 'Could not save profile');
      }
      const updated = await response.json();
      fillForm(updated);
      showStatus(successMessage, 'ok');
      return updated;
    }

    async function runSearchNow() {
      const profile = collectProfile();
      const agentSettings = collectAgentSettings();
      const agentResponse = await fetch('/api/agent-settings', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(agentSettings),
      });
      const agentPayload = await agentResponse.json().catch(() => ({}));
      if (!agentResponse.ok) {
        throw new Error(agentPayload.error || 'Could not save shortlist settings');
      }
      fillAgentSettings(agentPayload);
      await patchProfile(
        { search_settings: profile.search_settings, salary_preferences: profile.salary_preferences },
        'Search settings saved to profile.json.'
      );
      const response = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ search_settings: profile.search_settings }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || 'Could not start run');
      showStatus('Background run started. Return to results when complete.', 'ok');
      return payload;
    }

    async function applyOneSkipDecision(skill, choice) {
      const response = await fetch('/api/tuning-decisions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decisions: [{ skill, choice }] }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || 'Could not apply');
      return payload;
    }

    // -- Event listeners ---------------------------------------

    if (runNowButton) {
      runNowButton.addEventListener('click', async () => {
        try {
          await runSearchNow();
        } catch (error) {
          showStatus(error.message, 'error');
        }
      });
    }

    if (rebuildProfileButton) {
      rebuildProfileButton.addEventListener('click', () => {
        window.location.href = '/start?mode=rebuild';
      });
    }

    document.getElementById('refresh_review_data')?.addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      const originalLabel = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Refreshing...';
      try {
        await loadReviewData();
        showStatus('Suggested tuning refreshed.', 'ok', { autoHideMs: 3000 });
      } catch (error) {
        showStatus(error.message, 'error');
      } finally {
        btn.disabled = false;
        btn.textContent = originalLabel;
      }
    });

    const tuningPanel = document.getElementById('tuning_suggestions_panel');
    tuningPanel?.addEventListener('change', (e) => {
      const select = e.target.closest('.skill-choice');
      if (!select) return;
      const card = select.closest('.review-card');
      const guideBody = card?.querySelector('.review-choice-guide-body');
      if (!guideBody) return;
      guideBody.innerHTML = renderReviewChoiceGuide(select.value || '');
    });

    tuningPanel?.addEventListener('click', async (e) => {
      const btn = e.target.closest('.confirm-skill-btn');
      if (btn) {
        const card = btn.closest('.review-card');
        const select = card?.querySelector('.skill-choice');
        const skill = btn.dataset.skill;
        const choice = select?.value;
        if (!skill || !choice) return;
        btn.disabled = true;
        btn.textContent = 'Saving\u2026';
        try {
          const result = await applyOneSkipDecision(skill, choice);
          card.style.opacity = 'var(--opacity-med)';
          card.style.pointerEvents = 'none';
          btn.textContent = 'Applied';
          if (result && result.profile) fillForm(result.profile);
          await loadReviewData();
        } catch (error) {
          btn.disabled = false;
          btn.textContent = 'Confirm';
          showStatus(error.message, 'error');
        }
        return;
      }

      const addBtn = e.target.closest('.add-phrase-exclusion-btn');
      if (addBtn) {
        const card = addBtn.closest('.review-card');
        const reason = addBtn.dataset.reason || '';
        const suffix = reason.split(':').slice(1).join(':').replace(/_/g, ' ').trim().toLowerCase();
        if (!suffix) return;
        addBtn.disabled = true;
        addBtn.textContent = 'Saving\u2026';
        try {
          const response = await fetch('/api/rule/phrase', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phrase: suffix, reason: 'low-fit specialist area' }),
          });
          const payload = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(payload.error || 'Could not add rule');
          card.style.opacity = 'var(--opacity-med)';
          card.style.pointerEvents = 'none';
          addBtn.textContent = 'Added';
        } catch (error) {
          addBtn.disabled = false;
          addBtn.textContent = 'Add to exclusions';
          showStatus(error.message, 'error');
        }
        return;
      }

      const dismissBtn = e.target.closest('.dismiss-rule-card-btn');
      if (dismissBtn) {
        const card = dismissBtn.closest('.review-card');
        if (card) {
          card.style.opacity = 'var(--opacity-med)';
          card.style.pointerEvents = 'none';
          dismissBtn.textContent = 'Dismissed';
        }
      }
    });


    loadReviewData();

