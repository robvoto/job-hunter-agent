import json
from unittest.mock import patch

import pytest

from job_hunter_agent import profile_learning
from job_hunter_agent import role_title_knowledge
from job_hunter_agent.profile_learning import (
    _CURRENT_YEAR,
    build_learning_patch,
    build_role_title_review_signals,
    extract_title_pattern_suggestions,
)


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
        {"name": "stakeholder engagement", "level": "strong", "fit": "core", "aliases": ["stakeholder management"]},
        {"name": "process mapping", "level": "working", "fit": "core", "aliases": []},
        {"name": "requirements analysis", "level": "strong", "fit": "core", "aliases": ["requirements gathering"]},
    ],
    "target_roles": ["delivery lead"],
    "also_consider_roles": ["project coordinator"],
    "suggested_search_keywords": ["delivery lead", "business analysis"],
    "match_preferences": {"prefer_permanent": None, "work_mode_preference": None, "home_location": ""},
}


def test_build_learning_patch_returns_capabilities_and_cv_text():
    with patch("job_hunter_agent.profile_learning._llm_extract_from_cv", return_value=_LLM_FIXTURE):
        patch_result = build_learning_patch(SAMPLE_CV)

    assert patch_result.get("cv_text")
    rules = patch_result.get("capability_profile_rules", [])
    assert rules
    names = {r["name"] for r in rules}
    assert "stakeholder engagement" in names
    assert "process mapping" in names


def test_build_learning_patch_returns_empty_when_llm_unavailable():
    with patch("job_hunter_agent.profile_learning._llm_extract_from_cv", return_value={}):
        patch_result = build_learning_patch(SAMPLE_CV)

    assert patch_result.get("cv_text")
    assert not patch_result.get("capability_profile_rules")


def test_build_learning_patch_splits_compound_role_titles_before_learning():
    captured_titles = {}

    def fake_learn_title_normalization_candidates(titles, source="", source_text=""):
        captured_titles["titles"] = list(titles)
        captured_titles["source"] = source
        return {"pending": 0}

    with patch("job_hunter_agent.profile_learning._llm_extract_from_cv", return_value={
        "capabilities": [],
        "match_preferences": {},
        "role_titles": ["Senior Business Analyst and Scrum Master", "Product Owner / Delivery Manager"],
    }), \
         patch("job_hunter_agent.profile_learning.learn_title_normalization_candidates", side_effect=fake_learn_title_normalization_candidates):
        build_learning_patch("CV text")

    assert captured_titles["source"] == "CV parsing"
    assert captured_titles["titles"] == [
        "senior business analyst",
        "scrum master",
        "product owner",
        "delivery manager",
    ]


def test_build_learning_patch_routes_uncertain_capabilities_to_signal_registry():
    fixture = {
        "capabilities": [
            {"name": "business analysis", "level": "strong", "aliases": [], "needs_review": False},
            {"name": "unknown platform", "level": "working", "aliases": ["mystery platform"], "needs_review": True},
            {"name": "api design", "level": "basic", "aliases": [], "needs_review": True},
        ],
        "match_preferences": {},
    }
    captured = []

    def fake_knowledge_match(category, name, aliases=None):
        if name == "api design":
            return True, "API design"
        return False, ""

    def fake_register_signals(items):
        captured.extend(items)

    with patch("job_hunter_agent.profile_learning._llm_extract_from_cv", return_value=fixture), \
         patch("job_hunter_agent.profile_learning.signal_in_approved_knowledge", side_effect=fake_knowledge_match), \
         patch("job_hunter_agent.profile_learning.register_signals", side_effect=fake_register_signals):
        patch_result = build_learning_patch(SAMPLE_CV, source_sections=[{"label": "Skills", "text": "unknown platform"}])

    rules = patch_result.get("capability_profile_rules", [])
    assert [rule["name"] for rule in rules] == ["business analysis", "api design"]
    assert rules[1]["knowledge_match"] == "API design"
    assert captured == [
        {
            "signal": "unknown platform",
            "category": "capability_concept",
            "source": "CV parsing",
            "context": ["Skills: unknown platform"],
            "evidence": ["unknown platform", "mystery platform"],
            "needs_review": True,
        }
    ]


def test_build_learning_patch_does_not_emit_hard_blocker_pattern():
    fixture = {
        "capabilities": [
            {"name": "unknown platform", "level": "working", "aliases": [], "needs_review": True},
        ],
        "match_preferences": {},
    }
    captured = []

    def fake_register_signals(items):
        captured.extend(items)

    with patch("job_hunter_agent.profile_learning._llm_extract_from_cv", return_value=fixture), \
         patch("job_hunter_agent.profile_learning.signal_in_approved_knowledge", return_value=(False, "")), \
         patch("job_hunter_agent.profile_learning.register_signals", side_effect=fake_register_signals):
        build_learning_patch(SAMPLE_CV, source_sections=[{"label": "Skills", "text": "unknown platform"}])

    assert all(item.get("category") != "hard_blocker_pattern" for item in captured)


