"""Shared LLM protocol constants."""

LLM_ALLOWED_DECISIONS = frozenset({"KEEP", "REJECT", "MAYBE"})
LLM_ALLOWED_GRADES = frozenset({"EXCELLENT", "STRONG", "SOLID", "WEAK", "POOR", "MISMATCH"})

LLM_COVERAGE_IMPORTANCE_MANDATORY = "mandatory"
LLM_COVERAGE_IMPORTANCE_STRONGLY_PREFERRED = "strongly_preferred"
LLM_COVERAGE_IMPORTANCE_PREFERRED = "preferred"
LLM_COVERAGE_IMPORTANCE_BONUS = "bonus"
LLM_ALLOWED_COVERAGE_IMPORTANCES = frozenset(
    {
        LLM_COVERAGE_IMPORTANCE_MANDATORY,
        LLM_COVERAGE_IMPORTANCE_STRONGLY_PREFERRED,
        LLM_COVERAGE_IMPORTANCE_PREFERRED,
        LLM_COVERAGE_IMPORTANCE_BONUS,
    }
)

LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES = frozenset({"capability", "eligibility", "qualification"})
LLM_EXPERIENCE_COMPONENT_DURATION = "duration"
LLM_EXPERIENCE_COMPONENT_ROLE_ACTIVITY = "role_or_activity"
LLM_EXPERIENCE_COMPONENT_QUALIFIER = "qualifier"
LLM_ALLOWED_EXPERIENCE_COMPONENT_KINDS = frozenset(
    {
        LLM_EXPERIENCE_COMPONENT_DURATION,
        LLM_EXPERIENCE_COMPONENT_ROLE_ACTIVITY,
        LLM_EXPERIENCE_COMPONENT_QUALIFIER,
    }
)
LLM_ALLOWED_COVERAGE_MATCH_SOURCES = frozenset(
    {"capability_name", "related_skill", "eligibility", "qualification"}
)
LLM_PROFILE_RESOLUTION_EXISTING = "existing"
LLM_PROFILE_RESOLUTION_NEW = "new"
LLM_PROFILE_RESOLUTION_UNRESOLVED = "unresolved"
LLM_ALLOWED_PROFILE_RESOLUTIONS = frozenset(
    {
        LLM_PROFILE_RESOLUTION_EXISTING,
        LLM_PROFILE_RESOLUTION_NEW,
        LLM_PROFILE_RESOLUTION_UNRESOLVED,
    }
)
LLM_INVALID_PROFILE_RESOLUTION = "invalid"
LLM_INVALID_COVERAGE_REQUIREMENT_TYPE = "invalid"
LLM_INVALID_COVERAGE_STATUS = "invalid"
# Deterministic post-LLM validation could not confidently resolve capability vs
# eligibility (e.g. conflicting signals). Deliberately kept outside
# LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES so scoring/gap/gate consumers already
# treat it as unresolved without extra type-specific handling.
LLM_UNCERTAIN_COVERAGE_REQUIREMENT_TYPE = "uncertain"

LLM_ALLOWED_OCCUPATION_ALIGNMENTS = frozenset({"same", "adjacent", "different"})
LLM_INVALID_OCCUPATION_ALIGNMENT = "invalid"

LLM_ALLOWED_POSTING_CHANNEL_KINDS = frozenset({"agency_or_recruiter", "direct_employer", "unknown"})
LLM_INVALID_POSTING_CHANNEL_KIND = "invalid"
LLM_PROMPT_POSTING_CHANNEL_INTRO = (
    "For posting_channel: classify whether this ad was posted by the direct employer or by a "
    "recruitment/staffing agency on behalf of a client, based on the ad's own wording rather than "
    "the poster's company name alone."
)

