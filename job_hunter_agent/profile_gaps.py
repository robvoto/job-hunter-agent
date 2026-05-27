"""Profile gap detection: job requirements not yet confirmed in the candidate profile.

A 'gap' is a requirement extracted from a job ad that cannot be matched against
the candidate's candidate_capabilities. Gaps are presented to the user in the
workspace card under a 'Needs confirmation' block so they can respond:

  - Yes, I have this  → adds the term to candidate_capabilities
  - No, I don't have this → adds the term to must_not_require_skills
  - Decide later → client-side dismiss; the gap reappears on the next page load
"""

from __future__ import annotations

import re

STATUS_UNKNOWN = "unknown"
STATUS_CONFIRMED_HAVE = "confirmed_have"
STATUS_CONFIRMED_DO_NOT_HAVE = "confirmed_do_not_have"


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
    job_requirements: list[str],
    candidate_capabilities: list[dict],
    must_not_require_skills: list[str],
) -> list[dict]:
    """
    Return the subset of job requirements not confirmed in the candidate profile.

    Each returned gap: {requirement: str, evidence: str, status: 'unknown'}.
    Requirements already matched (confirmed_have or confirmed_do_not_have) are excluded.
    """
    gaps = []
    for req in job_requirements:
        req = str(req).strip()
        if not req:
            continue
        status = classify_requirement_status(req, candidate_capabilities, must_not_require_skills)
        if status == STATUS_UNKNOWN:
            gaps.append({"requirement": req, "evidence": req, "status": STATUS_UNKNOWN})
    return gaps
