"""Tests for profile learning."""

import logging
import hashlib as _hashlib
from unittest.mock import patch

import pytest

from job_hunter_agent import profile_learning
from job_hunter_agent.profile_learning import build_learning_patch
from job_hunter_agent.profile_store import VALID_CAPABILITY_ICON_KEYS

SAMPLE_CV = """
# Professional Summary
Senior Delivery Lead with experience across payments, process improvement, and delivery support.

# Professional Experience
Acme Bank - Senior Delivery Lead (2022 - Present)
- Led requirements workshops for payments change initiatives.
- Produced process maps, user stories, and business requirements for regulatory delivery.
- Coordinated stakeholders across technology and operations teams.

Northstar Consulting - Delivery Analyst (2019 - 2022)
- Ran stakeholder interviews and backlog refinement for digital transformation programs.
- Supported test planning, data analysis, and business process improvements.

City Services - Project Coordinator (2016 - 2019)
- Managed delivery reporting, governance packs, and vendor coordination.

# Skills
Business analysis
Requirements gathering
Stakeholder engagement
Process mapping
Payments
"""

_LLM_FIXTURE = {
    "capabilities": [
        {
            "name": "stakeholder engagement",
            "level": "strong",
            "fit": "core",
            "aliases": ["stakeholder management"],
            "icon_key": "communication_stakeholders",
        },
        {
            "name": "process mapping",
            "level": "working",
            "fit": "core",
            "aliases": [],
            "icon_key": "operations_process",
        },
        {
            "name": "requirements analysis",
            "level": "strong",
            "fit": "core",
            "aliases": ["requirements gathering"],
            "icon_key": "analysis_requirements",
        },
    ],
    "role_experience": [
        {"title": "Delivery Lead", "duration_months": 36, "end_year": 2025, "is_current": True},
        {"title": "Project Coordinator", "duration_months": 36, "end_year": 2019},
    ],
    "role_titles": ["delivery lead", "project coordinator"],
    "preferred_role_titles": ["delivery lead"],
    "alternative_role_titles": ["project coordinator"],
    "target_occupation_queries": ["Delivery Lead", "Project Coordinator"],
    "match_preferences": {
        "prefer_permanent": None,
        "work_mode_preference": None,
        "home_location": "",
    },
    "eligibility": [
        {
            "name": "PV clearance",
            "value": True,
            "evidence": ["Baseline Security Clearance"],
            "needs_review": False,
        }
    ],
}


def test_build_learning_patch_returns_titles_capabilities_and_queries_without_parser():
    with (
        patch("job_hunter_agent.profile_learning._llm_extract_from_cv", return_value=_LLM_FIXTURE),
        patch(
            "job_hunter_agent.profile_learning.signal_in_approved_knowledge",
            return_value=(False, ""),
        ),
    ):
        patch_result = build_learning_patch(SAMPLE_CV)

    assert "cv_text" not in patch_result
    rules = patch_result.get("candidate_capabilities", [])
    assert rules
    names = {r["name"] for r in rules}
    assert "stakeholder engagement" in names
    assert "process mapping" in names
    assert all(rule["icon_key"] in VALID_CAPABILITY_ICON_KEYS for rule in rules)
    assert patch_result["target_roles"] == ["delivery lead"]
    assert patch_result["also_consider_roles"] == ["project coordinator"]
    assert patch_result["target_occupation_queries"] == ["Delivery Lead", "Project Coordinator"]
    assert patch_result["candidate_eligibility"][0]["name"] == "PV clearance"
    assert patch_result["candidate_eligibility"][0]["value"] is True
    assert patch_result["role_experience"] == [
        {
            "normalized_title": "delivery lead",
            "total_duration_months": 36,
            "most_recent_end_year": profile_learning._CURRENT_YEAR,
            "title_variants": [
                {
                    "normalized_title": "delivery lead",
                    "total_duration_months": 36,
                    "most_recent_end_year": profile_learning._CURRENT_YEAR,
                }
            ],
        },
        {
            "normalized_title": "project coordinator",
            "total_duration_months": 36,
            "most_recent_end_year": 2019,
            "title_variants": [
                {
                    "normalized_title": "project coordinator",
                    "total_duration_months": 36,
                    "most_recent_end_year": 2019,
                }
            ],
        },
    ]


