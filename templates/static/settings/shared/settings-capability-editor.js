import { escapeHtml, settingsField } from './settings-utils.js';
import * as capabilityUi from '../../common/capability-ui.js';

export const JobHunterCapabilityEditor = (function () {
  const capabilityLabels = capabilityUi.labels || {};
  const capabilityLevelMeta = capabilityUi.capabilityLevelMeta || {};
  const genericCapabilityIconKey = capabilityUi.genericCapabilityIconKey;
  const capabilityLevels = Array.isArray(capabilityUi.capabilityLevels) && capabilityUi.capabilityLevels.length
    ? capabilityUi.capabilityLevels
    : Object.keys(capabilityLevelMeta);
  if (!capabilityLabels.settings_title || !capabilityLabels.help_text) {
    throw new Error('Missing capability UI labels.');
  }
  if (!genericCapabilityIconKey) {
    throw new Error('Missing generic capability icon key.');
  }

  let capabilityRuleState = [];
  let expandedCapabilityRows = new Set();
  let selectedCapabilityRows = new Set();
  let visibleCapabilityRowIndices = [];
  let capabilityBulkEditMode = false;

  function formatLabel(template, values = {}) {
    return String(template || '').replace(/\{(\w+)\}/g, (_, key) => {
      if (Object.prototype.hasOwnProperty.call(values, key)) {
        return String(values[key]);
      }
      return '';
    });
  }

  function capabilityRulesToText(rules) {
    return (rules || []).filter(rule => (rule.name || '').trim() && (rule.level || '').trim()).map(rule => {
      const aliases = (rule.aliases || []).join(', ');
      return `${rule.name || ''} || ${rule.level || ''} || ${rule.fit || 'supporting'} || ${aliases}`;
    }).join('\n');
  }

  function normalizeCapabilityAliasValue(value) {
    return String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  }

  function normalizeCapabilityRule(rule) {
    const name = String(rule?.name || '').replace(/\s+/g, ' ').trim();
    const rawLevel = String(rule?.level || 'basic').trim().toLowerCase();
    const validLevels = new Set(capabilityLevels);
    const level = validLevels.has(rawLevel) ? rawLevel : 'basic';

    const rawFit = String(rule?.fit || 'supporting').trim().toLowerCase();
    const validFits = new Set(['core', 'supporting']);
    const fit = validFits.has(rawFit) ? rawFit : 'supporting';

    const aliases = [];
    const seen = new Set();
    for (const value of Array.isArray(rule?.aliases) ? rule.aliases : []) {
      const cleaned = normalizeCapabilityAliasValue(value);
      if (!cleaned || cleaned === name.toLowerCase() || seen.has(cleaned)) continue;
      seen.add(cleaned);
      aliases.push(cleaned);
    }
    return {
      name,
      level,
      fit,
      aliases,
      icon_key: String(rule?.icon_key || '').trim().toLowerCase(),
      aliases_open: Boolean(rule?.aliases_open),
      needs_review: Boolean(rule?.needs_review) || aliases.length > 0,
    };
  }

  function applyCapabilityUiLabels() {
    const sectionTitle = document.getElementById('capability_matrix_section_title');
    const panelTitle = document.getElementById('capability_matrix_title');
    const panelCopy = document.getElementById('capability_matrix_help');
    const filterInput = document.getElementById('capability_matrix_filter');
    if (sectionTitle) sectionTitle.textContent = capabilityLabels.settings_title;
    if (panelTitle) panelTitle.textContent = capabilityLabels.settings_title;
    if (panelCopy) panelCopy.textContent = capabilityLabels.help_text;
    if (filterInput) {
      filterInput.placeholder = capabilityLabels.filter_placeholder;
      filterInput.setAttribute('aria-label', capabilityLabels.filter_placeholder);
    }
  }

  function pruneCapabilitySelection() {
    selectedCapabilityRows = new Set(
      [...selectedCapabilityRows].filter(index => index >= 0 && index < capabilityRuleState.length)
    );
  }

  function shiftCapabilityRowsAfterRemoval(index) {
    selectedCapabilityRows = new Set(
      [...selectedCapabilityRows]
        .filter(value => value !== index)
        .map(value => value > index ? value - 1 : value)
    );
    expandedCapabilityRows = new Set(
      [...expandedCapabilityRows]
        .filter(value => value !== index)
        .map(value => value > index ? value - 1 : value)
    );
  }

  function setCapabilitySelected(index, selected) {
    if (selected) {
      selectedCapabilityRows.add(index);
    } else {
      selectedCapabilityRows.delete(index);
    }
  }

  function toggleCapabilitySelection(index) {
    setCapabilitySelected(index, !selectedCapabilityRows.has(index));
    renderCapabilityRuleEditor();
  }

  function selectVisibleCapabilityRows() {
    visibleCapabilityRowIndices.forEach(index => selectedCapabilityRows.add(index));
    renderCapabilityRuleEditor();
  }

  function clearCapabilitySelection() {
    selectedCapabilityRows.clear();
    renderCapabilityRuleEditor();
  }

  function selectedCapabilityRowsSortedDescending() {
    return [...selectedCapabilityRows].sort((left, right) => right - left);
  }

  function renderCapabilityToolbar(selectedCount) {
    const copy = document.getElementById('capability_matrix_copy');
    if (copy) {
      copy.textContent = capabilityBulkEditMode
        ? formatLabel(capabilityLabels.settings_selected_copy, { count: selectedCount })
        : '';
    }
    const actions = document.getElementById('capability_matrix_actions');
    if (!actions) return;
    const bulkActions = capabilityBulkEditMode ? `
      <button class="btn btn-secondary btn-compact-action" type="button" data-select-visible-capabilities="true"${visibleCapabilityRowIndices.length ? '' : ' disabled'}>${escapeHtml(capabilityLabels.settings_select_shown_label)}</button>
      <button class="btn btn-secondary btn-compact-action" type="button" data-clear-capability-selection="true"${selectedCount ? '' : ' disabled'}>${escapeHtml(capabilityLabels.settings_clear_selection_label)}</button>
      <button class="btn btn-secondary btn-compact-action" type="button" data-remove-selected-capabilities="true"${selectedCount ? '' : ' disabled'}>${escapeHtml(capabilityLabels.settings_remove_selected_label)}</button>
      <button class="btn btn-secondary btn-compact-action" type="button" data-exit-capability-bulk-edit="true">${escapeHtml(capabilityLabels.settings_done_editing_label)}</button>
    ` : `
      <button class="btn btn-secondary btn-compact-action" type="button" data-enter-capability-bulk-edit="true">${escapeHtml(capabilityLabels.settings_edit_multiple_label)}</button>
    `;
    actions.innerHTML = `
      <button class="btn-add" id="add_capability_rule" type="button" aria-label="${escapeHtml(capabilityLabels.add_button_aria_label)}" title="${escapeHtml(capabilityLabels.add_button_aria_label)}">+</button>
      ${bulkActions}
    `;
  }

  function confirmCapabilityRemoval(count, name) {
    const baseMessage = count === 1
      ? `Remove ${name || 'this capability'}?`
      : `Remove ${name || `${count} selected capabilities`}?`;
    return window.confirm(`${baseMessage} This cannot be undone.`);
  }

  function removeCapabilityRule(index) {
    const rule = capabilityRuleState[index];
    if (!rule) return false;
    if (!confirmCapabilityRemoval(1, rule.name)) {
      return false;
    }
    capabilityRuleState.splice(index, 1);
    shiftCapabilityRowsAfterRemoval(index);
    settingsField('candidate_capabilities').value = capabilityRulesToText(capabilityRuleState);
    renderCapabilityRuleEditor();
    return true;
  }

  function removeSelectedCapabilityRules() {
    const selectedIndexes = selectedCapabilityRowsSortedDescending();
    if (!selectedIndexes.length) return;
    const selectedNames = selectedIndexes
      .map(index => capabilityRuleState[index]?.name)
      .filter(Boolean);
    const confirmationLabel = selectedNames.length
      ? selectedNames.slice(0, 3).join(', ')
      : `${selectedIndexes.length} selected capabilities`;
    if (!confirmCapabilityRemoval(selectedIndexes.length, confirmationLabel)) {
      return;
    }
    for (const index of selectedIndexes) {
      const rule = capabilityRuleState[index];
      if (!rule) continue;
      capabilityRuleState.splice(index, 1);
      shiftCapabilityRowsAfterRemoval(index);
    }
    selectedCapabilityRows.clear();
    settingsField('candidate_capabilities').value = capabilityRulesToText(capabilityRuleState);
    renderCapabilityRuleEditor();
  }

  function removeCapabilityAlias(index, aliasValue) {
    const rule = capabilityRuleState[index];
    if (!rule) return;
    const cleanedAlias = normalizeCapabilityAliasValue(aliasValue);
    const aliases = (rule.aliases || []).filter(alias => alias !== cleanedAlias);
    capabilityRuleState[index] = normalizeCapabilityRule({
      ...rule,
      aliases,
      aliases_open: aliases.length > 0 && rule.aliases_open,
    });
    if (!aliases.length) {
      expandedCapabilityRows.delete(index);
    }
    settingsField('candidate_capabilities').value = capabilityRulesToText(capabilityRuleState);
    renderCapabilityRuleEditor();
  }

  function renderCapabilityRuleEditor() {
    const container = document.getElementById('capability_matrix_editor');
    if (!container) return;
    applyCapabilityUiLabels();
    const filterTerm = String(document.getElementById('capability_matrix_filter')?.value || '').trim().toLowerCase();
    const rows = capabilityRuleState
      .map((rule, index) => ({ rule, index }))
      .filter(item => {
        if (!filterTerm) return true;
        return item.rule.name.toLowerCase().includes(filterTerm)
          || item.rule.aliases.some(alias => alias.includes(filterTerm));
      });
    visibleCapabilityRowIndices = rows.map(({ index }) => index);
    pruneCapabilitySelection();
    const selectedCount = selectedCapabilityRows.size;
    renderCapabilityToolbar(selectedCount);
    if (!capabilityRuleState.length) {
      container.innerHTML = `<div class="capability-editor-empty">${escapeHtml(capabilityLabels.settings_empty_text)}</div>`;
      return;
    }
    const cardsHtml = rows.length
      ? rows.map(({ rule, index }) => {
          const titleCaseName = rule.name.toLowerCase().split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
          const aliases = Array.isArray(rule.aliases) ? rule.aliases : [];
          const aliasCount = aliases.length;
          const previewAliases = aliases.slice(0, 2);
          const aliasPreviewHtml = previewAliases.length ? `
            <div class="capability-alias-preview" aria-label="${escapeHtml(capabilityLabels.related_skills_label)}">
              ${previewAliases.map(alias => `
                <span class="cap-alias-chip cap-alias-chip--preview" title="${escapeHtml(alias)}">
                  <span class="cap-alias-chip-label">${escapeHtml(alias)}</span>
                </span>
              `).join('')}
            </div>
          ` : '';
          const aliasChips = aliases.map(alias => `
            <span class="cap-alias-chip" title="${escapeHtml(alias)}">
              <span class="cap-alias-chip-label">${escapeHtml(alias)}</span>
              <button class="cap-alias-chip-remove" type="button" data-remove-capability-alias="${index}" data-capability-alias="${escapeHtml(alias)}" aria-label="${escapeHtml(capabilityLabels.remove_related_skill_aria_label)}" title="${escapeHtml(capabilityLabels.remove_related_skill_aria_label)}">&times;</button>
            </span>
          `).join('');
          const aliasRowHtml = aliasCount ? `
            <div class="capability-alias-row">
              ${aliasPreviewHtml}
              <details class="capability-alias-drawer"${expandedCapabilityRows.has(index) ? ' open' : ''}>
                <summary class="cap-alias-summary">
                  <span class="capability-summary-label">${escapeHtml(formatLabel(capabilityLabels.related_skills_summary, { count: aliasCount }))}</span>
                </summary>
                <div class="cap-alias-chips" aria-label="${escapeHtml(capabilityLabels.related_skills_label)}">${aliasChips}</div>
              </details>
            </div>
          ` : '';
          const meterLevels = ['basic', 'working', 'strong']
            .filter(level => capabilityLevels.includes(level));
          const selectedStrengthIndex = Math.max(0, meterLevels.indexOf(rule.level));
          const selectedStrengthMeta = capabilityLevelMeta[rule.level] || {
            label: rule.level,
            summary: '',
            tone: '',
          };
          const strengthChoices = meterLevels.map((level, levelIndex) => {
            const meta = capabilityLevelMeta[level] || { label: level };
            const inputId = `capability_level_${index}_${level}`;
            const checked = rule.level === level ? ' checked' : '';
            const filledClass = levelIndex <= selectedStrengthIndex ? ' is-filled' : '';
            return `
              <label class="capability-strength-dot${filledClass}" for="${inputId}" title="${escapeHtml(meta.label)}">
                <input id="${inputId}" type="radio" name="capability_level_${index}" value="${escapeHtml(level)}" data-capability-field="level"${checked} aria-label="${escapeHtml(meta.label)}">
                <span aria-hidden="true"></span>
              </label>
            `;
          }).join('');
          const selected = selectedCapabilityRows.has(index);
          return `
            <article class="capability-card${selected ? ' is-selected' : ''}" data-capability-index="${index}">
              <div class="capability-card-main">
                <div class="capability-card-head">
                  <input class="cap-name-input capability-card-name" type="text" data-capability-field="name" aria-label="Capability name"
                         value="${escapeHtml(titleCaseName)}"
                         placeholder="e.g. Agile Delivery">
                </div>
                ${aliasRowHtml}
                <div class="cap-strength">
                  <div class="capability-strength-meter ${escapeHtml(selectedStrengthMeta.tone || '')}"
                       role="radiogroup"
                       aria-label="Capability strength"
                       aria-describedby="capability_strength_help_${index}">
                    <span class="capability-strength-dots">${strengthChoices}</span>
                    <span class="capability-strength-label">${escapeHtml(selectedStrengthMeta.label)}</span>
                    <span class="capability-strength-tooltip" id="capability_strength_help_${index}" role="tooltip">
                      <strong>${escapeHtml(selectedStrengthMeta.label)}</strong>
                      <span>${escapeHtml(selectedStrengthMeta.summary)}</span>
                    </span>
                  </div>
                </div>
              </div>
              <div class="capability-card-actions" role="group" aria-label="Capability actions">
                <button class="cap-remove-btn capability-remove-btn" type="button" data-remove-capability="${index}"
                        aria-label="Remove ${escapeHtml(rule.name || 'capability')}"
                        title="Remove capability">
                  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" class="cap-remove-icon">
                    <path d="M9 3.5h6l1 1.5H19v2H5v-2h3l1-1.5Zm-1 5h8l-.6 9.3A2 2 0 0 1 13.4 20H10.6a2 2 0 0 1-1.99-1.7L8 8.5Zm2 2v6m4-6v6" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"></path>
                  </svg>
                </button>
              </div>
            </article>
          `;
        }).join('')
      : `<div class="capability-editor-empty-group">${escapeHtml(capabilityLabels.settings_no_match_text)}</div>`;

    container.innerHTML = `
      <div class="capability-grid">
        ${cardsHtml}
      </div>
    `;
  }

  function setCapabilityRuleState(rules) {
    capabilityRuleState = (rules || [])
      .map(normalizeCapabilityRule)
      .filter(rule => rule.name);
    expandedCapabilityRows = new Set(
      [...expandedCapabilityRows].filter(index => index >= 0 && index < capabilityRuleState.length)
    );
    pruneCapabilitySelection();
    settingsField('candidate_capabilities').value = capabilityRulesToText(capabilityRuleState);
    renderCapabilityRuleEditor();
  }

  function collectCapabilityRuleState() {
    const cleaned = capabilityRuleState
      .map(normalizeCapabilityRule)
      .filter(rule => rule.name);
    capabilityRuleState = cleaned;
    pruneCapabilitySelection();
    settingsField('candidate_capabilities').value = capabilityRulesToText(cleaned);
    return cleaned;
  }

  function addCapabilityRule() {
    capabilityRuleState = [...capabilityRuleState, {
      name: '',
      level: 'working',
      aliases: [],
      icon_key: genericCapabilityIconKey,
    }];
    expandedCapabilityRows.add(capabilityRuleState.length - 1);
    renderCapabilityRuleEditor();
    requestAnimationFrame(() => {
      const container = document.getElementById('capability_matrix_editor');
      const card = container?.querySelector('[data-capability-index]:last-child');
      const input = card?.querySelector('input[data-capability-field="name"]');
      if (card?.scrollIntoView) {
        card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
      if (input?.focus) {
        input.focus();
      }
    });
  }

  function initEventHandlers(markDirty) {
    // Capture-phase toggle listener so non-bubbling toggle events are caught
    document.addEventListener('toggle', function (e) {
      if (e.target.classList?.contains('capability-alias-drawer')) {
        const card = e.target.closest('[data-capability-index]');
        if (card) {
          const index = Number(card.dataset.capabilityIndex);
          if (e.target.open) {
            expandedCapabilityRows.add(index);
          } else {
            expandedCapabilityRows.delete(index);
          }
        }
      }
      if (e.target.classList?.contains('capability-alias-drawer') && e.target.open) {
        document.querySelectorAll('#capability_matrix_editor details.capability-alias-drawer').forEach(details => {
          if (details !== e.target && details.open) details.open = false;
        });
      }
    }, true);

    document.getElementById('capability_matrix_actions')?.addEventListener('click', (event) => {
      const addCapability = event.target.closest('#add_capability_rule');
      if (addCapability) {
        addCapabilityRule();
        markDirty();
        return;
      }

      const enterBulkEdit = event.target.closest('[data-enter-capability-bulk-edit]');
      if (enterBulkEdit) {
        capabilityBulkEditMode = true;
        renderCapabilityRuleEditor();
        return;
      }

      const exitBulkEdit = event.target.closest('[data-exit-capability-bulk-edit]');
      if (exitBulkEdit) {
        capabilityBulkEditMode = false;
        selectedCapabilityRows.clear();
        renderCapabilityRuleEditor();
        return;
      }

      const selectVisible = event.target.closest('[data-select-visible-capabilities]');
      if (selectVisible) {
        selectVisibleCapabilityRows();
        return;
      }

      const clearSelection = event.target.closest('[data-clear-capability-selection]');
      if (clearSelection) {
        clearCapabilitySelection();
        return;
      }

      const removeSelected = event.target.closest('[data-remove-selected-capabilities]');
      if (removeSelected) {
        removeSelectedCapabilityRules();
        markDirty();
      }
    });

    document.getElementById('capability_matrix_filter')?.addEventListener('input', () => {
      renderCapabilityRuleEditor();
    });

    document.getElementById('capability_matrix_editor')?.addEventListener('input', (event) => {
      const field = event.target.closest('[data-capability-field]');
      if (!field) return;
      const card = field.closest('[data-capability-index]');
      if (!card) return;
      const index = Number(card.dataset.capabilityIndex);
      const key = field.dataset.capabilityField;
      capabilityRuleState[index] = {
        ...capabilityRuleState[index],
        [key]: key === 'name' ? String(field.value || '').replace(/\s+/g, ' ').trim() : String(field.value || '').trim().toLowerCase(),
      };
      settingsField('candidate_capabilities').value = capabilityRulesToText(capabilityRuleState);
      markDirty();
    });

    document.getElementById('capability_matrix_editor')?.addEventListener('click', (event) => {
      if (!capabilityBulkEditMode) return;
      // Skip if clicking delete button or inside a form control
      if (event.target.closest('.cap-remove-btn, input, label, details')) return;
      const card = event.target.closest('[data-capability-index]');
      if (!card) return;
      const index = Number(card.dataset.capabilityIndex);
      toggleCapabilitySelection(index);
    });

    document.getElementById('capability_matrix_editor')?.addEventListener('click', (event) => {
      const toggleSelection = event.target.closest('[data-toggle-capability-selection]');
      if (toggleSelection) {
        toggleCapabilitySelection(Number(toggleSelection.dataset.toggleCapabilitySelection));
        return;
      }

      const removeAlias = event.target.closest('[data-remove-capability-alias]');
      if (!removeAlias) return;
      const card = removeAlias.closest('[data-capability-index]');
      if (!card) return;
      removeCapabilityAlias(Number(card.dataset.capabilityIndex), removeAlias.dataset.capabilityAlias);
      markDirty();
    });

    document.getElementById('capability_matrix_editor')?.addEventListener('change', (event) => {
      const field = event.target.closest('[data-capability-field]');
      if (!field) return;
      const card = field.closest('[data-capability-index]');
      if (!card) return;
      const index = Number(card.dataset.capabilityIndex);
      const key = field.dataset.capabilityField;
      capabilityRuleState[index] = {
        ...capabilityRuleState[index],
        [key]: key === 'name' ? String(field.value || '').replace(/\s+/g, ' ').trim() : String(field.value || '').trim().toLowerCase(),
      };
      renderCapabilityRuleEditor();
      markDirty();
    });

    document.getElementById('capability_matrix_editor')?.addEventListener('click', (event) => {
      const removeCard = event.target.closest('[data-remove-capability]');
      if (!removeCard) return;
      const index = Number(removeCard.dataset.removeCapability);
      if (removeCapabilityRule(index)) {
        markDirty();
      }
    });
  }

  return {
    setCapabilityRuleState,
    collectCapabilityRuleState,
    renderCapabilityRuleEditor,
    addCapabilityRule,
    initEventHandlers,
  };
}());
