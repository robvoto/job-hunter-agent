"""Classify a job title against the local O*NET occupation taxonomy.

Single public entry point:
    classify_title(title, profile, db_path=None) -> OccupationClassification

Classification logic:
- No exact normalized-title match in the index   → uncertain (reason: no_match)
- Multiple distinct SOC codes under one title    → uncertain (reason: ambiguous)
- Profile target roles yield no known SOC groups → uncertain (reason: no_profile_context)
- Matched SOC major group is in target families  → near
- Otherwise                                      → far

O*NET is reference data, not truth. This module never hard-rejects a job on its own.
The caller decides whether to use the classification result for rejection.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from job_hunter_agent.database import db_conn
from job_hunter_agent.onet_taxonomy_import import TAXONOMY_VERSION, normalize_title
from job_hunter_agent.paths import ONET_TAXONOMY_DIR

logger = logging.getLogger(__name__)

_INDEX_PATH = ONET_TAXONOMY_DIR / "onet_index.json"

RESULT_NEAR = "near"
RESULT_FAR = "far"
RESULT_UNCERTAIN = "uncertain"

_CONFIDENCE_EXACT = 0.9
_CONFIDENCE_AMBIGUOUS = 0.4
_CONFIDENCE_NO_MATCH = 0.0
_CONFIDENCE_NO_CONTEXT = 0.0


@dataclass(frozen=True)
class OccupationClassification:
    result: str
    matched_occupation_code: str | None
    confidence: float
    reason: str


@lru_cache(maxsize=1)
def _load_index() -> dict[str, list[dict[str, str]]]:
    if not _INDEX_PATH.is_file():
        raise FileNotFoundError(
            f"O*NET index not found at {_INDEX_PATH}. "
            "Run: python -m job_hunter_agent.onet_taxonomy_import <path/to/OccupationalListings.zip>"
        )
    data = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    return data["by_normalized_title"]


def _compute_profile_hash(profile: dict[str, Any]) -> str:
    relevant = {
        "target_occupation_queries": sorted(profile.get("target_occupation_queries") or []),
        "target_roles": sorted(profile.get("target_roles") or []),
        "also_consider_roles": sorted(profile.get("also_consider_roles") or []),
    }
    canonical = json.dumps(relevant, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _derive_near_soc_major_groups(profile: dict[str, Any], index: dict[str, list[dict[str, str]]]) -> set[str]:
    """Return SOC major-group codes (e.g. '13', '15') for the profile's target occupations.

    Source priority:
      1. target_occupation_queries  — machine-facing O*NET queries generated at onboarding
      2. target_roles + also_consider_roles  — display titles, used as fallback

    Using target_occupation_queries first ensures that precise occupation terms
    drive classification rather than vague display labels like "coordinator".
    """
    primary = list(profile.get("target_occupation_queries") or [])
    if primary:
        roles = primary
    else:
        roles = list(profile.get("target_roles") or []) + list(profile.get("also_consider_roles") or [])

    groups: set[str] = set()
    for role in roles:
        for match in index.get(normalize_title(role)) or []:
            code = match.get("occupation_code") or ""
            if "-" in code:
                groups.add(code.split("-")[0])
    return groups


def _cache_lookup(
    normalized_title: str,
    profile_hash: str,
    db_path: Path | None,
) -> OccupationClassification | None:
    with db_conn(db_path) as conn:
        row = conn.execute(
            """
            SELECT result, matched_occupation_code, confidence
              FROM occupation_title_cache
             WHERE normalized_title = ?
               AND candidate_profile_hash = ?
               AND taxonomy_version = ?
            """,
            (normalized_title, profile_hash, TAXONOMY_VERSION),
        ).fetchone()
    if row is None:
        return None
    return OccupationClassification(
        result=row["result"],
        matched_occupation_code=row["matched_occupation_code"],
        confidence=row["confidence"],
        reason="cached",
    )


def _cache_save(
    normalized_title: str,
    profile_hash: str,
    classification: OccupationClassification,
    db_path: Path | None,
) -> None:
    with db_conn(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO occupation_title_cache
                (normalized_title, candidate_profile_hash, taxonomy_version,
                 result, matched_occupation_code, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_title,
                profile_hash,
                TAXONOMY_VERSION,
                classification.result,
                classification.matched_occupation_code,
                classification.confidence,
            ),
        )


def _log_classification(
    title: str,
    normalized: str,
    profile: dict[str, Any],
    result: OccupationClassification,
) -> None:
    from job_hunter_agent.logging_utils import format_log_block
    logger.info(format_log_block("PIPELINE][ONET_TITLE_CLASSIFY", {
        "title": title,
        "normalized_title": normalized,
        "target_occupation_queries": profile.get("target_occupation_queries") or [],
        "result": result.result,
        "matched_occupation_code": result.matched_occupation_code,
        "confidence": result.confidence,
        "reason": result.reason,
    }))


def classify_title(
    title: str,
    profile: dict[str, Any],
    db_path: Path | None = None,
    _index: dict[str, list[dict[str, str]]] | None = None,
) -> OccupationClassification:
    """Classify a job title as near, far, or uncertain relative to the candidate profile.

    _index is for testing only — pass a minimal dict to avoid loading onet_index.json.
    """
    normalized = normalize_title(title)
    profile_hash = _compute_profile_hash(profile)

    cached = _cache_lookup(normalized, profile_hash, db_path)
    if cached is not None:
        return cached

    index = _index if _index is not None else _load_index()
    matches = list(index.get(normalized) or [])

    if not matches:
        result = OccupationClassification(
            result=RESULT_UNCERTAIN,
            matched_occupation_code=None,
            confidence=_CONFIDENCE_NO_MATCH,
            reason="no_match",
        )
        _cache_save(normalized, profile_hash, result, db_path)
        _log_classification(title, normalized, profile, result)
        return result

    unique_codes = {m["occupation_code"] for m in matches if m.get("occupation_code")}

    if len(unique_codes) > 1:
        result = OccupationClassification(
            result=RESULT_UNCERTAIN,
            matched_occupation_code=None,
            confidence=_CONFIDENCE_AMBIGUOUS,
            reason="ambiguous",
        )
        _cache_save(normalized, profile_hash, result, db_path)
        _log_classification(title, normalized, profile, result)
        return result

    occupation_code = next(iter(unique_codes))
    near_groups = _derive_near_soc_major_groups(profile, index)

    if not near_groups:
        result = OccupationClassification(
            result=RESULT_UNCERTAIN,
            matched_occupation_code=occupation_code,
            confidence=_CONFIDENCE_NO_CONTEXT,
            reason="no_profile_context",
        )
        _cache_save(normalized, profile_hash, result, db_path)
        _log_classification(title, normalized, profile, result)
        return result

    soc_major = occupation_code.split("-")[0] if "-" in occupation_code else ""
    if soc_major and soc_major in near_groups:
        result = OccupationClassification(
            result=RESULT_NEAR,
            matched_occupation_code=occupation_code,
            confidence=_CONFIDENCE_EXACT,
            reason=RESULT_NEAR,
        )
    else:
        result = OccupationClassification(
            result=RESULT_FAR,
            matched_occupation_code=occupation_code,
            confidence=_CONFIDENCE_EXACT,
            reason=RESULT_FAR,
        )

    _cache_save(normalized, profile_hash, result, db_path)
    _log_classification(title, normalized, profile, result)
    return result
