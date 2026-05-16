from job_hunter_agent.capability_matrix import choose_capability_name, derive_job_description_aliases, expand_capability_terms
from job_hunter_agent.profile_store import normalize_capability_rules
from job_hunter_agent.capability_matching import find_profile_capability_matches


def test_expand_capability_terms_returns_name_and_aliases():
    terms = expand_capability_terms({
        "name": "requirements analysis",
        "aliases": ["requirements gathering", "business requirements"],
    })
    assert terms == ["requirements analysis", "requirements gathering", "business requirements"]


def test_expand_capability_terms_deduplicates():
    terms = expand_capability_terms({
        "name": "agile delivery",
        "aliases": ["agile delivery", "scrum", "scrum"],
    })
    assert terms == ["agile delivery", "scrum"]


def test_expand_capability_terms_respects_max():
    terms = expand_capability_terms({"name": "a", "aliases": ["b", "c", "d"]}, max_terms=2)
    assert terms == ["a", "b"]


def test_derive_job_description_aliases_excludes_canonical_name():
    aliases = derive_job_description_aliases(
        "stakeholder engagement",
        ["stakeholder management", "stakeholder engagement", "engagement"],
    )
    assert "stakeholder engagement" not in aliases
    assert "stakeholder management" in aliases
    assert "engagement" in aliases


def test_derive_job_description_aliases_deduplicates():
    aliases = derive_job_description_aliases("agile", ["scrum", "scrum", "kanban"])
    assert aliases == ["scrum", "kanban"]


def test_derive_job_description_aliases_respects_max():
    aliases = derive_job_description_aliases("x", ["a", "b", "c", "d"], max_aliases=2)
    assert aliases == ["a", "b"]


def test_choose_capability_name_returns_cleaned_name():
    assert choose_capability_name("Requirements Analysis", []) == "requirements analysis"


def test_choose_capability_name_falls_back_to_first_alias():
    assert choose_capability_name("", ["stakeholder engagement", "stakeholder management"]) == "stakeholder engagement"


def test_choose_capability_name_empty_input():
    assert choose_capability_name("", []) == ""


def test_normalize_capability_rules_uses_choose_capability_name():
    rules = normalize_capability_rules([
        {
            "name": "Stakeholder Engagement",
            "level": "strong",
            "fit": "core",
            "aliases": ["stakeholder management"],
        }
    ])
    assert rules[0]["name"] == "stakeholder engagement"


def test_find_profile_capability_matches_uses_expanded_alias_terms():
    matches = find_profile_capability_matches(
        "You will coach agile delivery teams, run Scrum ceremonies, and improve Kanban flow.",
        {
            "capability_profile_rules": [
                {
                    "name": "agile delivery",
                    "level": "strong",
                    "fit": "core",
                    "aliases": ["scrum", "kanban"],
                }
            ],
            "must_not_require_skills": [],
        },
    )
    assert matches["core"] == ["Agile delivery"]