def test_build_learning_patch_groups_role_experience_by_normalized_title():
    fixture = {
        "capabilities": [
            {
                "name": "stakeholder engagement",
                "level": "strong",
                "aliases": [],
                "icon_key": "communication_stakeholders",
                "needs_review": False,
            },
        ],
        "role_experience": [
            {"title": "Senior Business Analyst", "duration_months": 24, "end_year": 2024},
            {"title": " senior   business analyst ", "duration_months": 18, "end_year": 2022},
            {"title": "", "duration_months": 12, "end_year": 2020},
        ],
        "role_titles": ["Business Analyst"],
        "preferred_role_titles": ["Business Analyst"],
        "alternative_role_titles": [],
        "target_occupation_queries": ["Business Analyst"],
        "match_preferences": {},
    }

    with (
        patch("job_hunter_agent.profile_learning._llm_extract_from_cv", return_value=fixture),
        patch(
            "job_hunter_agent.profile_learning.signal_in_approved_knowledge",
            return_value=(False, ""),
        ),
    ):
        patch_result = build_learning_patch(SAMPLE_CV)

    assert patch_result["role_experience"] == [
        {
            "normalized_title": "senior business analyst",
            "total_duration_months": 42,
            "most_recent_end_year": 2024,
            "title_variants": [
                {
                    "normalized_title": "senior business analyst",
                    "total_duration_months": 42,
                    "most_recent_end_year": 2024,
                }
            ],
        }
    ]


def test_build_learning_patch_groups_role_experience_by_canonical_title_and_preserves_variants():
    fixture = {
        "capabilities": [
            {
                "name": "stakeholder engagement",
                "level": "strong",
                "aliases": [],
                "icon_key": "communication_stakeholders",
                "needs_review": False,
            },
        ],
        "role_experience": [
            {
                "title": "BA",
                "canonical_title": "Business Analyst",
                "duration_months": 12,
                "end_year": 2020,
            },
            {
                "title": "Business Analyst",
                "canonical_title": "Business Analyst",
                "duration_months": 24,
                "end_year": 2022,
            },
            {
                "title": "Senior BA",
                "canonical_title": "Business Analyst",
                "duration_months": 24,
                "end_year": 2024,
            },
        ],
        "role_titles": ["BA", "Business Analyst", "Senior BA"],
        "preferred_role_titles": ["Business Analyst"],
        "alternative_role_titles": [],
        "target_occupation_queries": ["Business Analyst"],
        "match_preferences": {},
    }

    with (
        patch("job_hunter_agent.profile_learning._llm_extract_from_cv", return_value=fixture),
        patch(
            "job_hunter_agent.profile_learning.signal_in_approved_knowledge",
            return_value=(False, ""),
        ),
    ):
        patch_result = build_learning_patch(SAMPLE_CV)

    assert patch_result["role_experience"] == [
        {
            "normalized_title": "business analyst",
            "total_duration_months": 60,
            "most_recent_end_year": 2024,
            "title_variants": [
                {
                    "normalized_title": "ba",
                    "total_duration_months": 12,
                    "most_recent_end_year": 2020,
                },
                {
                    "normalized_title": "business analyst",
                    "total_duration_months": 24,
                    "most_recent_end_year": 2022,
                },
                {
                    "normalized_title": "senior ba",
                    "total_duration_months": 24,
                    "most_recent_end_year": 2024,
                },
            ],
        }
    ]


