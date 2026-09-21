const labels = window.__JOB_HUNTER_CAPABILITY_UI_LABELS__;
if (!labels) {
  throw new Error('Missing capability UI labels.');
}

export const capabilityLevelMeta = {
  strong: {
    label: 'Strong',
    tone: 'strength-strong',
    summary: 'Use this when the capability is current, repeated, and should carry the most weight in matching.',
  },
  working: {
    label: 'Working',
    tone: 'strength-working',
    summary: 'Use this when the capability is real and useful, but should influence matching less than your strongest areas.',
  },
  basic: {
    label: 'Basic',
    tone: 'strength-basic',
    summary: 'Use this when the experience is real but thin, stale, or should have only a light influence on matching.',
  },
};

export const capabilityLevels = ['strong', 'working', 'basic'];

function escapeCapabilityHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function dataAttributesMarkup(attributes = {}) {
  return Object.entries(attributes)
    .filter(([key, value]) => key && value !== undefined && value !== null)
    .map(([key, value]) => `${escapeCapabilityHtml(key)}="${escapeCapabilityHtml(value)}"`)
    .join(' ');
}

export function capabilityStrengthMeterMarkup({
  selectedValue = '',
  groupName,
  inputIdPrefix = groupName,
  inputDataAttributes = {},
  meterDataAttributes = {},
  ariaLabel = 'Capability strength',
  helpId = '',
  emptyLabel = 'Select strength',
} = {}) {
  if (!groupName || !inputIdPrefix) {
    throw new Error('Capability strength meter requires groupName and inputIdPrefix.');
  }
  const meterLevels = ['basic', 'working', 'strong'].filter(level => capabilityLevels.includes(level));
  const selectedIndex = meterLevels.indexOf(selectedValue);
  const selectedMeta = selectedIndex >= 0
    ? capabilityLevelMeta[selectedValue]
    : { label: emptyLabel, summary: 'Choose Basic, Working, or Strong.', tone: '' };
  const inputAttrs = dataAttributesMarkup(inputDataAttributes);
  const meterAttrs = dataAttributesMarkup(meterDataAttributes);
  const resolvedHelpId = helpId || `${inputIdPrefix}_help`;
  const choices = meterLevels.map((level, levelIndex) => {
    const meta = capabilityLevelMeta[level] || { label: level };
    const inputId = `${inputIdPrefix}_${level}`;
    const checked = level === selectedValue ? ' checked' : '';
    const filledClass = selectedIndex >= 0 && levelIndex <= selectedIndex ? ' is-filled' : '';
    return `
      <label class="capability-strength-dot${filledClass}" for="${escapeCapabilityHtml(inputId)}" title="${escapeCapabilityHtml(meta.label)}">
        <input id="${escapeCapabilityHtml(inputId)}" type="radio" name="${escapeCapabilityHtml(groupName)}" value="${escapeCapabilityHtml(level)}"${inputAttrs ? ` ${inputAttrs}` : ''}${checked} aria-label="${escapeCapabilityHtml(meta.label)}">
        <span aria-hidden="true"></span>
      </label>
    `;
  }).join('');
  return `
    <div class="capability-strength-meter ${escapeCapabilityHtml(selectedMeta?.tone || '')}"
         role="radiogroup"
         aria-label="${escapeCapabilityHtml(ariaLabel)}"
         aria-describedby="${escapeCapabilityHtml(resolvedHelpId)}"${meterAttrs ? ` ${meterAttrs}` : ''}>
      <span class="capability-strength-dots">${choices}</span>
      <span class="capability-strength-label">${escapeCapabilityHtml(selectedMeta?.label || emptyLabel)}</span>
      <span class="capability-strength-tooltip" id="${escapeCapabilityHtml(resolvedHelpId)}" role="tooltip">
        <strong>${escapeCapabilityHtml(selectedMeta?.label || emptyLabel)}</strong>
        <span>${escapeCapabilityHtml(selectedMeta?.summary || '')}</span>
      </span>
    </div>
  `;
}

export function updateCapabilityStrengthMeter(meter, selectedValue, emptyLabel = 'Select strength') {
  if (!meter) return;
  const meterLevels = ['basic', 'working', 'strong'].filter(level => capabilityLevels.includes(level));
  const selectedIndex = meterLevels.indexOf(selectedValue);
  const selectedMeta = selectedIndex >= 0
    ? capabilityLevelMeta[selectedValue]
    : { label: emptyLabel, summary: 'Choose Basic, Working, or Strong.', tone: '' };
  Object.values(capabilityLevelMeta).forEach(meta => {
    if (meta?.tone) meter.classList.remove(meta.tone);
  });
  if (selectedMeta?.tone) meter.classList.add(selectedMeta.tone);
  meter.querySelectorAll('.capability-strength-dot').forEach((dot, index) => {
    dot.classList.toggle('is-filled', selectedIndex >= 0 && index <= selectedIndex);
  });
  const label = meter.querySelector('.capability-strength-label');
  if (label) label.textContent = selectedMeta?.label || emptyLabel;
  const tooltipLabel = meter.querySelector('.capability-strength-tooltip strong');
  if (tooltipLabel) tooltipLabel.textContent = selectedMeta?.label || emptyLabel;
  const tooltipSummary = meter.querySelector('.capability-strength-tooltip span');
  if (tooltipSummary) tooltipSummary.textContent = selectedMeta?.summary || '';
}
export { labels };
export const reviewStrengthPromptLabel = labels.review_strength_prompt_label;
export const genericCapabilityIconKey = 'generic_capability';

export function capabilityIconHtml(iconKey, capabilityName = '') {
  return `
    <span class="capability-card-icon capability-card-icon--${genericCapabilityIconKey}" aria-hidden="true" data-icon-key="${String(iconKey || genericCapabilityIconKey).trim().toLowerCase() || genericCapabilityIconKey}">
      <svg viewBox="0 0 24 24" class="capability-card-icon-svg" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
        <rect x="4.5" y="4.5" width="15" height="15" rx="5"/>
        <path d="M12 7.2 13.5 10h3l-2.4 1.8.9 2.9L12 13l-3 1.7.9-2.9L7.5 10h3z"/>
      </svg>
    </span>
  `;
}

export const genericCapabilityIconHtml = capabilityIconHtml(genericCapabilityIconKey);

export function splitCapabilityAliasesForDisplay(aliases, previewCount = 2) {
  const normalizedAliases = Array.isArray(aliases) ? aliases : [];
  const safePreviewCount = Math.max(0, Number(previewCount) || 0);
  return {
    preview: normalizedAliases.slice(0, safePreviewCount),
    remaining: normalizedAliases.slice(safePreviewCount),
  };
}
