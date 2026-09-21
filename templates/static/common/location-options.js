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

function optionValue(option) {
  return normalizeValue(option?.value);
}

export function resolveLocationValue(value) {
  const raw = normalizeValue(value);
  const candidates = [raw];
  const firstPart = raw.split(',', 1)[0].trim();
  if (firstPart && firstPart !== raw) candidates.push(firstPart);
  for (const option of rawOptions) {
    const candidateValue = optionValue(option).toLowerCase();
    const candidateLabel = optionLabel(option).toLowerCase();
    for (const candidate of candidates) {
      const normalized = candidate.toLowerCase();
      if (normalized && (normalized === candidateValue || normalized === candidateLabel)) {
        return optionValue(option);
      }
    }
  }
  return '';
}

export function getLocationLabel(value) {
  const resolved = resolveLocationValue(value);
  if (!resolved) return '';
  const option = rawOptions.find((item) => optionValue(item).toLowerCase() === resolved.toLowerCase());
  return optionLabel(option);
}

export function renderLocationOptions(select, options = {}) {
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
    const value = optionValue(option);
    if (value && !excludedValues.has(value)) {
      grouped.get(group).push(option);
    }
  });
  const values = new Set(
    rawOptions
      .map(optionValue)
      .filter((value) => Boolean(value) && !excludedValues.has(value))
  );
  const requestedValue = resolveLocationValue(select.value || defaultLocation || optionValue(rawOptions[0]) || optionLabel(rawOptions[0]) || '');
  const fallbackValue = resolveLocationValue(defaultLocation || optionValue(rawOptions[0]) || optionLabel(rawOptions[0]) || '');
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
      const value = optionValue(option);
      const label = optionLabel(option);
      const selected = value && value === selectedValue ? ' selected' : '';
      markup.push(`<option value="${escapeHtml(value)}"${selected}>${escapeHtml(label)}</option>`);
    });
    markup.push('</optgroup>');
  });
  select.innerHTML = markup.join('');
  if (selectedValue) select.value = selectedValue;
}

export function ensureDefaultLocation(select) {
  if (!select) return '';
  const current = String(select.value || '').trim();
  if (current) return current;
  const fallback = resolveLocationValue(defaultLocation || optionValue(rawOptions[0]) || optionLabel(rawOptions[0]));
  if (fallback) select.value = fallback;
  return String(select.value || '').trim();
}



function locationCheckboxInputs(container) {
  if (!container) return [];
  return Array.from(container.querySelectorAll('input[type="checkbox"][data-location-value]'));
}

export function getSelectedLocationValues(container) {
  return locationCheckboxInputs(container)
    .filter((input) => input.checked)
    .map((input) => normalizeValue(input.dataset.locationValue))
    .filter(Boolean);
}

export function syncLocationSelectionLimit(container, maxSelected) {
  const inputs = locationCheckboxInputs(container);
  const max = Number(maxSelected);
  if (!Number.isFinite(max) || max < 1) return;
  const selectedCount = inputs.filter((input) => input.checked).length;
  inputs.forEach((input) => {
    input.disabled = !input.checked && selectedCount >= max;
  });
}

export function renderLocationCheckboxOptions(container, options = {}) {
  if (!container) return;
  const allowedKinds = new Set(
    (Array.isArray(options.allowedKinds) ? options.allowedKinds : ['state', 'territory', 'city'])
      .map((kind) => normalizeValue(kind).toLowerCase())
      .filter(Boolean)
  );
  const selectedValues = new Set(
    (Array.isArray(options.selectedValues) ? options.selectedValues : [])
      .map((value) => resolveLocationValue(value) || normalizeValue(value))
      .filter(Boolean)
  );
  const grouped = new Map();
  rawOptions.forEach((option) => {
    const kind = normalizeValue(option?.kind).toLowerCase();
    if (!allowedKinds.has(kind)) return;
    const group = normalizeValue(option?.group || 'Locations');
    const value = optionValue(option);
    const label = optionLabel(option);
    if (!group || !value || !label) return;
    if (!grouped.has(group)) grouped.set(group, []);
    grouped.get(group).push({ value, label });
  });

  container.innerHTML = '';
  grouped.forEach((groupOptions, group) => {
    const section = document.createElement('fieldset');
    section.className = ['checkbox-list-group', 'location-checkbox-group', groupOptions.length > 6 ? 'checkbox-list-group--dense' : '']
      .filter(Boolean)
      .join(' ');
    const legend = document.createElement('legend');
    legend.textContent = group;
    section.appendChild(legend);

    const optionsWrap = document.createElement('div');
    optionsWrap.className = 'checkbox-list-options location-checkbox-options';
    groupOptions.forEach(({ value, label }) => {
      const item = document.createElement('label');
      item.className = 'checkbox-list-option location-checkbox-option';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.className = 'jh-checkbox';
      input.dataset.locationValue = value;
      input.checked = selectedValues.has(value);
      input.addEventListener('change', () => {
        syncLocationSelectionLimit(container, options.maxSelected);
        if (typeof options.onChange === 'function') {
          options.onChange(getSelectedLocationValues(container));
        }
      });
      const text = document.createElement('span');
      text.textContent = label;
      item.append(input, text);
      optionsWrap.appendChild(item);
    });
    section.appendChild(optionsWrap);
    container.appendChild(section);
  });
  syncLocationSelectionLimit(container, options.maxSelected);
}

export { defaultLocation, rawOptions as options };
