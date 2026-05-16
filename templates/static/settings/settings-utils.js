window.JobHunterSettingsUtils = (function () {
  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function toLines(value) {
    return value.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  }

  function rulesToText(rules, key) {
    return (rules || []).map(rule => `${rule[key] || ''} || ${rule.reason || ''}`).join('\n');
  }

  function textToRules(value, key) {
    return toLines(value).map(line => {
      const parts = line.split('||');
      return {
        [key]: (parts[0] || '').trim(),
        reason: (parts[1] || '').trim(),
      };
    }).filter(rule => rule[key]);
  }

  function settingsField(id) {
    const aliases = {
      secondary_title_patterns: 'adjacent_title_patterns',
      secondary_title_patterns_add: 'adjacent_title_patterns_add',
      secondary_title_patterns_chips: 'adjacent_title_patterns_chips',
    };
    return document.getElementById(id) || document.getElementById(aliases[id] || '');
  }

  function bindCurrencyFields(ids) {
    const currencyUi = window.JobHunterCurrencyUi || {};
    (ids || []).forEach(id => currencyUi.bindCurrencyInput?.(document.getElementById(id)));
  }

  function setCurrencyFieldValue(id, value) {
    const input = document.getElementById(id);
    if (!input) return;
    const currencyUi = window.JobHunterCurrencyUi || {};
    if (currencyUi.setCurrencyInputValue) {
      currencyUi.setCurrencyInputValue(input, value);
    } else {
      input.value = String(value ?? '');
    }
  }

  function readCurrencyFieldValue(id, fallback) {
    if (fallback === undefined) fallback = 0;
    const input = document.getElementById(id);
    if (!input) return fallback;
    const currencyUi = window.JobHunterCurrencyUi || {};
    const parsed = currencyUi.parseCurrencyValue
      ? currencyUi.parseCurrencyValue(input.value)
      : Number(String(input.value || '').replace(/,/g, ''));
    return Number.isFinite(parsed) && parsed !== '' ? parsed : fallback;
  }

  return { escapeHtml, toLines, rulesToText, textToRules, settingsField, bindCurrencyFields, setCurrencyFieldValue, readCurrencyFieldValue };
}());
