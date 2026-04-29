(function () {
  const capabilityLevelMeta = {
    strong: {
      label: 'Expert',
      summary: 'Can lead, innovate, and mentor others.',
      tone: 'strength-strong',
    },
    working: {
      label: 'Advanced',
      summary: 'Can handle complex tasks independently.',
      tone: 'strength-working',
    },
    basic: {
      label: 'Intermediate',
      summary: 'Can handle routine tasks with minimal help.',
      tone: 'strength-basic',
    },
    low: {
      label: 'Beginner',
      summary: 'Learning the basics; needs heavy supervision.',
      tone: 'strength-low',
    },
  };

  const capabilityPriorityMeta = {
    core: {
      label: 'Essential',
      summary: 'Capabilities that should matter a lot for your target roles.',
    },
    supporting: {
      label: 'Helpful',
      summary: 'Relevant capabilities that should help, but not define, the match.',
    },
    contextual: {
      label: 'Background',
      summary: 'Experience that should stay in the background.',
    },
    avoid: {
      label: 'Not a fit',
      summary: 'Capabilities that point toward the wrong kinds of roles.',
    },
  };

  const capabilityModeMeta = {
    core_skill: {
      label: 'Essential',
      summary: 'One of your main strengths for the roles you want.',
      useWhen: 'Use this when the capability should matter a lot in matching.',
      engineEffect: 'The app will treat it as a strong core capability.',
      level: 'strong',
      fit: 'core',
    },
    useful_support: {
      label: 'Helpful',
      summary: 'This is a real skill, but it should support matching rather than define it.',
      useWhen: 'Use this when the capability is relevant and useful, but not central to your pitch.',
      engineEffect: 'The app will treat it as a positive supporting capability.',
      level: 'working',
      fit: 'supporting',
    },
    background_only: {
      label: 'Background',
      summary: 'This is acceptable context, but it should not drive matching on its own.',
      useWhen: 'Use this for adjacent or lighter experience that should stay in the background.',
      engineEffect: 'The app will keep it as a weak contextual signal.',
      level: 'basic',
      fit: 'contextual',
    },
    not_for_me: {
      label: 'Not a fit',
      summary: 'Jobs that lean on this capability are probably the wrong direction.',
      useWhen: 'Use this when the capability points toward work you do not want the app to favour.',
      engineEffect: 'The app will treat it as a capability to avoid.',
      level: 'none',
      fit: 'avoid',
    },
  };

  window.JobHunterCapabilityUi = {
    capabilityLevelMeta,
    capabilityPriorityMeta,
    capabilityModeMeta,
    capabilityModeOptions: ['core_skill', 'useful_support', 'background_only', 'not_for_me'],
    strengthGuideTitle: 'Strength shows your depth. Relevance decides how much that capability should influence matching.',
    reviewPromptLabel: 'How relevant is this to your target roles?',
    emptyReviewChoiceMeta: {
      label: 'Choose an option',
      summary: 'Pick the simplest description of how this capability fits your target roles.',
      useWhen: 'Choose the closest option based on your CV and the kept-role examples.',
      engineEffect: 'Nothing changes until you confirm.',
    },
  };
}());