@pytest.mark.parametrize(
    "fixture, expected",
    [
        (
            {
                "capabilities": [
                    {
                        "name": "stakeholder engagement",
                        "level": "strong",
                        "aliases": [],
                        "icon_key": "communication_stakeholders",
                        "needs_review": False,
                    },
                ],
                "role_titles": [],
                "preferred_role_titles": [],
                "alternative_role_titles": [],
                "target_occupation_queries": ["Delivery Lead"],
                "match_preferences": {},
            },
            "role titles, preferred role titles",
        ),
        (
            {
                "capabilities": [],
                "role_titles": ["Delivery Lead"],
                "preferred_role_titles": ["Delivery Lead"],
                "alternative_role_titles": [],
                "target_occupation_queries": ["Delivery Lead"],
                "match_preferences": {},
            },
            "capability groups",
        ),
        (
            {
                "capabilities": [
                    {
                        "name": "stakeholder engagement",
                        "level": "strong",
                        "aliases": [],
                        "icon_key": "communication_stakeholders",
                        "needs_review": False,
                    },
                ],
                "role_titles": ["Delivery Lead"],
                "preferred_role_titles": ["Delivery Lead"],
                "alternative_role_titles": [],
                "target_occupation_queries": [],
                "match_preferences": {},
            },
            "target occupation queries",
        ),
    ],
)
def test_build_learning_patch_raises_when_llm_omits_required_fields(fixture, expected):
    with (
        patch("job_hunter_agent.profile_learning._llm_extract_from_cv", return_value=fixture),
        patch(
            "job_hunter_agent.profile_learning.signal_in_approved_knowledge",
            return_value=(False, ""),
        ),
    ):
        with pytest.raises(ValueError, match=expected):
            build_learning_patch(SAMPLE_CV)


@pytest.mark.parametrize(
    "fixture",
    [
        {
            "capabilities": [
                {
                    "name": "stakeholder engagement",
                    "level": "strong",
                    "aliases": [],
                    "needs_review": False,
                },
            ],
            "role_titles": ["Delivery Lead"],
            "preferred_role_titles": ["Delivery Lead"],
            "alternative_role_titles": [],
            "target_occupation_queries": ["Delivery Lead"],
            "match_preferences": {},
        },
        {
            "capabilities": [
                {
                    "name": "stakeholder engagement",
                    "level": "strong",
                    "aliases": [],
                    "icon_key": "not_real",
                    "needs_review": False,
                },
            ],
            "role_titles": ["Delivery Lead"],
            "preferred_role_titles": ["Delivery Lead"],
            "alternative_role_titles": [],
            "target_occupation_queries": ["Delivery Lead"],
            "match_preferences": {},
        },
    ],
)
def test_build_learning_patch_rejects_missing_or_invalid_icon_key(fixture):
    with (
        patch("job_hunter_agent.profile_learning._llm_extract_from_cv", return_value=fixture),
        patch(
            "job_hunter_agent.profile_learning.signal_in_approved_knowledge",
            return_value=(False, ""),
        ),
    ):
        with pytest.raises(ValueError, match="icon_key"):
            build_learning_patch(SAMPLE_CV)


def test_build_learning_patch_does_not_register_title_normalization_candidate_signals():
    captured = []

    def fake_register_signals(items):
        captured.extend(items)

    with (
        patch(
            "job_hunter_agent.profile_learning._llm_extract_from_cv",
            return_value={
                "capabilities": [
                    {
                        "name": "business analysis",
                        "level": "working",
                        "aliases": [],
                        "icon_key": "analysis_requirements",
                        "needs_review": False,
                    },
                ],
                "role_titles": ["Business Analyst"],
                "preferred_role_titles": ["Business Analyst"],
                "alternative_role_titles": [],
                "target_occupation_queries": ["Business Analyst"],
                "match_preferences": {},
            },
        ),
        patch(
            "job_hunter_agent.profile_learning.signal_in_approved_knowledge",
            return_value=(False, ""),
        ),
        patch(
            "job_hunter_agent.profile_learning.register_signals", side_effect=fake_register_signals
        ),
    ):
        build_learning_patch("CV text")

    assert not any(
        item.get("suggested_category") == "title_normalization_candidate" for item in captured
    )


