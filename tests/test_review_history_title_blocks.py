from __future__ import annotations

import pytest

from job_hunter_agent import review_history_service


def test_save_block_similar_feedback_requires_explicit_phrase(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(review_history_service, "normalize_job_key", lambda value: "job-1")

    with pytest.raises(ValueError, match="At least one exact title block phrase is required"):
        review_history_service.save_block_similar_feedback(
            "job-1",
            title="Senior Business Analyst - SAP",
            block_phrases=[],
        )


def test_save_block_similar_feedback_normalizes_and_dedupes_explicit_phrases(
    monkeypatch: pytest.MonkeyPatch,
):
    profile = {"reject_title_rules": []}
    saved_profiles: list[dict] = []
    rebuilds: list[str] = []
    events: list[tuple[tuple, dict]] = []

    monkeypatch.setattr(review_history_service, "normalize_job_key", lambda value: "job-1")
    monkeypatch.setattr(review_history_service, "load_profile", lambda: profile)
    monkeypatch.setattr(review_history_service, "save_profile", lambda payload: saved_profiles.append(payload))
    monkeypatch.setattr(
        review_history_service,
        "rebuild_workspace_after_rule_change",
        lambda reason="": rebuilds.append(reason),
    )
    monkeypatch.setattr(
        review_history_service,
        "persist_review_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )

    result = review_history_service.save_block_similar_feedback(
        "job-1",
        title="Senior Business Analyst - SAP",
        block_phrases=[" SAP ", "sap", "sap finance"],
    )

    assert result["block_phrases"] == ["sap", "sap finance"]
    assert profile["reject_title_rules"] == [
        {"pattern": r"\bsap\b", "reason": "TITLE_BAD_KEYWORD:sap"},
        {"pattern": r"\bsap\s+finance\b", "reason": "TITLE_BAD_KEYWORD:sap finance"},
    ]
    assert saved_profiles == [profile]
    assert rebuilds == ["title block added for sap, sap finance"]
    assert events
