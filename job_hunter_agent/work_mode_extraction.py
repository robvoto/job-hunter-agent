"""Work mode extraction from job metadata and description text.

Design principles:
- Metadata is trusted before heuristics. Structured platform fields and DOM metadata
  are more reliable than keyword scanning of free-text descriptions.
- Search filters are search context, not always per-job proof. A SEEK filter panel
  with "Hybrid" checked tells you the search was filtered, but it applies to all
  results on that page, not any specific job record. Source label: "seek_filter_panel".
- Fallback text inference must be reviewable. Any result derived from description
  text is flagged work_mode_needs_review=True so a human or downstream process
  can verify it before acting on it.
- No preference, scoring, or rejection logic belongs here. This module extracts
  and labels evidence only. Consumers decide what to do with the result.

This module provides logic for identifying work arrangements (remote, hybrid,
onsite) from job listings. It prioritises structured metadata and platform-specific
fields (like SEEK's filter panel or LinkedIn's structured attributes) over
heuristic-based text analysis. Evidence is labeled and flagged for review
when derived from free-text fallbacks.
"""

import logging
import re
from functools import lru_cache
from typing import Any, Optional

from job_hunter_agent.io_utils import load_ui_labels, load_work_mode_rules

logger = logging.getLogger(__name__)

# Canonical work mode values — always lowercase
WORK_MODE_REMOTE = "remote"
WORK_MODE_HYBRID = "hybrid"
WORK_MODE_ONSITE = "onsite"
WORK_MODE_UNKNOWN = "unknown"

# SEEK DOM selectors for the search page filter panel
_SELECTOR_FILTER_PANEL = '[data-automation="refineWorkArrangement"]'
_SELECTOR_CHECKED = '[role="checkbox"][aria-checked="true"]'

# LinkedIn jobspy fields, in priority order within each group.
# Explicit workplace-type strings take priority over boolean remote flags.
_LINKEDIN_WORKPLACE_TEXT_FIELDS = [
    "workplace_type",
    "workplaceType",
    "job_workplace",
]
_LINKEDIN_BOOL_FIELDS = [
    "remote_allowed",
    "is_remote",
]

# Map normalised visible labels / field values to canonical modes.
# Normalisation (applied before lookup): lowercase, hyphens/underscores → space.
# "On-site", "on_site", "ON SITE" all normalise to "on site" → onsite.
_LABEL_TO_CANONICAL: dict[str, str] = {
    "remote": WORK_MODE_REMOTE,
    "fully remote": WORK_MODE_REMOTE,
    "100% remote": WORK_MODE_REMOTE,
    "work from home": WORK_MODE_REMOTE,
    "wfh": WORK_MODE_REMOTE,
    "hybrid": WORK_MODE_HYBRID,
    "on site": WORK_MODE_ONSITE,
    "onsite": WORK_MODE_ONSITE,
    "in office": WORK_MODE_ONSITE,
    "office based": WORK_MODE_ONSITE,
}


def _build_result(mode: str, source: str, evidence: str, needs_review: bool) -> dict:
    return {
        "work_mode": mode,
        "work_mode_source": source,
        "work_mode_evidence": evidence,
        "work_mode_needs_review": needs_review,
    }


def _normalise_label(text: str) -> str:
    """Lowercase and collapse hyphens/underscores to spaces for label lookup."""
    normalised = re.sub(r"[-_]+", " ", text.strip().lower())
    return re.sub(r"\s+", " ", normalised).strip()


def _lookup_label(text: str) -> Optional[str]:
    """Return canonical mode for a known label, or None if unrecognised."""
    return _LABEL_TO_CANONICAL.get(_normalise_label(text))


def canonical_work_mode_value(value: object) -> str:
    """Canonicalise one already-proven structured work-mode value.

    This is shape normalisation only. It never scans surrounding text or
    infers a mode from other fields, so callers can preserve a source owner's
    explicit known/unknown field-state semantics.
    """
    text = str(value or "").strip()
    if not text:
        return WORK_MODE_UNKNOWN
    return _lookup_label(text) or WORK_MODE_UNKNOWN


def _extract_parenthetical_mode(line: str) -> Optional[str]:
    """Return a canonical mode if the line contains a parenthesised work mode token.

    Matches patterns like 'Sydney NSW (Hybrid)' or 'Melbourne VIC (Remote)'.
    The parenthetical must be the last token on the line (how SEEK renders it).
    """
    m = re.search(r"\(([^)]+)\)\s*$", line)
    if not m:
        return None
    return _lookup_label(m.group(1))


@lru_cache(maxsize=1)
def _work_mode_display_labels() -> dict[str, str]:
    labels = load_ui_labels().get("work_mode_labels", {})
    if not isinstance(labels, dict):
        return {}
    return {
        "remote": str(labels.get("remote_label") or "").strip(),
        "hybrid": str(labels.get("hybrid_label") or "").strip(),
        "onsite": str(labels.get("onsite_label") or "").strip(),
    }


