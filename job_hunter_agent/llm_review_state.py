"""Helpers for validating LLM review completeness on kept jobs."""

from __future__ import annotations

from job_hunter_agent.record_schema import (
    RECORD_LLM_DECISION_KEY,
    RECORD_LLM_FIT_GRADE_KEY,
    RECORD_REQUIREMENT_COVERAGE_KEY,
)


def has_complete_llm_keep_data(record: dict) -> bool:
    """Return True only when a kept job has complete LLM-backed fit data.

    Normal workspace matches must have:
    - llm_decision in {KEEP, MAYBE} (both are surfaced to the user as a keep,
      with `llm_fit_grade` carrying the actual confidence signal)
    - llm_fit_grade present
    - requirement_coverage present and non-empty
    """
    llm_decision = str(record.get(RECORD_LLM_DECISION_KEY) or "").strip().upper()
    llm_fit_grade = str(record.get(RECORD_LLM_FIT_GRADE_KEY) or "").strip().upper()
    requirement_coverage = record.get(RECORD_REQUIREMENT_COVERAGE_KEY)

    return (
        llm_decision in {"KEEP", "MAYBE"}
        and bool(llm_fit_grade)
        and isinstance(requirement_coverage, list)
        and len(requirement_coverage) > 0
    )
