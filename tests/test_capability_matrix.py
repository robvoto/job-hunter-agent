from job_hunter_agent.capability_matrix import derive_job_description_aliases, expand_capability_terms
from job_hunter_agent.source_connector import find_profile_capability_matches


def test_derive_job_description_aliases_converts_phrase_fragments_to_job_terms():
    aliases = derive_job_description_aliases(
        "agile methodologies",
        [
            "bpmn agile scrum",
            "agile scrum kanban",
            "scrum kanban",
            "security agile scrum",
        ],
    )

    assert "agile" in aliases
    assert "scrum" in aliases
    assert "kanban" in aliases
    assert "bpmn agile scrum" not in aliases


def test_expand_capability_terms_keeps_useful_shortened_name_terms():
    terms = expand_capability_terms(
        {
            "name": "primary stakeholder engagement",
            "aliases": ["acted primary client-facing", "primary ba"],
        }
    )

    assert "primary stakeholder engagement" in terms
    assert "stakeholder engagement" in terms


def test_find_profile_capability_matches_uses_expanded_alias_terms():
    matches = find_profile_capability_matches(
        "You will coach agile delivery teams, run Scrum ceremonies, and improve Kanban flow.",
        {
            "capability_profile_rules": [
                {
                    "name": "agile methodologies",
                    "level": "strong",
                    "fit": "core",
                    "aliases": [
                        "bpmn agile scrum",
                        "agile scrum kanban",
                        "scrum kanban",
                    ],
                }
            ],
            "must_not_require_skills": [],
        },
    )

    assert matches["core"] == ["Agile methodologies"]
