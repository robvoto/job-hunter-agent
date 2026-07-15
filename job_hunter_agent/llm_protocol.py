"""Shared LLM protocol constants."""

LLM_ALLOWED_DECISIONS = frozenset({"KEEP", "REJECT", "MAYBE"})
LLM_ALLOWED_GRADES = frozenset({"EXCELLENT", "STRONG", "SOLID", "WEAK", "POOR", "MISMATCH"})

LLM_ALLOWED_COVERAGE_IMPORTANCES = frozenset(
    {"mandatory", "strongly_preferred", "preferred", "nice_to_have"}
)

LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES = frozenset({"capability", "eligibility"})
LLM_ALLOWED_COVERAGE_MATCH_SOURCES = frozenset(
    {"capability_name", "related_skill", "profile_brief", "eligibility"}
)
LLM_INVALID_COVERAGE_REQUIREMENT_TYPE = "invalid"
LLM_INVALID_COVERAGE_STATUS = "invalid"

LLM_ALLOWED_OCCUPATION_ALIGNMENTS = frozenset({"same", "adjacent", "different"})
LLM_INVALID_OCCUPATION_ALIGNMENT = "invalid"

LLM_FIT_REVIEW_PROMPT_SHAPE = (
    '{"fit_review":{"decision":"KEEP|REJECT|MAYBE","grade":"EXCELLENT|STRONG|SOLID|WEAK|POOR|MISMATCH"},'
    '"occupation_alignment":"same|adjacent|different","occupation_alignment_reason":"...",'
    '"job_requirements":["..."],'
    '"requirement_coverage":[{"requirement":"...","importance":"mandatory|strongly_preferred|preferred|nice_to_have",'
    '"requirement_type":"capability|eligibility","status":"supported|partially_supported|not_shown|mismatch",'
    '"profile_name":"...","matched_job_text":"...","profile_support":["..."]}],'
    '"debug_reason":"..."}'
)
LLM_FIT_REVIEW_DEBUG_PROMPT_SHAPE = (
    '{"fit_review":{"decision":"KEEP|REJECT|MAYBE","grade":"EXCELLENT|STRONG|SOLID|WEAK|POOR|MISMATCH"},'
    '"occupation_alignment":"same|adjacent|different","occupation_alignment_reason":"...",'
    '"job_requirements":["..."],'
    '"requirement_coverage":[{"requirement":"...","importance":"mandatory|strongly_preferred|preferred|nice_to_have",'
    '"requirement_type":"capability|eligibility","status":"supported|partially_supported|not_shown|mismatch",'
    '"profile_name":"...","match_source":"capability_name|related_skill|profile_brief|eligibility",'
    '"matched_profile_term":"...","matched_job_text":"...","profile_support":["..."]}],'
    '"debug_reason":"..."}'
)
LLM_PROMPT_DEBUG_REASON_INTRO = (
    "For debug_reason: one short internal sentence explaining why this grade and decision were chosen, "
    "citing the key requirement coverage finding. For logs and debugging only — not shown to the user."
)
LLM_PROMPT_OCCUPATION_ALIGNMENT_INTRO = (
    "For occupation_alignment: classify the job as same, adjacent, or different relative to the "
    "candidate's target roles, using only the job title and dominant duties. "
    "occupation_alignment_reason is one short sentence explaining the call."
)
LLM_PROMPT_FIT_REVIEW_ONLY_INTRO = "For fit_review: focus only on candidate fit. Do not suggest learning signals, learning categories, or new taxonomy labels."
LLM_LEARNING_ONLY_PROMPT_SHAPE = (
    '{"learning_candidates":[{"signal":"...","suggested_category":"...","suggested_values":["..."],'
    '"context_terms":["..."],"confidence":"high|medium|low|ambiguous","needs_review":true,"original_texts":["..."]}]}'
)

LLM_JOB_REQUIREMENTS_PROMPT_SHAPE = '{"job_requirements":["..."]}'


LLM_PROMPT_CANDIDATE_FIT_BRIEF_HEADER = "AI fit brief:"
LLM_PROMPT_CAPABILITY_LEVELS_HEADER = "Capability matrix:"
LLM_PROMPT_ELIGIBILITY_HEADER = "Eligibility matrix:"
LLM_PROMPT_MATCH_PREFERENCES_HEADER = "Match preferences:"
LLM_PROMPT_TARGET_ROLES_HEADER = "Candidate target roles:"
LLM_PROMPT_DEFAULT_FIT_REVIEW_GUIDANCE_HEADER = "Fit review guidance:"
LLM_PROMPT_CAPABILITY_NAMING_INTRO = "You are reviewing and labelling candidate professional capability clusters extracted from a CV."
LLM_PROMPT_DEFAULT_CAPABILITY_NAMING_GUIDANCE_HEADER = "Default capability naming guidance:"
LLM_PROMPT_CLUSTERS_HEADER = "Clusters:"
LLM_PROMPT_SYSTEM_REVIEW_INTRO = (
    "You are helping decide whether a candidate should apply for a job."
)
LLM_PROMPT_JSON_ONLY = "Return JSON only."
LLM_PROMPT_JOB_DESCRIPTION_PREFIX = "Job description:\n"
LLM_PROMPT_NO_FIT_DECISION_REQUIRED = "No fit decision is required."
LLM_PROMPT_DO_NOT_SAVE = "Do not save anything."
LLM_PROMPT_DO_NOT_INVENT = "Do not invent new categories."
LLM_PROMPT_USE_VISIBLE_STRINGS = "Use only concise candidate strings already visible in the ad."
LLM_PROMPT_LEARNING_PENDING_ONLY = "Learning candidates must be pending review only."
LLM_REJECTION_SUGGESTIONS_JSON_SHAPE = '{"blockers":[{"term":"term"}]}'

LLM_SECTION_LABEL_CLASSIFICATION_SHAPE = (
    '{"bucket":"primary|secondary|supplementary","confident":true|false}'
)

LLM_ALLOWED_TITLE_JUDGMENT_VERDICTS = frozenset({"match", "no_match", "uncertain"})
LLM_TITLE_JUDGMENT_SHAPE = '{"verdict":"match|no_match|uncertain","reason":"..."}'