LLM_FIT_REVIEW_PROMPT_SHAPE = (
    '{"fit_review":{"decision":"KEEP|REJECT|MAYBE","grade":"EXCELLENT|STRONG|SOLID|WEAK|POOR|MISMATCH"},'
    '"occupation_alignment":"same|adjacent|different","occupation_alignment_reason":"...",'
    '"posting_channel":{"kind":"agency_or_recruiter|direct_employer|unknown","confident":true|false,"evidence":"..."},'
    '"eligibility_requirements":[{"requirement":"...","importance":"mandatory|strongly_preferred|preferred|bonus",'
    '"requirement_type":"eligibility","requirement_subtype":"...","canonical_requirement":"...","named_alternatives":["..."],"canonical_fact_resolved":true|false,"classification_reviewable":true|false,"status":"supported|partially_supported|not_shown|mismatch",'
    '"matched_candidate_fact":"...","matched_job_text":"...","profile_support":["..."],"covered_requirement_elements":["..."],"experience_components":[{"kind":"duration|role_or_activity|qualifier","text":"...","profile_supported":true|false,"profile_evidence":["..."],"matched_role_family":"..."}],"role_defining":true|false,"role_defining_group":"..."}],'
    '"requirement_coverage":[{"requirement":"...","importance":"mandatory|strongly_preferred|preferred|bonus",'
    '"requirement_type":"capability|eligibility|qualification","requirement_subtype":"...","canonical_requirement":"...","named_alternatives":["..."],"canonical_fact_resolved":true|false,"classification_reviewable":true|false,"status":"supported|partially_supported|not_shown|mismatch",'
    '"matched_candidate_fact":"...","matched_job_text":"...","profile_support":["..."],"covered_requirement_elements":["..."],"experience_components":[{"kind":"duration|role_or_activity|qualifier","text":"...","profile_supported":true|false,"profile_evidence":["..."],"matched_role_family":"..."}],"role_defining":true|false,"role_defining_group":"..."}],'
    '"debug_reason":"..."}'
)
LLM_FIT_REVIEW_DEBUG_PROMPT_SHAPE = (
    '{"fit_review":{"decision":"KEEP|REJECT|MAYBE","grade":"EXCELLENT|STRONG|SOLID|WEAK|POOR|MISMATCH"},'
    '"occupation_alignment":"same|adjacent|different","occupation_alignment_reason":"...",'
    '"posting_channel":{"kind":"agency_or_recruiter|direct_employer|unknown","confident":true|false,"evidence":"..."},'
    '"eligibility_requirements":[{"requirement":"...","importance":"mandatory|strongly_preferred|preferred|bonus",'
    '"requirement_type":"eligibility","requirement_subtype":"...","canonical_requirement":"...","named_alternatives":["..."],"canonical_fact_resolved":true|false,"classification_reviewable":true|false,"status":"supported|partially_supported|not_shown|mismatch",'
    '"matched_candidate_fact":"...","matched_job_text":"...","profile_support":["..."],"covered_requirement_elements":["..."],"experience_components":[{"kind":"duration|role_or_activity|qualifier","text":"...","profile_supported":true|false,"profile_evidence":["..."],"matched_role_family":"..."}],"role_defining":true|false,"role_defining_group":"..."}],'
    '"requirement_coverage":[{"requirement":"...","importance":"mandatory|strongly_preferred|preferred|bonus",'
    '"requirement_type":"capability|eligibility|qualification","requirement_subtype":"...","canonical_requirement":"...","named_alternatives":["..."],"canonical_fact_resolved":true|false,"classification_reviewable":true|false,"status":"supported|partially_supported|not_shown|mismatch",'
    '"matched_candidate_fact":"...","match_source":"capability_name|related_skill|eligibility|qualification",'
    '"matched_profile_term":"...","matched_job_text":"...","profile_support":["..."],"covered_requirement_elements":["..."],"experience_components":[{"kind":"duration|role_or_activity|qualifier","text":"...","profile_supported":true|false,"profile_evidence":["..."],"matched_role_family":"..."}],"role_defining":true|false,"role_defining_group":"..."}],'
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

LLM_PROMPT_CAPABILITY_LEVELS_HEADER = "Capability matrix:"
LLM_PROMPT_ROLE_EXPERIENCE_HEADER = "Role experience matrix:"
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
