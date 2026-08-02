import { escapeHtml, settingsField } from './settings-utils.js';

export const JobHunterEligibilityEditor = (function () {
  const labels = window.__JOB_HUNTER_SETTINGS_CLEARANCES_LABELS__;
  if (!labels) throw new Error('Missing settings clearances labels.');

  let factState = [];

  function normalizeText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function normalizeFact(fact) {
    const aliases = Array.isArray(fact?.aliases)
      ? fact.aliases.map(normalizeText).filter(Boolean)
      : [];
    return {
      name: normalizeText(fact?.name || ''),
      value: fact?.value !== false,
      aliases,
      subtype: normalizeText(fact?.subtype || ''),
      evidence: Array.isArray(fact?.evidence) ? fact.evidence : [],
      needs_review: Boolean(fact?.needs_review),
      aliases_auto_generated: Boolean(fact?.aliases_auto_generated),
      aliases_edited: Boolean(fact?.aliases_edited),
    };
  }

  function persist() {
    settingsField('candidate_eligibility_facts').value = JSON.stringify(
      factState.map(({ displayReview, aliases_edited, ...fact }) => fact)
    );
  }

  function render() {
    const title = document.getElementById('eligibility_editor_title');
    const help = document.getElementById('eligibility_editor_help');
    const addInput = document.getElementById('eligibility_name_add');
    const addButton = document.getElementById('eligibility_add');
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
      const review = fact.needs_review ? `<p class="clearance-card-state">${escapeHtml(labels.eligibility_aliases_review_label)}</p>` : '';
      return `
        <article class="capability-card clearance-card" data-eligibility-index="${index}">
          <div class="capability-card-main clearance-card-main">
            <div class="clearance-card-copy">
              <label class="clearance-card-title" for="eligibility_name_${index}">${escapeHtml(labels.eligibility_name_label)}</label>
              <input id="eligibility_name_${index}" class="token-input-field" data-eligibility-field="name" data-eligibility-index="${index}" value="${escapeHtml(fact.name)}">
              <label class="clearance-card-title" for="eligibility_aliases_${index}">${escapeHtml(labels.eligibility_aliases_label)}</label>
              <input id="eligibility_aliases_${index}" class="token-input-field" data-eligibility-field="aliases" data-eligibility-index="${index}" value="${escapeHtml(fact.aliases.join(', '))}" placeholder="${escapeHtml(labels.eligibility_aliases_placeholder)}">
              ${review}
            </div>
          </div>
          <div class="capability-card-actions clearance-card-actions">
            <label class="toggle-switch toggle-switch--compact" for="${toggleId}">
              <span class="toggle-switch-control">
                <input id="${toggleId}" type="checkbox" role="switch" data-eligibility-field="value" data-eligibility-index="${index}"${fact.value ? ' checked' : ''}>
                <span class="toggle-switch-ui"></span>
              </span>
            </label>
            <button class="btn btn-secondary btn-compact-action" type="button" data-eligibility-field="remove" data-eligibility-index="${index}">${escapeHtml(labels.eligibility_remove_button_label)}</button>
          </div>
        </article>`;
    }).join('');
    container.innerHTML = cards ? `<div class="capability-grid clearance-grid">${cards}</div>` : `<p class="panel-copy">${escapeHtml(labels.eligibility_empty_text)}</p>`;
  }

  function setEligibilityFactState(facts) {
    factState = (Array.isArray(facts) ? facts : []).map(normalizeFact).filter((fact) => fact.name);
    persist();
    render();
  }

  function collectEligibilityFactState() {
    factState = factState.map(normalizeFact).filter((fact) => fact.name);
    persist();
    return factState.map(({ displayReview, aliases_edited, ...fact }) => {
      const output = { ...fact };
      if (!output.aliases.length && !aliases_edited) delete output.aliases;
      return output;
    });
  }

  function initEventHandlers(markDirty) {
    document.getElementById('eligibility_add')?.addEventListener('click', () => {
      const input = document.getElementById('eligibility_name_add');
      const name = normalizeText(input?.value);
      if (!name) return;
      if (!factState.some((fact) => fact.name.toLowerCase() === name.toLowerCase())) {
        factState.push(normalizeFact({ name, value: true, aliases: [] }));
        persist();
        render();
        markDirty();
      }
      if (input) input.value = '';
    });
    document.getElementById('eligibility_editor')?.addEventListener('input', (event) => {
      const field = event.target.closest('[data-eligibility-field]');
      if (!field) return;
      const index = Number(field.dataset.eligibilityIndex);
      if (!Number.isInteger(index) || !factState[index]) return;
      if (field.dataset.eligibilityField === 'name') factState[index].name = normalizeText(field.value);
      if (field.dataset.eligibilityField === 'aliases') {
        factState[index].aliases = String(field.value || '').split(',').map(normalizeText).filter(Boolean);
        factState[index].aliases_edited = true;
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

  return { setEligibilityFactState, collectEligibilityFactState, initEventHandlers };
}());