def test_build_role_title_review_signals_routes_uncertain_titles_to_signals():
    def fake_knowledge_match(category, name, aliases=None):
        if name == "analyst":
            return True, "analyst"
        return False, ""

    with patch("job_hunter_agent.profile_learning.signal_in_approved_knowledge", side_effect=fake_knowledge_match):
        signals = build_role_title_review_signals(
            ["Senior BA", "Delivery Ninja"],
            source_sections=[{"label": "Experience", "text": "Senior BA\nDelivery Ninja"}],
        )

    assert signals == [
        {
            "signal": "ninja",
            "category": "role_title_token",
            "source": "CV parsing",
            "context": ["Experience: Delivery Ninja"],
            "evidence": ["Delivery Ninja", "delivery ninja"],
            "needs_review": True,
        }
    ]


def test_extract_title_pattern_suggestions_returns_llm_patterns():
    with patch("job_hunter_agent.profile_learning._llm_extract_from_cv", return_value=_LLM_FIXTURE):
        result = extract_title_pattern_suggestions(SAMPLE_CV, {"extraction_lookback_years": 8})

    assert any("delivery lead" in item for item in result["target_roles"])
    assert any("delivery lead" in item for item in result["suggested_search_keywords"])


def test_extract_title_pattern_suggestions_respects_max_limits():
    fixture = {
        **_LLM_FIXTURE,
        "target_roles": ["a", "b", "c", "d", "e"],
        "also_consider_roles": ["x", "y", "z"],
    }
    with patch("job_hunter_agent.profile_learning._llm_extract_from_cv", return_value=fixture):
        result = extract_title_pattern_suggestions(SAMPLE_CV, {"max_target_patterns": 2, "max_secondary_patterns": 1})

    assert len(result["target_roles"]) <= 2
    assert len(result["also_consider_roles"]) <= 1


# ── _parse_role_entries: inline format (title/employer set directly) ───────────

def test_parse_role_entries_captures_inline_dash_format_in_header_lines():
    parsed = profile_learning._parse_role_entries(
        """
# Professional Experience
Business Analyst - Contoso (2016 - 2020)
"""
    )

    assert parsed
    assert "Business Analyst" in parsed[0]["header_lines"]
    assert "Contoso" in parsed[0]["header_lines"]


def test_parse_role_entries_collects_bullets_for_inline_roles():
    parsed = profile_learning._parse_role_entries(
        """
# Professional Experience
Senior Business Analyst - Payments (2024 - Present)
- Requirements workshops, process mapping, user stories.
- Stakeholder management and backlog refinement.
"""
    )

    assert parsed
    assert "Senior Business Analyst" in parsed[0]["header_lines"]
    assert parsed[0]["bullets"] == [
        "Requirements workshops, process mapping, user stories.",
        "Stakeholder management and backlog refinement.",
    ]


def test_parse_role_entries_accepts_title_with_dates_only():
    parsed = profile_learning._parse_role_entries(
        """
# Professional Experience
Business Analyst (2022 - 2024)
- Insurance platform delivery, UAT, backlog refinement.
"""
    )

    assert parsed
    assert parsed[0]["title"] == "Business Analyst"
    assert parsed[0]["employer"] == ""
    assert parsed[0]["bullets"] == ["Insurance platform delivery, UAT, backlog refinement."]


def test_parse_role_entries_accepts_project_manager_title():
    parsed = profile_learning._parse_role_entries(
        """
# Professional Experience
Project Manager (2021 - 2023)
- Delivered projects.
"""
    )

    assert parsed
    assert parsed[0]["title"] == "Project Manager"
    assert parsed[0]["header_lines"] == ["Project Manager"]


def test_parse_role_entries_pipe_format_uses_previous_line_as_employer():
    parsed = profile_learning._parse_role_entries(
        """
EMPLOYMENT HISTORY
Department of Employment and Workplace Relations (DEWR)
Senior Systems Analyst | 2025 - Present | Federal Government | Contract
Systems analysis and requirements definition.
Produced functional specifications.
"""
    )

    assert parsed
    assert parsed[0]["title"] == "Senior Systems Analyst"
    assert parsed[0]["employer"] == "Department of Employment and Workplace Relations (DEWR)"
    assert parsed[0]["bullets"] == [
        "Systems analysis and requirements definition.",
        "Produced functional specifications.",
    ]


