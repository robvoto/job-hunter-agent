window.JobHunterChipEditor = (function () {
  const { escapeHtml, toLines, rulesToText, textToRules, settingsField } = window.JobHunterSettingsUtils;

  const chipEditors = {
    target_roles: { kind: 'list', listId: 'target_roles_chips', inputId: 'target_roles_add', emptyText: 'No target roles yet.' },
    also_consider_roles: { kind: 'list', listId: 'also_consider_roles_chips', inputId: 'also_consider_roles_add', emptyText: 'No also-consider roles yet.' },
    must_not_require_skills: { kind: 'list', listId: 'must_not_require_skills_chips', inputId: 'must_not_require_skills_add', emptyText: 'No mandatory skills to reject yet.' },
    reject_title_rules: { kind: 'rule', key: 'pattern', listId: 'reject_title_rules_chips', inputId: 'reject_title_rules_add', emptyText: 'No blocked job titles yet.' },
    reject_description_phrase_rules: { kind: 'rule', key: 'phrase', listId: 'reject_description_phrase_rules_chips', inputId: 'reject_description_phrase_rules_add', emptyText: 'No excluded keywords or phrases yet.' },
  };

  const chipHtmlIdAliases = {};

  function resolveChipEditorId(id) { return chipHtmlIdAliases[id] || id; }

  function escapeRegExp(value) {
    return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  function normalizePlainPhrase(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function normalizeReasonToken(value) {
    return normalizePlainPhrase(value).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'custom';
  }

  function titlePhraseToPattern(value) {
    const tokens = normalizePlainPhrase(value).toLowerCase().match(/[a-z0-9]+/g) || [];
    if (!tokens.length) return '';
    return `\\b${tokens.map(escapeRegExp).join('\\s+')}\\b`;
  }

  function normalizeTitleBlockPhrase(value) {
    const tokens = String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().split(/\s+/).filter(Boolean);
    return tokens.slice(0, 3).join(' ');
  }

  function patternToLabel(pattern) {
    return normalizePlainPhrase(
      String(pattern || '')
        .replace(/\\b/g, '')
        .replace(/\\s\+/g, ' ')
        .replace(/\\ /g, ' ')
        .replace(/\\/g, '')
    );
  }

  function friendlyListLabel(id, value) {
    if (id === 'target_roles' || id === 'also_consider_roles') {
      return patternToLabel(value) || value;
    }
    return normalizePlainPhrase(value);
  }

  function friendlyRuleLabel(id, rule) {
    if (id === 'reject_title_rules') {
      const reason = String(rule.reason || '');
      const label = reason.startsWith('TITLE_BAD_KEYWORD:') ? reason.replace('TITLE_BAD_KEYWORD:', '') : '';
      return normalizePlainPhrase(label || patternToLabel(rule.pattern) || rule.pattern);
    }
    return normalizePlainPhrase(rule.phrase || rule.pattern || '');
  }

  function listIdentity(id, value) {
    return friendlyListLabel(id, value).toLowerCase();
  }

  function ruleIdentity(id, rule) {
    return friendlyRuleLabel(id, rule).toLowerCase();
  }

  function getListItems(id) {
    const field = settingsField(id);
    return field ? toLines(field.value) : [];
  }

  function setListItems(id, items) {
    const field = settingsField(id);
    if (field) field.value = (items || []).join('\n');
  }

  function getRuleItems(id) {
    const editor = chipEditors[id];
    const field = settingsField(id);
    return field && editor ? textToRules(field.value, editor.key) : [];
  }

  function setRuleItems(id, items) {
    const editor = chipEditors[id];
    const field = settingsField(id);
    if (field && editor) field.value = rulesToText(items || [], editor.key);
  }

  function buildChipValue(id, rawValue) {
    const raw = normalizePlainPhrase(rawValue);
    if (!raw) return null;
    if (id === 'target_roles' || id === 'also_consider_roles') return titlePhraseToPattern(raw);
    if (id === 'must_not_require_skills') return raw;
    if (id === 'reject_title_rules') {
      const phrase = normalizeTitleBlockPhrase(raw);
      if (!phrase) return null;
      return { pattern: titlePhraseToPattern(phrase), reason: `TITLE_BAD_KEYWORD:${phrase}` };
    }
    if (id === 'reject_description_phrase_rules') {
      const phrase = raw.toLowerCase();
      return { phrase, reason: `DESC_REJECT:${normalizeReasonToken(phrase)}` };
    }
    return raw;
  }

  function renderChipEditor(id) {
    const editor = chipEditors[id];
    const list = editor ? settingsField(editor.listId) : null;
    if (!editor || !list) return;

    const isRule = editor.kind === 'rule';
    const items = isRule ? getRuleItems(id) : getListItems(id);
    if (!items.length) {
      list.innerHTML = `<span class="badge-editor-empty">${escapeHtml(editor.emptyText)}</span>`;
      return;
    }
    list.innerHTML = items.map((item, index) => {
      const label = isRule ? friendlyRuleLabel(id, item) : friendlyListLabel(id, item);
      const title = isRule ? (item[editor.key] || label) : item;
      return `<span class="rule-chip">
        <span title="${escapeHtml(title)}">${escapeHtml(label || title)}</span>
        <button type="button" data-remove-chip="${escapeHtml(id)}" data-chip-index="${index}" title="Remove ${escapeHtml(label || title)}">&#215;</button>
      </span>`;
    }).join('');
  }

  function renderGlobalChipEditors() {
    Object.keys(chipEditors).forEach(renderChipEditor);
  }

  function addChipValue(id) {
    const editor = chipEditors[id];
    const input = editor ? settingsField(editor.inputId) : null;
    if (!editor || !input) return false;
    const value = buildChipValue(id, input.value);
    if (!value) return false;
    if (editor.kind === 'rule') {
      const items = getRuleItems(id);
      const identity = ruleIdentity(id, value);
      if (identity && !items.some(item => ruleIdentity(id, item) === identity)) {
        items.push(value);
        setRuleItems(id, items);
      }
    } else {
      const items = getListItems(id);
      const identity = listIdentity(id, value);
      if (identity && !items.some(item => listIdentity(id, item) === identity)) {
        items.push(value);
        setListItems(id, items);
      }
    }
    input.value = '';
    renderChipEditor(id);
    return true;
  }

  function removeChipValue(id, index) {
    const editor = chipEditors[id];
    if (!editor) return;
    if (editor.kind === 'rule') {
      const items = getRuleItems(id);
      if (editor.minItems && items.length <= editor.minItems) return;
      items.splice(index, 1);
      setRuleItems(id, items);
    } else {
      const items = getListItems(id);
      if (editor.minItems && items.length <= editor.minItems) return;
      items.splice(index, 1);
      setListItems(id, items);
    }
    renderChipEditor(id);
  }

  function flushChipEditorInputs() {
    Object.keys(chipEditors).forEach(id => {
      const input = settingsField(chipEditors[id].inputId);
      if (input && input.value.trim()) addChipValue(id);
    });
  }

  function initEventHandlers(markDirty) {
    document.addEventListener('click', e => {
      const addBtn = e.target.closest('[data-add-chip]');
      if (addBtn) {
        addChipValue(resolveChipEditorId(addBtn.dataset.addChip));
        markDirty();
        return;
      }
      const removeBtn = e.target.closest('[data-remove-chip]');
      if (removeBtn) {
        removeChipValue(resolveChipEditorId(removeBtn.dataset.removeChip), Number(removeBtn.dataset.chipIndex));
        markDirty();
      }
    });

    document.addEventListener('keydown', e => {
      const input = e.target.closest('[data-chip-input]');
      if (!input || e.key !== 'Enter') return;
      e.preventDefault();
      addChipValue(resolveChipEditorId(input.dataset.chipInput));
      markDirty();
    });
  }

  return {
    resolveChipEditorId,
    renderChipEditor,
    renderGlobalChipEditors,
    addChipValue,
    removeChipValue,
    flushChipEditorInputs,
    initEventHandlers,
  };
}());
