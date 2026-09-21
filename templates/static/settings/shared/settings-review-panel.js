import { escapeHtml } from './settings-utils.js';
import { refreshSettingsForm, showStatus } from './settings-page.js';
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
  SEARCH_STOPPING_TITLE,
  SEARCH_STOPPING_COPY,
  SEARCH_STOPPING_SUBCOPY,
  RUN_COMPLETE_REDIRECT_DELAY_MS,
} from '../../common/wait-state.js';

const waitMount = document.getElementById('job_hunter_wait_mount');
const waitUi = createController(waitMount);
let runStatusPollHandle = null;
let runStatusWasRunning = false;

const capabilityLabels = capabilityUi.labels || {};
if (!capabilityLabels.onboarding_title || !capabilityLabels.help_text) {
  throw new Error('Missing capability UI labels.');
}

const RULE_REASON_TITLE_NOT_TARGET = 'TITLE_NOT_TARGET';
const RULE_REASON_TITLE_BAD_KEYWORD = 'TITLE_BAD_KEYWORD';
const RULE_REASON_ONET_UNCERTAIN_TITLE = 'ONET_UNCERTAIN_TITLE';
const DECLINE_CAPABILITY_LABEL = capabilityLabels.decline_capability_label;
// Keep the current UI clear even if a long-running local server still has the legacy
// managed label cached. The managed source now owns "Ignore suggestion"; this bridge
// can disappear once the old "Dismiss" value is no longer possible at runtime.
const DISMISS_CAPABILITY_SUGGESTION_LABEL = capabilityLabels.dismiss_capability_suggestion_label === 'Dismiss'
  ? 'Ignore suggestion'
  : capabilityLabels.dismiss_capability_suggestion_label;

function getReviewChoiceMeta(choice) {
  if (!choice) return { label: 'Choose a strength' };
  return capabilityUi.capabilityLevelMeta?.[choice] || { label: 'Choose a strength' };
}

function strengthQuestionMarkup(groupName) {
  return `
    <div class="field-label-row review-strength-question">
      <span class="review-strength-question-label">${escapeHtml(capabilityUi.reviewStrengthPromptLabel)}</span>
      <details class="field-info-drawer">
        <summary class="field-info" aria-label="About capability strength">i</summary>
        <div class="field-info-panel">Strength controls how much this capability influences matching. Basic = light influence. Working = normal influence. Strong = high influence.</div>
      </details>
    </div>
    <div class="review-strength-meter">
      ${capabilityUi.capabilityStrengthMeterMarkup({
        selectedValue: '',
        groupName,
        inputIdPrefix: groupName,
        ariaLabel: capabilityUi.reviewStrengthPromptLabel,
        emptyLabel: 'Select strength',
      })}
    </div>
  `;
}

