"""Shared LLM protocol constants."""

LLM_ALLOWED_DECISIONS = frozenset({"KEEP", "REJECT", "MAYBE"})
LLM_ALLOWED_GRADES = frozenset({"EXCELLENT", "STRONG", "SOLID", "WEAK", "POOR", "MISMATCH"})

LLM_MAX_TOKENS_FIT_DECISION = 50
LLM_MAX_TOKENS_CV_EXTRACTION = 500
LLM_MAX_CV_EVIDENCE_JSON_CHARS = 12000
LLM_MAX_CV_FALLBACK_CHARS = 3000
LLM_MAX_TOKENS_REJECTION_SUGGESTIONS = 300

LLM_REVIEW_PROMPT_SHAPE = (
    '{"decision":"KEEP|REJECT|MAYBE","grade":"EXCELLENT|STRONG|SOLID|WEAK|POOR|MISMATCH",'
    '"learning_candidates":[{"signal":"...","suggested_category":"...","original_texts":["..."]}]}'
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
LLM_PROMPT_USE_AT_MOST_FOUR = "Use at most four learning candidates."
LLM_MAX_JOB_DESCRIPTION_CHARS = 5000
LLM_MAX_PROFILE_BRIEF_CHARS = 2500
LLM_MAX_CAPABILITY_RULES = 20
LLM_MAX_CAPABILITY_RULE_ALIASES = 8
LLM_MAX_FIT_GUIDANCE_CHARS = 1200
LLM_MAX_CAPABILITY_NAMING_GUIDANCE_CHARS = 1200
LLM_MAX_CAPABILITY_NAMING_ALIASES = 6
LLM_MAX_RAW_OUTPUT_LOG_CHARS = 1200
LLM_REJECTION_SUGGESTIONS_JSON_SHAPE = (
    '{"blockers":[{"term":"term"}]}'
)
