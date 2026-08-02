import { escapeHtml, settingsField } from './settings-utils.js';

export const JobHunterClearanceEditor = (function () {
  const labels = window.__JOB_HUNTER_SETTINGS_CLEARANCES_LABELS__;
  if (!labels) {
    throw new Error('Missing settings clearances labels.');
  }

  const clearanceOptions = window.__JOB_HUNTER_CLEARANCE_OPTIONS__;
  if (!Array.isArray(clearanceOptions) || !clearanceOptions.length) {
    throw new Error('Missing clearance options.');
  }

  let clearanceRuleState = [];

  function normalizeText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function normalizeLookup(value) {
    return normalizeText(value).toLowerCase();
  }

  function normalizeClearanceRule(rule) {
    const name = normalizeText(rule?.name || '');
    const evidence = Array.isArray(rule?.evidence) ? rule.evidence : [];
    return {
      name,
      value: rule?.value !== false,
      evidence,
      needs_review: Boolean(rule?.needs_review),
      displayLabel: normalizeText(rule?.displayLabel || name),
    };
  }

  const preparedOptions = clearanceOptions.map((option) => {
    const value = normalizeText(option?.value);
    const label = normalizeText(option?.label);
    const rank = Number(option?.rank);
    const aliases = Array.isArray(option?.aliases)
      ? option.aliases.map((alias) => normalizeText(alias)).filter(Boolean)
      : [];
    if (!value || !label || !Number.isFinite(rank) || rank <= 0) {
      throw new Error('Invalid clearance option.');
    }
    return {
      value,
      label,
      rank,
      matchKeys: new Set([value, label, ...aliases].map(normalizeLookup).filter(Boolean)),
    };
  });

  function clearanceRuleStateToText(rules) {
    return JSON.stringify(rules || []);
  }

  function applyClearanceUiLabels() {
    const title = document.getElementById('clearance_editor_title');
    const help = document.getElementById('clearance_editor_help');
    if (title) title.textContent = labels.settings_title;
    if (help) help.textContent = labels.help_text;
  }

  function persistClearanceRuleState() {
    settingsField('candidate_eligibility').value = clearanceRuleStateToText(
      clearanceRuleState
        .map(({ name, value, evidence, needs_review }) => ({ name, value, evidence, needs_review }))
    );
  }

  function findClearanceOption(name) {
    const key = normalizeLookup(name);
    if (!key) return null;
    return preparedOptions.find((option) => option.matchKeys.has(key)) || null;
  }

  function buildDefaultClearanceRows() {
    return preparedOptions.map((option) => ({
      name: option.value,
      value: false,
      evidence: [],
      needs_review: false,
      displayLabel: option.label,
    }));
  }

  function mergeClearanceRuleState(rules) {
    const fixedRows = buildDefaultClearanceRows();
    const fixedRowIndex = new Map(fixedRows.map((rule, index) => [normalizeLookup(rule.name), index]));

    for (const rawRule of rules || []) {
      const normalizedRule = normalizeClearanceRule(rawRule);
      if (!normalizedRule.name) continue;
      const option = findClearanceOption(normalizedRule.name);
      if (!option) continue;
      const index = fixedRowIndex.get(normalizeLookup(option.value));
      if (index === undefined) continue;
      fixedRows[index] = {
        ...fixedRows[index],
        name: option.value,
        value: normalizedRule.value,
        evidence: normalizedRule.evidence,
        needs_review: normalizedRule.needs_review,
        displayLabel: option.label,
      };
    }

    return fixedRows;
  }

  function isRowImpliedByHigherClearance(index) {
    // A row is implied (held automatically, not independently editable) whenever
    // some higher-ranked row is currently held — holding NV2 guarantees Baseline
    // and NV1, so those lower rows lock until NV2 is turned off again.
    const rank = preparedOptions[index]?.rank;
    if (!Number.isFinite(rank)) return false;
    return clearanceRuleState.some((other, otherIndex) => {
      const otherRank = preparedOptions[otherIndex]?.rank;
      return Number.isFinite(otherRank) && otherRank > rank && other.value;
    });
  }

  function stateLabel(rule, implied) {
    if (implied) return labels.implied_state_label;
    return rule.value ? labels.held_state_label : labels.not_held_state_label;
  }

  function renderClearanceRuleEditor() {
    const container = document.getElementById('clearance_editor');
    if (!container) return;
    applyClearanceUiLabels();
    const cardsHtml = clearanceRuleState.map((rule, index) => {
      const toggleId = `clearance_toggle_${index}`;
      const stateId = `${toggleId}_state`;
      const implied = isRowImpliedByHigherClearance(index);
      return `
        <article class="capability-card clearance-card" data-clearance-index="${index}">
          <div class="capability-card-main clearance-card-main">
            <div class="clearance-card-copy">
              <h4 class="clearance-card-title">${escapeHtml(rule.displayLabel || rule.name)}</h4>
              <p class="clearance-card-state" id="${stateId}">${escapeHtml(stateLabel(rule, implied))}</p>
            </div>
          </div>
          <div class="capability-card-actions clearance-card-actions">
            <label class="toggle-switch toggle-switch--compact" for="${toggleId}">
              <span class="toggle-switch-control">
                <input id="${toggleId}" type="checkbox" role="switch" data-clearance-field="value"
                       data-clearance-index="${index}" aria-describedby="${stateId}"${rule.value ? ' checked' : ''}${implied ? ' disabled' : ''}>
                <span class="toggle-switch-ui"></span>
              </span>
            </label>
          </div>
        </article>
      `;
    }).join('');
    container.innerHTML = `<div class="capability-grid clearance-grid">${cardsHtml}</div>`;
  }

  function setClearanceRuleState(rules) {
    clearanceRuleState = mergeClearanceRuleState(rules);
    persistClearanceRuleState();
    renderClearanceRuleEditor();
  }

  function collectClearanceRuleState() {
    const cleaned = clearanceRuleState.map(normalizeClearanceRule).filter((rule) => rule.name);
    clearanceRuleState = mergeClearanceRuleState(cleaned);
    persistClearanceRuleState();
    return cleaned.map(({ name, value, evidence, needs_review }) => ({ name, value, evidence, needs_review }));
  }

  function applyClearanceHierarchyCascade(changedIndex) {
    // preparedOptions and clearanceRuleState are always built and kept in the same
    // order (see buildDefaultClearanceRows/mergeClearanceRuleState), so index i in
    // one lines up with index i in the other.
    const changedRank = preparedOptions[changedIndex]?.rank;
    if (!Number.isFinite(changedRank)) return;
    const heldNow = clearanceRuleState[changedIndex].value;
    clearanceRuleState.forEach((rule, index) => {
      const rank = preparedOptions[index]?.rank;
      if (!Number.isFinite(rank)) return;
      if (heldNow && rank <= changedRank) {
        rule.value = true;
      } else if (!heldNow && rank >= changedRank) {
        rule.value = false;
      }
    });
  }

  function initEventHandlers(markDirty) {
    document.getElementById('clearance_editor')?.addEventListener('change', (event) => {
      const field = event.target.closest('[data-clearance-field="value"]');
      if (!field || field.disabled) return;
      const index = Number(field.dataset.clearanceIndex);
      if (!Number.isInteger(index) || !clearanceRuleState[index]) return;
      if (isRowImpliedByHigherClearance(index)) return;
      clearanceRuleState[index] = {
        ...clearanceRuleState[index],
        value: field.checked,
      };
      applyClearanceHierarchyCascade(index);
      persistClearanceRuleState();
      renderClearanceRuleEditor();
      markDirty();
    });
  }

  return {
    setClearanceRuleState,
    collectClearanceRuleState,
    renderClearanceRuleEditor,
    initEventHandlers,
  };
}());
