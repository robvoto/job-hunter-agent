const labels = window.__JOB_HUNTER_CAPABILITY_UI_LABELS__;
if (!labels) {
  throw new Error('Missing capability UI labels.');
}

export const capabilityLevelMeta = {
  strong: {
    label: 'Strong',
    tone: 'strength-strong',
    summary: 'Use this when the capability is current, repeated, and clearly one of your strongest areas.',
  },
  working: {
    label: 'Working',
    tone: 'strength-working',
    summary: 'Professional proficiency. Independent execution with solid recent evidence in production environments.',
  },
  basic: {
    label: 'Basic',
    tone: 'strength-basic',
    summary: 'Use this when the experience is real but stale, thin, or no longer a current strength capability.',
  },
};

export const capabilityLevels = ['strong', 'working', 'basic'];
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
