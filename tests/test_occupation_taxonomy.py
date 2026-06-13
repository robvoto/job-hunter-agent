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
_TEST_INDEX = {
    "business analyst": [
        {
            "occupation_code": "13-1111.00",
            "occupation_title": "Management Analysts",
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
    "software developers": [
        {
            "occupation_code": "15-1252.00",
            "occupation_title": "Software Developers",
            "source": "occupation_title",
        }
    ],
    "software engineer": [
        {
            "occupation_code": "15-1252.00",
            "occupation_title": "Software Developers",
            "matched_title": "Software Engineer",
            "source": "alternate_title",
        }
    ],
    "engineer": [
        {
            "occupation_code": "15-1252.00",
            "occupation_title": "Software Developers",
            "matched_title": "Engineer",
            "source": "alternate_title",
        }
    ],
    "data engineer": [
        {
            "occupation_code": "15-2051.00",
            "occupation_title": "Data Scientists",
            "matched_title": "Data Engineer",
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
    "project management specialist": [
        {
            "occupation_code": "13-1082.00",
            "occupation_title": "Project Management Specialists",
            "source": "occupation_title",
        }
    ],
    "project delivery manager": [
        {
            "occupation_code": "13-1082.00",
            "occupation_title": "Project Management Specialists",
            "matched_title": "Project Delivery Manager",
            "source": "alternate_title",
        }
    ],
    "accountant": [
        {
            "occupation_code": "13-2011.00",
            "occupation_title": "Accountants and Auditors",
            "source": "occupation_title",
        }
    ],
    "bookkeeper": [
        {
            "occupation_code": "43-3031.00",
            "occupation_title": "Bookkeeping, Accounting, and Auditing Clerks",
            "source": "occupation_title",
        }
    ],
    "payroll clerk": [
        {
            "occupation_code": "43-3051.00",
            "occupation_title": "Payroll and Timekeeping Clerks",
            "source": "occupation_title",
        }
    ],
    "accounts payable officer": [
        {
            "occupation_code": "43-3031.00",
            "occupation_title": "Bookkeeping, Accounting, and Auditing Clerks",
            "matched_title": "Accounts Payable Officer",
            "source": "alternate_title",
        }
    ],
    "office administrator": [
        {
            "occupation_code": "43-6014.00",
            "occupation_title": "Secretaries and Administrative Assistants",
            "source": "occupation_title",
        }
    ],
    "administrative assistant": [
        {
            "occupation_code": "43-6014.00",
            "occupation_title": "Secretaries and Administrative Assistants",
            "matched_title": "Administrative Assistant",
            "source": "alternate_title",
        }
    ],
    "electrician": [
        {
            "occupation_code": "47-2111.00",
            "occupation_title": "Electricians",
            "source": "occupation_title",
        }
    ],
    "registered nurse": [
        {
            "occupation_code": "29-1141.00",
            "occupation_title": "Registered Nurses",
            "source": "occupation_title",
        }
    ],
    "nurse": [
        {
            "occupation_code": "29-1141.00",
            "occupation_title": "Registered Nurses",
            "matched_title": "Nurse",
            "source": "alternate_title",
        }
    ],
    "help desk technician": [
        {
            "occupation_code": "15-1232.00",
            "occupation_title": "Computer User Support Specialists",
            "source": "occupation_title",
        }
    ],
}

_ANALYST_PROFILE = {
    "target_occupation_queries": ["business analyst"],
    "target_roles": ["chef"],
    "also_consider_roles": ["project manager"],
}

_ACCOUNTING_PROFILE = {
    "target_occupation_queries": ["accountant", "bookkeeper", "payroll clerk"],
}

_SOFTWARE_PROFILE = {
    "target_occupation_queries": ["software developers"],
}

_ADMIN_PROFILE = {
    "target_occupation_queries": ["administrative assistant", "office administrator"],
}

_PROJECT_PROFILE = {
    "target_occupation_queries": ["project management specialist"],
}

_HEALTHCARE_PROFILE = {
    "target_occupation_queries": ["registered nurse"],
}

_ICT_PROFILE = {
    "target_occupation_queries": ["help desk technician"],
}


@pytest.fixture()
def tmp_db(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)
    return db


# ── exact title lookup ────────────────────────────────────────────────────────


def test_exact_title_returns_near(tmp_db):
    result = classify_title(
        "business analyst", _ANALYST_PROFILE, db_path=tmp_db, _index=_TEST_INDEX
    )
    assert result.result == RESULT_NEAR
    assert result.matched_occupation_code == "13-1111.00"
    assert result.confidence > 0.5


def test_title_normalisation_applied(tmp_db):
    # Uppercase and extra spaces should match after normalisation.
    result = classify_title(
        "Business  Analyst", _ANALYST_PROFILE, db_path=tmp_db, _index=_TEST_INDEX
    )
    assert result.result == RESULT_NEAR


def test_duplicate_entries_same_code_resolves_near(tmp_db):
    # Two index entries for same occupation_code must not trigger ambiguous path.
    result = classify_title("analyst", _ANALYST_PROFILE, db_path=tmp_db, _index=_TEST_INDEX)
    assert result.result == RESULT_NEAR
    assert result.matched_occupation_code == "13-1111.00"


# ── alternate title lookup ────────────────────────────────────────────────────


def test_alternate_title_returns_near(tmp_db):
    result = classify_title(
        "management consultant", _ANALYST_PROFILE, db_path=tmp_db, _index=_TEST_INDEX
    )
    assert result.result == RESULT_NEAR
    assert result.matched_occupation_code == "13-1111.00"
    assert result.match_type == "exact_title"
    assert result.matched_phrase == "Management Consultant"


def test_embedded_software_engineer_phrase_returns_near(tmp_db):
    result = classify_title(
        "Senior Software Engineer - Java daily rates up to $1100!",
        _SOFTWARE_PROFILE,
        db_path=tmp_db,
        _index=_TEST_INDEX,
    )
    assert result.result == RESULT_NEAR
    assert result.matched_occupation_code == "15-1252.00"
    assert result.match_type == "onet_phrase"
    assert result.matched_phrase == "Software Engineer"


def test_embedded_accountant_preferred_title_returns_near(tmp_db):
    result = classify_title(
        "Senior Accountant", _ACCOUNTING_PROFILE, db_path=tmp_db, _index=_TEST_INDEX
    )
    assert result.result == RESULT_NEAR
    assert result.matched_occupation_code == "13-2011.00"
    assert result.match_type == "onet_phrase"
    assert result.matched_phrase == "Accountants and Auditors"


def test_one_word_alternate_title_is_not_used_for_embedded_match(tmp_db):
    result = classify_title(
        "AI Core Platform Engineer AWS", _SOFTWARE_PROFILE, db_path=tmp_db, _index=_TEST_INDEX
    )
    assert result.result == RESULT_UNCERTAIN
    assert result.reason == "no_match"
    assert result.match_type == "none"
    assert result.matched_phrase is None


# ── no match → uncertain ──────────────────────────────────────────────────────


def test_no_match_returns_uncertain(tmp_db):
    result = classify_title(
        "ict portfolio transformation lead", _ANALYST_PROFILE, db_path=tmp_db, _index=_TEST_INDEX
    )
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


def test_data_engineer_remains_far_for_accounting_profile(tmp_db):
    result = classify_title(
        "Data Engineer", _ACCOUNTING_PROFILE, db_path=tmp_db, _index=_TEST_INDEX
    )
    assert result.result == RESULT_FAR
    assert result.matched_occupation_code == "15-2051.00"
    assert result.match_type == "exact_title"
    assert result.matched_phrase == "Data Engineer"


# ── cache hit returns cached result ──────────────────────────────────────────


def test_cache_hit_returns_cached_result(tmp_db):
    # First call classifies and writes to cache.
    first = classify_title("business analyst", _ANALYST_PROFILE, db_path=tmp_db, _index=_TEST_INDEX)
    assert first.result == RESULT_NEAR
    assert first.match_type == "exact_title"

    # Second call with an empty index — must come from cache, not re-classify.
    second = classify_title("business analyst", _ANALYST_PROFILE, db_path=tmp_db, _index={})
    assert second.result == RESULT_NEAR
    assert second.reason == "cached"
    assert second.match_type == "exact_title"
    assert second.matched_phrase == "Management Analysts"


def test_cache_is_keyed_by_profile_hash(tmp_db):
    # Different non-query profile fields must not change cache results.
    other_profile = {
        "target_occupation_queries": ["business analyst"],
        "target_roles": ["chef"],
        "also_consider_roles": ["surgeon"],
    }
    classify_title("business analyst", _ANALYST_PROFILE, db_path=tmp_db, _index=_TEST_INDEX)
    result = classify_title("business analyst", other_profile, db_path=tmp_db, _index={})
    assert result.result == RESULT_NEAR
    assert result.reason == "cached"


# ── no profile context → uncertain ───────────────────────────────────────────


def test_no_profile_context_returns_uncertain(tmp_db):
    empty_profile: dict = {
        "target_roles": ["business analyst"],
        "also_consider_roles": ["project manager"],
    }
    result = classify_title("business analyst", empty_profile, db_path=tmp_db, _index=_TEST_INDEX)
    assert result.result == RESULT_UNCERTAIN
    assert result.reason == "no_profile_context"
    # occupation_code is still set so callers can see what O*NET found
    assert result.matched_occupation_code == "13-1111.00"


def test_profile_with_queries_that_do_not_match_returns_uncertain(tmp_db):
    # Unknown queries should not fall back to title strings.
    unknown_profile = {
        "target_occupation_queries": ["ict portfolio transformation lead"],
        "target_roles": ["business analyst"],
        "also_consider_roles": [],
    }
    result = classify_title("business analyst", unknown_profile, db_path=tmp_db, _index=_TEST_INDEX)
    assert result.result == RESULT_UNCERTAIN
    assert result.reason == "no_profile_context"


# ── target_occupation_queries ─────────────────────────────────────────────────


def test_target_occupation_queries_used_for_classification(tmp_db):
    """target_occupation_queries codes must be included when deriving target occupations."""
    result = classify_title(
        "accounts payable officer", _ACCOUNTING_PROFILE, db_path=tmp_db, _index=_TEST_INDEX
    )
    assert result.result == RESULT_NEAR
    assert result.matched_occupation_code == "43-3031.00"


def test_admin_profile_uses_occupation_queries(tmp_db):
    """Multiple target occupation queries should expand the target code set."""
    result = classify_title(
        "office administrator", _ADMIN_PROFILE, db_path=tmp_db, _index=_TEST_INDEX
    )
    assert result.result == RESULT_NEAR
    assert result.matched_occupation_code == "43-6014.00"


def test_missing_target_occupation_queries_does_not_fall_back_to_target_roles(tmp_db):
    """Display titles must not be reused as machine-facing occupation context."""
    profile_without_queries = {
        "target_roles": ["business analyst"],
        "also_consider_roles": ["project manager"],
    }
    result = classify_title(
        "business analyst", profile_without_queries, db_path=tmp_db, _index=_TEST_INDEX
    )
    assert result.result == RESULT_UNCERTAIN
    assert result.reason == "no_profile_context"


def test_empty_target_occupation_queries_does_not_fall_back_to_target_roles(tmp_db):
    """An empty occupation-query list must still leave O*NET uncertain."""
    profile = {
        "target_roles": ["business analyst"],
        "also_consider_roles": [],
        "target_occupation_queries": [],
    }
    result = classify_title("business analyst", profile, db_path=tmp_db, _index=_TEST_INDEX)
    assert result.result == RESULT_UNCERTAIN
    assert result.reason == "no_profile_context"


def test_accounting_profile_accepts_related_occupation_titles(tmp_db):
    cases = [
        ("Accountant", "13-2011.00"),
        ("Payroll Clerk", "43-3051.00"),
        ("Accounts Payable Officer", "43-3031.00"),
    ]

    for title, occupation_code in cases:
        result = classify_title(title, _ACCOUNTING_PROFILE, db_path=tmp_db, _index=_TEST_INDEX)
        assert result.result == RESULT_NEAR
        assert result.matched_occupation_code == occupation_code


def test_admin_profile_keeps_unrelated_titles_far(tmp_db):
    result = classify_title("Electrician", _ADMIN_PROFILE, db_path=tmp_db, _index=_TEST_INDEX)
    assert result.result == RESULT_FAR
    assert result.matched_occupation_code == "47-2111.00"


def test_healthcare_profile_uses_occupation_queries(tmp_db):
    result = classify_title("Nurse", _HEALTHCARE_PROFILE, db_path=tmp_db, _index=_TEST_INDEX)
    assert result.result == RESULT_NEAR
    assert result.matched_occupation_code == "29-1141.00"


def test_ict_profile_uses_occupation_queries(tmp_db):
    result = classify_title(
        "Help Desk Technician", _ICT_PROFILE, db_path=tmp_db, _index=_TEST_INDEX
    )
    assert result.result == RESULT_NEAR
    assert result.matched_occupation_code == "15-1232.00"


def test_project_profile_marks_finance_roles_far(tmp_db):
    for title, occupation_code in [("Accountant", "13-2011.00"), ("Payroll Clerk", "43-3051.00")]:
        result = classify_title(title, _PROJECT_PROFILE, db_path=tmp_db, _index=_TEST_INDEX)
        assert result.result == RESULT_FAR
        assert result.matched_occupation_code == occupation_code


# ── ONET_TITLE_CLASSIFY log event ─────────────────────────────────────────────


def test_onet_classify_log_emitted(tmp_db, caplog):
    """A structured ONET_TITLE_CLASSIFY log line must be written for every classification."""
    import logging

    with caplog.at_level(logging.INFO, logger="job_hunter_agent.occupation_taxonomy"):
        classify_title(
            "Senior Software Engineer - Java daily rates up to $1100!",
            _SOFTWARE_PROFILE,
            db_path=tmp_db,
            _index=_TEST_INDEX,
        )
    assert any("ONET_TITLE_CLASSIFY" in r.message for r in caplog.records)
    assert any("profile_target_occupation_queries" in r.message for r in caplog.records)
    assert any("derived_target_occupation_codes" in r.message for r in caplog.records)
    assert any("matched_occupation_code" in r.message for r in caplog.records)
    assert any("matched_phrase" in r.message for r in caplog.records)
    assert any("match_type" in r.message for r in caplog.records)
    assert any("reason" in r.message for r in caplog.records)


def test_multicode_embedded_phrase_outside_target_returns_far(tmp_db):
    index = dict(_TEST_INDEX)
    index["accountant"] = [
        {"occupation_code": "13-2011.00", "occupation_title": "Accountants and Auditors", "source": "occupation_title"},
        {"occupation_code": "13-2082.00", "occupation_title": "Tax Preparers", "source": "occupation_title"},
    ]
    result = classify_title("Senior Tax Accountant", _ANALYST_PROFILE, db_path=tmp_db, _index=index)
    assert result.result == RESULT_FAR
    assert result.reason == RESULT_FAR
    assert result.matched_occupation_code is None
    assert result.match_type == "onet_phrase"


def test_multicode_embedded_phrase_mixed_target_returns_uncertain(tmp_db):
    index = dict(_TEST_INDEX)
    index["accountant"] = [
        {"occupation_code": "13-2011.00", "occupation_title": "Accountants and Auditors", "source": "occupation_title"},
        {"occupation_code": "13-2082.00", "occupation_title": "Tax Preparers", "source": "occupation_title"},
    ]
    index["audit analyst"] = [
        {"occupation_code": "13-2011.00", "occupation_title": "Accountants and Auditors", "source": "alternate_title"}
    ]
    mixed_profile = {"target_occupation_queries": ["business analyst", "audit analyst"]}
    result = classify_title("Senior Tax Accountant", mixed_profile, db_path=tmp_db, _index=index)
    assert result.result == RESULT_UNCERTAIN
    assert result.reason == "ambiguous"
    assert result.matched_occupation_code is None
    assert result.match_type == "onet_phrase"


def test_multicode_embedded_phrase_without_target_context_returns_uncertain(tmp_db):
    index = dict(_TEST_INDEX)
    index["accountant"] = [
        {"occupation_code": "13-2011.00", "occupation_title": "Accountants and Auditors", "source": "occupation_title"},
        {"occupation_code": "13-2082.00", "occupation_title": "Tax Preparers", "source": "occupation_title"},
    ]
    result = classify_title("Senior Tax Accountant", {}, db_path=tmp_db, _index=index)
    assert result.result == RESULT_UNCERTAIN
    assert result.reason == "no_profile_context"
    assert result.matched_occupation_code is None
    assert result.match_type == "onet_phrase"


def test_multicode_embedded_phrase_all_inside_target_returns_near(tmp_db):
    index = dict(_TEST_INDEX)
    index["accountant"] = [
        {"occupation_code": "13-2011.00", "occupation_title": "Accountants and Auditors", "source": "occupation_title"},
        {"occupation_code": "13-2082.00", "occupation_title": "Tax Preparers", "source": "occupation_title"},
    ]
    profile = {"target_occupation_queries": ["accountant", "tax preparers"]}
    index["tax preparers"] = [
        {"occupation_code": "13-2082.00", "occupation_title": "Tax Preparers", "source": "occupation_title"}
    ]
    result = classify_title("Senior Tax Accountant", profile, db_path=tmp_db, _index=index)
    assert result.result == RESULT_NEAR
    assert result.reason == RESULT_NEAR
    assert result.matched_occupation_code is None
    assert result.match_type == "onet_phrase"


def test_onet_classify_logs_fresh_and_cached_lookups(tmp_db, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="job_hunter_agent.occupation_taxonomy"):
        classify_title("business analyst", _ANALYST_PROFILE, db_path=tmp_db, _index=_TEST_INDEX)
        classify_title("business analyst", _ANALYST_PROFILE, db_path=tmp_db, _index=_TEST_INDEX)

    assert any("lookup_source" in r.message and "fresh" in r.message for r in caplog.records)
    assert any("lookup_source" in r.message and "cache" in r.message for r in caplog.records)
