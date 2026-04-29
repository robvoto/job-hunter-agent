from job_hunter_agent import filters


def test_missing_requirement_detector_separates_required_from_desirable():
    assert filters.matches_missing_requirement("SAP experience is mandatory for this role.", "SAP")
    assert filters.matches_missing_requirement("Proven experience in financial services is required.", "financial services")
    assert not filters.matches_missing_requirement("SAP experience is desirable for this role.", "SAP")
    assert not filters.matches_missing_requirement("Strong SAP experience is preferred but not essential.", "SAP")


def test_secondary_title_requires_stronger_role_proof(monkeypatch):
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
            "must_not_require_skills": [],
        },
    )

    ok, reason = filters.passes_content_filters(
        "Great opportunity in a dynamic team. Coordination, reporting, liaison, and scheduling support.",
        title_reason="TITLE_POTENTIAL_MATCH",
    )

    assert not ok
    assert reason == "DESC_ROLE_PROOF_MISSING"


def test_secondary_title_with_clear_role_evidence_can_pass(monkeypatch):
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


def test_secondary_title_alias_only_mentions_do_not_count_as_role_proof(monkeypatch):
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: {
            "capability_profile_rules": [
                {
                    "name": "agile methodologies",
                    "level": "strong",
                    "fit": "core",
                    "aliases": ["scrum", "kanban"],
                },
            ],
            "reject_description_phrase_rules": [],
            "must_not_require_skills": [],
        },
    )

    ok, reason = filters.passes_content_filters(
        """
Responsibilities:
- Run scrum ceremonies with delivery teams
- Support kanban flow reporting
""",
        title_reason="TITLE_POTENTIAL_MATCH",
    )

    assert not ok
    assert reason == "DESC_ROLE_PROOF_MISSING"


def test_direct_title_can_still_reject_overly_vague_description(monkeypatch):
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: {
            "capability_profile_rules": [],
            "reject_description_phrase_rules": [],
            "must_not_require_skills": [],
        },
    )

    ok, reason = filters.passes_content_filters(
        "Great opportunity in a dynamic team with excellent communication skills and a fast-paced environment.",
        title_reason="OK",
    )

    assert not ok
    assert reason == "DESC_VAGUE_TARGET_ROLE"


def test_generic_business_analyst_target_pattern_allows_common_ba_titles(monkeypatch):
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: {
            "target_title_patterns": [r"\bbusiness\ analyst\b"],
            "secondary_title_patterns": [],
            "reject_title_rules": [],
        },
    )

    ok_plain, reason_plain = filters.passes_title_filters("Business Analyst")
    ok_lead, reason_lead = filters.passes_title_filters("Lead Business Analyst")
    ok_ai, reason_ai = filters.passes_title_filters("Senior Business Analyst Senior (AI Foundations)")

    assert ok_plain is True
    assert reason_plain == "OK"
    assert ok_lead is True
    assert reason_lead == "OK"
    assert ok_ai is True
    assert reason_ai == "OK"
