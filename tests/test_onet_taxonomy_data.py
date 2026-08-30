"""Regression checks for the committed generated O*NET reference data."""

import json
from pathlib import Path

from job_hunter_agent.occupation_taxonomy import RESULT_FAR, classify_title

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "data" / "knowledge" / "occupation_taxonomy" / "onet_index.json"


def _committed_index():
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def test_committed_taxonomy_uses_full_versioned_onet_job_titles_data():
    payload = _committed_index()
    metadata = payload["metadata"]

    assert metadata["source"] == "O*NET Database JSON"
    assert metadata["database_release"]
    assert len(metadata["dataset_fingerprint"]) == 64
    assert metadata["record_counts"]["job_title_rows"] >= 10_000
    assert "cloud engineer" in payload["by_normalized_title"]


def test_committed_taxonomy_rejects_senior_cloud_engineer_for_business_analyst_target(
    monkeypatch,
):
    payload = _committed_index()
    monkeypatch.setattr(
        "job_hunter_agent.occupation_taxonomy._cache_lookup", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "job_hunter_agent.occupation_taxonomy._cache_save", lambda *args, **kwargs: None
    )

    result = classify_title(
        "Senior Cloud Engineer",
        {"target_roles": ["Business Analyst"]},
        _index=payload["by_normalized_title"],
    )

    assert result.result == RESULT_FAR
    assert result.matched_phrase == "Cloud Engineer"