def test_build_learning_patch_routes_uncertain_capabilities_to_signal_registry():
    fixture = {
        "capabilities": [
            {
                "name": "business analysis",
                "level": "strong",
                "aliases": [],
                "icon_key": "analysis_requirements",
                "needs_review": False,
            },
            {
                "name": "unknown platform",
                "level": "working",
                "aliases": ["mystery platform"],
                "icon_key": "systems_platforms",
                "needs_review": True,
            },
            {
                "name": "api design",
                "level": "basic",
                "aliases": [],
                "icon_key": "technical_build",
                "needs_review": True,
            },
        ],
        "role_titles": ["Business Analyst"],
        "preferred_role_titles": ["Business Analyst"],
        "alternative_role_titles": [],
        "target_occupation_queries": ["Business Analyst"],
        "match_preferences": {},
    }
    captured = []

    def fake_knowledge_match(category, name, aliases=None):
        if name == "api design":
            return True, "API design"
        return False, ""

    def fake_register_signals(items):
        captured.extend(items)

    with (
        patch("job_hunter_agent.profile_learning._llm_extract_from_cv", return_value=fixture),
        patch(
            "job_hunter_agent.profile_learning.signal_in_approved_knowledge",
            side_effect=fake_knowledge_match,
        ),
        patch(
            "job_hunter_agent.profile_learning.register_signals", side_effect=fake_register_signals
        ),
    ):
        patch_result = build_learning_patch(
            SAMPLE_CV, source_sections=[{"label": "Skills", "text": "unknown platform"}]
        )

    rules = patch_result.get("candidate_capabilities", [])
    assert [rule["name"] for rule in rules] == ["business analysis", "api design"]
    assert rules[1]["knowledge_match"] == "API design"
    assert captured == [
        {
            "signal": "unknown platform",
            "category": "capability_concept",
            "source": "CV parsing",
            "context": ["Skills: unknown platform"],
            "evidence": ["unknown platform", "mystery platform"],
            "aliases": ["mystery platform"],
            "needs_review": True,
        }
    ]


def test_build_learning_patch_does_not_emit_hard_blocker_pattern():
    fixture = {
        "capabilities": [
            {
                "name": "unknown platform",
                "level": "working",
                "aliases": [],
                "icon_key": "systems_platforms",
                "needs_review": False,
            },
        ],
        "role_titles": ["Business Analyst"],
        "preferred_role_titles": ["Business Analyst"],
        "alternative_role_titles": [],
        "target_occupation_queries": ["Business Analyst"],
        "match_preferences": {},
    }
    captured = []

    def fake_register_signals(items):
        captured.extend(items)

    with (
        patch("job_hunter_agent.profile_learning._llm_extract_from_cv", return_value=fixture),
        patch(
            "job_hunter_agent.profile_learning.signal_in_approved_knowledge",
            return_value=(False, ""),
        ),
        patch(
            "job_hunter_agent.profile_learning.register_signals", side_effect=fake_register_signals
        ),
    ):
        build_learning_patch(
            SAMPLE_CV, source_sections=[{"label": "Skills", "text": "unknown platform"}]
        )

    assert all(item.get("category") != "hard_blocker_pattern" for item in captured)


def test_update_job_history_does_not_write_sightings():
    from job_hunter_agent.history import update_job_history

    history: dict = {}
    record = {
        "job_key": "seek:999",
        "title": "Business Analyst",
        "company": "Acme",
        "url": "https://seek.com/job/999",
        "source": "seek",
        "decision": "KEEP",
        "posted": "3 days ago",
        "posted_age_days": 3,
    }
    update_job_history(history, record, "2026-01-01T00:00:00+10:00")

    entry = history["seek:999"]
    assert "sightings" not in entry
    assert entry["times_seen"] == 1
    assert entry["first_seen_at"] == "2026-01-01T00:00:00+10:00"
    assert entry["last_seen_at"] == "2026-01-01T00:00:00+10:00"


