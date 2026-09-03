"""Job quality signal detection.

Purpose: collect evidence for repost, closure, date-mismatch, and CV-farming
signals without making the final rejection decision.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.error import URLError
from urllib.request import Request, urlopen

from job_hunter_agent.paths import (
    CV_FARMING_RULES_DESCRIPTION,
    CV_FARMING_RULES_NAME,
    CV_FARMING_RULES_VERSION,
)
from job_hunter_agent.signal_schema import CATEGORY_CV_FARMING_PATTERN
from job_hunter_agent.text_processing import compact_whitespace

logger = logging.getLogger(__name__)

SIGNAL_KIND_DATE_MISMATCH = "date_mismatch"
SIGNAL_KIND_JOB_CLOSED = "job_closed"
SIGNAL_KIND_CV_FARMING = "cv_farming"
SIGNAL_KIND_BROAD_ENGAGEMENT = "broad_engagement"




def _clean_text(value: object) -> str:
    """Normalize whitespace and coerce any value to a trimmed string."""
    return compact_whitespace(value)


def _clean_aliases(values: object, *, canonical: str = "") -> list[str]:
    """Normalize alias lists while keeping the canonical value out of the result."""
    if isinstance(values, str):
        raw_values = re.split(r"[\n,]", values)
    elif isinstance(values, list):
        raw_values = values
    else:
        raw_values = []

    canonical_key = _clean_text(canonical).lower()
    aliases: list[str] = []
    seen: set[str] = {canonical_key} if canonical_key else set()
    for value in raw_values:
        alias = _clean_text(value)
        alias_key = alias.lower()
        if not alias or alias_key in seen:
            continue
        seen.add(alias_key)
        aliases.append(alias)
    return aliases


def _normalize_entry(entry: object) -> dict[str, object] | None:
    """Validate and normalize a single managed-knowledge entry."""
    if not isinstance(entry, dict):
        return None
    value = _clean_text(entry.get("value"))
    if not value:
        return None
    return {
        "value": value,
        "aliases": _clean_aliases(entry.get("aliases"), canonical=value),
    }


def _merge_entries(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    """Merge duplicate entries while preserving order and alias coverage."""
    merged: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for entry in entries:
        normalized = _normalize_entry(entry)
        if normalized is None:
            continue
        value_key = str(normalized["value"]).lower()
        bucket = merged.get(value_key)
        if bucket is None:
            bucket = {
                "value": normalized["value"],
                "aliases": [],
            }
            merged[value_key] = bucket
            order.append(value_key)
        seen_aliases = {
            str(bucket["value"]).lower(),
            *(str(alias).lower() for alias in bucket["aliases"]),
        }
        for alias in normalized["aliases"]:
            alias_key = str(alias).lower()
            if alias_key in seen_aliases:
                continue
            seen_aliases.add(alias_key)
            bucket["aliases"].append(alias)
    return [merged[key] for key in order]


def load_cv_farming_rules() -> list[dict[str, object]]:
    """Load approved CV-farming patterns from managed knowledge."""
    from job_hunter_agent.knowledge_store import get_knowledge

    payload = get_knowledge("cv_farming_rules") or {}
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return []
    return _merge_entries(entries)


def save_cv_farming_rules(entries: list[dict[str, object]]) -> dict[str, object]:
    """Persist the CV-farming knowledge store using the shared managed-knowledge schema."""
    payload = {
        "kind": "managed_knowledge",
        "name": CV_FARMING_RULES_NAME,
        "version": CV_FARMING_RULES_VERSION,
        "description": CV_FARMING_RULES_DESCRIPTION,
        "entries": _merge_entries(entries),
    }
    from job_hunter_agent.knowledge_store import set_knowledge

    set_knowledge("cv_farming_rules", payload)
    return payload


def upsert_cv_farming_rule(value: str, aliases: list[str] | None = None) -> dict[str, object]:
    """Insert or update a CV-farming pattern in the shared knowledge store."""
    cleaned_value = _clean_text(value)
    if not cleaned_value:
        raise ValueError("value is required")

    entries = list(load_cv_farming_rules())
    incoming_aliases = _clean_aliases(aliases or [], canonical=cleaned_value)
    for entry in entries:
        if _clean_text(entry.get("value")).lower() != cleaned_value.lower():
            continue
        existing_aliases = _clean_aliases(entry.get("aliases"), canonical=cleaned_value)
        merged: list[str] = []
        seen: set[str] = {cleaned_value.lower()}
        for alias in [*existing_aliases, *incoming_aliases]:
            alias_key = alias.lower()
            if alias_key in seen:
                continue
            seen.add(alias_key)
            merged.append(alias)
        entry["value"] = cleaned_value
        entry["aliases"] = merged
        return save_cv_farming_rules(entries)

    entries.append(
        {
            "value": cleaned_value,
            "aliases": incoming_aliases,
        }
    )
    return save_cv_farming_rules(entries)


def load_dodgy_job_rules() -> dict:
    """Load the quality rules used for closed-job and CV-farming detection."""
    from job_hunter_agent.knowledge_store import get_knowledge

    base_rules = get_knowledge("dodgy_job_rules") or {}
    if "external_date_mismatch_flag_days" not in base_rules:
        raise ValueError("dodgy_job_rules.json must define external_date_mismatch_flag_days")
    try:
        flag_days = int(base_rules["external_date_mismatch_flag_days"])
    except Exception as exc:
        raise ValueError(
            "dodgy_job_rules.json must define a whole-number external_date_mismatch_flag_days"
        ) from exc
    if flag_days <= 0:
        raise ValueError(
            "dodgy_job_rules.json must define a positive external_date_mismatch_flag_days"
        )

    return {
        "cv_farming_patterns": [
            str(entry.get("value") or "")
            for entry in load_cv_farming_rules()
            if _clean_text(entry.get("value"))
        ],
        "job_closed_indicators": [
            _clean_text(value)
            for value in base_rules.get("job_closed_indicators", [])
            if _clean_text(value)
        ],
        "external_date_mismatch_flag_days": flag_days,
    }


def fetch_external_html(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    req = Request(raw, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, ValueError, OSError) as exc:
        logger.warning("Failed to fetch external HTML from %s: %s", url, exc)
        return ""


class _StructuredPostingDateParser(HTMLParser):
    """Collect schema.org posting-date values without interpreting visible page copy."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.json_ld_blocks: list[str] = []
        self.microdata_values: list[str] = []
        self._json_ld_parts: list[str] | None = None
        self._microdata_tag = ""
        self._microdata_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {
            str(name or "").strip().lower(): str(value or "").strip()
            for name, value in attrs
        }

        if tag.lower() == "script":
            media_type = attr_map.get("type", "").split(";", 1)[0].strip().lower()
            if media_type == "application/ld+json":
                self._json_ld_parts = []

        itemprop_tokens = {
            token.strip().lower()
            for token in attr_map.get("itemprop", "").split()
            if token.strip()
        }
        if "dateposted" not in itemprop_tokens:
            return

        structured_value = (
            attr_map.get("content")
            or attr_map.get("datetime")
            or attr_map.get("value")
        )
        if structured_value:
            self.microdata_values.append(structured_value)
            return

        self._microdata_tag = tag.lower()
        self._microdata_parts = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._json_ld_parts is not None:
            self._json_ld_parts.append(data)
        if self._microdata_tag:
            self._microdata_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "script" and self._json_ld_parts is not None:
            block = "".join(self._json_ld_parts).strip()
            if block:
                self.json_ld_blocks.append(block)
            self._json_ld_parts = None

        if lowered == self._microdata_tag:
            value = compact_whitespace(" ".join(self._microdata_parts))
            if value:
                self.microdata_values.append(value)
            self._microdata_tag = ""
            self._microdata_parts = []


