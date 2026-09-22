"""Tests for the daily agent runner CLI."""

from datetime import datetime

from job_hunter_agent import agent_runner
from job_hunter_agent.agent_runner import (
    SCHEDULE_ACTION_MISSED_WINDOW,
    SCHEDULE_ACTION_RUN,
    SCHEDULE_ACTION_WAIT,
    SCHEDULE_STATUS_SUCCEEDED,
    STATE_SCHEDULER_LAST_SEEN_AT,
    _build_arg_parser,
    _scheduled_state_updates,
    evaluate_schedule_action,
    run_agent_loop,
)


def test_daily_agent_runner_accepts_step_flag():
    args = _build_arg_parser().parse_args(["--step"])

    assert args.step is True
    assert args.loop is False


def test_evaluate_schedule_action_runs_when_loop_was_alive_before_window():
    loop_started_at = datetime.fromisoformat("2026-07-28T08:55:00+10:00")
    now = datetime.fromisoformat("2026-07-28T09:05:00+10:00")

    action = evaluate_schedule_action({}, "09:00", now, loop_started_at)

    assert action == SCHEDULE_ACTION_RUN


def test_evaluate_schedule_action_skips_missed_window_after_late_start():
    loop_started_at = datetime.fromisoformat("2026-07-28T09:30:00+10:00")
    now = datetime.fromisoformat("2026-07-28T09:31:00+10:00")

    action = evaluate_schedule_action({}, "09:00", now, loop_started_at)

    assert action == SCHEDULE_ACTION_MISSED_WINDOW


def test_evaluate_schedule_action_waits_after_today_attempt():
    loop_started_at = datetime.fromisoformat("2026-07-28T08:30:00+10:00")
    now = datetime.fromisoformat("2026-07-28T09:31:00+10:00")

    action = evaluate_schedule_action(
        {"last_scheduled_attempt_at": "2026-07-28T09:00:00+10:00"},
        "09:00",
        now,
        loop_started_at,
    )

    assert action == SCHEDULE_ACTION_WAIT


def test_scheduled_state_updates_record_success_details():
    payload = _scheduled_state_updates(
        SCHEDULE_STATUS_SUCCEEDED,
        attempted_at="2026-07-28T09:00:00+10:00",
        finished_at="2026-07-28T09:12:00+10:00",
        message="Scheduled run completed successfully.",
        summary_path="/tmp/agent_last_summary.txt",
    )

    assert payload["last_scheduled_attempt_at"] == "2026-07-28T09:00:00+10:00"
    assert payload["last_scheduled_status"] == "succeeded"
    assert payload["last_scheduled_finished_at"] == "2026-07-28T09:12:00+10:00"
    assert payload["last_scheduled_success_at"] == "2026-07-28T09:12:00+10:00"
    assert payload["last_scheduled_summary_path"] == "/tmp/agent_last_summary.txt"