def display_work_mode_label(record: dict) -> str:
    raw_mode = str(record.get("work_mode") or "").strip()
    if not raw_mode:
        return ""

    canonical = _lookup_label(raw_mode)
    if not canonical:
        canonical = _normalise_label(raw_mode)
    if canonical not in {WORK_MODE_REMOTE, WORK_MODE_HYBRID, WORK_MODE_ONSITE}:
        return ""

    return _work_mode_display_labels().get(canonical, "")


def _text_fallback(text: str, source_label: str) -> dict:
    """Infer work mode from free text using managed indicator rules.

    Fallback text inference is not reliable — a description may mention hybrid
    arrangements in passing or reference a previous role. Every result here is
    flagged needs_review=True for downstream verification.
    """
    if not text:
        return _build_result(WORK_MODE_UNKNOWN, source_label, "", True)

    lowered = text.lower()
    rules = load_work_mode_rules().get("work_mode_indicators", {})

    for token in rules.get("strict_onsite", []):
        if token in lowered:
            return _build_result(WORK_MODE_ONSITE, source_label, token, True)

    for token in rules.get("hybrid", []):
        if token in lowered:
            return _build_result(WORK_MODE_HYBRID, source_label, token, True)

    for token in rules.get("remote", []):
        if token in lowered:
            return _build_result(WORK_MODE_REMOTE, source_label, token, True)

    for token in rules.get("onsite", []):
        if token in lowered:
            return _build_result(WORK_MODE_ONSITE, source_label, token, True)

    return _build_result(WORK_MODE_UNKNOWN, source_label, "", True)


# ---------------------------------------------------------------------------
# SEEK filter panel (search-page level context)
# ---------------------------------------------------------------------------


def extract_seek_filter_panel_state(list_page) -> Optional[dict]:
    """Extract the active work arrangement filter from the SEEK search results page.

    Returns a result dict when exactly one filter checkbox is checked.
    Returns None when zero or more than one filter is active — multiple checked
    filters are ambiguous and should not be used as per-job evidence.

    The filter panel reflects search intent, not individual job metadata.
    Source label: "seek_filter_panel".
    """
    container = list_page.query_selector(_SELECTOR_FILTER_PANEL)
    try:
        if not container:
            return None

        checked = container.query_selector_all(_SELECTOR_CHECKED)
        if not checked:
            return None

        modes = []
        for el in checked:
            raw = (el.inner_text() or "").strip()
            mode = _lookup_label(raw)
            if mode:
                modes.append((mode, raw))

        if len(modes) != 1:
            return None

        mode, evidence = modes[0]
        return _build_result(mode, "seek_filter_panel", evidence, False)
    except Exception as exc:
        logger.warning(
            "[work_mode] Failed to extract SEEK filter panel state (selectors may be out of date): %s",
            exc,
        )
        return None


# ---------------------------------------------------------------------------
# SEEK job card (per-card on search listing page)
# ---------------------------------------------------------------------------


def extract_from_seek_card(card_text: str, filter_state: Optional[dict] = None) -> dict:
    """Extract work mode from a SEEK job card's visible text.

    Priority:
    1. Card metadata lines — short lines near the top of the card, before the
       description teaser. Work arrangement labels appear here as standalone
       text (e.g. "Hybrid", "Remote", "On-site").
    2. Filter panel state — search-level context passed in from the caller.
       Used only when no card-level label is found.
    3. Text fallback — substring inference across the full card text.
       Flagged needs_review=True.
    """
    # Scan early short lines for exact work arrangement labels.
    # Card metadata (title, company, location, work mode, salary) precedes the teaser.
    # Lines longer than 80 chars are likely prose — stop scanning at that point.
    lines = [line.strip() for line in card_text.splitlines() if line.strip()]
    for line in lines[:15]:
        if len(line) > 80:
            break
        mode = _lookup_label(line) or _extract_parenthetical_mode(line)
        if mode:
            result = _build_result(mode, "seek_card", line, False)
            _log_result("seek", result)
            return result

    # Fall back to the search filter panel state (page-level search context).
    if filter_state and filter_state.get("work_mode") not in (None, WORK_MODE_UNKNOWN):
        result = {**filter_state, "work_mode_source": "seek_filter_panel"}
        _log_result("seek", result)
        return result

    # Last resort: text inference on card content.
    result = _text_fallback(card_text, "fallback_text")
    _log_result("seek", result)
    return result


# ---------------------------------------------------------------------------
# SEEK job detail page
# ---------------------------------------------------------------------------


