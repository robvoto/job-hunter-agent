import { escapeHtml, settingsField } from './settings-utils.js';

export const JobHunterClearanceEditor = (function () {
  const labels = window.__JOB_HUNTER_SETTINGS_CLEARANCES_LABELS__;
  if (!labels) {
    throw new Error('Missing settings clearances labels.');
  }

  let clearanceRuleState = [];

  function normalizeClearanceRule(rule) {
    const name = String(rule?.name || '').replace(/\s+/g, ' ').trim();
    const evidence = Array.isArray(rule?.evidence) ? rule.evidence : [];
    return {
      name,
      value: rule?.value !== false,
      evidence,
      needs_review: Boolean(rule?.needs_review),
    };
  }

  function clearanceRuleStateToText(rules) {
    return JSON.stringify(rules || []);
  }

  function applyClearanceUiLabels() {
    const title = document.getElementById('clearance_editor_title');
    const help = document.getElementById('clearance_editor_help');
    const addBtn = document.getElementById('add_clearance_rule');
    if (title) title.textContent = labels.settings_title;
    if (help) help.textContent = labels.help_text;
    if (addBtn) {
      addBtn.setAttribute('aria-label', labels.add_button_aria_label);
      addBtn.setAttribute('title', labels.add_button_aria_label);
    }
  }

  function persistClearanceRuleState() {
    settingsField('candidate_eligibility').value = clearanceRuleStateToText(clearanceRuleState);
  }

  function renderClearanceRuleEditor() {
    const container = document.getElementById('clearance_editor');
    if (!container) return;
    applyClearanceUiLabels();
    if (!clearanceRuleState.length) {
      container.innerHTML = `<div class="capability-editor-empty">${escapeHtml(labels.settings_empty_text)}</div>`;
      return;
    }
    const cardsHtml = clearanceRuleState.map((rule, index) => `
      <article class="capability-card" data-clearance-index="${index}">
        <div class="capability-card-main">
          <div class="capability-card-head">
            <input class="cap-name-input" type="text" data-clearance-field="name"
                   aria-label="${escapeHtml(labels.name_placeholder)}"
                   value="${escapeHtml(rule.name)}" placeholder="${escapeHtml(labels.name_placeholder)}">
          </div>
          <div class="cap-strength">
            <label class="toggle-switch">
              <span class="toggle-switch-copy">
                <span class="toggle-switch-title">${escapeHtml(labels.have_label)}</span>
              </span>
              <span class="toggle-switch-control">
                <input type="checkbox" role="switch" data-clearance-field="value"
                       aria-label="${escapeHtml(labels.have_label)}: ${escapeHtml(rule.name || labels.name_placeholder)}"${rule.value ? ' checked' : ''}>
                <span class="toggle-switch-ui"></span>
              </span>
            </label>
          </div>
        </div>
        <div class="capability-card-actions" role="group" aria-label="Clearance actions">
          <button class="cap-remove-btn capability-remove-btn" type="button" data-remove-clearance="${index}"
                  aria-label="${escapeHtml(labels.remove_button_aria_label)}" title="${escapeHtml(labels.remove_button_aria_label)}">
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" class="cap-remove-icon">
              <path d="M9 3.5h6l1 1.5H19v2H5v-2h3l1-1.5Zm-1 5h8l-.6 9.3A2 2 0 0 1 13.4 20H10.6a2 2 0 0 1-1.99-1.7L8 8.5Zm2 2v6m4-6v6" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"></path>
            </svg>
          </button>
        </div>
      </article>
    `).join('');
    container.innerHTML = `<div class="capability-grid">${cardsHtml}</div>`;
  }

  function setClearanceRuleState(rules) {
    clearanceRuleState = (rules || []).map(normalizeClearanceRule).filter(rule => rule.name);
    persistClearanceRuleState();
    renderClearanceRuleEditor();
  }

  function collectClearanceRuleState() {
    const cleaned = clearanceRuleState.map(normalizeClearanceRule).filter(rule => rule.name);
    clearanceRuleState = cleaned;
    persistClearanceRuleState();
    return cleaned;
  }

  function addClearanceRule() {
    clearanceRuleState = [...clearanceRuleState, { name: '', value: true, evidence: [], needs_review: false }];
    renderClearanceRuleEditor();
    requestAnimationFrame(() => {
      const container = document.getElementById('clearance_editor');
      const row = container?.querySelector('[data-clearance-index]:last-child');
      const input = row?.querySelector('input[data-clearance-field="name"]');
      if (row?.scrollIntoView) {
        row.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
      if (input?.focus) {
        input.focus();
      }
    });
  }

  function removeClearanceRule(index) {
    const rule = clearanceRuleState[index];
    if (!rule) return false;
    if (!window.confirm(`Remove ${rule.name || 'this clearance'}? This cannot be undone.`)) {
      return false;
    }
    clearanceRuleState.splice(index, 1);
    persistClearanceRuleState();
    renderClearanceRuleEditor();
    return true;
  }

  function initEventHandlers(markDirty) {
    document.getElementById('add_clearance_rule')?.addEventListener('click', () => {
      addClearanceRule();
      markDirty();
    });

    document.getElementById('clearance_editor')?.addEventListener('input', (event) => {
      const field = event.target.closest('[data-clearance-field="name"]');
      if (!field) return;
      const row = field.closest('[data-clearance-index]');
      if (!row) return;
      const index = Number(row.dataset.clearanceIndex);
      clearanceRuleState[index] = {
        ...clearanceRuleState[index],
        name: String(field.value || '').replace(/\s+/g, ' ').trim(),
      };
      persistClearanceRuleState();
      markDirty();
    });

    document.getElementById('clearance_editor')?.addEventListener('change', (event) => {
      const field = event.target.closest('[data-clearance-field="value"]');
      if (!field) return;
      const row = field.closest('[data-clearance-index]');
      if (!row) return;
      const index = Number(row.dataset.clearanceIndex);
      clearanceRuleState[index] = {
        ...clearanceRuleState[index],
        value: field.checked,
      };
      persistClearanceRuleState();
      markDirty();
    });

    document.getElementById('clearance_editor')?.addEventListener('click', (event) => {
      const removeBtn = event.target.closest('[data-remove-clearance]');
      if (!removeBtn) return;
      const index = Number(removeBtn.dataset.removeClearance);
      if (removeClearanceRule(index)) {
        markDirty();
      }
    });
  }

  return {
    setClearanceRuleState,
    collectClearanceRuleState,
    renderClearanceRuleEditor,
    addClearanceRule,
    initEventHandlers,
  };
}());
