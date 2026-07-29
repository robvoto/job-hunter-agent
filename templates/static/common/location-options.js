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

function groupedLocationOptions() {
  const groups = new Map([
    ['Capital cities', []],
    ['States and territories', []],
  ]);
  rawOptions.forEach((option) => {
    const kind = String(option?.kind || '').trim().toLowerCase();
    const group = kind === 'city'
      ? 'Capital cities'
      : ['state', 'territory'].includes(kind)
        ? 'States and territories'
        : '';
    if (group) groups.get(group).push(option);
  });
  return groups;
}

export function renderLocationCheckboxes(container, options = {}) {
  if (!container) return;
  const selectedValues = new Set(
    (Array.isArray(options.selectedValues) ? options.selectedValues : [])
      .map(normalizeValue)
      .filter(Boolean)
  );
  const maxSelected = Number(options.maxSelected);
  const onChange = typeof options.onChange === 'function' ? options.onChange : () => {};

  container.innerHTML = '';
  groupedLocationOptions().forEach((groupOptions, group) => {
    const fieldset = document.createElement('fieldset');
    fieldset.className = 'checkbox-list-group location-checkbox-group';

    const legend = document.createElement('legend');
    legend.textContent = group;
    fieldset.appendChild(legend);

    const optionList = document.createElement('div');
    optionList.className = 'checkbox-list-options checkbox-list-options--two-column location-checkbox-options';

    groupOptions.forEach((option) => {
      const value = optionValue(option);
      const label = optionLabel(option);
      if (!value || !label) return;

      const item = document.createElement('label');
      item.className = 'checkbox-list-option location-checkbox-option';

      const input = document.createElement('input');
      input.type = 'checkbox';
      input.className = 'jh-checkbox';
      input.dataset.locationValue = value;
      input.checked = selectedValues.has(value);

      const text = document.createElement('span');
      text.textContent = label;
      item.append(input, text);
      optionList.appendChild(item);
    });

    fieldset.appendChild(optionList);
    container.appendChild(fieldset);
  });

  const inputs = Array.from(container.querySelectorAll('.jh-checkbox[data-location-value]'));
  const syncLimit = () => {
    if (!Number.isFinite(maxSelected) || maxSelected < 1) return;
    const count = inputs.filter((input) => input.checked).length;
    inputs.forEach((input) => {
      input.disabled = !input.checked && count >= maxSelected;
    });
  };
  inputs.forEach((input) => {
    input.addEventListener('change', () => {
      syncLimit();
      onChange(getSelectedLocationValues(container));
    });
  });
  syncLimit();
}

export function getSelectedLocationValues(container) {
  if (!container) return [];
  return Array.from(container.querySelectorAll('.jh-checkbox[data-location-value]:checked'))
    .map((input) => normalizeValue(input.dataset.locationValue))
    .filter(Boolean);
}

export { defaultLocation, rawOptions as options };
