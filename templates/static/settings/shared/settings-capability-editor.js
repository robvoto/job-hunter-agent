import { escapeHtml, settingsField } from './settings-utils.js';
import * as capabilityUi from '../../common/capability-ui.js';

export const JobHunterCapabilityEditor = (function () {
  const capabilityLabels = capabilityUi.labels || {};
  const capabilityLevelMeta = capabilityUi.capabilityLevelMeta || {};
  const capabilityLevels = Array.isArray(capabilityUi.capabilityLevels) && capabilityUi.capabilityLevels.length
    ? capabilityUi.capabilityLevels
    : Object.keys(capabilityLevelMeta);
  if (!capabilityLabels.settings_title || !capabilityLabels.help_text) {
    throw new Error('Missing capability UI labels.');
  }

  let capabilityRuleState = [];
  let expandedCapabilityRows = new Set();

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
    settingsField('capability_profile_rules').value = capabilityRulesToText(capabilityRuleState);
    renderCapabilityRuleEditor();
  }

  function renderCapabilityRuleEditor() {
    const container = document.getElementById('capability_matrix_editor');
    if (!container) return;
    applyCapabilityUiLabels();
    if (!capabilityRuleState.length) {
      container.innerHTML = `<div class="capability-editor-empty">${escapeHtml(capabilityLabels.settings_empty_text)}</div>`;
      return;
    }
    const filterTerm = String(document.getElementById('capability_matrix_filter')?.value || '').trim().toLowerCase();
    const rows = capabilityRuleState
      .map((rule, index) => ({ rule, index }))
      .filter(item => {
        if (!filterTerm) return true;
        return item.rule.name.toLowerCase().includes(filterTerm)
          || item.rule.aliases.some(alias => alias.includes(filterTerm));
      });
    const cardsHtml = rows.length
      ? rows.map(({ rule, index }) => {
          const titleCaseName = rule.name.toLowerCase().split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
          const aliases = Array.isArray(rule.aliases) ? rule.aliases : [];
          const aliasCount = aliases.length;
          const aliasChips = aliases.map(alias => `
            <span class="cap-alias-chip" title="${escapeHtml(alias)}">
              <span class="cap-alias-chip-label">${escapeHtml(alias)}</span>
              <button class="cap-alias-chip-remove" type="button" data-remove-capability-alias="${index}" data-capability-alias="${escapeHtml(alias)}" aria-label="${escapeHtml(capabilityLabels.remove_related_skill_aria_label)}" title="${escapeHtml(capabilityLabels.remove_related_skill_aria_label)}">&times;</button>
            </span>
          `).join('');
          const strengthChoices = capabilityLevels.map((level) => {
            const meta = capabilityLevelMeta[level] || { label: level };
            const inputId = `capability_level_${index}_${level}`;
            const checked = rule.level === level ? ' checked' : '';
            return `
              <label class="choice-card choice-card--strength" for="${inputId}">
                <input id="${inputId}" type="radio" name="capability_level_${index}" value="${escapeHtml(level)}" data-capability-field="level"${checked} aria-label="${escapeHtml(meta.label)}">
                <span>${escapeHtml(meta.label)}</span>
              </label>
            `;
          }).join('');
          return `
            <article class="capability-card" data-capability-index="${index}">
              <div class="capability-card-head">
                <input class="cap-name-input capability-card-name" type="text" data-capability-field="name" aria-label="Capability name"
                       value="${escapeHtml(titleCaseName)}"
                       placeholder="e.g. Agile Delivery">
                <button class="cap-remove-btn capability-remove-btn" type="button" data-remove-capability="${index}"
                        aria-label="Remove ${escapeHtml(rule.name || 'capability')}"
                        title="Remove capability">
                  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" class="cap-remove-icon">
                    <path d="M9 3.5h6l1 1.5H19v2H5v-2h3l1-1.5Zm-1 5h8l-.6 9.3A2 2 0 0 1 13.4 20H10.6a2 2 0 0 1-1.99-1.7L8 8.5Zm2 2v6m4-6v6" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"></path>
                  </svg>
                </button>
              </div>
                <div class="cap-strength">
                  <span>Strength</span>
                  <div class="choice-strip capability-strength-strip" role="radiogroup" aria-label="Capability strength">
                    ${strengthChoices}
                  </div>
                </div>
                <div class="capability-card-meta">
                  ${aliasCount ? `
                    <details class="capability-alias-drawer"${expandedCapabilityRows.has(index) ? ' open' : ''}>
                      <summary class="cap-alias-summary">
                        <span class="capability-summary-label">${escapeHtml(capabilityLabels.related_skills_summary.replace('{count}', String(aliasCount)))}</span>
                      </summary>
                      <div class="cap-alias-chips" aria-label="${escapeHtml(capabilityLabels.related_skills_label)}">${aliasChips}</div>
                    </details>
                  ` : ''}
                </div>
              </article>
            `;
        }).join('')
      : `<div class="capability-editor-empty-group">${escapeHtml(capabilityLabels.settings_no_match_text)}</div>`;

    container.innerHTML = `
      <section class="capability-group">
        <div class="capability-group-head">
          <span class="cap-count">${escapeHtml(String(rows.length))} shown</span>
        </div>
        <div class="capability-grid">
          ${cardsHtml}
        </div>
      </section>
    `;
  }

  function setCapabilityRuleState(rules) {
    capabilityRuleState = (rules || [])
      .map(normalizeCapabilityRule)
      .filter(rule => rule.name);
    expandedCapabilityRows = new Set(
      [...expandedCapabilityRows].filter(index => index >= 0 && index < capabilityRuleState.length)
    );
    settingsField('capability_profile_rules').value = capabilityRulesToText(capabilityRuleState);
    renderCapabilityRuleEditor();
  }

  function collectCapabilityRuleState() {
    const cleaned = capabilityRuleState
      .map(normalizeCapabilityRule)
      .filter(rule => rule.name);
    capabilityRuleState = cleaned;
    settingsField('capability_profile_rules').value = capabilityRulesToText(cleaned);
    return cleaned;
  }

  function addCapabilityRule() {
    capabilityRuleState = [...capabilityRuleState, { name: '', level: 'working', aliases: [] }];
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

    document.getElementById('add_capability_rule')?.addEventListener('click', () => {
      addCapabilityRule();
      markDirty();
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
      settingsField('capability_profile_rules').value = capabilityRulesToText(capabilityRuleState);
      markDirty();
    });

    document.getElementById('capability_matrix_editor')?.addEventListener('click', (event) => {
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
      capabilityRuleState.splice(index, 1);
      expandedCapabilityRows = new Set(
        [...expandedCapabilityRows]
          .filter(value => value !== index)
          .map(value => value > index ? value - 1 : value)
      );
      setCapabilityRuleState(capabilityRuleState);
      markDirty();
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
