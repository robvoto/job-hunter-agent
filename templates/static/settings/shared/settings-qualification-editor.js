import { escapeHtml, settingsField } from './settings-utils.js';

export const JobHunterQualificationEditor = (function () {
  const labels = window.__JOB_HUNTER_SETTINGS_CLEARANCES_LABELS__;
  if (!labels) throw new Error('Missing settings clearances labels.');

  let state = [];

  function normalizeText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function normalizeItem(item) {
    return {
      name: normalizeText(item?.name || ''),
      value: item?.value !== false,
      aliases: Array.isArray(item?.aliases) ? item.aliases : [],
      evidence: Array.isArray(item?.evidence) ? item.evidence : [],
    };
  }

  async function saveQualification(payload) {
    const response = await window.jobHunterFetch('/api/profile/qualification', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body?.error) {
      const error = new Error(body?.error || 'Could not save qualification.');
      error.serverMessage = body?.error || '';
      throw error;
    }
    return body;
  }

  function persist() {
    settingsField('candidate_qualifications').value = JSON.stringify(state);
  }

  function render() {
    const title = document.getElementById('qualification_editor_title');
    const help = document.getElementById('qualification_editor_help');
    const input = document.getElementById('qualification_name_add');
    const add = document.getElementById('qualification_add');
    if (title) title.textContent = labels.qualification_settings_title;
    if (help) help.textContent = labels.qualification_help_text;
    if (input) input.placeholder = labels.qualification_name_placeholder;
    if (add) add.textContent = labels.qualification_add_button_label;
    const container = document.getElementById('qualification_editor');
    if (!container) return;
    const cards = state.map((item, index) => {
      const toggleId = `qualification_toggle_${index}`;
      return `<article class="capability-card eligibility-card" data-qualification-index="${index}">
        <div class="capability-card-main eligibility-card-main">
          <div class="eligibility-card-copy">
            <label class="eligibility-card-title" for="qualification_name_${index}">${escapeHtml(labels.qualification_name_label)}</label>
            <input id="qualification_name_${index}" class="token-input-field" data-qualification-field="name" data-qualification-index="${index}" value="${escapeHtml(item.name)}">
          </div>
        </div>
        <div class="capability-card-actions eligibility-card-actions">
          <label class="toggle-switch toggle-switch--compact" for="${toggleId}">
            <span class="toggle-switch-control"><input id="${toggleId}" type="checkbox" role="switch" data-qualification-field="value" data-qualification-index="${index}"${item.value ? ' checked' : ''}><span class="toggle-switch-ui"></span></span>
          </label>
          <button class="jh-button jh-button--danger jh-button--compact" type="button" data-qualification-field="remove" data-qualification-index="${index}">${escapeHtml(labels.qualification_remove_button_label)}</button>
        </div>
      </article>`;
    }).join('');
    container.innerHTML = cards ? `<div class="capability-grid eligibility-grid">${cards}</div>` : `<p class="panel-copy">${escapeHtml(labels.qualification_empty_text)}</p>`;
  }

  function setQualificationState(items) {
    state = (Array.isArray(items) ? items : []).map(normalizeItem).filter((item) => item.name);
    persist();
    render();
  }

  function collectQualificationState() {
    state = state.map(normalizeItem).filter((item) => item.name);
    persist();
    return state;
  }

  function upsertFromServer(item) {
    const normalized = normalizeItem(item);
    const index = state.findIndex((row) => row.name.toLowerCase() === normalized.name.toLowerCase());
    if (index === -1) state.push(normalized);
    else state[index] = normalized;
    persist();
    render();
  }

  function initEventHandlers(markDirty) {
    document.getElementById('qualification_add')?.addEventListener('click', async () => {
      const input = document.getElementById('qualification_name_add');
      const name = normalizeText(input?.value);
      if (!name || state.some((item) => item.name.toLowerCase() === name.toLowerCase())) return;
      try {
        const body = await saveQualification({ name, value: true });
        upsertFromServer(body.qualification);
        if (input) input.value = '';
        markDirty();
      } catch (error) {
        window.alert(error.serverMessage || labels.qualification_add_error_message);
      }
    });
    document.getElementById('qualification_editor')?.addEventListener('input', (event) => {
      const field = event.target.closest('[data-qualification-field="name"]');
      if (!field) return;
      const index = Number(field.dataset.qualificationIndex);
      if (state[index]) state[index].name = normalizeText(field.value);
      persist();
      markDirty();
    });
    document.getElementById('qualification_editor')?.addEventListener('change', (event) => {
      const field = event.target.closest('[data-qualification-field="value"]');
      if (!field) return;
      const index = Number(field.dataset.qualificationIndex);
      if (state[index]) state[index].value = field.checked;
      persist();
      render();
      markDirty();
    });
    document.getElementById('qualification_editor')?.addEventListener('click', (event) => {
      const field = event.target.closest('[data-qualification-field="remove"]');
      if (!field) return;
      state.splice(Number(field.dataset.qualificationIndex), 1);
      persist();
      render();
      markDirty();
    });
  }

  return { setQualificationState, collectQualificationState, initEventHandlers, saveQualification, upsertFromServer };
}());