def test_run_agent_once_builds_digest_with_saved_job_history(monkeypatch):
    saved_history = {"seek:94004529": {"title": "Product Owner", "company": "Shiftcare"}}
    workspace_record_calls = []

    monkeypatch.setattr(agent_runner, "load_user_settings", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(agent_runner, "load_agent_state", lambda: {})
    monkeypatch.setattr(agent_runner, "save_agent_state", lambda _state: None)
    monkeypatch.setattr(agent_runner, "load_last_kept_records", lambda: [])
    monkeypatch.setattr(agent_runner, "rebuild_workspace_results", lambda **_kwargs: None)
    monkeypatch.setattr(agent_runner, "load_latest_run_stats", lambda: {})
    monkeypatch.setattr(agent_runner, "load_profile", lambda: {})
    monkeypatch.setattr(agent_runner, "get_manual_skip_sets", lambda _profile: (set(), set()))
    monkeypatch.setattr(agent_runner, "load_job_history", lambda: saved_history)
    monkeypatch.setattr(
        agent_runner,
        "build_workspace_record_sets",
        lambda *args, **kwargs: workspace_record_calls.append((args, kwargs)) or {},
    )
    monkeypatch.setattr(
        agent_runner,
        "build_digest_payload",
        lambda *_args: {
            "run_finished_at": "2026-09-22T09:00:00+10:00",
            "current_keys": [],
            agent_runner.KEY_DIGEST_WORKSPACE_REF: "workspace-ref",
        },
    )
    monkeypatch.setattr(agent_runner, "format_daily_summary", lambda _payload: "summary")
    monkeypatch.setattr(
        agent_runner, "format_daily_summary_html", lambda _payload: "<p>summary</p>"
    )
    monkeypatch.setattr(agent_runner, "write_last_summary", lambda _summary: None)

    agent_runner.run_agent_once(no_scrape=True, notify=False)

    assert workspace_record_calls[0][0][1] == saved_history


def test_run_agent_loop_stops_cleanly_when_stop_requested(monkeypatch):
    saved_states = []

    class _FakeStopEvent:
        def __init__(self) -> None:
            self._set = False

        def is_set(self) -> bool:
            return self._set

        def wait(self, _seconds: float) -> bool:
            self._set = True
            return True

    monkeypatch.setattr(
        "job_hunter_agent.agent_runner.load_user_settings",
        lambda _user_id, create_if_missing=True: {
            "schedule": {
                "enabled": False,
                "daily_time_local": "09:00",
                "loop_sleep_seconds": 300,
            }
        },
    )
    monkeypatch.setattr("job_hunter_agent.agent_runner.load_agent_state", lambda: {})
    monkeypatch.setattr(
        "job_hunter_agent.agent_runner.save_agent_state",
        lambda state: saved_states.append(dict(state)) or state,
    )

    run_agent_loop(stop_event=_FakeStopEvent())

    assert saved_states
    assert STATE_SCHEDULER_LAST_SEEN_AT in saved_states[0]


def test_run_agent_loop_executes_and_records_success(monkeypatch):
    saved_states = []
    run_calls = []

    class _FakeStopEvent:
        def __init__(self) -> None:
            self._set = False

        def is_set(self) -> bool:
            return self._set

        def wait(self, _seconds: float) -> bool:
            self._set = True
            return True

    monkeypatch.setattr(
        "job_hunter_agent.agent_runner.load_user_settings",
        lambda _user_id, create_if_missing=True: {
            "schedule": {
                "enabled": True,
                "daily_time_local": "09:00",
                "loop_sleep_seconds": 300,
            }
        },
    )
    monkeypatch.setattr("job_hunter_agent.agent_runner.load_agent_state", lambda: dict(saved_states[-1]) if saved_states else {})
    monkeypatch.setattr(
        "job_hunter_agent.agent_runner.save_agent_state",
        lambda state: saved_states.append(dict(state)) or state,
    )
    monkeypatch.setattr(
        "job_hunter_agent.agent_runner.evaluate_schedule_action",
        lambda state, daily_time_local, now, loop_started_at: SCHEDULE_ACTION_RUN,
    )
    monkeypatch.setattr(
        "job_hunter_agent.agent_runner.run_agent_once",
        lambda **kwargs: run_calls.append(kwargs) or {
            "summary_path": "/tmp/agent_last_summary.txt",
            "summary_text": "Scheduled summary",
            "summary": {"run_finished_at": "2026-09-05T09:01:00+10:00"},
        },
    )

    run_agent_loop(stop_event=_FakeStopEvent())

    assert run_calls == [
        {"no_scrape": False, "notify": True, "scrape_trigger": "scheduled daily runner"}
    ]
    assert any(state.get("last_scheduled_status") == "running" for state in saved_states)
    assert saved_states[-1]["last_scheduled_status"] == "succeeded"
    assert saved_states[-1]["last_scheduled_finished_at"] == "2026-09-05T09:01:00+10:00"
    assert saved_states[-1]["last_scheduled_message"] == "Scheduled run completed successfully."
