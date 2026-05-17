(function () {
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
    capabilityLevels: ['strong', 'working', 'basic'],
    capabilityLevelMeta,
    reviewStrengthPromptLabel: 'How strong is this capability for you?',
    reviewCopy: {
      onboardingHelp: 'Review the capabilities Job Hunter learned from your CV. Keep only the ones that clearly belong to your profile; you can refine them later in Settings.',
      settingsHelp: 'Keep the set tight. These rows feed fit scoring, CV learning, and review. Aliases are generated automatically when you save.',
    },
  };
}());
