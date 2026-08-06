"""Regression tests for bounded parallel SEEK title review."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import job_hunter_agent.scrapers.seek_runner as seek_runner


def _record(job_key: str, title: str) -> dict:
    return {"job_key": job_key, "title": title}


def test_pre_detail_batch_continues_other_roles_while_one_waits(monkeypatch):
    release_slow = threading.Event()
    slow_started = threading.Event()
    completed: list[str] = []

    def fake_review(record, context):
        if record["job_key"] == "seek:slow":
            slow_started.set()
            release_slow.wait(timeout=1)
        completed.append(record["job_key"])
        return ({"decision": "REJECT"}, record, [], False)

    monkeypatch.setattr(seek_runner, "review_pre_detail_normalized_job", fake_review)
    monkeypatch.setattr(seek_runner, "SEEK_JOB_WAIT_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(seek_runner, "finalize_record", lambda *args, **kwargs: None)

    context = SimpleNamespace(job_history={}, audit_rows=[], run_iso="run-1")
    started = time.monotonic()
    pre_decided, needs_detail = seek_runner._review_pre_detail_batch(
        [_record("seek:slow", "Slow role"), _record("seek:fast", "Fast role")],
        context,
        max_workers=2,
    )
    elapsed = time.monotonic() - started
    release_slow.set()

    assert slow_started.is_set()
    assert "seek:fast" in completed
    assert elapsed < 0.2
    assert needs_detail == []
    assert pre_decided[0][1][0]["reject_reason"] == "SEEK_JOB_TIMEOUT"
    assert pre_decided[1][1][1]["job_key"] == "seek:fast"


def test_pre_detail_timeout_starts_when_worker_starts_not_when_queued(monkeypatch):
    release_first = threading.Event()
    calls: list[str] = []

    def fake_review(record, context):
        calls.append(record["job_key"])
        if record["job_key"] == "seek:first":
            release_first.wait(timeout=1)
        return ({"decision": "REJECT"}, record, [], False)

    monkeypatch.setattr(seek_runner, "review_pre_detail_normalized_job", fake_review)
    monkeypatch.setattr(seek_runner, "SEEK_JOB_WAIT_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(seek_runner, "finalize_record", lambda *args, **kwargs: None)

    context = SimpleNamespace(job_history={}, audit_rows=[], run_iso="run-1")
    result_holder = {}
    runner = threading.Thread(
        target=lambda: result_holder.setdefault(
            "result",
            seek_runner._review_pre_detail_batch(
                [_record("seek:first", "First"), _record("seek:queued", "Queued")],
                context,
                max_workers=1,
            ),
        ),
        daemon=True,
    )
    runner.start()
    time.sleep(0.08)
    release_first.set()
    runner.join(timeout=1)

    assert not runner.is_alive()
    assert calls == ["seek:first", "seek:queued"]
    pre_decided, _ = result_holder["result"]
    assert pre_decided[1][1][1]["job_key"] == "seek:queued"
