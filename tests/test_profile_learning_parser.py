import importlib

from job_hunter_agent import profile_learning
from job_hunter_agent.profile_learning import (
    _CURRENT_YEAR,
    _collect_phrase_stats,
    _parse_role_entries,
    build_learning_patch,
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


def test_build_learning_patch_extracts_evidence_and_capabilities():
    patch = build_learning_patch(SAMPLE_CV)

    assert "evidence_signals" not in patch
    assert patch.get("capability_profile_rules")
    assert any(
        rule["name"] in {"process mapping", "stakeholder engagement", "requirement workshop"}
        for rule in patch["capability_profile_rules"]
    )


def test_extract_title_pattern_suggestions_prefers_recent_roles():
    suggestion = extract_title_pattern_suggestions(SAMPLE_CV, {"extraction_lookback_years": 8})

    assert suggestion["target_title_patterns"]
    assert any("delivery lead" in keyword for keyword in suggestion["suggested_search_keywords"])


def test_collect_phrase_stats_uses_configured_lookback_for_recent_roles():
    cv_text = f"""
# Professional Experience
Alpha Co - Process Lead ({_CURRENT_YEAR - 7} - {_CURRENT_YEAR - 7})
- Led process mapping workshops and process mapping documentation.

Beta Co - Process Analyst ({_CURRENT_YEAR - 11} - {_CURRENT_YEAR - 10})
- Delivered process mapping improvements and process mapping artefacts.
"""

    roles = _parse_role_entries(cv_text)
    short_stats = _collect_phrase_stats(cv_text, roles, {"extraction_lookback_years": 5})
    long_stats = _collect_phrase_stats(cv_text, roles, {"extraction_lookback_years": 8})

    assert len(short_stats["process lead"]["recent_roles"]) == 0
    assert len(long_stats["process lead"]["recent_roles"]) == 1


def test_parse_role_entries_accepts_title_and_employer_before_dates():
    parsed = profile_learning._parse_role_entries(
        """
# Professional Experience
Senior Delivery Lead
Acme Bank
2022 - Present
- Led workshops
"""
    )

    assert parsed
    assert parsed[0]["title"] == "Senior Delivery Lead"
    assert parsed[0]["employer"] == "Acme Bank"


def test_parse_role_entries_accepts_inline_title_then_employer_before_dates():
    parsed = profile_learning._parse_role_entries(
        """
# Professional Experience
Business Analyst - Contoso (2016 - 2020)
"""
    )

    assert parsed
    assert parsed[0]["title"] == "Business Analyst"
    assert parsed[0]["employer"] == "Contoso"


def test_parse_role_entries_collects_followup_bullets_for_inline_roles():
    parsed = profile_learning._parse_role_entries(
        """
# Professional Experience
Senior Business Analyst - Payments (2024 - Present)
- Requirements workshops, process mapping, user stories.
- Stakeholder management and backlog refinement.
"""
    )

    assert parsed
    assert parsed[0]["title"] == "Senior Business Analyst"
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


def test_parse_role_entries_does_not_swap_title_and_employer_when_dates_come_first():
    parsed = profile_learning._parse_role_entries(
        """
# Professional Experience
2022 - Present
Senior Delivery Lead
Acme Bank
- Led workshops
"""
    )

    assert parsed
    assert parsed[0]["title"] == "Senior Delivery Lead"
    assert parsed[0]["employer"] == "Acme Bank"


def test_parse_role_entries_keeps_plain_paragraphs_after_prefix_title_and_dates():
    parsed = profile_learning._parse_role_entries(
        """
# Professional Experience
Senior Delivery Lead
Acme Bank
2022 - Present
Led workshops across product and delivery teams.
Produced process maps and business requirements.
"""
    )

    assert parsed
    assert parsed[0]["title"] == "Senior Delivery Lead"
    assert parsed[0]["employer"] == "Acme Bank"
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
\u2022 Led workshops
\u2022 Produced user stories
"""
    )

    assert parsed
    assert parsed[0]["bullets"] == [
        "Led workshops",
        "Produced user stories",
    ]


def test_llm_capability_naming_only_renames_selected_clusters():
    llm_gate = importlib.import_module("job_hunter_agent.llm_gate")
    original = llm_gate.name_capability_clusters

    try:
        llm_gate.name_capability_clusters = lambda clusters: ["process modelling"]
        renamed = profile_learning._apply_llm_capability_names(
            [
                {
                    "name": "process maps",
                    "level": "working",
                    "fit": "core",
                    "aliases": ["workflow redesign", "bpmn", "as-is to-be"],
                }
            ]
        )
    finally:
        llm_gate.name_capability_clusters = original

    assert renamed[0]["name"] == "process modelling"
    assert "process maps" in renamed[0]["aliases"]


def test_llm_capability_naming_rejects_tokens_not_grounded_in_source():
    llm_gate = importlib.import_module("job_hunter_agent.llm_gate")
    original = llm_gate.name_capability_clusters

    try:
        llm_gate.name_capability_clusters = lambda clusters: ["analytical scrum"]
        renamed = profile_learning._apply_llm_capability_names(
            [
                {
                    "name": "analyst scrum",
                    "level": "working",
                    "fit": "supporting",
                    "aliases": ["scrum analyst"],
                }
            ]
        )
    finally:
        llm_gate.name_capability_clusters = original

    assert renamed[0]["name"] == "analyst scrum"

