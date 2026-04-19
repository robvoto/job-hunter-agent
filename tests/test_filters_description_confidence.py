from job_hunter_agent import filters


def test_adjacent_title_requires_stronger_role_proof(monkeypatch):
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: {
            "capability_profile_rules": [
                {
                    "name": "requirements elicitation",
                    "level": "strong",
                    "fit": "core",
                    "aliases": ["requirements elicitation", "requirements gathering"],
                },
                {
                    "name": "process mapping",
                    "level": "working",
                    "fit": "core",
                    "aliases": ["process mapping", "as-is", "to-be"],
                },
            ],
            "reject_description_phrase_rules": [],
            "reject_description_regex_rules": [],
            "must_not_require_skills": [],
        },
    )

    ok, reason = filters.passes_content_filters(
        "Great opportunity in a dynamic team. Coordination, reporting, liaison, and scheduling support.",
        title_reason="TITLE_POTENTIAL_MATCH",
    )

    assert not ok
    assert reason == "DESC_ROLE_PROOF_MISSING"


def test_adjacent_title_with_clear_role_evidence_can_pass(monkeypatch):
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: {
            "capability_profile_rules": [
                {
                    "name": "requirements elicitation",
                    "level": "strong",
                    "fit": "core",
                    "aliases": ["requirements elicitation", "requirements gathering"],
                },
                {
                    "name": "process mapping",
                    "level": "working",
                    "fit": "core",
                    "aliases": ["process mapping", "as-is", "to-be"],
                },
            ],
            "reject_description_phrase_rules": [],
            "reject_description_regex_rules": [],
            "must_not_require_skills": [],
        },
    )

    ok, reason = filters.passes_content_filters(
        """
Responsibilities:
- Lead requirements elicitation workshops with business stakeholders
- Produce process mapping artefacts across current-state and future-state flows
- Gather and document requirements for delivery teams
""",
        title_reason="TITLE_POTENTIAL_MATCH",
    )

    assert ok
    assert reason == "OK"


def test_direct_title_can_still_reject_overly_vague_description(monkeypatch):
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: {
            "capability_profile_rules": [],
            "reject_description_phrase_rules": [],
            "reject_description_regex_rules": [],
            "must_not_require_skills": [],
        },
    )

    ok, reason = filters.passes_content_filters(
        "Great opportunity in a dynamic team with excellent communication skills and a fast-paced environment.",
        title_reason="OK",
    )

    assert not ok
    assert reason == "DESC_VAGUE_TARGET_ROLE"
