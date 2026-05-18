"""Shared LLM protocol constants."""

LLM_ALLOWED_DECISIONS = frozenset({"KEEP", "REJECT", "MAYBE"})
LLM_ALLOWED_GRADES = frozenset({"EXCELLENT", "STRONG", "SOLID", "WEAK", "POOR", "MISMATCH"})

LLM_FIT_REVIEW_PROMPT_SHAPE = (
    '{"fit_review":{"decision":"KEEP|REJECT|MAYBE","grade":"EXCELLENT|STRONG|SOLID|WEAK|POOR|MISMATCH"},'
    '"contextual_capability_matches":[{"capability_name":"...","confidence":"high|medium|low","matched_text":"...","reason":"..."}]}'
)
LLM_PROMPT_CONTEXTUAL_CAPABILITY_INTRO = (
    "For contextual_capability_matches: identify profile capabilities evidenced in the ad but not stated verbatim. "
    "Use only capability names from the 'Capability levels' list above. "
    "Set confidence to high (clearly evidenced), medium (plausibly evidenced), or low (weak signal only). "
    "Leave the list empty if nothing is clearly evidenced beyond what is verbatim."
)

LLM_LEARNING_ONLY_PROMPT_SHAPE = (
    '{"learning_candidates":[{"signal":"...","suggested_category":"...","original_texts":["..."]}]}'
)

LLM_REVIEW_GRADE_GUIDANCE = (
    "Use EXCELLENT or STRONG for clearly aligned roles, SOLID for broadly aligned roles with manageable gaps, "
    "WEAK for superficial or mixed fit, POOR for very limited fit, and MISMATCH for clear mismatch."
)

LLM_PROMPT_CANDIDATE_FIT_BRIEF_HEADER = "Candidate fit brief:"
LLM_PROMPT_CAPABILITY_LEVELS_HEADER = "Capability levels:"
LLM_PROMPT_MATCH_PREFERENCES_HEADER = "Match preferences:"
LLM_PROMPT_DEFAULT_FIT_REVIEW_GUIDANCE_HEADER = "Default fit review guidance:"
LLM_PROMPT_USER_FIT_REVIEW_GUIDANCE_HEADER = "User fit review guidance:"
LLM_PROMPT_CAPABILITY_NAMING_INTRO = (
    "You are reviewing and labelling candidate professional capability clusters extracted from a CV."
)
LLM_PROMPT_DEFAULT_CAPABILITY_NAMING_GUIDANCE_HEADER = "Default capability naming guidance:"
LLM_PROMPT_USER_CAPABILITY_NAMING_GUIDANCE_HEADER = "User capability naming guidance:"
LLM_PROMPT_CLUSTERS_HEADER = "Clusters:"
LLM_PROMPT_SYSTEM_REVIEW_INTRO = "You are helping decide whether a candidate should apply for a job."
LLM_PROMPT_REVIEW_OUTPUT_FORMAT = "Answer with exactly ONE line in uppercase using this format: DECISION|GRADE."
LLM_PROMPT_JSON_ONLY = "Return JSON only."
LLM_PROMPT_JOB_DESCRIPTION_PREFIX = "Job description:\n"
LLM_PROMPT_NO_FIT_DECISION_REQUIRED = "No fit decision is required."
LLM_PROMPT_DO_NOT_SAVE = "Do not save anything."
LLM_PROMPT_DO_NOT_INVENT = "Do not invent new categories."
LLM_PROMPT_USE_VISIBLE_STRINGS = "Use only concise candidate strings already visible in the ad."
LLM_PROMPT_LEARNING_PENDING_ONLY = "Learning candidates must be pending review only."
LLM_REJECTION_SUGGESTIONS_JSON_SHAPE = (
    '{"blockers":[{"term":"term"}]}'
)
