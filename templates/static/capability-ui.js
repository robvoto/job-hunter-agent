(function () {
  const capabilityLevelMeta = {
    strong: {
      label: 'Expert',
      tone: 'strength-strong',
      summary: 'Use this when the capability is current, repeated, and clearly one of your strongest areas.',
    },
    intermediate: {
      label: 'Intermediate',
      tone: 'strength-working',
      summary: 'Professional proficiency. Independent execution with solid recent evidence in production environments.',
    },
    historical: {
      label: 'Historical',
      tone: 'strength-basic',
      summary: 'Use this when the experience is real but stale, thin, or no longer a current strength capability.',
    },
  };

  window.JobHunterCapabilityUi = {
    capabilityLevelMeta,
    reviewStrengthPromptLabel: 'How strong is this capability for you?',
  };
}());
