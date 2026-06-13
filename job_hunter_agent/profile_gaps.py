"""Profile gap detection for capability-like requirement coverage only.

The workspace confirmation flow should only surface uncertain capability
requirements from requirement_coverage. Raw job_requirements remain available
for display/debug, but they must not drive confirmation or profile writes.
"""

from __future__ import annotations

import re

STATUS_UNKNOWN = "unknown"
STATUS_CONFIRMED_HAVE = "confirmed_have"
STATUS_CONFIRMED_DO_NOT_HAVE = "confirmed_do_not_have"
_CONFIRMABLE_REQUIREMENT_STATUSES = frozenset({"not_shown", "partially_supported"})
PROFILE_GAP_JOB_REQUIREMENT_TEXT_KEY = "job_requirement_text"


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


def classify_requirement_status(
    requirement: str,
    candidate_capabilities: list[dict],
    must_not_require_skills: list[str],
) -> str:
    """
    Classify a single job requirement against the candidate profile.

    Checks must_not_require_skills first (stronger signal), then candidate_capabilities.
    Returns one of STATUS_UNKNOWN, STATUS_CONFIRMED_HAVE, STATUS_CONFIRMED_DO_NOT_HAVE.
    """
    req_norm = _normalize_for_match(requirement)
    if not req_norm:
        return STATUS_UNKNOWN
    if _requirement_in_must_not_require(req_norm, must_not_require_skills):
        return STATUS_CONFIRMED_DO_NOT_HAVE
    if any(_requirement_matches_capability(req_norm, cap) for cap in candidate_capabilities):
        return STATUS_CONFIRMED_HAVE
    return STATUS_UNKNOWN


def compute_profile_gaps(
    requirement_coverage: list[dict],
    candidate_capabilities: list[dict],
    must_not_require_skills: list[str],
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
        capability_name = str(item.get("capability_name") or "").strip()
        if not capability_name:
            continue
        if (
            classify_requirement_status(
                capability_name, candidate_capabilities, must_not_require_skills
            )
            != STATUS_UNKNOWN
        ):
            continue
        raw_requirement = str(item.get("requirement") or "").strip()
        matched_job_text = str(item.get("matched_job_text") or "").strip()
        gaps.append(
            {
                "capability_name": capability_name,
                "raw_requirement": raw_requirement,
                "matched_job_text": matched_job_text,
                "status": status,
                PROFILE_GAP_JOB_REQUIREMENT_TEXT_KEY: matched_job_text or raw_requirement,
            }
        )
    return gaps
