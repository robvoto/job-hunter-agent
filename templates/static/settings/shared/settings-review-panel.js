import { escapeHtml } from './settings-utils.js';
import { showStatus } from './settings-page.js';
import * as capabilityUi from '../../common/capability-ui.js';
import {
  createController,
  WORKSPACE_PATH,
  SEARCH_WAIT_COPY,
  SEARCH_RUNNING_TITLE,
  SEARCH_RUNNING_COPY,
  SEARCH_STARTING_TITLE,
  SEARCH_STARTING_COPY,
  SEARCH_REFRESHING_TITLE,
  SEARCH_REFRESHING_COPY,
  RUN_COMPLETE_REDIRECT_DELAY_MS,
} from '../../common/wait-state.js';

const waitMount = document.getElementById('job_hunter_wait_mount');
const waitUi = createController(waitMount);
let runStatusPollHandle = null;
let runStatusWasRunning = false;

function getReviewChoiceMeta(choice) {
  if (!choice) return { label: 'Choose a strength' };
  return capabilityUi.capabilityLevelMeta?.[choice] || { label: 'Choose a strength' };
}

function renderReviewChoiceGuide(choice) {
  const meta = getReviewChoiceMeta(choice);
  return `
    <strong>${escapeHtml(meta.label)}</strong>
    <p>This sets the capability strength used during matching.</p>
  `;
}

function reviewStrengthChoicesMarkup(selectedValue, groupName) {
  const levels = Array.isArray(capabilityUi.capabilityLevels) && capabilityUi.capabilityLevels.length
    ? capabilityUi.capabilityLevels
    : Object.keys(capabilityUi.capabilityLevelMeta || {});
  return levels.map((level) => {
    const meta = capabilityUi.capabilityLevelMeta?.[level];
    if (!meta || !meta.label) {
      throw new Error(`Missing capability strength label for ${level}.`);
    }
    const inputId = `${groupName}_${level}`;
    const checked = level === selectedValue ? ' checked' : '';
    return `
      <label class="choice-card choice-card--strength" for="${inputId}">
        <input id="${inputId}" type="radio" name="${groupName}" value="${escapeHtml(level)}"${checked} aria-label="${escapeHtml(meta.label)}">
        <span>${escapeHtml(meta.label)}</span>
      </label>
    `;
  }).join('');
}

function getSelectedReviewChoice(card) {
  return String(card?.querySelector('input[type="radio"]:checked')?.value || '').trim();
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
  if (!panel) return;
  const capabilitySuggestions = suggestions.capability_suggestions || [];
  const ruleSuggestions = suggestions.rule_suggestions || [];
  const summary = suggestions.summary || {};
  if (!capabilitySuggestions.length && !ruleSuggestions.length) {
    panel.innerHTML = '<p>No suggested tuning yet. After a scrape run, repeated useful capabilities and repeated exclusion patterns will show up here for confirmation.</p>';
    return;
  }
  const capabilityHtml = capabilitySuggestions.length ? `
    <div class="tuning-group">
      <h3>Capabilities from viable roles</h3>
      <p class="tuning-group-copy">Repeated skills from kept roles that need a decision before the engine can learn how to classify them consistently.</p>
      <div class="review-list">
        ${capabilitySuggestions.map((item, index) => `
          <div class="review-card">
            <h3>${escapeHtml(item.skill || 'Capability')}</h3>
            <p>Seen in ${escapeHtml(String(item.count || 0))} kept role(s).</p>
            <div class="suggestion-meta"><span class="suggestion-chip">Suggested: ${escapeHtml(item.recommended_label || 'Review')}</span></div>
            <label>${escapeHtml(capabilityUi.reviewStrengthPromptLabel)}</label>
            <div class="choice-strip capability-strength-strip review-strength-strip" role="radiogroup" aria-label="${escapeHtml(capabilityUi.reviewStrengthPromptLabel)}" data-skill="${escapeHtml(item.skill || '')}">
              ${reviewStrengthChoicesMarkup(item.recommended_choice || '', `skill-choice-${index}`)}
            </div>
            <details class="review-choice-guide">
              <summary>What this choice means</summary>
              <div class="review-choice-guide-body">${renderReviewChoiceGuide(item.recommended_choice || '')}</div>
            </details>
            <details class="review-examples">
              <summary>Examples from kept roles</summary>
              <div class="review-examples-body">${suggestionExamplesMarkup(item.examples || [], 'No example roles saved for this capability yet.')}</div>
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
    const friendlyReasons = {
      'DESC_ROLE_PROOF_MISSING': 'Validation Rejection: Missing Proof of Seniority/Domain',
      'DESC_CAPABILITY_LOW': 'Validation Rejection: Low Capability Alignment',
      'TITLE_BAD_KEYWORD': 'Title Filter: Blocked Keyword',
      'TITLE_NOT_TARGET': 'Title Filter: Out of Scope'
    };
    const title = item.headline || friendlyReasons[item.reason] || item.reason || 'Rule suggestion';
    return `
      <div class="review-card">
        <h3>${escapeHtml(title)}</h3>
        <p>${escapeHtml(item.detail || '')}</p>
        <div class="suggestion-meta">
          <span class="suggestion-chip">Target: ${escapeHtml(item.target || 'Matching rules')}</span>
          <span class="suggestion-chip">Count: ${escapeHtml(String(item.count || 0))}</span>
        </div>
        <p><strong>Suggested action:</strong> ${escapeHtml(item.recommendation || 'Review this suggestion and decide whether the matching rules need refinement.')}</p>
        <p>Examples:</p>
        ${suggestionExamplesMarkup(item.samples || [], 'No sample roles saved for this suggestion yet.')}
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
      <h3>Repeated exclusion patterns</h3>
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
      <div class="tuning-summary-card"><strong>${escapeHtml(String(summary.rule_count || ruleSuggestions.length || 0))}</strong><span>Rule suggestions to review</span></div>
    </div>
    ${capabilityHtml}
    ${ruleHtml}
  `;
}

