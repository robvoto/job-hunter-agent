(function () {
  const labels = window.__JOB_HUNTER_CAPABILITY_UI_LABELS__;
  if (!labels) {
    throw new Error('Missing capability UI labels.');
  }

  const capabilityLevelMeta = {
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

  window.JobHunterCapabilityUi = {
    labels,
    capabilityLevels: ['strong', 'working', 'basic'],
    capabilityLevelMeta,
    reviewStrengthPromptLabel: labels.review_strength_prompt_label,
  };
}());
