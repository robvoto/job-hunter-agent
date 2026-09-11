from __future__ import annotations

import json
from datetime import datetime

import job_hunter_agent.job_review_pipeline as job_review_pipeline
import job_hunter_agent.workspace_export as workspace_export
from job_hunter_agent.record_schema import (
    POSTING_CHANNEL_CLASSIFIER_VERSION,
    POSTING_CHANNEL_VERSION_KEY,
)

_NEW_TO_YOU_CUTOFF = datetime.fromisoformat("2026-09-08T09:00:00+10:00")


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
                POSTING_CHANNEL_VERSION_KEY: POSTING_CHANNEL_CLASSIFIER_VERSION,
                "kind": "agency_or_recruiter",
                "source": "metadata_first",
            },
        },
        "current",
        _NEW_TO_YOU_CUTOFF,
    )

    assert "Agency recruiter" in badges
    assert "Recruiter" not in badges


def test_workspace_export_badges_use_preserved_posting_channel_classification():
    direct_record = {
        "company": "Acme",
        "source": "linkedin",
        "source_metadata": {
            "platform": "linkedin",
            "apply_url": "https://jobs.lever.co/acme/123",
            "apply_domain": "jobs.lever.co",
            "company_profile_url": "https://acme.com.au",
            "company_profile_name": "Acme",
            "poster_company": "Acme",
            "hiring_company": "",
            "ats_source": "jobs.lever.co",
            "raw_source_fields": {
                "job_url_direct": "https://jobs.lever.co/acme/123",
                "company_url_direct": "https://acme.com.au",
            },
        },
    }
    recruiter_record = {
        "company": "Recruiter Co",
        "source": "seek",
        "source_metadata": {
            "platform": "seek",
            "apply_url": "",
            "apply_domain": "",
            "company_profile_url": "",
            "company_profile_name": "Recruiter Co",
            "poster_company": "Recruiter Co",
            "hiring_company": "",
            "ats_source": "",
            "raw_source_fields": {
                "recruiter_badge": "Recruiter",
            },
        },
    }

    job_review_pipeline._apply_source_metadata_to_record(
        direct_record,
        {
            "kind": "direct_employer",
            "confident": True,
            "evidence": "The ad describes Acme's own team and employee benefits.",
        },
    )
    job_review_pipeline._apply_source_metadata_to_record(recruiter_record, None)

    direct_badges = workspace_export._build_badges(
        direct_record, "current", _NEW_TO_YOU_CUTOFF
    )
    recruiter_badges = workspace_export._build_badges(
        recruiter_record, "current", _NEW_TO_YOU_CUTOFF
    )

    assert "Direct employer" in direct_badges
    assert "Source unclear" not in direct_badges
    assert "Agency recruiter" in recruiter_badges
    assert "Source unclear" not in recruiter_badges


def test_export_badges_show_source_unclear_for_unknown_channel():
    record = {
        "posting_channel_evidence": {
            POSTING_CHANNEL_VERSION_KEY: POSTING_CHANNEL_CLASSIFIER_VERSION,
            "kind": "unknown",
            "source": "insufficient_evidence",
            "trusted_metadata": [],
            "text_evidence": [],
            "needs_review": False,
        }
    }

    badges = workspace_export._build_badges(record, "current", _NEW_TO_YOU_CUTOFF)

    assert "Source unclear" in badges


def test_export_badges_suppress_stale_posting_channel_classification():
    record = {
        "posting_channel_evidence": {
            POSTING_CHANNEL_VERSION_KEY: POSTING_CHANNEL_CLASSIFIER_VERSION - 1,
            "kind": "direct_employer",
            "source": "metadata_first",
        }
    }

    badges = workspace_export._build_badges(record, "current", _NEW_TO_YOU_CUTOFF)

    assert "Direct employer" not in badges
    assert "Source unclear" not in badges


def test_export_badges_use_managed_posted_age_thresholds():
    badges = workspace_export._build_badges(
        {
            "posted_age_days": 7,
        },
        "current",
        _NEW_TO_YOU_CUTOFF,
    )

    assert "7+ Days Old" in badges
