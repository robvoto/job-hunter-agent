"""Shared LLM protocol constants."""

LLM_ALLOWED_DECISIONS = frozenset({"KEEP", "REJECT", "MAYBE"})
LLM_ALLOWED_GRADES = frozenset({"EXCELLENT", "STRONG", "SOLID", "WEAK", "POOR", "MISMATCH"})

LLM_ALLOWED_COVERAGE_IMPORTANCES = frozenset({
    "mandatory", "strongly_preferred", "preferred", "nice_to_have"
})

LLM_FIT_REVIEW_PROMPT_SHAPE = (
    '{"fit_review":{"decision":"KEEP|REJECT|MAYBE","grade":"EXCELLENT|STRONG|SOLID|WEAK|POOR|MISMATCH"},'
    '"job_requirements":["..."],'
    '"requirement_coverage":[{"requirement":"...","importance":"mandatory|strongly_preferred|preferred|nice_to_have",'
    '"status":"supported|partially_supported|not_shown|mismatch",'
    '"capability_name":"...","matched_job_text":"...","profile_support":["..."]}],'
    '"debug_reason":"..."}'
)
LLM_PROMPT_DEBUG_REASON_INTRO = (
    "For debug_reason: one short internal sentence explaining why this grade and decision were chosen, "
    "citing the key requirement coverage finding. For logs and debugging only — not shown to the user."
)
LLM_PROMPT_FIT_REVIEW_ONLY_INTRO = (
    "For fit_review: focus only on candidate fit. Do not suggest learning signals, learning categories, or new taxonomy labels."
)
LLM_LEARNING_ONLY_PROMPT_SHAPE = (
    '{"learning_candidates":[{"signal":"...","suggested_category":"...","suggested_values":["..."],'
    '"context_terms":["..."],"confidence":"high|medium|low|ambiguous","needs_review":true,"original_texts":["..."]}]}'
)

LLM_JOB_REQUIREMENTS_PROMPT_SHAPE = '{"job_requirements":["..."]}'


LLM_PROMPT_CANDIDATE_FIT_BRIEF_HEADER = "AI fit brief:"
LLM_PROMPT_CAPABILITY_LEVELS_HEADER = "Capability matrix:"
LLM_PROMPT_MATCH_PREFERENCES_HEADER = "Match preferences:"
LLM_PROMPT_DEFAULT_FIT_REVIEW_GUIDANCE_HEADER = "Fit review guidance:"
LLM_PROMPT_CAPABILITY_NAMING_INTRO = (
    "You are reviewing and labelling candidate professional capability clusters extracted from a CV."
)
LLM_PROMPT_DEFAULT_CAPABILITY_NAMING_GUIDANCE_HEADER = "Default capability naming guidance:"
LLM_PROMPT_CLUSTERS_HEADER = "Clusters:"
LLM_PROMPT_SYSTEM_REVIEW_INTRO = "You are helping decide whether a candidate should apply for a job."
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

LLM_SECTION_LABEL_CLASSIFICATION_SHAPE = (
    '{"bucket":"primary|secondary|supplementary","confident":true|false}'
)
