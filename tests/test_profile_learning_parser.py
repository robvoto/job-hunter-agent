import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import profile_learning
from profile_learning import build_learning_patch, extract_title_pattern_suggestions


SAMPLE_CV = """
# Professional Summary
Senior Business Analyst with experience across payments, process improvement, and delivery support.

# Professional Experience
Acme Bank - Senior Business Analyst (2022 - Present)
- Led requirements workshops for payments change initiatives.
- Produced process maps, user stories, and business requirements for regulatory delivery.
- Coordinated stakeholders across technology and operations teams.

Northstar Consulting - Business Analyst (2019 - 2022)
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

    assert patch.get("candidate_summary")
    assert "evidence_signals" in patch
    assert any("business analyst" in item for item in patch["evidence_signals"])
    assert patch.get("capability_profile_rules")
    assert any(
        rule["name"] in {"business analysis", "process mapping", "stakeholder engagement"}
        for rule in patch["capability_profile_rules"]
    )


def test_extract_title_pattern_suggestions_prefers_recent_roles():
    suggestion = extract_title_pattern_suggestions(SAMPLE_CV, {"title_extraction_lookback_years": 8})

    assert suggestion["target_title_patterns"]
    assert "business analyst" in suggestion["suggested_search_keywords"]


def test_llm_capability_naming_only_renames_selected_clusters():
    llm_gate = importlib.import_module("llm_gate")
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
