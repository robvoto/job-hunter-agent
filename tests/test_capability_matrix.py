from job_hunter_agent.capability_matrix import choose_capability_name, derive_job_description_aliases, expand_capability_terms
from job_hunter_agent.profile_store import normalize_capability_rules
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


def test_derive_job_description_aliases_rejects_title_like_mashups():
    aliases = derive_job_description_aliases(
        "business analyst scrum",
        [
            "analyst scrum",
            "business analyst scrum master",
            "scrum master",
            "scrum analyst",
        ],
    )

    assert aliases == ["scrum"]


def test_derive_job_description_aliases_prefers_stronger_multi_word_terms():
    aliases = derive_job_description_aliases(
        "process mapping",
        [
            "process design",
            "as-is to-be",
            "process maps",
        ],
        max_aliases=2,
    )

    assert "process design" in aliases
    assert "mapping" not in aliases


def test_derive_job_description_aliases_deprioritizes_action_phrases():
    aliases = derive_job_description_aliases(
        "stakeholder engagement",
        [
            "stakeholder management",
            "facilitate workshops",
            "stakeholder engagement",
        ],
        max_aliases=2,
    )

    assert "stakeholder management" in aliases
    assert "facilitate workshop" not in aliases


def test_derive_job_description_aliases_prefers_grounded_phrase_over_abstract_single_word():
    aliases = derive_job_description_aliases(
        "requirements elicitation",
        [
            "business analysis requirements elicitation",
            "requirements gathering",
            "functional requirements",
        ],
        max_aliases=1,
    )

    assert aliases == ["requirement gathering"]


def test_choose_capability_name_falls_back_from_title_like_label():
    assert choose_capability_name(
        "business analyst scrum",
        [
            "analyst scrum",
            "business analyst scrum master",
            "scrum master",
            "scrum analyst",
        ],
    ) == "scrum"


def test_normalize_capability_rules_cleans_existing_title_like_profile_rows():
    rules = normalize_capability_rules(
        [
            {
                "name": "business analyst scrum",
                "level": "strong",
                "fit": "core",
                "aliases": [
                    "analyst scrum",
                    "business analyst scrum master",
                    "scrum master",
                    "scrum analyst",
                ],
            }
        ]
    )

    assert rules == [
        {
            "name": "scrum",
            "level": "strong",
            "fit": "core",
            "aliases": [],
        }
    ]


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
