window.JobHunterCapabilityEditor = (function () {
  const capabilityUi = window.JobHunterCapabilityUi || {};
  const { escapeHtml, settingsField } = window.JobHunterSettingsUtils;
  const capabilityLevelMeta = capabilityUi.capabilityLevelMeta || {};
  const capabilityLevels = Array.isArray(capabilityUi.capabilityLevels) && capabilityUi.capabilityLevels.length
    ? capabilityUi.capabilityLevels
    : Object.keys(capabilityLevelMeta);

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

  function capabilityStrengthMeta(level) {
    const key = String(level || '').trim().toLowerCase();
    if (!key) return null;
    return capabilityLevelMeta[key] || capabilityLevelMeta.basic || { label: 'Basic' };
  }

  function renderCapabilityRuleEditor() {
    const container = document.getElementById('capability_matrix_editor');
    if (!container) return;
    if (!capabilityRuleState.length) {
      container.innerHTML = '<div class="capability-editor-empty">No capability rules yet. Run onboarding or add a capability row here.</div>';
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
            <span class="cap-alias-chip" title="${escapeHtml(alias)}">${escapeHtml(alias)}</span>
          `).join('');
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
              <div class="capability-card-meta">
                ${aliasCount ? `
                  <details class="capability-alias-drawer"${expandedCapabilityRows.has(index) ? ' open' : ''}>
                    <summary class="cap-alias-summary">${escapeHtml(`${aliasCount} alias${aliasCount === 1 ? '' : 'es'}`)}</summary>
                    <div class="cap-alias-chips">${aliasChips}</div>
                  </details>
                ` : ''}
              </div>
              <label class="cap-strength">
                <span>Strength</span>
                <select class="cap-level-select capability-strength-select level-${escapeHtml(rule.level || 'basic')}"
                        data-capability-field="level" aria-label="Capability strength">
                  <option value="strong"${rule.level === 'strong' ? ' selected' : ''}>${escapeHtml(capabilityStrengthMeta('strong')?.label || 'Strong')}</option>
                  <option value="working"${rule.level === 'working' ? ' selected' : ''}>${escapeHtml(capabilityStrengthMeta('working')?.label || 'Working')}</option>
                  <option value="basic"${rule.level === 'basic' ? ' selected' : ''}>${escapeHtml(capabilityStrengthMeta('basic')?.label || 'Basic')}</option>
                </select>
              </label>
            </article>
          `;
        }).join('')
      : '<div class="capability-editor-empty-group">No matching capabilities.</div>';

    const helpText = escapeHtml(capabilityUi.reviewCopy?.settingsHelp || '');
    container.innerHTML = `
      <section class="capability-group">
        <div class="capability-group-head">
          <div>
            <h4 class="capability-group-title">Capabilities</h4>
            <p class="capability-group-copy">${helpText}</p>
          </div>
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
    capabilityStrengthMeta,
    setCapabilityRuleState,
    collectCapabilityRuleState,
    renderCapabilityRuleEditor,
    addCapabilityRule,
    initEventHandlers,
  };
}());