function keptRoleCountLabel(count) {
  const value = Math.max(0, Number(count) || 0);
  return `Seen in ${value} kept ${value === 1 ? 'role' : 'roles'}`;
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

function requirementPhrasesMarkup(items, emptyLabel) {
  if (!items || !items.length) return `<p>${escapeHtml(emptyLabel)}</p>`;
  return `<ul>${items.map(item => `
    <li>${escapeHtml(item)}</li>
  `).join('')}</ul>`;
}


function normalizeSuggestionSkill(value) {
  return String(value || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

function mergeSuggestionExamples(left = [], right = []) {
  const seen = new Set();
  const merged = [];
  [...left, ...right].forEach((item) => {
    if (!item || typeof item !== 'object') return;
    const key = String(item.url || '').trim() || `${item.title || ''}|${item.company || ''}`;
    if (!key || seen.has(key)) return;
    seen.add(key);
    merged.push(item);
  });
  return merged;
}

function mergeCapabilitySuggestions(capabilitySuggestions, requirementSuggestions) {
  const merged = new Map();
  [...capabilitySuggestions, ...requirementSuggestions].forEach((item) => {
    const key = normalizeSuggestionSkill(item?.skill);
    if (!key) return;
    const existing = merged.get(key);
    if (!existing) {
      merged.set(key, {
        ...item,
        aliases: Array.isArray(item.aliases) ? [...item.aliases] : [],
        examples: Array.isArray(item.examples) ? [...item.examples] : [],
        evidenceKinds: new Set([item.kind || 'capability']),
      });
      return;
    }
    existing.count = Math.max(Number(existing.count) || 0, Number(item.count) || 0);
    existing.aliases = [...new Set([...(existing.aliases || []), ...((item.aliases || []))])];
    existing.examples = mergeSuggestionExamples(existing.examples, item.examples || []);
    existing.evidenceKinds.add(item.kind || 'capability');
  });
  return [...merged.values()]
    .map(item => ({ ...item, evidenceKinds: [...item.evidenceKinds] }))
    .sort((left, right) => (Number(right.count) || 0) - (Number(left.count) || 0) || String(left.skill).localeCompare(String(right.skill)));
}

function capabilityEvidenceMarkup(item) {
  const count = Math.max(0, Number(item.count) || 0);
  const aliases = Array.isArray(item.aliases) ? item.aliases : [];
  const sourceKinds = new Set(item.evidenceKinds || [item.kind || 'capability']);
  const countCopy = `Found repeatedly across ${count} ${count === 1 ? 'job' : 'jobs'} you kept.`;
  const requirementCopy = sourceKinds.has('requirement') && aliases.length
    ? `<p><strong>Job ads explicitly asked for:</strong></p>${requirementPhrasesMarkup(aliases, '')}`
    : '';
  return `
    <p><strong>${escapeHtml(countCopy)}</strong></p>
    ${requirementCopy}
    <p><strong>Examples where it appeared:</strong></p>
    ${suggestionExamplesMarkup(item.examples || [], 'No example jobs saved for this capability yet.')}
  `;
}

function renderCapabilitySuggestionCard(item, index) {
  const aliases = Array.isArray(item.aliases) ? item.aliases : [];
  const groupName = `skill-choice-${index}`;
  return `
    <div class="review-card" data-review-kind="capability">
      <div class="settings-subpanel-head review-card-heading">
        <h3>${escapeHtml(item.skill || 'Capability')}</h3>
        <span class="review-card-count">${escapeHtml(keptRoleCountLabel(item.count))}</span>
      </div>
      ${strengthQuestionMarkup(groupName)}
      <details class="review-examples review-evidence">
        <summary>Why Job Hunter suggested this</summary>
        <div class="review-examples-body">${capabilityEvidenceMarkup(item)}</div>
      </details>
      <div class="card-actions" style="margin-top:10px;">
        <button class="jh-button jh-button--primary jh-button--compact confirm-skill-btn" data-skill="${escapeHtml(item.skill || '')}" data-aliases="${escapeHtml(JSON.stringify(aliases))}" disabled>Confirm</button>
        <button class="jh-button jh-button--danger jh-button--compact do-not-have-skill-btn" data-skill="${escapeHtml(item.skill || '')}">${escapeHtml(DECLINE_CAPABILITY_LABEL)}</button>
        <button class="jh-button jh-button--secondary jh-button--compact decline-skill-btn" data-skill="${escapeHtml(item.skill || '')}" title="Hide this suggestion without saying you do not have the capability.">${escapeHtml(DISMISS_CAPABILITY_SUGGESTION_LABEL)}</button>
      </div>
    </div>
  `;
}

function renderRuleCard(item) {
  const friendlyReasons = {
    DESC_ROLE_PROOF_MISSING: 'Validation Rejection: Missing Proof of Seniority/Domain',
    DESC_CAPABILITY_LOW: 'Validation Rejection: Low Capability Alignment',
    [RULE_REASON_TITLE_BAD_KEYWORD]: 'Title Filter: Blocked Keyword',
    [RULE_REASON_TITLE_NOT_TARGET]: 'Title Filter: Out of Scope',
    [RULE_REASON_ONET_UNCERTAIN_TITLE]: 'Optimisation Suggestion: O*NET could not classify title',
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
        <button class="jh-button jh-button--danger jh-button--compact add-phrase-exclusion-btn" data-reason="${escapeHtml(item.reason || '')}">Add to exclusions</button>
      </div>` : ''}
      ${(item.reason || '').startsWith(RULE_REASON_TITLE_BAD_KEYWORD) ? `
      <div class="card-actions" style="margin-top:10px;">
        <button class="jh-button jh-button--neutral jh-button--compact dismiss-rule-card-btn">Dismiss</button>
      </div>` : ''}
    </div>`;
}


function renderSuggestionSection(title, copy, items, renderItem, emptyText = '') {
  const count = items.length;
  const body = count
    ? `<div class="review-list">${items.map(renderItem).join('')}</div>`
    : (emptyText ? `<p class="tuning-empty-state-copy">${escapeHtml(emptyText)}</p>` : '');
  if (!count && !body) return '';
  return `
    <div class="tuning-group">
      <div class="tuning-group-heading">
        <h3>${escapeHtml(title)} <span class="tuning-group-count">(${count})</span></h3>
      </div>
      ${copy ? `<p class="tuning-group-copy">${escapeHtml(copy)}</p>` : ''}
      ${body}
    </div>
  `;
}

function renderSuggestedTuning(reviewData) {
  const panel = document.getElementById('tuning_suggestions_panel');
  if (!panel) return;
  const suggestions = reviewData?.suggested_tuning || {};
  const capabilitySuggestions = suggestions.capability_suggestions || [];
  const requirementSuggestions = suggestions.requirement_suggestions || [];
  const optimizationSuggestions = suggestions.optimization_suggestions || [];
  const ruleSuggestions = suggestions.rule_suggestions || [];

  const profileSuggestions = mergeCapabilitySuggestions(capabilitySuggestions, requirementSuggestions);
  const actionableRules = ruleSuggestions.filter((item) => (item.reason || '') !== RULE_REASON_TITLE_BAD_KEYWORD);
  const matchingSuggestions = [...optimizationSuggestions, ...actionableRules];

  const reviewCount = document.getElementById('review_suggestions_count');
  if (reviewCount) reviewCount.textContent = `(${profileSuggestions.length})`;
  const profileHtml = profileSuggestions.length
    ? `<div class="review-list">${profileSuggestions.map((item, index) => renderCapabilitySuggestionCard(item, index)).join('')}</div>`
    : '<p class="tuning-empty-state-copy">No new capabilities to verify.</p>';
  const matchingHtml = renderSuggestionSection(
    'Search & filter improvements',
    'Patterns suggesting your matching or filtering could be improved.',
    matchingSuggestions,
    (item) => renderRuleCard(item),
  );

  panel.innerHTML = `
    <div class="tuning-suggestions-content">
      ${profileHtml}
      ${matchingHtml}
    </div>
  `;
}

async function loadReviewData() {
  const response = await jobHunterFetch('/api/review-data');
  if (!response.ok) { renderSuggestedTuning(null); return; }
  const payload = await response.json();
  renderSuggestedTuning(payload);
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
    const isStopping = payload?.status === 'stopping';
    const isStopped = payload?.status === 'stopped';
    if (isRunning || isStopping) {
      runStatusWasRunning = true;
      startRunStatusPolling();
      waitUi?.show({
        title: isStopping ? SEARCH_STOPPING_TITLE : SEARCH_RUNNING_TITLE,
        copy: isStopping ? SEARCH_STOPPING_COPY : SEARCH_RUNNING_COPY,
        subcopy: isStopping ? SEARCH_STOPPING_SUBCOPY : SEARCH_WAIT_COPY,
        progress: payload?.progress || '',
        progressDetail: payload?.progress_detail || null,
        elapsedText: payload?.elapsed_text || '',
      });
      return;
    }
    if (isStopped && runStatusWasRunning) {
      runStatusWasRunning = false;
      stopRunStatusPolling();
      waitUi?.show({
        title: SEARCH_STOPPING_TITLE,
        copy: SEARCH_STOPPING_COPY,
        subcopy: SEARCH_STOPPING_SUBCOPY,
        progress: payload?.progress || '',
        progressDetail: payload?.progress_detail || null,
        elapsedText: payload?.elapsed_text || '',
      });
      showStatus(SEARCH_REFRESHING_COPY, 'success');
      window.setTimeout(() => window.location.replace(WORKSPACE_PATH), RUN_COMPLETE_REDIRECT_DELAY_MS);
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
  refreshSettingsForm(updated);
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
    'Search settings saved to the runtime profile.'
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

async function applyOneSkipDecision(skill, choice, aliases = []) {
  const response = await jobHunterFetch('/api/tuning-decisions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decisions: [{ skill, choice, aliases }] }),
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
    if (!window.confirm('This overwrites your current profile with a fresh upload. This cannot be undone. Continue?')) {
      return;
    }
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
  if (!input || (!input.name?.startsWith('skill-choice-') && !input.name?.startsWith('requirement-choice-'))) return;
  const card = input.closest('.review-card');
  const confirmBtn = card?.querySelector('.confirm-skill-btn');
  if (confirmBtn) confirmBtn.disabled = false;
  capabilityUi.updateCapabilityStrengthMeter(card?.querySelector('.capability-strength-meter'), input.value || '', 'Select strength');
});

tuningPanel?.addEventListener('click', async (e) => {
  const btn = e.target.closest('.confirm-skill-btn');
  if (btn) {
    const card = btn.closest('.review-card');
    const skill = btn.dataset.skill;
    const aliases = (() => {
      try {
        const parsed = JSON.parse(btn.dataset.aliases || '[]');
        return Array.isArray(parsed) ? parsed : [];
      } catch {
        return [];
      }
    })();
    const choice = getSelectedReviewChoice(card);
    if (!skill || !choice) return;
    btn.disabled = true;
    btn.textContent = 'Saving…';
    try {
      const result = await applyOneSkipDecision(skill, choice, aliases);
      if (result && result.profile) refreshSettingsForm(result.profile);
      card?.remove();
      showStatus(`Added ${skill} — ${getReviewChoiceMeta(choice).label}.`, 'success', { autoHideMs: 3500 });
    } catch (error) {
      btn.disabled = false;
      btn.textContent = 'Confirm';
      showStatus(error.message, 'error');
    }
    return;
  }

  const doNotHaveBtn = e.target.closest('.do-not-have-skill-btn');
  if (doNotHaveBtn) {
    const card = doNotHaveBtn.closest('.review-card');
    const skill = doNotHaveBtn.dataset.skill;
    if (!skill) return;
    doNotHaveBtn.disabled = true;
    doNotHaveBtn.textContent = 'Saving…';
    try {
      const result = await applyOneSkipDecision(skill, 'do_not_have');
      if (result && result.profile) refreshSettingsForm(result.profile);
      card?.remove();
      showStatus(`Saved: you do not have ${skill}.`, 'success', { autoHideMs: 3500 });
    } catch (error) {
      doNotHaveBtn.disabled = false;
      doNotHaveBtn.textContent = DECLINE_CAPABILITY_LABEL;
      showStatus(error.message, 'error');
    }
    return;
  }

  const declineBtn = e.target.closest('.decline-skill-btn');
  if (declineBtn) {
    const card = declineBtn.closest('.review-card');
    const skill = declineBtn.dataset.skill;
    if (!skill) return;
    declineBtn.disabled = true;
    declineBtn.textContent = 'Saving…';
    try {
      const result = await applyOneSkipDecision(skill, 'dismiss');
      if (result && result.profile) refreshSettingsForm(result.profile);
      card?.remove();
      showStatus(`Ignored suggestion: ${skill}.`, 'success', { autoHideMs: 3000 });
    } catch (error) {
      declineBtn.disabled = false;
      declineBtn.textContent = DISMISS_CAPABILITY_SUGGESTION_LABEL;
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
