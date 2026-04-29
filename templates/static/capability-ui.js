(function () {
  const capabilityLevelMeta = {
    strong: {
      label: 'Expert',
      tone: 'strength-strong',
      summary: 'Use this when the capability is current, repeated, and clearly one of your strongest areas.',
    },
    working: {
      label: 'Advanced',
      tone: 'strength-working',
      summary: 'Use this when you can work independently with the capability and have solid recent evidence.',
    },
    basic: {
      label: 'Intermediate',
      tone: 'strength-basic',
      summary: 'Use this when you have usable experience, but it is not one of your strongest current signals.',
    },
    low: {
      label: 'Beginner',
      tone: 'strength-low',
      summary: 'Use this when the capability is older, lighter, or only shows up in limited evidence.',
    },
  };

  window.JobHunterCapabilityUi = {
    capabilityLevelMeta,
    strengthGuideTitle: 'Strength shows your current depth for this capability.',
    reviewStrengthPromptLabel: 'How strong is this capability for you?',
  };
}());
