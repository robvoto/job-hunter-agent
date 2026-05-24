from fastapi.testclient import TestClient

from job_hunter_agent.fastapi_app import create_app
from job_hunter_agent.io_utils import write_review_data


def test_api_review_data_returns_saved_suggested_tuning(monkeypatch, isolated_db):
    monkeypatch.setattr("job_hunter_agent.fastapi_app.is_auth_disabled", lambda: True)

    write_review_data(
        {
            "kept_job_urls": ["https://example.test/job-1"],
            "skill_observations": [
                {
                    "skill": "Process mapping",
                    "title": "Business Analyst",
                    "company": "Example Co",
                    "url": "https://example.test/job-1",
                    "search_location": "Sydney",
                }
            ],
            "unknown_skills": [],
            "rejections_by_reason": [],
            "suggested_tuning": {
                "summary": {"capability_count": 1, "rule_count": 0},
                "capability_suggestions": [
                    {
                        "kind": "capability",
                        "skill": "Process mapping",
                        "count": 1,
                        "headline": "Keep it",
                        "detail": "Use it",
                        "target": "Capability matrix",
                        "recommended_choice": "working",
                        "recommended_label": "Working",
                        "current_treatment": "Unclassified",
                        "examples": [
                            {
                                "title": "Business Analyst",
                                "company": "Example Co",
                                "url": "https://example.test/job-1",
                                "search_location": "Sydney",
                            }
                        ],
                    }
                ],
                "rule_suggestions": [],
            },
        }
    )

    client = TestClient(create_app())
    response = client.get("/api/review-data")

    assert response.status_code == 200
    payload = response.json()
    assert payload["suggested_tuning"]["capability_suggestions"][0]["skill"] == "Process mapping"
