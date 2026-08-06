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
const titleTierLabels = window.__JOB_HUNTER_TITLE_TIER_LABELS__ || {};
if (!capabilityLabels.onboarding_title || !capabilityLabels.help_text) {
  throw new Error('Missing capability UI labels.');
}
if (!titleTierLabels.target_roles_label || !titleTierLabels.target_roles_help || !titleTierLabels.target_roles_empty_text) {
  throw new Error('Missing onboarding title tier labels.');
}
const capabilityTitle = capabilityLabels.onboarding_title;
const preferredRolesLabel = titleTierLabels.target_roles_label;

const TUNING_TEXT = {
  capabilityHeading: capabilityTitle,
  capabilityCopy: capabilityLabels.help_text,
  capabilityEmpty: capabilityLabels.onboarding_empty_text,
  optimizationHeading: preferredRolesLabel,
  optimizationCopy: titleTierLabels.target_roles_help,
  optimizationEmpty: titleTierLabels.target_roles_empty_text,
  requirementHeading: 'Requirements to address',
  requirementCopy: 'Explicit requirements repeated in kept roles. Confirm them if you already have them, or treat them as a blocker if you do not.',
  titleTuningHeading: 'Search/title tuning',
  titleTuningCopy: 'These title-based signals are strong enough to consider a hard blocker later, once you are sure they are consistently wrong.',
  workingFiltersHeading: 'Filters already working correctly',
  workingFiltersCopy: 'These title keyword filters are already blocking off-target roles before deeper review.',
  otherRulesHeading: 'Repeated exclusion patterns',
  otherRulesCopy: 'Patterns from rejects that are worth keeping, strengthening, or watching before you touch search keywords.',
};

const NO_CAPABILITY_SUGGESTIONS_COPY = 'No capability suggestions yet. We found no saved review data from the latest search. Run a search again so kept jobs can be analysed for new capability signals.';
const NO_CAPABILITY_OBSERVATIONS_COPY = 'No capability suggestions yet. We found kept jobs, but no new capability observations were extracted from them.';

const RULE_REASON_TITLE_NOT_TARGET = 'TITLE_NOT_TARGET';
const RULE_REASON_TITLE_BAD_KEYWORD = 'TITLE_BAD_KEYWORD';
const RULE_REASON_ONET_UNCERTAIN_TITLE = 'ONET_UNCERTAIN_TITLE';
const DECLINE_CAPABILITY_LABEL = "No, I don't have this";

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
      <label class="choice-card choice-card--strength ${escapeHtml(meta.tone || '')}" for="${inputId}">
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

function requirementPhrasesMarkup(items, emptyLabel) {
  if (!items || !items.length) return `<p>${escapeHtml(emptyLabel)}</p>`;
  return `<ul>${items.map(item => `
    <li>${escapeHtml(item)}</li>
  `).join('')}</ul>`;
}

function slugifyReviewKey(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'choice';
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
        <button class="secondary add-phrase-exclusion-btn" data-reason="${escapeHtml(item.reason || '')}" style="font-size:0.9rem;padding:8px 16px;border-color:var(--state-error-border);color:var(--state-error-text);background:var(--state-error-bg);">Add to exclusions</button>
      </div>` : ''}
      ${(item.reason || '').startsWith(RULE_REASON_TITLE_BAD_KEYWORD) ? `
      <div class="card-actions" style="margin-top:10px;">
        <button class="secondary dismiss-rule-card-btn" style="font-size:0.9rem;padding:8px 16px;">Dismiss</button>
      </div>` : ''}
    </div>`;
}

function renderTuningGroup(title, copy, items, extraClass = '') {
  if (!items.length) return '';
  const className = extraClass ? ` tuning-group--${extraClass}` : '';
  return `
    <div class="tuning-group${className}">
      <h3>${escapeHtml(title)}</h3>
      <p class="tuning-group-copy">${escapeHtml(copy)}</p>
      <div class="review-list">
        ${items.map(item => renderRuleCard(item)).join('')}
      </div>
    </div>
  `;
}

