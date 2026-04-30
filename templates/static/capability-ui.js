(function () {
  const capabilityLevelMeta = {
    strong: {
      label: 'Expert',
      tone: 'strength-strong',
      summary: 'Use this when the capability is current, repeated, and clearly one of your strongest areas.',
    },
    working: {
      label: 'Intermediate',
      tone: 'strength-working',
      summary: 'Professional proficiency. Independent execution with solid recent evidence in production environments.',
    },
    basic: {
      label: 'Basic',
      tone: 'strength-basic',
      summary: 'Use this when you have usable experience, but it is not one of your strongest current signals.',
    },
  };

  window.JobHunterCapabilityUi = {
    capabilityLevelMeta,
    strengthGuideTitle: 'Strength shows your current depth for this capability.',
    reviewStrengthPromptLabel: 'How strong is this capability for you?',
  };
}());