def _is_job_posting_schema_type(value: object) -> bool:
    values = value if isinstance(value, list) else [value]
    for item in values:
        normalized = str(item or "").strip().rstrip("/").rsplit("/", 1)[-1].lower()
        if normalized == "jobposting":
            return True
    return False


def _iter_job_posting_date_values(value: object):
    if isinstance(value, list):
        for item in value:
            yield from _iter_job_posting_date_values(item)
        return
    if not isinstance(value, dict):
        return

    if _is_job_posting_schema_type(value.get("@type")):
        for key, candidate in value.items():
            if str(key).strip().lower() != "dateposted":
                continue
            if isinstance(candidate, list):
                for item in candidate:
                    if str(item or "").strip():
                        yield str(item).strip()
            elif str(candidate or "").strip():
                yield str(candidate).strip()

    for candidate in value.values():
        yield from _iter_job_posting_date_values(candidate)


def _parse_structured_posting_date(value: object) -> date | None:
    raw = compact_whitespace(value)
    if not raw:
        return None

    normalized = re.sub(r"(?<=\d)(?:st|nd|rd|th)\b", "", raw, flags=re.IGNORECASE)
    iso_value = normalized[:-1] + "+00:00" if normalized.endswith(("Z", "z")) else normalized
    try:
        return datetime.fromisoformat(iso_value).date()
    except ValueError:
        pass

    for date_format in ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(normalized, date_format).date()
        except ValueError:
            continue
    return None


