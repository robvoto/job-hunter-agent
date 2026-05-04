from job_hunter_agent.text_processing import compact_whitespace

MIN_TRUSTED_DESCRIPTION_LENGTH = 600
TRUSTED_DESCRIPTION_SOURCES = frozenset({"jobaddetails", "body", "linkedin_full_description"})


def get_trusted_full_description(record: dict) -> str:
    """Return the trusted full description text, or empty string if not available.

    Prefers the canonical ``full_description`` field. Falls back to
    ``fit_source_text`` when the source is trusted. Older saved LinkedIn
    snapshots did not always persist ``description_source``; if the detail
    status was OK and the fallback text is long enough, treat that as trusted
    legacy detail text so dashboard rebuilds do not lose evidence.
    """
    full = compact_whitespace(record.get("full_description") or "")
    if full:
        return full
    source = str(record.get("description_source") or "").strip().lower()
    fallback_text = compact_whitespace(record.get("fit_source_text") or "")
    if len(fallback_text) < MIN_TRUSTED_DESCRIPTION_LENGTH:
        return ""
    if source in TRUSTED_DESCRIPTION_SOURCES:
        return fallback_text
    details_status = str(record.get("details_status") or "").strip().lower()
    if details_status == "ok" and not source:
        return fallback_text
    return ""


def full_description_confidence(record: dict) -> str:
    """Return 'HIGH' if a trusted full description is available, else 'LOW'.

    Recomputes HIGH from trusted text first so legacy records with recovered
    detail text are not stuck with an old LOW confidence marker.
    """
    if get_trusted_full_description(record):
        return "HIGH"
    stored = str(record.get("fit_confidence") or "").strip().upper()
    if stored in {"HIGH", "LOW"}:
        return stored
    return "LOW"


def is_description_trusted(record: dict) -> bool:
    """Return True when a trusted full description is available for this record."""
    return full_description_confidence(record) == "HIGH"
