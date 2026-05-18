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

  function normalizeReviewText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function patternToLabel(pattern) {
    return normalizeReviewText(
      String(pattern || '')
        .replace(/\\b/g, '')
        .replace(/\\s\+/g, ' ')
        .replace(/\\ /g, ' ')
        .replace(/\\/g, '')
    );
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

  const workModePreferenceOptions = Array.isArray(window.__JOB_HUNTER_WORK_MODE_PREFERENCE_OPTIONS__)
    ? window.__JOB_HUNTER_WORK_MODE_PREFERENCE_OPTIONS__
    : [];
  const engagementTypeOptions = Array.isArray(window.__JOB_HUNTER_ENGAGEMENT_TYPE_OPTIONS__)
    ? window.__JOB_HUNTER_ENGAGEMENT_TYPE_OPTIONS__
    : [];
  const engagementTypeDefaultValues = Array.isArray(window.__JOB_HUNTER_ENGAGEMENT_TYPE_DEFAULT_VALUES__)
    ? window.__JOB_HUNTER_ENGAGEMENT_TYPE_DEFAULT_VALUES__
    : engagementTypeOptions.map((option) => option.value);
  const engagementTypeValues = new Set(
    engagementTypeOptions
      .map((option) => String(option.value || '').trim().toLowerCase())
      .filter(Boolean)
  );
  const governmentPreferenceDefault = String(
    window.__JOB_HUNTER_GOVERNMENT_PREFERENCE_DEFAULT__
    || 'any'
  ).trim().toLowerCase();
  const workModePreferenceValues = new Set(
    workModePreferenceOptions
      .map((option) => String(option.value || '').trim().toLowerCase())
      .filter(Boolean)
  );
  function normalizeWorkModePreferences(value) {
    const values = Array.isArray(value)
      ? value
      : String(value || '').split(/[,\n|/]+/);
    const selected = [];
    const seen = new Set();
    for (const option of workModePreferenceOptions) {
      const key = String(option.value || '').trim().toLowerCase();
      if (!key) continue;
      if (values.some((item) => String(item || '').trim().toLowerCase() === key) && !seen.has(key)) {
        seen.add(key);
        selected.push(key);
      }
    }
    return selected;
  }

  function normalizeEngagementTypePreferences(value, defaultToAll = true) {
    const values = Array.isArray(value)
      ? value
      : String(value || '').split(/[,\n|/]+/);
    const selected = [];
    const seen = new Set();
    for (const option of engagementTypeOptions) {
      const key = String(option.value || '').trim().toLowerCase();
      if (!key) continue;
      if (values.some((item) => String(item || '').trim().toLowerCase() === key) && !seen.has(key)) {
        seen.add(key);
        selected.push(key);
      }
    }
    if (selected.length) {
      return selected;
    }
    return defaultToAll
      ? engagementTypeDefaultValues.map((value) => String(value || '').trim().toLowerCase()).filter(Boolean)
      : [];
  }

  function getWorkModePreferenceValues() {
    return normalizeWorkModePreferences(
      Array.from(document.querySelectorAll('input[name="work_mode_preference"]:checked')).map((input) => input.value)
    );
  }

  function setWorkModePreferenceValues(values) {
    const selected = new Set(normalizeWorkModePreferences(values));
    document.querySelectorAll('input[name="work_mode_preference"]').forEach((input) => {
      input.checked = selected.size === 0 || selected.has(String(input.value || '').trim().toLowerCase());
    });
  }

  function getEngagementTypeValues() {
    return normalizeEngagementTypePreferences(
      Array.from(document.querySelectorAll('input[name="engagement_type"]:checked')).map((input) => input.value)
    );
  }

  function setEngagementTypeValues(value) {
    const selected = new Set(normalizeEngagementTypePreferences(value));
    const inputs = Array.from(document.querySelectorAll('input[name="engagement_type"]'));
    inputs.forEach((input) => {
      input.checked = selected.size === 0 || selected.has(String(input.value || '').trim().toLowerCase());
    });
  }

  function normalizeGovernmentPreferenceValues(value, defaultToAll = true) {
    const values = Array.isArray(value)
      ? value
      : String(value || '').split(/[,\n|/]+/);
    const inputs = Array.from(document.querySelectorAll('input[name="prefer_government"]'));
    const selected = [];
    const seen = new Set();
    for (const input of inputs) {
      const key = String(input.value || '').trim().toLowerCase();
      if (!key) continue;
      if (values.some((item) => String(item || '').trim().toLowerCase() === key) && !seen.has(key)) {
        seen.add(key);
        selected.push(key);
      }
    }
    if (selected.length) {
      return selected;
    }
    return defaultToAll
      ? inputs.map((input) => String(input.value || '').trim().toLowerCase()).filter(Boolean)
      : [];
  }

  function getGovernmentPreferenceValues() {
    return normalizeGovernmentPreferenceValues(
      Array.from(document.querySelectorAll('input[name="prefer_government"]:checked')).map((input) => input.value)
    );
  }

  function setGovernmentPreferenceValues(value) {
    const selected = new Set(normalizeGovernmentPreferenceValues(value));
    document.querySelectorAll('input[name="prefer_government"]').forEach((input) => {
      input.checked = selected.size === 0 || selected.has(String(input.value || '').trim().toLowerCase());
    });
  }

  function setToggleChecked(id, checked) {
    const input = document.getElementById(id);
    if (input) input.checked = Boolean(checked);
  }

  function getToggleChecked(id) {
    return Boolean(document.getElementById(id)?.checked);
  }

  function setChoiceGroupValue(name, value) {
    const inputs = Array.from(document.querySelectorAll(`input[name="${name}"]`));
    if (!inputs.length) {
      throw new Error(`Missing choice group for ${name}.`);
    }
    const selectedValue = String(value ?? '').trim();
    if (!selectedValue) {
      throw new Error(`Missing value for ${name}.`);
    }
    let matched = false;
    inputs.forEach((input) => {
      const checked = String(input.value || '').trim() === selectedValue;
      input.checked = checked;
      matched = matched || checked;
    });
    if (!matched) {
      throw new Error(`Invalid value for ${name}: ${selectedValue}`);
    }
  }

  function getChoiceGroupValue(name) {
    const value = String(document.querySelector(`input[name="${name}"]:checked`)?.value || '').trim();
    if (!value) {
      throw new Error(`Missing choice value for ${name}.`);
    }
    return value;
  }

  function settingsField(id) {
    return document.getElementById(id);
  }

  function bindCurrencyFields(ids) {
    const currencyUi = window.JobHunterCurrencyUi || {};
    (ids || []).forEach(id => currencyUi.bindCurrencyInput?.(document.getElementById(id)));
  }

  function setCurrencyFieldValue(id, value) {
    const input = (typeof id === 'string') ? document.getElementById(id) : id;
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
    const input = (typeof id === 'string') ? document.getElementById(id) : id;
    if (!input) return fallback;
    const currencyUi = window.JobHunterCurrencyUi || {};
    const parsed = currencyUi.parseCurrencyValue
      ? currencyUi.parseCurrencyValue(input.value)
      : Number(String(input.value || '').replace(/,/g, ''));
    return Number.isFinite(parsed) && parsed !== '' ? parsed : fallback;
  }

  function parseCurrencyValue(value) {
    const currencyUi = window.JobHunterCurrencyUi || {};
    return currencyUi.parseCurrencyValue
      ? currencyUi.parseCurrencyValue(value)
      : (Number(String(value || '').replace(/,/g, '')) || '');
  }

  return {
    escapeHtml,
    toLines,
    normalizeReviewText,
    patternToLabel,
    rulesToText,
    textToRules,
    settingsField,
    bindCurrencyFields,
    normalizeWorkModePreferences,
    getWorkModePreferenceValues,
    setWorkModePreferenceValues,
    normalizeEngagementTypePreferences,
    getEngagementTypeValues,
    setEngagementTypeValues,
    normalizeGovernmentPreferenceValues,
    getGovernmentPreferenceValues,
    setGovernmentPreferenceValues,
    setToggleChecked,
    getToggleChecked,
    setChoiceGroupValue,
    getChoiceGroupValue,
    ENGAGEMENT_TYPE_VALUES: engagementTypeValues,
    ENGAGEMENT_TYPE_DEFAULT_VALUES: engagementTypeDefaultValues,
    WORK_MODE_PREFERENCE_VALUES: workModePreferenceValues,
    GOVERNMENT_PREFERENCE_DEFAULT: governmentPreferenceDefault,
    parseCurrencyValue,
    setCurrencyFieldValue,
    readCurrencyFieldValue,
  };
}());
