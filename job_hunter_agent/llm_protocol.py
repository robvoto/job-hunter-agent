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
LLM_PROMPT_REQUIREMENT_COVERAGE_INTRO = (
    "For requirement_coverage: semantically decompose the job ad into atomic requirements — one skill, qualification, "
    "experience, or constraint per item. Do not put a whole sentence as a single item; split compound sentences into their atomic parts. "
    "For each atomic requirement: assign importance (mandatory = hard requirement explicitly stated, "
    "strongly_preferred = clearly expected but not explicitly blocking, preferred = desirable, nice_to_have = optional or bonus), "
    "then classify status against the candidate profile. "
    "Store the original job-ad sentence in matched_job_text for traceability — do not match the whole sentence directly to a capability. "
    "Link supported and partially_supported items to the exact profile capability name. "
    "Leave capability_name empty only for not_shown or mismatch items."
)
LLM_PROMPT_JOB_REQUIREMENTS_INTRO = (
    "For job_requirements: extract the job's explicit requirements as concise bullet-style phrases. "
    "Use only visible ad text, prefer the employer's own wording, keep each item short, and do not invent anything. "
    "Capture the requirements the user would want to read before opening the ad. "
    "If the ad states the work type explicitly, preserve it as one of: Permanent, Contract, Full Time Contract / FTC, Temporary. "
    "Use Unknown when the work type is unclear."
)
LLM_LEARNING_ONLY_PROMPT_SHAPE = (
    '{"learning_candidates":[{"signal":"...","suggested_category":"...","suggested_values":["..."],'
    '"context_terms":["..."],"confidence":"high|medium|low|ambiguous","needs_review":true,"original_texts":["..."]}]}'
)

LLM_JOB_REQUIREMENTS_PROMPT_SHAPE = '{"job_requirements":["..."]}'


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
LLM_PROMPT_FIT_REVIEW_GRADE_INTRO = (
    "Set fit_review.grade as a rough signal — the system re-derives the final grade from requirement_coverage. "
    "Prioritise accurate requirement_coverage over a precise grade. "
    "Use MISMATCH only when the candidate clearly cannot meet a mandatory requirement."
)
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
