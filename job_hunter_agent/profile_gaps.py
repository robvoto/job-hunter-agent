"""Profile gap detection for capability-like requirement coverage only.

The workspace confirmation flow should only surface uncertain capability
requirements from requirement_coverage. Raw job_requirements remain available
for display/debug, but they must not drive confirmation or profile writes.
"""

from __future__ import annotations

import re

from job_hunter_agent.llm_protocol import LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES

STATUS_UNKNOWN = "unknown"
STATUS_CONFIRMED_HAVE = "confirmed_have"
STATUS_CONFIRMED_DO_NOT_HAVE = "confirmed_do_not_have"
_CONFIRMABLE_REQUIREMENT_STATUSES = frozenset({"not_shown", "partially_supported"})
PROFILE_GAP_JOB_REQUIREMENT_TEXT_KEY = "job_requirement_text"
_ELIGIBILITY_TRUE_KEYS = frozenset({"true", "yes", "y", "1", "have", "has", "held", "present"})
_ELIGIBILITY_FALSE_KEYS = frozenset({"false", "no", "n", "0", "absent", "missing", "none", "not"})


def _normalize_for_match(text: str) -> str:
    """Lowercase, strip punctuation, compact whitespace for fuzzy matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", "", text.lower())).strip()


def _requirement_matches_capability(requirement_norm: str, capability: dict) -> bool:
    """Return True if the normalized requirement overlaps a capability name or alias."""
    names = [str(capability.get("name") or "")]
    names += [str(a) for a in (capability.get("aliases") or [])]
    for name in names:
        cap_norm = _normalize_for_match(name)
        if cap_norm and (cap_norm in requirement_norm or requirement_norm in cap_norm):
            return True
    return False


def _requirement_in_must_not_require(requirement_norm: str, must_not_require: list[str]) -> bool:
    """Return True if the normalized requirement overlaps any must_not_require_skills entry."""
    for term in must_not_require:
        term_norm = _normalize_for_match(str(term))
        if term_norm and (term_norm in requirement_norm or requirement_norm in term_norm):
            return True
    return False


def _requirement_matches_eligibility(
    requirement_norm: str, candidate_eligibility: list[dict]
) -> str:
    """Return the normalized eligibility state for a requirement, if present."""
    for item in candidate_eligibility:
        if not isinstance(item, dict):
            continue
        name_norm = _normalize_for_match(str(item.get("name") or ""))
        if not name_norm or not (name_norm in requirement_norm or requirement_norm in name_norm):
            continue
        raw_value = item.get("value", True)
        if isinstance(raw_value, str):
            lowered = raw_value.strip().lower()
            if lowered in _ELIGIBILITY_FALSE_KEYS:
                return STATUS_CONFIRMED_DO_NOT_HAVE
            if lowered in _ELIGIBILITY_TRUE_KEYS:
                return STATUS_CONFIRMED_HAVE
        if bool(raw_value):
            return STATUS_CONFIRMED_HAVE
        return STATUS_CONFIRMED_DO_NOT_HAVE
    return STATUS_UNKNOWN


def _requirement_matches_qualification(
    requirement_norm: str, candidate_qualifications: list[dict]
) -> str:
    return _requirement_matches_eligibility(requirement_norm, candidate_qualifications)


def classify_requirement_status(
    requirement: str,
    candidate_capabilities: list[dict],
    must_not_require_skills: list[str],
    candidate_eligibility: list[dict] | None = None,
    candidate_eligibility_facts: list[dict] | None = None,
    candidate_qualifications: list[dict] | None = None,
    requirement_type: str = "capability",
) -> str:
    """
    Classify a single job requirement against the candidate profile.

    Checks must_not_require_skills first (stronger signal), then candidate_capabilities.
    Returns one of STATUS_UNKNOWN, STATUS_CONFIRMED_HAVE, STATUS_CONFIRMED_DO_NOT_HAVE.
    """
    req_norm = _normalize_for_match(requirement)
    if not req_norm:
        return STATUS_UNKNOWN
    normalized_requirement_type = str(requirement_type or "").strip().lower()
    if normalized_requirement_type not in LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES:
        return STATUS_UNKNOWN
    if normalized_requirement_type == "eligibility":
        return _requirement_matches_eligibility(
            req_norm,
            [*(candidate_eligibility or []), *(candidate_eligibility_facts or [])],
        )
    if normalized_requirement_type == "qualification":
        return _requirement_matches_qualification(req_norm, candidate_qualifications or [])
    if _requirement_in_must_not_require(req_norm, must_not_require_skills):
        return STATUS_CONFIRMED_DO_NOT_HAVE
    if any(_requirement_matches_capability(req_norm, cap) for cap in candidate_capabilities):
        return STATUS_CONFIRMED_HAVE
    return STATUS_UNKNOWN


def compute_profile_gaps(
    requirement_coverage: list[dict],
    candidate_capabilities: list[dict],
    must_not_require_skills: list[str],
    candidate_eligibility: list[dict] | None = None,
    candidate_eligibility_facts: list[dict] | None = None,
    candidate_qualifications: list[dict] | None = None,
) -> list[dict]:
    """
    Return capability-like requirement_coverage items that still need confirmation.

    Each returned gap keeps the canonical capability name plus supporting display
    text from the job ad so the workspace can explain why the item is uncertain.
    """
    gaps = []
    for item in requirement_coverage:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        if status not in _CONFIRMABLE_REQUIREMENT_STATUSES:
            continue
        if item.get("profile_action_allowed") is not True:
            continue
        capability_name = str(
            item.get("capability_name")
            or item.get("qualification_name")
            or item.get("eligibility_name")
            or ""
        ).strip()
        requirement_type = str(item.get("requirement_type") or "capability").strip().lower()
        if requirement_type not in LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES:
            continue
        matched_candidate_fact = str(
            item.get("matched_candidate_fact") or item.get("profile_name") or capability_name or ""
        ).strip()
        if not capability_name:
            capability_name = matched_candidate_fact
        if not capability_name:
            continue
        if (
            classify_requirement_status(
                capability_name,
                candidate_capabilities,
                must_not_require_skills,
                candidate_eligibility,
                candidate_eligibility_facts,
                requirement_type=requirement_type,
                candidate_qualifications=candidate_qualifications,
            )
            != STATUS_UNKNOWN
        ):
            continue
        raw_requirement = str(item.get("requirement") or "").strip()
        matched_job_text = str(item.get("matched_job_text") or "").strip()
        gaps.append(
            {
                "capability_name": capability_name,
                "qualification_name": (
                    capability_name if requirement_type == "qualification" else ""
                ),
                "matched_candidate_fact": matched_candidate_fact,
                "requirement_type": requirement_type,
                "raw_requirement": raw_requirement,
                "matched_job_text": matched_job_text,
                "status": status,
                PROFILE_GAP_JOB_REQUIREMENT_TEXT_KEY: matched_job_text or raw_requirement,
            }
        )
    return gaps
