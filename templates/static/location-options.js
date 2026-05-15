(() => {
  const rawOptions = Array.isArray(window.__JOB_HUNTER_LOCATION_OPTIONS__)
    ? window.__JOB_HUNTER_LOCATION_OPTIONS__
    : [];
  const defaultLocation = String(window.__JOB_HUNTER_DEFAULT_LOCATION__ || '').trim();

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function optionLabel(option) {
    return String(option?.label || option?.value || '').trim();
  }

  function normalizeValue(value) {
    return String(value || '').trim();
  }

  function renderLocationOptions(select, options = {}) {
    if (!select) return;
    const excludedValues = new Set(
      Array.isArray(options.excludedValues)
        ? options.excludedValues.map(normalizeValue).filter(Boolean)
        : []
    );
    const grouped = new Map();
    rawOptions.forEach((option) => {
      const group = String(option?.group || 'Locations').trim();
      if (!grouped.has(group)) grouped.set(group, []);
      const value = optionLabel(option);
      if (value && !excludedValues.has(value)) {
        grouped.get(group).push(option);
      }
    });
    const values = new Set(
      rawOptions
        .map(optionLabel)
        .filter((value) => Boolean(value) && !excludedValues.has(value))
    );
    const requestedValue = normalizeValue(select.value || defaultLocation || optionLabel(rawOptions[0]) || '');
    const fallbackValue = normalizeValue(defaultLocation || optionLabel(rawOptions[0]) || '');
    const selectedValue = values.has(requestedValue)
      ? requestedValue
      : values.has(fallbackValue)
        ? fallbackValue
        : String(Array.from(values)[0] || '').trim();
    const markup = [];
    markup.push('<option value="">Select one location</option>');
    grouped.forEach((options, group) => {
      markup.push(`<optgroup label="${escapeHtml(group)}">`);
      options.forEach((option) => {
        const value = optionLabel(option);
        const selected = value && value === selectedValue ? ' selected' : '';
        markup.push(`<option value="${escapeHtml(value)}"${selected}>${escapeHtml(value)}</option>`);
      });
      markup.push('</optgroup>');
    });
    select.innerHTML = markup.join('');
    if (selectedValue) select.value = selectedValue;
  }

  function ensureDefaultLocation(select) {
    if (!select) return '';
    const current = String(select.value || '').trim();
    if (current) return current;
    const fallback = defaultLocation || optionLabel(rawOptions[0]);
    if (fallback) select.value = fallback;
    return String(select.value || '').trim();
  }

  window.JobHunterLocationUi = {
    defaultLocation,
    options: rawOptions,
    ensureDefaultLocation,
    renderLocationOptions,
  };
})();