async function loadReviewData() {
  const response = await jobHunterFetch('/api/review-data');
  if (!response.ok) { renderSuggestedTuning({ capability_suggestions: [], rule_suggestions: [], summary: {} }); return; }
  const payload = await response.json();
  renderSuggestedTuning(payload.suggested_tuning || { capability_suggestions: [], rule_suggestions: [], summary: {} });
}

function stopRunStatusPolling() {
  if (runStatusPollHandle) {
    window.clearInterval(runStatusPollHandle);
    runStatusPollHandle = null;
  }
}

function startRunStatusPolling() {
  if (runStatusPollHandle) return;
  runStatusPollHandle = window.setInterval(syncRunStatus, 10000);
}

async function syncRunStatus() {
  try {
    const response = await jobHunterFetch('/api/run-status', { method: 'GET' });
    if (!response.ok) throw new Error('Could not check run status.');
    const payload = await response.json().catch(() => ({}));
    const isRunning = payload?.status === 'running';
    if (isRunning) {
      runStatusWasRunning = true;
      startRunStatusPolling();
      waitUi?.show({ title: SEARCH_RUNNING_TITLE, copy: SEARCH_RUNNING_COPY, subcopy: SEARCH_WAIT_COPY });
      return;
    }
    stopRunStatusPolling();
    if (runStatusWasRunning) {
      runStatusWasRunning = false;
      waitUi?.update({ title: SEARCH_REFRESHING_TITLE, copy: SEARCH_REFRESHING_COPY });
      showStatus('Search finished. Loading the workspace now.', 'success');
      window.setTimeout(() => window.location.replace(WORKSPACE_PATH), RUN_COMPLETE_REDIRECT_DELAY_MS);
      return;
    }
    waitUi?.hide();
  } catch (error) {
  }
}

async function patchProfile(payload, successMessage) {
  const response = await jobHunterFetch('/api/profile', {
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
  showStatus(successMessage, 'success');
  return updated;
}

async function runSearchNow() {
  const profile = collectProfile();
  const agentSettings = collectUserSettings();
  const agentResponse = await jobHunterFetch('/api/user-settings', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(agentSettings),
  });
  const agentPayload = await agentResponse.json().catch(() => ({}));
  if (!agentResponse.ok) throw new Error(agentPayload.error || 'Could not save shortlist settings');
  fillUserSettings(agentPayload);
  await patchProfile(
    { search_settings: profile.search_settings, salary_preferences: profile.salary_preferences },
    'Search settings saved to profile.json.'
  );
  waitUi?.show({ title: SEARCH_STARTING_TITLE, copy: SEARCH_STARTING_COPY, subcopy: SEARCH_WAIT_COPY });
  const response = await jobHunterFetch('/api/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ search_settings: profile.search_settings }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || 'Could not start run');
  runStatusWasRunning = true;
  startRunStatusPolling();
  void syncRunStatus();
  waitUi?.show({ title: SEARCH_RUNNING_TITLE, copy: SEARCH_RUNNING_COPY, subcopy: SEARCH_WAIT_COPY });
  showStatus('Search started. The workspace will open when it finishes.', 'success');
  return payload;
}

async function applyOneSkipDecision(skill, choice) {
  const response = await jobHunterFetch('/api/tuning-decisions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decisions: [{ skill, choice }] }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || 'Could not apply');
  return payload;
}

// -- Event listeners ---------------------------------------

const runNowButton = document.getElementById('run_now');
const rebuildProfileButton = document.getElementById('rebuild_profile');

  if (runNowButton) {
  runNowButton.addEventListener('click', async () => {
    try {
      await runSearchNow();
    } catch (error) {
      waitUi?.hide();
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
    showStatus('Suggested tuning refreshed.', 'success', { autoHideMs: 3000 });
  } catch (error) {
    showStatus(error.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = originalLabel;
  }
});

const tuningPanel = document.getElementById('tuning_suggestions_panel');
tuningPanel?.addEventListener('change', (e) => {
  const input = e.target.closest('input[type="radio"]');
  if (!input || !input.name?.startsWith('skill-choice-')) return;
  const card = input.closest('.review-card');
  const guideBody = card?.querySelector('.review-choice-guide-body');
  if (!guideBody) return;
  guideBody.innerHTML = renderReviewChoiceGuide(input.value || '');
});

tuningPanel?.addEventListener('click', async (e) => {
  const btn = e.target.closest('.confirm-skill-btn');
  if (btn) {
    const card = btn.closest('.review-card');
    const skill = btn.dataset.skill;
    const choice = getSelectedReviewChoice(card);
    if (!skill || !choice) return;
    btn.disabled = true;
    btn.textContent = 'Saving…';
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
    addBtn.textContent = 'Saving…';
    try {
      const response = await jobHunterFetch('/api/rule/phrase', {
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

if (document.getElementById('tuning_suggestions_panel')) {
  loadReviewData();
}