# CV extraction disk cache (regression: in-memory cache lost on server restart)


def _reset_cv_extraction_cache():
    profile_learning._cv_extraction_cache.clear()
    profile_learning._cv_extraction_cache_loaded = False


def test_llm_extract_from_cv_cache_hit_skips_save(caplog):
    """A cache hit must return the stored result without calling save."""
    cv_text = "Test CV for cache-hit test"
    lookback, alias_limit = 5, 3
    cache_key = _hashlib.sha256(f"role-tier-v1:{lookback}:{alias_limit}:{cv_text}".encode()).hexdigest()[
        :16
    ]
    fake_result = {
        "capabilities": [{"name": "delivery management", "icon_key": "delivery_project"}]
    }

    _reset_cv_extraction_cache()
    profile_learning._cv_extraction_cache[cache_key] = fake_result

    saved = []
    with (
        patch("job_hunter_agent.profile_learning._ensure_cv_extraction_cache_loaded"),
        patch("job_hunter_agent.io_utils.save_cv_extraction_cache", side_effect=saved.append),
        caplog.at_level(logging.INFO, logger="job_hunter_agent.profile_learning"),
    ):
        result = profile_learning._llm_extract_from_cv(cv_text, lookback, alias_limit)

    assert result == fake_result
    assert saved == [], "save must not be called on a cache hit"
    assert "[ONBOARDING][LLM_CACHE_HIT] purpose=cv_extraction" in caplog.text
    assert "capabilities=1" in caplog.text


def test_llm_extract_from_cv_logs_when_client_is_unavailable(caplog, monkeypatch):
    cv_text = "Test CV for unavailable-client test"
    lookback, alias_limit = 5, 3

    _reset_cv_extraction_cache()
    monkeypatch.setattr(profile_learning, "_ensure_cv_extraction_cache_loaded", lambda: None)
    monkeypatch.setattr("job_hunter_agent.llm_gate.client", None)

    with caplog.at_level(logging.INFO, logger="job_hunter_agent.profile_learning"):
        result = profile_learning._llm_extract_from_cv(cv_text, lookback, alias_limit)

    assert result == {}
    assert "[ONBOARDING][LLM_CALL_SKIPPED] purpose=cv_extraction" in caplog.text
    assert "reason=missing_openai_api_key" in caplog.text


def test_llm_extract_from_cv_loads_disk_cache_before_calling_llm():
    """Simulates server restart: disk cache has a prior result; LLM must not be called."""
    cv_text = "My CV content for disk restore test"
    lookback, alias_limit = 5, 3
    cache_key = _hashlib.sha256(f"role-tier-v1:{lookback}:{alias_limit}:{cv_text}".encode()).hexdigest()[
        :16
    ]
    prior_result = {
        "capabilities": [
            {"name": "stakeholder engagement", "icon_key": "communication_stakeholders"}
        ]
    }

    _reset_cv_extraction_cache()

    def fake_load():
        return {cache_key: prior_result}

    with (
        patch("job_hunter_agent.io_utils.load_cv_extraction_cache", side_effect=fake_load),
        patch("job_hunter_agent.io_utils.save_cv_extraction_cache"),
    ):
        profile_learning._cv_extraction_cache_loaded = False
        profile_learning._ensure_cv_extraction_cache_loaded()

        assert cache_key in profile_learning._cv_extraction_cache

        saved = []
        with patch("job_hunter_agent.io_utils.save_cv_extraction_cache", side_effect=saved.append):
            result = profile_learning._llm_extract_from_cv(cv_text, lookback, alias_limit)

    assert result == prior_result
    assert saved == [], "save must not be called when the disk cache already had the entry"
