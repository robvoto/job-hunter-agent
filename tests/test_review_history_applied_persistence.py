from __future__ import annotations

import pytest

from job_hunter_agent import review_history_service
from job_hunter_agent.io_utils import load_job_history
from job_hunter_agent.profile_store import load_profile
from job_hunter_agent.record_schema import RECORD_FIRST_APPLIED_AT_KEY, RECORD_LAST_APPLIED_AT_KEY

JOB_KEY = "seek:test-applied-job-1"


def test_append_review_key_applied_persists_profile_and_history(monkeypatch: pytest.MonkeyPatch):
    """Clicking Applied must survive a process restart: both the profile's
    applied_job_keys list and the job_history applied timestamps are read back
    from the DB fresh (no in-memory cache), so this exercises the same
    persistence path api_review() relies on for acceptance criteria #4/#6.
    """
    monkeypatch.setattr(
        review_history_service,
        "rebuild_workspace_after_rule_change",
        lambda reason="", **kwargs: None,
    )

    result = review_history_service.append_review_key(
        "applied",
        JOB_KEY,
        url="https://example.test/jobs/test-applied-job-1",
        title="Senior Backend Engineer",
        company="Acme Corp",
        teaser="Build and ship backend services.",
    )

    assert result["ok"] is True
    assert result["action"] == "applied"
    assert result["job_key"] == JOB_KEY

    profile = load_profile()
    assert JOB_KEY in profile["review_controls"]["applied_job_keys"]

    history = load_job_history()
    entry = history[JOB_KEY]
    assert entry[RECORD_FIRST_APPLIED_AT_KEY]
    assert entry[RECORD_LAST_APPLIED_AT_KEY]
    assert entry["title"] == "Senior Backend Engineer"
    assert entry["company"] == "Acme Corp"


def test_review_action_refreshes_workspace_in_background(monkeypatch: pytest.MonkeyPatch):
    # The client moves the card in place, so the review action must not block on
    # the rebuild or ask the browser to full-page reload (that froze Applied/Hide
    # for seconds and lost scroll position).
    refresh_calls = []

    monkeypatch.setattr(
        review_history_service,
        "rebuild_workspace_after_rule_change",
        lambda reason="", **kwargs: refresh_calls.append((reason, kwargs)) or "refresh-id",
    )

    result = review_history_service.append_review_key(
        "hidden",
        "seek:test-hidden-job-1",
        title="Business Analyst",
        company="Acme Corp",
    )

    assert result["workspace_refresh_async"] is True
    assert refresh_calls == [
        ("review action saved: hidden", {}),
    ]


def test_append_review_key_applied_is_idempotent_and_keeps_first_applied_at(
    monkeypatch: pytest.MonkeyPatch,
):
    """Re-applying the same job (e.g. after an unapply/re-apply cycle) must not
    duplicate the profile entry or clobber the original first-applied timestamp.
    """
    monkeypatch.setattr(
        review_history_service,
        "rebuild_workspace_after_rule_change",
        lambda reason="", **kwargs: None,
    )

    review_history_service.append_review_key("applied", JOB_KEY, title="Senior Backend Engineer")
    first_history = load_job_history()
    first_applied_at = first_history[JOB_KEY][RECORD_FIRST_APPLIED_AT_KEY]

    review_history_service.append_review_key("applied", JOB_KEY, title="Senior Backend Engineer")

    profile = load_profile()
    assert profile["review_controls"]["applied_job_keys"].count(JOB_KEY) == 1

    history = load_job_history()
    assert history[JOB_KEY][RECORD_FIRST_APPLIED_AT_KEY] == first_applied_at


def test_duplicate_append_review_request_is_true_noop(monkeypatch: pytest.MonkeyPatch):
    refresh_calls = []
    monkeypatch.setattr(
        review_history_service,
        "rebuild_workspace_after_rule_change",
        lambda reason="", **kwargs: refresh_calls.append(reason) or "refresh-id",
    )

    first = review_history_service.append_review_key(
        "hidden", "seek:test-idempotent-hidden", title="Business Analyst"
    )
    second = review_history_service.append_review_key(
        "hidden", "seek:test-idempotent-hidden", title="Business Analyst"
    )

    assert first["state_changed"] is True
    assert second["state_changed"] is False
    assert second["workspace_refresh_id"] is None
    assert second["reload_workspace"] is False
    assert refresh_calls == ["review action saved: hidden"]


def test_duplicate_remove_review_request_is_true_noop(monkeypatch: pytest.MonkeyPatch):
    refresh_calls = []
    monkeypatch.setattr(
        review_history_service,
        "rebuild_workspace_after_rule_change",
        lambda reason="", **kwargs: refresh_calls.append(reason) or "refresh-id",
    )
    key = "seek:test-idempotent-unhide"
    review_history_service.append_review_key("hidden", key, title="Business Analyst")
    refresh_calls.clear()

    first = review_history_service.remove_review_key("unhide", key)
    second = review_history_service.remove_review_key("unhide", key)

    assert first["state_changed"] is True
    assert second["state_changed"] is False
    assert second["workspace_refresh_id"] is None
    assert refresh_calls == ["review action saved: unhide"]
