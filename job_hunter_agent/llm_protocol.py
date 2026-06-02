"""Shared LLM protocol constants."""

LLM_ALLOWED_DECISIONS = frozenset({"KEEP", "REJECT", "MAYBE"})
LLM_ALLOWED_GRADES = frozenset({"EXCELLENT", "STRONG", "SOLID", "WEAK", "POOR", "MISMATCH"})

LLM_FIT_REVIEW_PROMPT_SHAPE = (
    '{"fit_review":{"decision":"KEEP|REJECT|MAYBE","grade":"EXCELLENT|STRONG|SOLID|WEAK|POOR|MISMATCH"},'
    '"contextual_capability_matches":[{"capability_name":"...","confidence":"high|medium|low","matched_text":"...","reason":"..."}],'
    '"learning_candidates":[{"signal":"...","suggested_category":"...","suggested_values":["..."],'
    '"context_terms":["..."],"confidence":"high|medium|low|ambiguous","needs_review":true,"original_texts":["..."]}],'
    '"job_requirements":["..."]}'
)
LLM_PROMPT_CONTEXTUAL_CAPABILITY_INTRO = (
    "For contextual_capability_matches: identify profile capabilities evidenced in the ad but not stated verbatim. "
    "Use the related skills to recognise a capability in the ad, but capability_name must always be the exact group name "
    "from the 'Capability levels' list — never a related skill or your own wording. "
    "Set confidence to high (clearly evidenced), medium (plausibly evidenced), or low (weak signal only). "
    "Leave the list empty if nothing is clearly evidenced beyond what is verbatim."
)
LLM_PROMPT_JOB_REQUIREMENTS_INTRO = (
    "For job_requirements: extract the job's explicit requirements as concise bullet-style phrases. "
    "Use only visible ad text, prefer the employer's own wording, keep each item short, and do not invent anything. "
    "Capture the requirements the user would want to read before opening the ad. "
    "If the ad states the work type explicitly, preserve it as one of: Permanent, Contract, Full Time Contract / FTC, Temporary. "
    "Use Unknown when the work type is unclear."
)
LLM_PROMPT_LEARNING_CANDIDATES_INTRO = (
    "For learning_candidates: actively identify new signals visible in this ad that are not yet captured "
    "in the candidate profile or approved knowledge — role title patterns, government/clearance context patterns, "
    "and capability concepts not already listed above. "
    "Use only visible ad text. Follow the category guidance above for each signal type. "
    "Set needs_review=true for all entries. Leave the list empty only if nothing new is found."
)

LLM_LEARNING_ONLY_PROMPT_SHAPE = (
    '{"learning_candidates":[{"signal":"...","suggested_category":"...","suggested_values":["..."],'
    '"context_terms":["..."],"confidence":"high|medium|low|ambiguous","needs_review":true,"original_texts":["..."]}]}'
)

LLM_JOB_REQUIREMENTS_PROMPT_SHAPE = '{"job_requirements":["..."]}'

LLM_REVIEW_GRADE_GUIDANCE = (
    "Use EXCELLENT or STRONG for clearly aligned roles, SOLID for broadly aligned roles with manageable gaps, "
    "WEAK for superficial or mixed fit, POOR for very limited fit, and MISMATCH for clear mismatch."
)

LLM_PROMPT_CANDIDATE_FIT_BRIEF_HEADER = "Candidate fit brief:"
LLM_PROMPT_CAPABILITY_LEVELS_HEADER = "Capability levels:"
LLM_PROMPT_MATCH_PREFERENCES_HEADER = "Match preferences:"
LLM_PROMPT_DEFAULT_FIT_REVIEW_GUIDANCE_HEADER = "Default fit review guidance:"
LLM_PROMPT_CAPABILITY_NAMING_INTRO = (
    "You are reviewing and labelling candidate professional capability clusters extracted from a CV."
)
LLM_PROMPT_DEFAULT_CAPABILITY_NAMING_GUIDANCE_HEADER = "Default capability naming guidance:"
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
LLM_PROMPT_ROLE_TITLE_PATTERN_GUIDANCE = (
    "Learning categories available: capability_concept, cv_farming_pattern.\n"
    "capability_concept: skills, tools, methods, or domain concepts visible in the job ad. "
    "Use only concise terms already present in the ad text.\n"
    "cv_farming_pattern: wording that suggests the employer is collecting CVs rather than advertising a live role."
)
LLM_REJECTION_SUGGESTIONS_JSON_SHAPE = (
    '{"blockers":[{"term":"term"}]}'
)

LLM_SECTION_LABEL_CLASSIFICATION_SHAPE = (
    '{"bucket":"primary|secondary|supplementary","confident":true|false}'
)
