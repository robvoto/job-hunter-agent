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

export { defaultLocation, rawOptions as options };
