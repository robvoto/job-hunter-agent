import pytest
from job_hunter_agent.job_identity import normalize_job_key, _normalized_job_key
from job_hunter_agent.record_schema import RECORD_JOB_KEY, RECORD_SOURCE_KEY, RECORD_URL_KEY

def test_normalize_job_key_canonical():
    """Verify that already canonical keys are returned as-is."""
    assert normalize_job_key("seek:12345") == "seek:12345"
    assert normalize_job_key("linkedin:abc_123") == "linkedin:abc_123"
    assert normalize_job_key("indeed:99-88") == "indeed:99-88"

def test_normalize_job_key_seek_url():
    """Verify extraction from various SEEK URL formats."""
    # Standard URL
    assert normalize_job_key("https://www.seek.com.au/job/7945621") == "seek:7945621"
    # URL with tracking parameters
    assert normalize_job_key("https://seek.com.au/job/7945621?type=standout&tracking=abc") == "seek:7945621"
    # Source passed explicitly overrides/confirms
    assert normalize_job_key("https://www.seek.com.au/job/7945621", source="seek") == "seek:7945621"

def test_normalize_job_key_linkedin_url():
    """Verify extraction from various LinkedIn URL formats."""
    # Standard view URL
    assert normalize_job_key("https://www.linkedin.com/jobs/view/39845512/") == "linkedin:39845512"
    # URL with query string
    assert normalize_job_key("https://linkedin.com/jobs/view/39845512?refId=xyz") == "linkedin:39845512"
    # Alternative 'job' instead of 'jobs'
    assert normalize_job_key("https://www.linkedin.com/job/view/39845512") == "linkedin:39845512"

def test_normalize_job_key_raw_id_with_source():
    """Verify that raw numeric IDs are namespaced when source is provided."""
    assert normalize_job_key("7945621", source="seek") == "seek:7945621"
    assert normalize_job_key("39845512", source="LinkedIn") == "linkedin:39845512"
    assert normalize_job_key("123", source="  indeed  ") == "indeed:123"

def test_normalize_job_key_invalid_cases():
    """Verify that ambiguous or invalid inputs return an empty string (Prototype Strictness)."""
    # Empty/None
    assert normalize_job_key("") == ""
    assert normalize_job_key(None) == ""
    
    # Missing source context for raw IDs is rejected in strict mode
    assert normalize_job_key("12345") == ""
    
    # Unrecognized URL domain without explicit source
    assert normalize_job_key("https://unknown-board.com/job/123") == ""
    
    # Malformed canonical key (e.g. spaces or invalid chars)
    assert normalize_job_key("seek : 123") == ""
    assert normalize_job_key("seek:123 456") == ""

def test_normalize_job_key_case_and_spacing():
    """Verify robustness to casing and whitespace."""
    # Normalizing source to lowercase
    assert normalize_job_key("SEEK:12345") == "seek:12345"
    # Mixed case URLs
    assert normalize_job_key("https://www.SEEK.com.au/JOB/12345") == "seek:12345"
    # Whitespace stripping
    assert normalize_job_key("  seek:12345  ") == "seek:12345"
    assert normalize_job_key("\thttps://seek.com.au/job/123\n") == "seek:123"

def test_record_helper_normalization():
    """Ensure the internal record-based helper uses schema constants correctly."""
    record = {
        RECORD_JOB_KEY: "https://seek.com.au/job/12345",
        RECORD_SOURCE_KEY: "SEEK"
    }
    assert _normalized_job_key(record) == "seek:12345"
    
    record_no_key = {RECORD_URL_KEY: "https://linkedin.com/jobs/view/999"}
    # This currently requires RECORD_JOB_KEY or source metadata; verification of fallback logic
    assert _normalized_job_key(record_no_key) == ""