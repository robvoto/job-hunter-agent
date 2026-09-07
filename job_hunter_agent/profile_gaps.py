"""Profile gap detection for capability-like requirement coverage only.

The workspace confirmation flow only surfaces uncertain capability
requirements from requirement_coverage, which is the canonical reviewed source.
"""

from __future__ import annotations

import re

from job_hunter_agent.llm_protocol import (
    LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES,
    LLM_COVERAGE_IMPORTANCE_MANDATORY,
)

STATUS_UNKNOWN = "unknown"
CUSTOM_BLOCKER_REASON_RESOLVED = "resolved"
CUSTOM_BLOCKER_REASON_NO_MATCH = "no_match"
CUSTOM_BLOCKER_REASON_AMBIGUOUS = "ambiguous"
CUSTOM_BLOCKER_REASON_NOT_REQUIRED = "not_required"
CUSTOM_BLOCKER_REASON_INVALID_INPUT = "invalid_input"
STATUS_CONFIRMED_HAVE = "confirmed_have"
STATUS_CONFIRMED_DO_NOT_HAVE = "confirmed_do_not_have"
# Coverage statuses whose row may offer a profile-confirm action (Add capability /
# "I don't have this"). This is the single owner of that policy: routes/review.py
# imports it for the /api/profile-gap gate, and workspace_renderer.py mirrors it in
# css-modifier space (partially_supported -> "partially-supported",
# not_shown + mandatory -> "mandatory-not-shown", not_shown -> "not-shown").
# partially_supported is included so an unconfirmed partial row is not a dead end:
# the row stays a Partial match, but the exact requested canonical_requirement can
# still be added when it is not already a confirmed profile fact.
CONFIRMABLE_REQUIREMENT_STATUSES = frozenset(
    {"not_shown", "mismatch", "invalid", "partially_supported"}
)
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
        # JH-298: behavioural-expectation rows are held in
        # requirement_coverage_behavioural and never passed in here, so they can
        # never become a gap. Their forced "not_assessed" status is also outside
        # CONFIRMABLE_REQUIREMENT_STATUSES as a second line of defence.
        status = str(item.get("status") or "").strip().lower()
        if status not in CONFIRMABLE_REQUIREMENT_STATUSES:
            continue
        # OR requirements (decomposition.operator == "or") carry no row-level
        # canonical_requirement and profile_action_allowed is False, so they are
        # skipped here: a single OR branch must never be surfaced as a gap (or
        # resolved via resolve_custom_blocker) as though that branch alone were
        # the whole requirement. See docs/REQUIREMENT_DECOMPOSITION_RATIONALE.md.
        if item.get("profile_action_allowed") is not True:
            continue
        capability_name = str(
            item.get("canonical_requirement")
            or item.get("capability_name")
            or item.get("qualification_name")
            or item.get("eligibility_name")
            or ""
        ).strip()
        requirement_type = str(item.get("requirement_type") or "capability").strip().lower()
        if requirement_type not in LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES:
            continue
        matched_candidate_fact = str(item.get("matched_candidate_fact") or "").strip()
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


