"""Tests for occupation_taxonomy.py: lookup, classification, and cache behaviour."""
import pytest

from job_hunter_agent.database import db_conn, init_db
from job_hunter_agent.occupation_taxonomy import (
    RESULT_FAR,
    RESULT_NEAR,
    RESULT_UNCERTAIN,
    classify_title,
)

# Minimal test index.
# SOC major groups used:
#   13 = Business and Financial Operations  (target family for ANALYST_PROFILE)
#   11 = Management                         (also-consider family for ANALYST_PROFILE)
#   35 = Food Preparation and Serving       (clearly far from an analyst profile)
_TEST_INDEX = {
    "business analyst": [
        {
            "occupation_code": "13-1111.00",
            "occupation_title": "Management Analysts",
            "source": "occupation_title",
        }
    ],
    "project manager": [
        {
            "occupation_code": "11-9199.00",
            "occupation_title": "Managers, All Other",
            "source": "occupation_title",
        }
    ],
    # Alternate title pointing to same code as "business analyst"
    "management consultant": [
        {
            "occupation_code": "13-1111.00",
            "occupation_title": "Management Analysts",
            "matched_title": "Management Consultant",
            "source": "alternate_title",
        }
    ],
    # Clearly unrelated occupation family
    "chef": [
        {
            "occupation_code": "35-1011.00",
            "occupation_title": "Chefs and Head Cooks",
            "source": "occupation_title",
        }
    ],
    # Multiple distinct codes → ambiguous
    "coordinator": [
        {
            "occupation_code": "11-3121.00",
            "occupation_title": "Human Resources Managers",
            "source": "alternate_title",
        },
        {
            "occupation_code": "43-6014.00",
            "occupation_title": "Secretaries and Administrative Assistants",
            "source": "alternate_title",
        },
    ],
    # Two entries, same code — should resolve as near (not ambiguous)
    "analyst": [
        {
            "occupation_code": "13-1111.00",
            "occupation_title": "Management Analysts",
            "source": "occupation_title",
        },
        {
            "occupation_code": "13-1111.00",
            "occupation_title": "Management Analysts",
            "matched_title": "Analyst",
            "source": "alternate_title",
        },
    ],
}

_ANALYST_PROFILE = {
    "target_roles": ["business analyst"],
    "also_consider_roles": ["project manager"],
}


@pytest.fixture()
def tmp_db(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)
    return db


# ── exact title lookup ────────────────────────────────────────────────────────

def test_exact_title_returns_near(tmp_db):
    result = classify_title("business analyst", _ANALYST_PROFILE, db_path=tmp_db, _index=_TEST_INDEX)
    assert result.result == RESULT_NEAR
    assert result.matched_occupation_code == "13-1111.00"
    assert result.confidence > 0.5


def test_title_normalisation_applied(tmp_db):
    # Uppercase and extra spaces should match after normalisation.
    result = classify_title("Business  Analyst", _ANALYST_PROFILE, db_path=tmp_db, _index=_TEST_INDEX)
    assert result.result == RESULT_NEAR


def test_duplicate_entries_same_code_resolves_near(tmp_db):
    # Two index entries for same occupation_code must not trigger ambiguous path.
    result = classify_title("analyst", _ANALYST_PROFILE, db_path=tmp_db, _index=_TEST_INDEX)
    assert result.result == RESULT_NEAR
    assert result.matched_occupation_code == "13-1111.00"


# ── alternate title lookup ────────────────────────────────────────────────────

def test_alternate_title_returns_near(tmp_db):
    result = classify_title("management consultant", _ANALYST_PROFILE, db_path=tmp_db, _index=_TEST_INDEX)
    assert result.result == RESULT_NEAR
    assert result.matched_occupation_code == "13-1111.00"


# ── no match → uncertain ──────────────────────────────────────────────────────

def test_no_match_returns_uncertain(tmp_db):
    result = classify_title("ict portfolio transformation lead", _ANALYST_PROFILE, db_path=tmp_db, _index=_TEST_INDEX)
    assert result.result == RESULT_UNCERTAIN
    assert result.matched_occupation_code is None
    assert result.reason == "no_match"
    assert result.confidence == 0.0


# ── ambiguous match → uncertain ───────────────────────────────────────────────

def test_ambiguous_match_returns_uncertain(tmp_db):
    result = classify_title("coordinator", _ANALYST_PROFILE, db_path=tmp_db, _index=_TEST_INDEX)
    assert result.result == RESULT_UNCERTAIN
    assert result.reason == "ambiguous"
    assert result.matched_occupation_code is None


# ── far occupation family ─────────────────────────────────────────────────────

