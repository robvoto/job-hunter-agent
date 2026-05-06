import json

from fastapi.testclient import TestClient

from job_hunter_agent.fastapi_app import create_app


def test_fastapi_health_and_unknown_route_json_errors():
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    missing = client.get("/api/no-such-endpoint")
    assert missing.status_code == 404
    assert missing.json() == {"error": "Not found"}


def test_docs_route_returns_docs_payload():
    client = TestClient(create_app())
    r = client.get("/docs")
    assert r.status_code == 200
    payload = r.json()
    assert "docs" in payload
    assert isinstance(payload["docs"], list)