def resolve_custom_blocker(raw_text: str, requirement_coverage: list[dict]) -> dict:
    """Resolve free-text "Not For Me" blocker input against a job's requirement_coverage.

    Custom blocker text must never be saved to must_not_require_skills as-is
    (see job-filtering non-negotiables). This ties it to a structured, already
    LLM-vetted requirement for the same job instead: only an exact match
    (case/whitespace-insensitive) against a requirement_coverage item's
    canonical_requirement/matched_job_text/requirement, where that item is
    profile_action_allowed (canonical_requirement is a genuine single concept,
    not just a display label) and importance == mandatory, resolves. No
    substring/fuzzy matching, so a broad or generic term cannot silently match
    a specific requirement.

    OR requirements (decomposition.operator == "or") have no row-level
    canonical_requirement and profile_action_allowed is False, so they never
    resolve here: a single OR branch must never be persisted to
    must_not_require_skills as though that branch alone were the whole mandatory
    requirement. See docs/REQUIREMENT_DECOMPOSITION_RATIONALE.md.
    """
    query_norm = _normalize_for_match(raw_text)
    result = {
        "ok": False,
        "reason_code": CUSTOM_BLOCKER_REASON_INVALID_INPUT,
        "raw_input": str(raw_text or "").strip(),
        "canonical_requirement": "",
        "requirement_type": "",
        "importance": "",
        "matched_job_text": "",
    }
    if len(query_norm) < 2:
        return result

    required_matches: dict[str, dict] = {}
    non_required_match: dict | None = None
    for item in requirement_coverage:
        if not isinstance(item, dict):
            continue
        requirement_type = str(item.get("requirement_type") or "").strip().lower()
        if requirement_type not in LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES:
            continue
        if item.get("profile_action_allowed") is not True:
            continue
        canonical_requirement = str(item.get("canonical_requirement") or "").strip()
        if not canonical_requirement:
            continue
        candidates_norm = {
            _normalize_for_match(canonical_requirement),
            _normalize_for_match(str(item.get("matched_job_text") or "")),
            _normalize_for_match(str(item.get("requirement") or "")),
        }
        candidates_norm.discard("")
        if query_norm not in candidates_norm:
            continue
        importance = str(item.get("importance") or "").strip().lower()
        canonical_key = _normalize_for_match(canonical_requirement)
        if importance == LLM_COVERAGE_IMPORTANCE_MANDATORY:
            required_matches[canonical_key] = item
        elif non_required_match is None:
            non_required_match = item

    if len(required_matches) > 1:
        result["reason_code"] = CUSTOM_BLOCKER_REASON_AMBIGUOUS
        return result
    if len(required_matches) == 1:
        item = next(iter(required_matches.values()))
        result.update(
            {
                "ok": True,
                "reason_code": CUSTOM_BLOCKER_REASON_RESOLVED,
                "canonical_requirement": str(item.get("canonical_requirement") or "").strip(),
                "requirement_type": str(item.get("requirement_type") or "").strip().lower(),
                "importance": LLM_COVERAGE_IMPORTANCE_MANDATORY,
                "matched_job_text": str(item.get("matched_job_text") or "").strip(),
            }
        )
        return result
    if non_required_match is not None:
        result.update(
            {
                "reason_code": CUSTOM_BLOCKER_REASON_NOT_REQUIRED,
                "canonical_requirement": str(
                    non_required_match.get("canonical_requirement") or ""
                ).strip(),
                "requirement_type": str(
                    non_required_match.get("requirement_type") or ""
                ).strip().lower(),
                "importance": str(non_required_match.get("importance") or "").strip().lower(),
                "matched_job_text": str(non_required_match.get("matched_job_text") or "").strip(),
            }
        )
        return result
    result["reason_code"] = CUSTOM_BLOCKER_REASON_NO_MATCH
    return result


def list_custom_blocker_candidates(requirement_coverage: list[dict]) -> list[dict]:
    """List the requirements a custom "Not For Me" blocker is allowed to resolve to.

    This is exactly the set resolve_custom_blocker() accepts as a RESOLVED match
    (profile_action_allowed, a real canonical_requirement, importance == mandatory).
    The rejection panel shows these so the user ticks a real requirement instead of
    typing a term blind. Deduped by normalized canonical_requirement, input order
    preserved. Widening this set widens what can be persisted to
    must_not_require_skills, so it must stay in lockstep with resolve_custom_blocker.
    """
    seen: set[str] = set()
    candidates: list[dict] = []
    for item in requirement_coverage:
        if not isinstance(item, dict):
            continue
        requirement_type = str(item.get("requirement_type") or "").strip().lower()
        if requirement_type not in LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES:
            continue
        if item.get("profile_action_allowed") is not True:
            continue
        canonical_requirement = str(item.get("canonical_requirement") or "").strip()
        if not canonical_requirement:
            continue
        if str(item.get("importance") or "").strip().lower() != LLM_COVERAGE_IMPORTANCE_MANDATORY:
            continue
        canonical_key = _normalize_for_match(canonical_requirement)
        if not canonical_key or canonical_key in seen:
            continue
        seen.add(canonical_key)
        candidates.append(
            {
                "term": canonical_requirement,
                "requirement_type": requirement_type,
                "matched_job_text": str(item.get("matched_job_text") or "").strip(),
            }
        )
    return candidates
