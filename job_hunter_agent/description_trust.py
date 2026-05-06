from job_hunter_agent.text_processing import compact_whitespace
from job_hunter_agent.io_utils import load_parsing_rules
from job_hunter_agent.parsing_schema import PARSING_TRUSTED_DESCRIPTION_SOURCES_KEY
from job_hunter_agent.record_schema import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    RECORD_DESCRIPTION_SOURCE_KEY,
    RECORD_FIT_SOURCE_TEXT_KEY,
    RECORD_FULL_DESCRIPTION_KEY,
)

MIN_TRUSTED_DESCRIPTION_LENGTH = 600

def _trusted_sources():
    return set(load_parsing_rules().get(PARSING_TRUSTED_DESCRIPTION_SOURCES_KEY, []))

def get_trusted_sources() -> set[str]:
    """Return the set of sources allowed to provide full descriptions."""
    return _trusted_sources()


def get_trusted_full_description(record: dict) -> str:
    """Return the trusted full description text, or empty string if not available.

    Prefers the canonical full_description field. Falls back to
    fit_source_text only when the source is explicitly trusted.
    """
    full = compact_whitespace(record.get(RECORD_FULL_DESCRIPTION_KEY) or "")
    if full:
        return full

    source = str(record.get(RECORD_DESCRIPTION_SOURCE_KEY) or "").strip().lower()
    fallback_text = compact_whitespace(record.get(RECORD_FIT_SOURCE_TEXT_KEY) or "")

    if len(fallback_text) < MIN_TRUSTED_DESCRIPTION_LENGTH:
        return ""

    if source in _trusted_sources():
        return fallback_text

    return ""

def full_description_confidence(record: dict) -> str:
    """Return HIGH when a trusted full description is available, else LOW."""
    if get_trusted_full_description(record):
        return CONFIDENCE_HIGH
    return CONFIDENCE_LOW


def is_description_trusted(record: dict) -> bool:
    """Return True when a trusted full description is available for this record."""
    return bool(get_trusted_full_description(record))