function renderRequirementGroup(items) {
  if (!items.length) return '';
  return `
    <div class="tuning-group tuning-group--requirements">
      <h3>${escapeHtml(TUNING_TEXT.requirementHeading)}</h3>
      <p class="tuning-group-copy">${escapeHtml(TUNING_TEXT.requirementCopy)}</p>
      <div class="review-list">
        ${items.map(item => renderRequirementCard(item)).join('')}
      </div>
    </div>
  `;
}

function renderTuningSection(title, copy, items, emptyText, renderItem, extraClass = '') {
  const className = extraClass ? ` tuning-group--${extraClass}` : '';
  const body = items.length
    ? `<div class="review-list">${items.map(renderItem).join('')}</div>`
    : `<p class="tuning-empty-state-copy">${escapeHtml(emptyText)}</p>`;
  return `
    <div class="tuning-group${className}">
      <h3>${escapeHtml(title)}</h3>
      <p class="tuning-group-copy">${escapeHtml(copy)}</p>
      ${body}
    </div>
  `;
}

function renderRequirementCard(item) {
  const aliases = Array.isArray(item.aliases) ? item.aliases : [];
  const choiceGroupName = `requirement-choice-${slugifyReviewKey(item.skill || '')}`;
  return `
    <div class="review-card">
      <h3>${escapeHtml(item.skill || 'Requirement')}</h3>
      <p>${escapeHtml(item.detail || '')}</p>
      <p><strong>Prompt:</strong> ${escapeHtml(item.prompt || 'Do you have this capability?')}</p>
      <div class="suggestion-meta">
        <span class="suggestion-chip">Suggested: ${escapeHtml(item.recommended_label || 'Review')}</span>
        <span class="suggestion-chip">Count: ${escapeHtml(String(item.count || 0))}</span>
      </div>
      <label>${escapeHtml(capabilityUi.reviewStrengthPromptLabel)}</label>
      <div class="choice-strip capability-strength-strip review-strength-strip" role="radiogroup" aria-label="${escapeHtml(capabilityUi.reviewStrengthPromptLabel)}" data-skill="${escapeHtml(item.skill || '')}" data-aliases="${escapeHtml(JSON.stringify(aliases))}">
        ${reviewStrengthChoicesMarkup(item.recommended_choice || '', choiceGroupName)}
      </div>
      <details class="review-choice-guide">
        <summary>What this choice means</summary>
        <div class="review-choice-guide-body">${renderReviewChoiceGuide(item.recommended_choice || '')}</div>
      </details>
      <details class="review-examples">
        <summary>Requirement wording</summary>
        <div class="review-examples-body">${requirementPhrasesMarkup(aliases, 'No literal requirement text saved yet.')}</div>
      </details>
      <details class="review-examples">
        <summary>Examples from kept roles</summary>
        <div class="review-examples-body">${suggestionExamplesMarkup(item.examples || [], 'No example roles saved for this requirement yet.')}</div>
      </details>
      <div class="card-actions" style="margin-top:10px;">
        <button class="jh-button jh-button--primary jh-button--compact confirm-skill-btn" data-skill="${escapeHtml(item.skill || '')}" data-aliases="${escapeHtml(JSON.stringify(aliases))}">Confirm</button>
      </div>
    </div>
  `;
}