def test_far_occupation_returns_far(tmp_db):
    result = classify_title("chef", _ANALYST_PROFILE, db_path=tmp_db, _index=_TEST_INDEX)
    assert result.result == RESULT_FAR
    assert result.matched_occupation_code == "35-1011.00"
    assert result.confidence > 0.5


# ── cache hit returns cached result ──────────────────────────────────────────

def test_cache_hit_returns_cached_result(tmp_db):
    # First call classifies and writes to cache.
    first = classify_title("business analyst", _ANALYST_PROFILE, db_path=tmp_db, _index=_TEST_INDEX)
    assert first.result == RESULT_NEAR

    # Second call with an empty index — must come from cache, not re-classify.
    second = classify_title("business analyst", _ANALYST_PROFILE, db_path=tmp_db, _index={})
    assert second.result == RESULT_NEAR
    assert second.reason == "cached"


def test_cache_is_keyed_by_profile_hash(tmp_db):
    # Different profiles must not share cached decisions.
    other_profile = {"target_roles": [], "also_consider_roles": []}
    classify_title("business analyst", _ANALYST_PROFILE, db_path=tmp_db, _index=_TEST_INDEX)
    result = classify_title("business analyst", other_profile, db_path=tmp_db, _index=_TEST_INDEX)
    assert result.result == RESULT_UNCERTAIN
    assert result.reason == "no_profile_context"


# ── no profile context → uncertain ───────────────────────────────────────────

def test_no_profile_context_returns_uncertain(tmp_db):
    empty_profile: dict = {"target_roles": [], "also_consider_roles": []}
    result = classify_title("business analyst", empty_profile, db_path=tmp_db, _index=_TEST_INDEX)
    assert result.result == RESULT_UNCERTAIN
    assert result.reason == "no_profile_context"
    # occupation_code is still set so callers can see what O*NET found
    assert result.matched_occupation_code == "13-1111.00"


def test_profile_with_unknown_roles_returns_uncertain(tmp_db):
    # Profile roles that don't exist in the index yield no SOC groups.
    unknown_profile = {
        "target_roles": ["ict portfolio transformation lead"],
        "also_consider_roles": [],
    }
    result = classify_title("business analyst", unknown_profile, db_path=tmp_db, _index=_TEST_INDEX)
    assert result.result == RESULT_UNCERTAIN
    assert result.reason == "no_profile_context"


# ── target_occupation_queries ─────────────────────────────────────────────────

def test_target_occupation_queries_preferred_over_vague_target_roles(tmp_db):
    """Precise machine-facing queries must be used instead of vague display titles.

    Scenario: the display title "coordinator" is ambiguous in O*NET (two distinct
    SOC codes → uncertain by itself). But target_occupation_queries includes
    "business analyst" which maps clearly to SOC major group 13. A job title
    of "analyst" (SOC 13-xxxx) must therefore classify as near.
    """
    profile = {
        "target_roles": ["coordinator"],          # vague — would yield no useful SOC groups
        "also_consider_roles": [],
        "target_occupation_queries": ["business analyst"],  # precise → SOC group 13
    }
    result = classify_title("analyst", profile, db_path=tmp_db, _index=_TEST_INDEX)
    assert result.result == RESULT_NEAR
    assert result.matched_occupation_code == "13-1111.00"


def test_missing_target_occupation_queries_falls_back_to_target_roles(tmp_db):
    """When target_occupation_queries is absent, classification uses target_roles as before."""
    profile_without_queries = {
        "target_roles": ["business analyst"],
        "also_consider_roles": ["project manager"],
        # no target_occupation_queries key
    }
    result = classify_title("analyst", profile_without_queries, db_path=tmp_db, _index=_TEST_INDEX)
    assert result.result == RESULT_NEAR
    assert result.matched_occupation_code == "13-1111.00"


def test_empty_target_occupation_queries_falls_back_to_target_roles(tmp_db):
    """An empty list must not suppress the target_roles fallback."""
    profile = {
        "target_roles": ["business analyst"],
        "also_consider_roles": [],
        "target_occupation_queries": [],
    }
    result = classify_title("analyst", profile, db_path=tmp_db, _index=_TEST_INDEX)
    assert result.result == RESULT_NEAR


# ── ONET_TITLE_CLASSIFY log event ─────────────────────────────────────────────

def test_onet_classify_log_emitted(tmp_db, caplog):
    """A structured ONET_TITLE_CLASSIFY log line must be written for every classification."""
    import logging
    with caplog.at_level(logging.INFO, logger="job_hunter_agent.occupation_taxonomy"):
        classify_title("business analyst", _ANALYST_PROFILE, db_path=tmp_db, _index=_TEST_INDEX)
    assert any("ONET_TITLE_CLASSIFY" in r.message for r in caplog.records)