# ── _parse_role_entries: date-first / prefix format (header_lines used) ───────

def test_parse_role_entries_captures_prefix_lines_as_header_lines():
    parsed = profile_learning._parse_role_entries(
        """
# Professional Experience
Senior Business Analyst
Acme Bank
2022 - Present
- Led workshops
"""
    )

    assert parsed
    assert "Senior Business Analyst" in parsed[0]["header_lines"]
    assert "Acme Bank" in parsed[0]["header_lines"]


def test_parse_role_entries_captures_post_date_lines_as_header_lines():
    parsed = profile_learning._parse_role_entries(
        """
# Professional Experience
2022 - Present
Senior Business Analyst
Acme Bank
- Led workshops
"""
    )

    assert parsed
    assert "Senior Business Analyst" in parsed[0]["header_lines"]
    assert "Acme Bank" in parsed[0]["header_lines"]


def test_parse_role_entries_keeps_plain_paragraphs_after_prefix_in_date_first():
    parsed = profile_learning._parse_role_entries(
        """
# Professional Experience
Senior Business Analyst
Acme Bank
2022 - Present
Led workshops across product and delivery teams.
Produced process maps and business requirements.
"""
    )

    assert parsed
    assert "Senior Business Analyst" in parsed[0]["header_lines"]
    assert "Acme Bank" in parsed[0]["header_lines"]
    assert parsed[0]["bullets"] == [
        "Led workshops across product and delivery teams.",
        "Produced process maps and business requirements.",
    ]


def test_parse_role_entries_supports_unicode_bullet_markers():
    parsed = profile_learning._parse_role_entries(
        """
# Professional Experience
Business Analyst
Contoso
2022 - Present
• Led workshops
• Produced user stories
"""
    )

    assert parsed
    assert "Business Analyst" in parsed[0]["header_lines"]
    assert parsed[0]["bullets"] == ["Led workshops", "Produced user stories"]


def test_parse_role_entries_date_first_layout_captures_employer_in_header_lines():
    parsed = profile_learning._parse_role_entries(
        """
EMPLOYMENT HISTORY
NSW eHealth
Digital & Infrastructure Business Analyst / Project Coordinator
May 2022 - Nov 2023
Led workshops with stakeholders.
Produced onboarding documentation.
"""
    )

    assert parsed
    assert "NSW eHealth" in parsed[0]["header_lines"]
    assert "Digital & Infrastructure Business Analyst / Project Coordinator" in parsed[0]["header_lines"]


def test_role_title_knowledge_file_contains_enabled_entries():
    payload = json.loads(role_title_knowledge.ROLE_TITLE_KNOWLEDGE_PATH.read_text(encoding="utf-8"))

    assert payload["kind"] == "managed_knowledge"
    assert any(entry.get("value") for entry in payload["entries"])
    assert all(set(entry.keys()) == {"value"} for entry in payload["entries"])
    assert "analyst" in profile_learning._generic_role_tokens()


def test_role_title_detection_uses_managed_generic_role_tokens():
    assert profile_learning._looks_like_role_title_line("Operations Support Officer") is True
    assert profile_learning._looks_like_role_title_line("Sr BA") is True
    assert profile_learning._looks_like_role_title_line("TechCorp Ltd") is False


@pytest.mark.parametrize(
    "line,expected",
    [
        ("Senior Business Analyst", True),
        ("Project Manager", True),
        ("Evangelist", False),
        ("Strategist", False),
        ("Velocity", False),
        ("Digital Edge", False),
    ],
)
def test_role_title_detection_requires_an_approved_role_token(line, expected):
    assert profile_learning._looks_like_role_title_line(line) is expected


def test_role_title_detection_uses_parsing_config_for_line_rules(monkeypatch):
    monkeypatch.setattr(
        profile_learning,
        "_load_parsing_rules",
        lambda: {
            "title_candidate_line_rules": {
                "max_length_chars": 12,
                "max_tokens": 2,
                "punctuation_blockers": [";"],
            },
            "title_candidate_leading_verb_blockers": ["working"],
        },
    )
    profile_learning._load_title_candidate_line_rules.cache_clear()

    assert profile_learning._looks_like_role_title_line("Software Engineer") is False
    assert profile_learning._looks_like_role_title_line("Lead;Engineer") is False
    assert profile_learning._looks_like_role_title_line("Working Lead") is False

    profile_learning._load_title_candidate_line_rules.cache_clear()


def test_role_title_normalization_expands_abbreviations():
    assert profile_learning._normalize_role_title_value("Sr BA") == "senior business analyst"
    assert profile_learning._normalize_role_title_value("PO") == "product owner"
