import { escapeHtml, settingsField } from './settings-utils.js';

export const JobHunterEligibilityEditor = (function () {
  const labels = window.__JOB_HUNTER_SETTINGS_CLEARANCES_LABELS__;
  if (!labels) throw new Error('Missing settings clearances labels.');

  let factState = [];

  function normalizeText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function showAddStatus(element, message, kind) {
    if (!element) return;
    element.textContent = message;
    element.className = message ? `field-help inline-status ${kind}` : 'field-help';
  }

  function normalizeFact(fact) {
    return {
      name: normalizeText(fact?.name || ''),
      value: fact?.value !== false,
      evidence: Array.isArray(fact?.evidence) ? fact.evidence : [],
    };
  }

  // Shared save path for both the Settings "Add" flow and the job-results
  // "Add to profile" prefill flow (see /api/profile/eligibility).
  async function saveEligibilityFact(payload) {
    const response = await window.jobHunterFetch('/api/profile/eligibility', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body?.error) {
      const error = new Error(body?.error || 'Could not save eligibility fact.');
      error.serverMessage = body?.error || '';
      throw error;
    }
    return body;
  }

  function upsertFactFromServer(serverFact) {
    const normalized = normalizeFact(serverFact);
    const index = factState.findIndex(
      (fact) => fact.name.toLowerCase() === normalized.name.toLowerCase()
    );
    if (index === -1) {
      factState.push(normalized);
    } else {
      factState[index] = normalized;
    }
    persist();
    render();
    return normalized;
  }

  function persist() {
    settingsField('candidate_eligibility_facts').value = JSON.stringify(factState);
  }

  function render() {
    const groupTitle = document.getElementById('eligibility_group_title');
    const groupHelp = document.getElementById('eligibility_group_help');
    const title = document.getElementById('eligibility_editor_title');
    const help = document.getElementById('eligibility_editor_help');
    const addInput = document.getElementById('eligibility_name_add');
    const addButton = document.getElementById('eligibility_add');
    if (groupTitle) groupTitle.textContent = labels.eligibility_group_title;
    if (groupHelp) groupHelp.textContent = labels.eligibility_group_help_text;
    if (title) title.textContent = labels.eligibility_settings_title;
    if (help) help.textContent = labels.eligibility_help_text;
    if (addInput) addInput.placeholder = labels.eligibility_name_placeholder;
    if (addButton) {
      addButton.textContent = labels.eligibility_add_button_label;
      addButton.setAttribute('aria-label', labels.eligibility_add_button_aria_label);
    }
    const container = document.getElementById('eligibility_editor');
    if (!container) return;
    const cards = factState.map((fact, index) => {
      const toggleId = `eligibility_toggle_${index}`;
      return `
        <article class="capability-card eligibility-card" data-eligibility-index="${index}">
          <div class="capability-card-main eligibility-card-main">
            <div class="eligibility-card-copy">
              <label class="eligibility-card-title" for="eligibility_name_${index}">${escapeHtml(labels.eligibility_name_label)}</label>
              <input id="eligibility_name_${index}" class="token-input-field" data-eligibility-field="name" data-eligibility-index="${index}" value="${escapeHtml(fact.name)}">
            </div>
          </div>
          <div class="capability-card-actions eligibility-card-actions">
            <label class="toggle-switch toggle-switch--compact" for="${toggleId}">
              <span class="toggle-switch-control">
                <input id="${toggleId}" type="checkbox" role="switch" data-eligibility-field="value" data-eligibility-index="${index}"${fact.value ? ' checked' : ''}>
                <span class="toggle-switch-ui"></span>
              </span>
            </label>
            <button class="cap-remove-btn capability-remove-btn" type="button" data-eligibility-field="remove" data-eligibility-index="${index}"
                    aria-label="${escapeHtml(labels.eligibility_remove_button_label)} ${escapeHtml(fact.name)}"
                    title="${escapeHtml(labels.eligibility_remove_button_label)}">
              <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" class="cap-remove-icon">
                <path d="M9 3.5h6l1 1.5H19v2H5v-2h3l1-1.5Zm-1 5h8l-.6 9.3A2 2 0 0 1 13.4 20H10.6a2 2 0 0 1-1.99-1.7L8 8.5Zm2 2v6m4-6v6" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"></path>
              </svg>
            </button>
          </div>
        </article>`;
    }).join('');
    container.innerHTML = cards ? `<div class="capability-grid eligibility-grid">${cards}</div>` : `<p class="panel-copy">${escapeHtml(labels.eligibility_empty_text)}</p>`;
  }

  function setEligibilityFactState(facts) {
    factState = (Array.isArray(facts) ? facts : []).map(normalizeFact).filter((fact) => fact.name);
    persist();
    render();
  }

  function collectEligibilityFactState() {
    factState = factState.map(normalizeFact).filter((fact) => fact.name);
    persist();
    return factState;
  }

  function initEventHandlers(markDirty) {
    document.getElementById('eligibility_add')?.addEventListener('click', async () => {
      const input = document.getElementById('eligibility_name_add');
      const addButton = document.getElementById('eligibility_add');
      const statusEl = document.getElementById('eligibility_add_status');
      const name = normalizeText(input?.value);
      showAddStatus(statusEl, '', '');
      if (!name) return;
      if (factState.some((fact) => fact.name.toLowerCase() === name.toLowerCase())) {
        if (input) input.value = '';
        return;
      }
      if (addButton) addButton.disabled = true;
      showAddStatus(statusEl, labels.eligibility_add_loading_message, 'loading');
      try {
        const body = await saveEligibilityFact({ name, value: true });
        upsertFactFromServer(body.eligibility_fact);
        markDirty();
        if (input) input.value = '';
        showAddStatus(statusEl, '', '');
      } catch (error) {
        showAddStatus(statusEl, error.serverMessage || labels.eligibility_add_error_message, 'error');
      } finally {
        if (addButton) addButton.disabled = false;
      }
    });
    document.getElementById('eligibility_editor')?.addEventListener('input', (event) => {
      const field = event.target.closest('[data-eligibility-field]');
      if (!field) return;
      const index = Number(field.dataset.eligibilityIndex);
      if (!Number.isInteger(index) || !factState[index]) return;
      if (field.dataset.eligibilityField === 'name') {
        factState[index].name = normalizeText(field.value);
      }
      persist();
      markDirty();
    });
    document.getElementById('eligibility_editor')?.addEventListener('click', (event) => {
      const field = event.target.closest('[data-eligibility-field="remove"]');
      if (!field) return;
      const index = Number(field.dataset.eligibilityIndex);
      if (!Number.isInteger(index) || !factState[index]) return;
      factState.splice(index, 1);
      persist();
      render();
      markDirty();
    });
    document.getElementById('eligibility_editor')?.addEventListener('change', (event) => {
      const field = event.target.closest('[data-eligibility-field="value"]');
      if (!field) return;
      const index = Number(field.dataset.eligibilityIndex);
      if (!Number.isInteger(index) || !factState[index]) return;
      factState[index].value = field.checked;
      persist();
      render();
      markDirty();
    });
  }

  return {
    setEligibilityFactState,
    collectEligibilityFactState,
    initEventHandlers,
    saveEligibilityFact,
    upsertFactFromServer,
  };
}());