function renderSuggestedTuning(reviewData) {
  const panel = document.getElementById('tuning_suggestions_panel');
  if (!panel) return;
  const suggestions = reviewData.suggested_tuning || {};
  const capabilitySuggestions = suggestions.capability_suggestions || [];
  const requirementSuggestions = suggestions.requirement_suggestions || [];
  const optimizationSuggestions = suggestions.optimization_suggestions || [];
  const ruleSuggestions = suggestions.rule_suggestions || [];
  const summary = suggestions.summary || {};
  const capabilityEmptyCopy = Number(summary.capability_count || 0) > 0
    ? NO_CAPABILITY_OBSERVATIONS_COPY
    : NO_CAPABILITY_SUGGESTIONS_COPY;
  const capabilityHtml = renderTuningSection(
    TUNING_TEXT.capabilityHeading,
    TUNING_TEXT.capabilityCopy,
    capabilitySuggestions,
    capabilityEmptyCopy,
    (item, index) => `
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
          <button class="jh-button jh-button--primary jh-button--compact confirm-skill-btn" data-skill="${escapeHtml(item.skill || '')}">Confirm</button>
          <button class="jh-button jh-button--secondary jh-button--compact decline-skill-btn" data-skill="${escapeHtml(item.skill || '')}">${escapeHtml(DECLINE_CAPABILITY_LABEL)}</button>
        </div>
      </div>
    `,
    'capabilities'
  );
  const optimizationHtml = renderTuningSection(
    TUNING_TEXT.optimizationHeading,
    TUNING_TEXT.optimizationCopy,
    optimizationSuggestions,
    TUNING_TEXT.optimizationEmpty,
    (item) => renderRuleCard(item),
    'optimization'
  );
  const titleTuningRules = ruleSuggestions.filter((item) => (item.reason || '') === RULE_REASON_TITLE_NOT_TARGET);
  const workingFilterRules = ruleSuggestions.filter((item) => (item.reason || '') === RULE_REASON_TITLE_BAD_KEYWORD);
  const otherRuleSuggestions = ruleSuggestions.filter((item) => {
    const reason = item.reason || '';
    return reason !== RULE_REASON_TITLE_NOT_TARGET && reason !== RULE_REASON_TITLE_BAD_KEYWORD && reason !== RULE_REASON_ONET_UNCERTAIN_TITLE;
  });
  const renderedRuleCount = titleTuningRules.length + workingFilterRules.length + otherRuleSuggestions.length;
  const requirementHtml = requirementSuggestions.length ? renderRequirementGroup(requirementSuggestions) : '';

  const ruleHtml = renderedRuleCount ? `
    ${renderTuningGroup(TUNING_TEXT.titleTuningHeading, TUNING_TEXT.titleTuningCopy, titleTuningRules, 'title-tuning')}
    ${renderTuningGroup(TUNING_TEXT.workingFiltersHeading, TUNING_TEXT.workingFiltersCopy, workingFilterRules, 'working-filters')}
    ${renderTuningGroup(TUNING_TEXT.otherRulesHeading, TUNING_TEXT.otherRulesCopy, otherRuleSuggestions, 'other-rules')}
  ` : '';

  panel.innerHTML = `
    <div class="tuning-suggestions-content">
      <div class="tuning-summary">
        <div class="tuning-summary-card"><strong>${escapeHtml(String(summary.capability_count || capabilitySuggestions.length || 0))}</strong><span>${escapeHtml(`${capabilityTitle} suggestions`)}</span></div>
        <div class="tuning-summary-card"><strong>${escapeHtml(String(summary.requirement_count || requirementSuggestions.length || 0))}</strong><span>Requirement suggestions</span></div>
        <div class="tuning-summary-card"><strong>${escapeHtml(String(summary.optimization_count || optimizationSuggestions.length || 0))}</strong><span>${escapeHtml(`${preferredRolesLabel} suggestions`)}</span></div>
        <div class="tuning-summary-card"><strong>${escapeHtml(String(renderedRuleCount))}</strong><span>Rule suggestions to review</span></div>
      </div>
      ${capabilityHtml}
      ${optimizationHtml}
      ${requirementHtml}
      ${ruleHtml}
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

function setAppliedCardState(card, button, label) {
  if (card) {
    card.style.opacity = 'var(--opacity-med)';
    card.style.pointerEvents = 'none';
  }
  if (button) {
    button.textContent = label;
  }
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
  const guideBody = card?.querySelector('.review-choice-guide-body');
  if (!guideBody) return;
  guideBody.innerHTML = renderReviewChoiceGuide(input.value || '');
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
      setAppliedCardState(card, btn, 'Applied');
      if (result && result.profile) fillForm(result.profile);
      await loadReviewData();
    } catch (error) {
      btn.disabled = false;
      btn.textContent = 'Confirm';
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
      setAppliedCardState(card, declineBtn, 'Removed');
      if (result && result.profile) fillForm(result.profile);
      await loadReviewData();
    } catch (error) {
      declineBtn.disabled = false;
      declineBtn.textContent = DECLINE_CAPABILITY_LABEL;
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
