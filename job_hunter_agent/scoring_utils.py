import math
import re
from datetime import datetime
from typing import List, Optional

from job_hunter_agent.profile_store import get_evidence_tiers
from job_hunter_agent.role_analysis import text_contains_term
from job_hunter_agent.text_processing import compact_whitespace, dedupe_preserve_order


def weighted_points(value: int, weight: float) -> int:
    scaled = float(value) * float(weight)
    if scaled >= 0:
        return int(math.floor(scaled + 0.5))
    return -int(math.floor(abs(scaled) + 0.5))


def build_scoring_source_text(record: dict) -> str:
    source_parts: List[str] = []
    for value in [
        record.get("fit_source_text"),
        record.get("full_description"),
        record.get("title"),
        record.get("company"),
        record.get("role_snapshot"),
        record.get("teaser"),
    ]:
        cleaned = compact_whitespace(value)
        if cleaned and cleaned != "N/A":
            source_parts.append(cleaned)
    return "\n".join(dedupe_preserve_order(source_parts))


def extract_contract_months(details_text: str) -> Optional[int]:
    lowered = compact_whitespace(details_text).lower()
    matches = [int(value) for value in re.findall(r"\b(\d{1,2})\s*[-‑– ]?(?:month|months|mth)\b", lowered)]
    if not matches:
        return None
    return max(matches)


def find_old_experience_year(profile: dict, aliases: List[str]) -> Optional[int]:
    cv_text = compact_whitespace(profile.get("cv_text") or "").lower()
    if not cv_text:
        return None
    for alias in aliases:
        cleaned = str(alias).strip().lower()
        if not cleaned:
            continue
        match = re.search(rf"{re.escape(cleaned)}.{{0,90}}old from (\d{{4}})", cv_text)
        if match:
            try:
                return int(match.group(1))
            except Exception:
                return None
    return None


def _line_year_context(line: str, current_year: int) -> Optional[int]:
    lowered = compact_whitespace(line).lower()
    if not lowered:
        return None

    patterns = [
        r"(20\d{2})\s*[-–]\s*(present|current|ongoing|20\d{2})",
        r"from\s+(20\d{2})\s+to\s+(20\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if not match:
            continue
        end_value = match.group(2)
        if end_value in {"present", "current", "ongoing"}:
            return current_year
        try:
            return int(end_value)
        except Exception:
            continue
    return None


def find_profile_experience_year_in_text(source_text: str, aliases: List[str]) -> Optional[int]:
    text = str(source_text or "")
    if not text.strip():
        return None

    current_year = datetime.now().year
    most_recent_year: Optional[int] = None
    section_year: Optional[int] = None

    for raw_line in text.splitlines():
        line = compact_whitespace(raw_line)
        if not line:
            continue
        updated_year = _line_year_context(line, current_year)
        if updated_year:
            section_year = updated_year
        lowered_line = line.lower()
        if any(text_contains_term(lowered_line, alias) for alias in aliases if str(alias).strip()):
            candidate_year = updated_year or section_year
            if candidate_year and (most_recent_year is None or candidate_year > most_recent_year):
                most_recent_year = candidate_year
    return most_recent_year


def find_profile_experience_year(profile: dict, aliases: List[str]) -> Optional[int]:
    explicit_old_year = find_old_experience_year(profile, aliases)
    if explicit_old_year:
        return explicit_old_year

    evidence_tiers = get_evidence_tiers(profile)
    candidate_years = [
        find_profile_experience_year_in_text(evidence_tiers.get("primary_current_evidence", ""), aliases),
        find_profile_experience_year_in_text(evidence_tiers.get("secondary_older_evidence", ""), aliases),
        find_profile_experience_year_in_text(evidence_tiers.get("background_optional_evidence", ""), aliases),
        find_profile_experience_year_in_text(str(profile.get("cv_text") or ""), aliases),
    ]
    candidate_years = [year for year in candidate_years if year]
    if not candidate_years:
        return None
    return max(candidate_years)


def profile_recency_multiplier(profile: dict, aliases: List[str]) -> float:
    most_recent_year = find_profile_experience_year(profile, aliases)
    if not most_recent_year:
        return 0.0
    years_ago = max(datetime.now().year - int(most_recent_year), 0)
    if years_ago <= 5:
        return 1.0
    if years_ago <= 10:
        return 0.6
    return 0.3
