"""Shared job/record field names."""

RECORD_TITLE_KEY = "title"
RECORD_COMPANY_KEY = "company"
RECORD_URL_KEY = "url"
RECORD_RUN_STARTED_AT_KEY = "run_started_at"
RECORD_FULL_DESCRIPTION_KEY = "full_description"
RECORD_DESCRIPTION_SOURCE_KEY = "description_source"
RECORD_FIT_SOURCE_TEXT_KEY = "fit_source_text"
RECORD_FIT_SCORE_KEY = "fit_score"
RECORD_FIT_SCORE_BREAKDOWN_KEY = "fit_score_breakdown"
RECORD_FIT_LABEL_KEY = "fit_label"
RECORD_FIT_TONE_CLASS_KEY = "fit_tone_class"
RECORD_DETAILS_STATUS_KEY = "details_status"
RECORD_FIT_CONFIDENCE_KEY = "fit_confidence"
RECORD_SEARCH_LOCATION_KEY = "search_location"
RECORD_SEARCH_KEYWORDS_KEY = "search_keywords"
RECORD_SEARCH_CLASSIFICATIONS_KEY = "search_classifications"
RECORD_PAGE_KEY = "page"
RECORD_SOURCE_NAME_KEY = "source_name"
RECORD_SOURCE_KEY = "source"
RECORD_SOURCE_METADATA_KEY = "source_metadata"
RECORD_MARKET_MAP_JOB_ID_KEY = "market_map_job_id"
RECORD_MARKET_MAP_IDENTITY_KEY = "market_map_identity_key"
RECORD_MARKET_MAP_JD_FETCHED_AT_KEY = "market_map_jd_fetched_at"
RECORD_MARKET_MAP_JD_SOURCE_KEY = "market_map_jd_source"
SOURCE_METADATA_VERSION_KEY = "schema_version"
SOURCE_METADATA_SCHEMA_VERSION = 1
SOURCE_POSTER_COMPANY_INDUSTRY_KEY = "poster_company_industry"
RECORD_SOURCE_PLATFORM_JOB_ID_KEY = "platform_job_id"
RECORD_SOURCE_ATS_REQUISITION_ID_KEY = "ats_requisition_id"
RECORD_SOURCE_ATS_SOURCE_KEY = "ats_source"
RECORD_SOURCE_APPLY_URL_KEY = "apply_url"
RECORD_SOURCE_CANONICAL_URL_KEY = "canonical_url"
RECORD_SOURCE_ADVERTISER_ID_KEY = "advertiser_id"
RECORD_JOB_KEY = "job_key"
RECORD_LOCATION_KEY = "location"
RECORD_POSTED_KEY = "posted"
RECORD_POSTED_AGE_DAYS_KEY = "posted_age_days"
RECORD_ORIGINAL_POSTED_DATE_KEY = "original_posted_date"
RECORD_ORIGINAL_POSTED_AGE_DAYS_KEY = "original_posted_age_days"
RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY = "original_posted_date_status"
RECORD_IS_REPOSTED_KEY = "is_reposted"
RECORD_WORK_MODE_KEY = "work_mode"
RECORD_WORK_MODE_SOURCE_KEY = "work_mode_source"
RECORD_WORK_MODE_EVIDENCE_KEY = "work_mode_evidence"
RECORD_WORK_MODE_NEEDS_REVIEW_KEY = "work_mode_needs_review"
RECORD_WORK_TYPE_KEY = "work_type"
RECORD_SECTOR_KEY = "sector"
RECORD_SALARY_KEY = "salary"
RECORD_CARD_SALARY_KEY = "card_salary"
RECORD_TEASER_KEY = "teaser"
RECORD_DETAILS_TEXT_KEY = "details_text"
RECORD_DETAILS_LENGTH_KEY = "details_length"
RECORD_DECISION_KEY = "decision"
RECORD_REJECT_REASON_KEY = "reject_reason"
RECORD_RETRYABLE_KEY = "retryable"
RECORD_RETRY_REASON_KEY = "retry_reason"
REJECT_REASON_ALREADY_APPLIED_REPOST = "ALREADY_APPLIED_REPOST"
REJECT_REASON_MANUALLY_HIDDEN_REPOST = "MANUALLY_HIDDEN_REPOST"
REJECT_REASON_JMM_JD_ENRICHMENT_FAILED = "JMM_JD_ENRICHMENT_FAILED"
REJECT_REASON_JMM_JD_UNAVAILABLE = "JMM_JD_UNAVAILABLE"
RECORD_DECISION_EXPLANATION_KEY = "decision_explanation"
RECORD_TITLE_REASON_KEY = "title_reason"
RECORD_TITLE_MATCH_METADATA_KEY = "title_match_metadata"
RECORD_ONET_CLASSIFICATION_KEY = "onet_classification"
RECORD_LLM_TITLE_JUDGMENT_KEY = "llm_title_judgment"
RECORD_CONTENT_REASON_KEY = "content_reason"
RECORD_LLM_DECISION_KEY = "llm_decision"
RECORD_REVIEW_SOURCE_KEY = "review_source"
RECORD_LLM_FIT_GRADE_KEY = "llm_fit_grade"
RECORD_LLM_DEBUG_REASON_KEY = "llm_debug_reason"
RECORD_LLM_ELAPSED_MS_KEY = "llm_elapsed_ms"
RECORD_LLM_COST_USD_KEY = "llm_cost_usd"
RECORD_LLM_INPUT_TOKENS_KEY = "llm_input_tokens"
RECORD_LLM_OUTPUT_TOKENS_KEY = "llm_output_tokens"
RECORD_ROLE_SNAPSHOT_KEY = "role_snapshot"
RECORD_FIT_HIGHLIGHTS_KEY = "fit_highlights"
RECORD_COMPETITIVE_SIGNALS_KEY = "competitive_signals"
RECORD_SOFT_RISK_REASONS_KEY = "soft_risk_reasons"
RECORD_MISSING_PROFILE_SUPPORT_KEY = "missing_profile_support"
RECORD_MISSING_CLEARANCE_SUPPORT_KEY = "missing_clearance_support"
RECORD_REVIEWED_SIGNAL_MATCHES_KEY = "reviewed_signal_matches"
RECORD_POSTING_CHANNEL_EVIDENCE_KEY = "posting_channel_evidence"
POSTING_CHANNEL_VERSION_KEY = "classifier_version"
# Bump whenever posting-channel metadata precedence, managed LLM contract, or
# unresolved-classification fallback behaviour changes. History reuse and the
# relevant LLM cache namespaces depend on this value.
POSTING_CHANNEL_CLASSIFIER_VERSION = 4
RECORD_JOB_QUALITY_SIGNALS_KEY = "job_quality_signals"
RECORD_REQUIREMENT_COVERAGE_KEY = "requirement_coverage"
RECORD_IGNORED_REQUIREMENT_SUGGESTIONS_KEY = "ignored_requirement_suggestions"
# Optional non_capability requirement rows: retained for analysis/debugging but
# excluded from grade, gate, scoring, and the normal job card.
RECORD_REQUIREMENT_COVERAGE_HIDDEN_KEY = "requirement_coverage_hidden"
# JH-298 behavioural-expectation rows (generic personal-conduct / disposition
# wording). Frozen alongside requirement_coverage so the card can render them as
# read-only employer context, but structurally excluded from grade, gate,
# scoring, profile gaps, custom blockers, and pending-signal learning. Owned by
# the fit-review LLM contract (llm_gate.partition_behavioural_requirement_coverage).
RECORD_REQUIREMENT_COVERAGE_BEHAVIOURAL_KEY = "requirement_coverage_behavioural"
# JH-298 correction: capability rows the fit-review LLM left without a valid
# requirement_kind. They fail closed to `unclassified` and are frozen here,
# structurally excluded from grade, gate, scoring, profile gaps, custom blockers,
# and pending-signal learning — until a fresh review classifies them. Owned by
# the fit-review LLM contract (llm_gate.partition_unclassified_requirement_coverage).
RECORD_REQUIREMENT_COVERAGE_UNCLASSIFIED_KEY = "requirement_coverage_unclassified"
RECORD_REQUIREMENT_COVERAGE_VERSION_KEY = "requirement_coverage_contract_version"
# Bump when requirement-coverage semantics change in a way that makes persisted
# coverage unsafe to reuse without a fresh LLM fit review.
# v3: canonical decomposition block (operator + elements[] + capability_judgement)
# replaces named_alternatives / canonical_fact_resolved / classification_reviewable.
# v4 (JH-298): capability rows carry a requirement_kind axis; behavioural rows are
# partitioned into requirement_coverage_behavioural. Old cached coverage without
# the split is unsafe to reuse and is re-reviewed (never guessed).
# v5 (JH-298 correction): a missing / invalid requirement_kind on a capability row
# fails closed to `unclassified` (non-scoring) instead of defaulting to
# professional_capability, and is partitioned into
# requirement_coverage_unclassified. v4 coverage may hold rows scored under the
# old default, so it is re-reviewed, not migrated.
# v6 (JH-299): positive coverage now requires traceable same-concept evidence and
# non-positive rows carry no matched fact / profile_support. v5 coverage can hold
# over-stated matches, so it is re-reviewed, not migrated.
# v7 (JH-298/JH-299 corrections): a capability row scores only when it is
# explicitly professional_capability (missing/empty/invalid now fail closed too),
# and same-concept evidence no longer accepts a single shared modifier token. v6
# coverage can hold rows scored under both looser rules, so it is re-reviewed.
# v8 (JH-300): OR-branch profile actions are restricted to explicitly named,
# professional capability atoms and all other branches remain non-actionable.
# v7 coverage can therefore expose unsafe branch actions and is re-reviewed.
REQUIREMENT_COVERAGE_CONTRACT_VERSION = 8
RECORD_OCCUPATION_ALIGNMENT_KEY = "occupation_alignment"
RECORD_OCCUPATION_ALIGNMENT_REASON_KEY = "occupation_alignment_reason"
RECORD_DESCRIPTION_COMPACTION_KEY = "description_compaction"
RECORD_APPLY_METHOD_KEY = "apply_method"

