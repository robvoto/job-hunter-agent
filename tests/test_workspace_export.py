from __future__ import annotations

import json

import job_hunter_agent.workspace_export as workspace_export


def test_export_workspace_jobs_merges_existing_export(tmp_path, monkeypatch):
    export_dir = tmp_path / "workspace"
    current_records = [
        {
            "job_key": "abc",
            "title": "Senior Business Analyst",
            "company": "Virtusa",
            "location": "Sydney NSW",
            "url": "https://example.com/jobs/abc",
            "source": "seek",
            "posted": "5h ago",
            "fit_score": 88,
        }
    ]

    monkeypatch.setattr(workspace_export, "get_workspace_export_dir", lambda: export_dir)
    monkeypatch.setattr(workspace_export, "load_profile", lambda: {"match_levels": []})
    monkeypatch.setattr(
        workspace_export,
        "load_run_stats",
        lambda: {
            "run_started_at": "2026-04-28T08:30:51+10:00",
            "run_finished_at": "2026-04-28T08:31:58+10:00",
        },
    )
    monkeypatch.setattr(workspace_export, "load_job_history", lambda: {})
    monkeypatch.setattr(workspace_export, "get_manual_skip_sets", lambda profile: (set(), set()))
    monkeypatch.setattr(
        workspace_export.workspace_service,
        "load_last_kept_records",
        lambda: current_records,
    )
    monkeypatch.setattr(
        workspace_export.workspace_service,
        "build_workspace_record_sets",
        lambda *args, **kwargs: {
            "current_records": current_records,
            "recent_archive_records": [],
            "stale_archive_records": [],
            "applied_records": [],
            "hidden_records": [],
        },
    )
    monkeypatch.setattr(
        workspace_export,
        "fit_score_displayed",
        lambda record, profile=None: int(record.get("fit_score", 0) or 0),
    )

    export_dir.mkdir(parents=True, exist_ok=True)
    existing_payload = {
        "jobs": [
            {
                "job_key": "abc",
                "title": "Old title",
                "company": "OldCo",
                "location": "Old City",
                "url": "https://old.example",
                "score_total": 10,
            }
        ]
    }
    (export_dir / workspace_export.EXPORT_JSON_FILENAME).write_text(
        json.dumps(existing_payload), encoding="utf-8"
    )

    merged = workspace_export.export_workspace_jobs(mode="merge")
    merged_payload = json.loads((export_dir / workspace_export.EXPORT_JSON_FILENAME).read_text())

    assert merged["job_count"] == 1
    assert merged_payload["jobs"][0]["title"] == "Senior Business Analyst"
    assert merged_payload["jobs"][0]["company"] == "Virtusa"

    current_records[0]["title"] = "Senior Business Analyst - refreshed"
    fresh = workspace_export.export_workspace_jobs(mode="fresh")
    fresh_payload = json.loads((export_dir / workspace_export.EXPORT_JSON_FILENAME).read_text())

    assert fresh["job_count"] == 1
    assert fresh_payload["jobs"][0]["title"] == "Senior Business Analyst - refreshed"


def test_workspace_export_uses_agency_recruiter_badge():
    badges = workspace_export._build_badges(
        {
            "source": "seek",
            "posting_channel_evidence": {
                "kind": "agency_or_recruiter",
                "source": "metadata_first",
            },
        },
        "current",
    )

    assert "Agency recruiter" in badges
    assert "Recruiter" not in badges