def _unique_verified_date(
    raw_values: list[str],
    run_date: date,
) -> tuple[date, str] | None:
    parsed_values: list[tuple[date, str]] = []
    for raw_value in raw_values:
        parsed = _parse_structured_posting_date(raw_value)
        if parsed is None or parsed > run_date:
            continue
        parsed_values.append((parsed, raw_value))

    unique_dates = {parsed for parsed, _ in parsed_values}
    if len(unique_dates) != 1:
        return None

    verified_date = next(iter(unique_dates))
    raw_value = next(raw for parsed, raw in parsed_values if parsed == verified_date)
    return verified_date, raw_value


def extract_external_original_posting_date(html: str, run_date: date) -> dict[str, object] | None:
    """Return a verified original posting date from structured job-page metadata only."""

    if not str(html or "").strip():
        return None

    parser = _StructuredPostingDateParser()
    try:
        parser.feed(html)
        parser.close()
    except (TypeError, ValueError):
        return None

    json_ld_values: list[str] = []
    for block in parser.json_ld_blocks:
        try:
            payload = json.loads(block)
        except (json.JSONDecodeError, TypeError):
            continue
        json_ld_values.extend(_iter_job_posting_date_values(payload))

    structured_sources = (
        ("jobposting_json_ld", json_ld_values),
        ("schema_dateposted_microdata", parser.microdata_values),
    )
    for evidence_source, raw_values in structured_sources:
        if not raw_values:
            continue
        verified = _unique_verified_date(raw_values, run_date)
        if verified is None:
            return None
        posted_on, raw_value = verified
        age_days = (run_date - posted_on).days
        return {
            "age_days": float(age_days),
            "posted_on": posted_on.isoformat(),
            "evidence_source": evidence_source,
            "raw_value": raw_value,
        }

    return None


def detect_external_date_signals(
    html: str,
    linkedin_age_days: float | None,
    rules: dict,
    run_date: date,
    *,
    detect_closed: bool = True,
) -> list:
    if not html:
        return []

    signals = []
    flag_days = int(rules["external_date_mismatch_flag_days"])

    if detect_closed:
        for pat in rules.get("job_closed_indicators", []):
            if re.search(pat, html, re.IGNORECASE):
                signals.append(
                    {
                        "kind": SIGNAL_KIND_JOB_CLOSED,
                        "label": "Job Closed",
                        "evidence": "External page indicates this role is no longer available.",
                        "needs_review": True,
                    }
                )
                return signals

    verification = extract_external_original_posting_date(html, run_date)
    external_age = int(verification["age_days"]) if verification is not None else None

    if external_age is not None and linkedin_age_days is not None:
        diff = external_age - float(linkedin_age_days)
        if diff >= flag_days:
            signals.append(
                {
                    "kind": SIGNAL_KIND_DATE_MISMATCH,
                    "label": "Date Mismatch",
                    "evidence": (
                        f"LinkedIn shows ~{int(linkedin_age_days)}d old; "
                        f"external page metadata shows ~{external_age}d old "
                        f"({int(diff)}d discrepancy)."
                    ),
                    "needs_review": True,
                    "linkedin_age_days": int(linkedin_age_days),
                    "external_age_days": external_age,
                    "mismatch_days": int(diff),
                }
            )

    return signals



def detect_broad_engagement_signal(record: dict) -> list:
    """Flag jobs that advertise for both permanent and contract — may indicate a broad talent-pool search."""
    work_type = _clean_text(record.get("work_type") or "").lower()
    if not work_type:
        return []
    perm_keywords = ("full time", "permanent", "full-time")
    contract_keywords = ("contract",)
    is_perm = any(k in work_type for k in perm_keywords)
    is_contract = any(k in work_type for k in contract_keywords)
    if is_perm and is_contract:
        return [
            {
                "kind": SIGNAL_KIND_BROAD_ENGAGEMENT,
                "label": "Broad Ad",
                "evidence": f'Ad lists both permanent and contract work types ("{work_type}") — may be a wide talent-pool search rather than a specific vacancy.',
                "needs_review": False,
            }
        ]
    return []


def detect_cv_farming_signals(description_text: str, rules: dict) -> list:
    """Return a single review signal when the description matches a learned CV-farming pattern."""
    patterns = rules.get("cv_farming_patterns", [])
    if not patterns:
        return []

    for pat in patterns:
        m = re.search(pat, description_text, re.IGNORECASE)
        if m:
            match_text = _clean_text(m.group(0))[:80]
            return [
                {
                    "kind": SIGNAL_KIND_CV_FARMING,
                    "label": "CV Farming",
                    "signal": pat,
                    "suggested_category": CATEGORY_CV_FARMING_PATTERN,
                    "original_texts": [match_text],
                    "evidence": f'Description matches talent-pool pattern: "{match_text}"',
                    "needs_review": True,
                }
            ]
    return []