APPLY_METHOD_EASY_APPLY = "easy_apply"
APPLY_METHOD_QUICK_APPLY = "quick_apply"
APPLY_METHOD_EXTERNAL_APPLY = "external_apply"
APPLY_METHOD_UNKNOWN = "unknown"

RECORD_LAST_KEPT_SNAPSHOT_KEY = "last_kept_snapshot"
REVIEW_SNAPSHOT_REQUIRED_FIELDS = (
    RECORD_JOB_KEY,
    RECORD_TITLE_KEY,
    RECORD_COMPANY_KEY,
    RECORD_URL_KEY,
    RECORD_SOURCE_KEY,
)
RECORD_TIMES_KEPT_KEY = "times_kept"
RECORD_FIRST_KEPT_AT_KEY = "first_kept_at"
RECORD_LAST_KEPT_AT_KEY = "last_kept_at"
RECORD_TIMES_SEEN_KEY = "times_seen"
RECORD_FIRST_SEEN_AT_KEY = "first_seen_at"
RECORD_LAST_SEEN_AT_KEY = "last_seen_at"
RECORD_TIMES_VIEWED_KEY = "times_viewed"
RECORD_FIRST_VIEWED_AT_KEY = "first_viewed_at"
RECORD_LAST_VIEWED_AT_KEY = "last_viewed_at"
RECORD_SEEN_BEFORE_KEY = "seen_before"
RECORD_REUSED_HISTORY_KEY = "reused_history"
RECORD_DUPLICATE_LINKS_KEY = "duplicate_links"
RECORD_POTENTIAL_DUPLICATE_LINKS_KEY = "potential_duplicate_links"
RECORD_SOURCE_PROVENANCE_KEY = "source_provenance"
RECORD_HARD_BLOCK_REASONS_KEY = "hard_block_reasons"
RECORD_REVIEW_EVENTS_KEY = "review_events"
RECORD_IS_HIDDEN_KEY = "is_hidden"
RECORD_FIRST_HIDDEN_AT_KEY = "first_hidden_at"
RECORD_LAST_HIDDEN_AT_KEY = "last_hidden_at"
RECORD_LAST_UNHIDDEN_AT_KEY = "last_unhidden_at"
RECORD_FIRST_APPLIED_AT_KEY = "first_applied_at"
RECORD_LAST_APPLIED_AT_KEY = "last_applied_at"
RECORD_LAST_UNAPPLIED_AT_KEY = "last_unapplied_at"
RECORD_IS_LIKED_KEY = "is_liked"
RECORD_FIRST_LIKED_AT_KEY = "first_liked_at"
RECORD_LAST_LIKED_AT_KEY = "last_liked_at"
RECORD_LAST_UNLIKED_AT_KEY = "last_unliked_at"
# First-party outcome tracking: the candidate clicked "Rejected" or "No answer"
# on this job themselves, inside JobHunter. This is the real signal the
# rejection-sheet email import was always meant to be replaced by.
RECORD_FIRST_REJECTED_AT_KEY = "first_rejected_at"
RECORD_LAST_REJECTED_AT_KEY = "last_rejected_at"
RECORD_LAST_UNREJECTED_AT_KEY = "last_unrejected_at"
RECORD_FIRST_NO_RESPONSE_AT_KEY = "first_no_response_at"
RECORD_LAST_NO_RESPONSE_AT_KEY = "last_no_response_at"
RECORD_LAST_UN_NO_RESPONSE_AT_KEY = "last_un_no_response_at"
RECORD_LAST_NOT_FOR_ME_AT_KEY = "last_not_for_me_at"
RECORD_TIMES_NOT_FOR_ME_KEY = "times_not_for_me"
RECORD_LAST_BLOCK_TITLE_AT_KEY = "last_block_title_at"
RECORD_TIMES_BLOCK_TITLE_KEY = "times_block_title"
RECORD_REJECT_TITLE_RULES_KEY = "reject_title_rules"
RECORD_REJECT_DESCRIPTION_PHRASE_RULES_KEY = "reject_description_phrase_rules"

