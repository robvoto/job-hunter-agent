"""Shared LLM protocol constants."""

LLM_ALLOWED_DECISIONS = frozenset({"KEEP", "REJECT", "MAYBE"})
LLM_ALLOWED_GRADES = frozenset({"EXCELLENT", "STRONG", "SOLID", "WEAK", "POOR", "MISMATCH"})

LLM_FIT_REVIEW_PROMPT_SHAPE = (
    '{"fit_review":{"decision":"KEEP|REJECT|MAYBE","grade":"EXCELLENT|STRONG|SOLID|WEAK|POOR|MISMATCH"},'
    '"contextual_capability_matches":[{"capability_name":"...","confidence":"high|medium|low","matched_text":"...","reason":"..."}],'
    '"job_requirements":["..."]}'
)
LLM_PROMPT_CONTEXTUAL_CAPABILITY_INTRO = (
    "For contextual_capability_matches: identify profile capabilities evidenced in the ad but not stated verbatim. "
    "Use only capability names from the 'Capability levels' list above. "
    "Set confidence to high (clearly evidenced), medium (plausibly evidenced), or low (weak signal only). "
    "Leave the list empty if nothing is clearly evidenced beyond what is verbatim."
)
LLM_PROMPT_JOB_REQUIREMENTS_INTRO = (
    "For job_requirements: extract the job's explicit requirements as concise bullet-style phrases. "
    "Use only visible ad text, prefer the employer's own wording, keep each item short, and do not invent anything. "
    "Capture the requirements the user would want to read before opening the ad."
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
    "Learning categories available: capability_concept, government_context, government_context_pattern, "
    "role_title_token, role_title_pattern, title_normalization_candidate, cv_farming_pattern.\n"
    "role_title_pattern: use when a job title has a structural shape with an unknown variable part. "
    "Always use [*] as the wildcard placeholder. "
    "For example, a title like 'Head of Operations' suggests the pattern 'Head of [*]' — "
    "not the specific title and not the bare word 'head'. "
    "Do not suggest a role_title_token for the same title if you suggest a role_title_pattern.\n"
    "role_title_token: use only for well-known generic role words (analyst, manager, coordinator). "
    "Never suggest a bare word that only makes sense as part of a phrase.\n"
    "title_normalization_candidate: use for short role-title abbreviations, acronyms, or compressed forms that may "
    "normalize to a standard role title. If context clearly resolves the meaning, include the resolved title in "
    "suggested_values and the resolving words in context_terms. If context does not resolve it, leave suggested_values "
    "empty and keep needs_review=true. "
    "For example, PM may resolve to project manager when the text mentions delivery, implementation, project, "
    "program, portfolio, roadmap, or go-to-market. Do not invent a mapping without context.\n"
    "government_context_pattern: use when a government/clearance term has a structural shape with an unknown variable part. "
    "Always use [*] as the wildcard placeholder. "
    "For example, 'Baseline Clearance' suggests 'Baseline [*] clearance' and 'NV1' suggests 'NV[*] clearance' — "
    "not the bare abbreviation alone. "
    "Do not suggest a government_context token for the same term if you suggest a government_context_pattern."
)
LLM_REJECTION_SUGGESTIONS_JSON_SHAPE = (
    '{"blockers":[{"term":"term"}]}'
)

LLM_SECTION_LABEL_CLASSIFICATION_SHAPE = (
    '{"bucket":"primary|secondary|supplementary","confident":true|false}'
)