def _find_work_arrangement_in_redux(payload: Any) -> Optional[str]:
    """Recursively search a SEEK redux/server-state payload for a work arrangement value.

    SEEK embeds job metadata in window.SEEK_REDUX_DATA. Field names vary across
    layouts but typically contain "workArrangement", "workplace", or similar.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_lower = str(key or "").lower()
            if any(
                k in key_lower
                for k in ("workarrangement", "workplace", "remote", "hybrid", "onsite")
            ):
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, str) and item.strip():
                            return item.strip()
                        if isinstance(item, dict):
                            label = item.get("label") or item.get("value") or item.get("text") or ""
                            if label:
                                return str(label).strip()
            nested = _find_work_arrangement_in_redux(value)
            if nested:
                return nested
    elif isinstance(payload, list):
        for item in payload:
            nested = _find_work_arrangement_in_redux(item)
            if nested:
                return nested
    return None


def extract_from_seek_detail(redux_payload: Any, visible_text: str) -> dict:
    """Extract work mode from a SEEK job detail page.

    Priority:
    1. Embedded SEEK_REDUX_DATA payload — structured server state is more reliable
       than visible text parsing or heuristics.
    2. Visible metadata lines at the top of the detail page text (before the
       description body).
    3. Text fallback across the full description. Flagged needs_review=True.
    """
    # Embedded structured payload — most trustworthy source on the detail page.
    if redux_payload not in (None, "", [], {}):
        raw = _find_work_arrangement_in_redux(redux_payload)
        if raw:
            mode = _lookup_label(raw)
            if mode:
                result = _build_result(mode, "seek_detail_payload", raw, False)
                _log_result("seek", result)
                return result

    # Visible metadata text at the top of the detail page.
    lines = [line.strip() for line in (visible_text or "").splitlines() if line.strip()]
    for line in lines[:20]:
        if len(line) > 80:
            break
        mode = _lookup_label(line) or _extract_parenthetical_mode(line)
        if mode:
            result = _build_result(mode, "seek_detail_visible", line, False)
            _log_result("seek", result)
            return result

    # Text fallback.
    result = _text_fallback(visible_text, "fallback_text")
    _log_result("seek", result)
    return result


# ---------------------------------------------------------------------------
# LinkedIn (python-jobspy structured fields)
# ---------------------------------------------------------------------------


def extract_from_linkedin(raw_fields: dict) -> dict:
    """Extract work mode from LinkedIn jobspy structured fields.

    Priority:
    1. Explicit workplace type strings (workplace_type, workplaceType, job_workplace).
    2. Boolean remote flags (remote_allowed, is_remote).
    3. Location field when its value is exactly "Remote".

    Returns unknown if no field yields a usable signal. Callers handle
    the text-fallback step once description text is available.

    Note: search keywords like "hybrid or remote" represent search intent, not
    job-level evidence. Only structured state fields are treated as metadata here.
    """
    fields = raw_fields if isinstance(raw_fields, dict) else {}

    # Explicit workplace type strings take priority over booleans.
    for field in _LINKEDIN_WORKPLACE_TEXT_FIELDS:
        raw = fields.get(field)
        if raw is None:
            continue
        text = str(raw).strip()
        if not text or text.lower() in ("none", "nan", ""):
            continue
        mode = _lookup_label(text)
        if mode:
            evidence = f"{field}={text}"
            result = _build_result(mode, "linkedin_structured", evidence, False)
            _log_result("linkedin", result)
            return result

    # Boolean remote flags.
    for field in _LINKEDIN_BOOL_FIELDS:
        raw = fields.get(field)
        if raw is None:
            continue
        val = str(raw).strip().lower()
        if val in ("true", "1", "yes"):
            result = _build_result(WORK_MODE_REMOTE, "linkedin_structured", f"{field}=true", False)
            _log_result("linkedin", result)
            return result
        if val in ("false", "0", "no"):
            result = _build_result(WORK_MODE_ONSITE, "linkedin_structured", f"{field}=false", False)
            _log_result("linkedin", result)
            return result

    # Location "Remote" (exact) or a parenthetical work mode e.g. "Sydney NSW (Hybrid)".
    location = str(fields.get("location") or "").strip()
    location_mode = _lookup_label(location) or _extract_parenthetical_mode(location)
    if location_mode:
        result = _build_result(location_mode, "linkedin_structured", f"location={location}", False)
        _log_result("linkedin", result)
        return result

    return _build_result(WORK_MODE_UNKNOWN, "linkedin_structured", "", False)


# ---------------------------------------------------------------------------
# Public text fallback (for display-time enrichment)
# ---------------------------------------------------------------------------


def extract_from_text(text: str, source_label: str = "fallback_text") -> dict:
    """Infer work mode from free text. Always sets needs_review=True.

    Use only when no structured metadata is available. Results are provisional —
    description text can mention arrangements that do not apply to the advertised role.
    """
    return _text_fallback(text, source_label)


# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------


def _log_result(source_board: str, result: dict, job_id: str = "") -> None:
    logger.debug(
        "[work_mode] board=%s job=%s mode=%s source=%s evidence=%r fallback=%s review=%s",
        source_board,
        job_id,
        result.get("work_mode"),
        result.get("work_mode_source"),
        result.get("work_mode_evidence"),
        result.get("work_mode_source") == "fallback_text",
        result.get("work_mode_needs_review"),
    )


def log_work_mode_result(job_id: str, source_board: str, result: dict) -> None:
    """Log work mode extraction result with job context. Call from scrapers after extracting."""
    _log_result(source_board, result, job_id)