RECORD_REQUIRED_PROFILE_GAPS_KEY = "required_profile_gaps"

DETAILS_STATUS_OK = "ok"
CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_LOW = "LOW"
REASON_OK = "OK"
ORIGINAL_POSTED_DATE_STATUS_VERIFIED = "verified"
ORIGINAL_POSTED_DATE_STATUS_UNVERIFIED = "unverified"

# Resolved employer outcome history attached per record. Always one of the
# states owned by employer_outcome_display, never absent-by-accident.
RECORD_EMPLOYER_OUTCOME_KEY = "employer_outcome"


def validate_review_snapshot(snapshot: object, expected_job_key: str) -> dict:
    """Validate the current job snapshot required by Applied/Hidden state."""

    if not isinstance(snapshot, dict):
        raise ValueError(f"Job history entry is missing {RECORD_LAST_KEPT_SNAPSHOT_KEY}")
    for field in REVIEW_SNAPSHOT_REQUIRED_FIELDS:
        if not str(snapshot.get(field) or "").strip():
            raise ValueError(f"Job history snapshot is missing required field: {field}")
    if str(snapshot[RECORD_JOB_KEY]).strip().lower() != str(expected_job_key).strip().lower():
        raise ValueError("Job history snapshot job_key does not match review state")
    return snapshot
