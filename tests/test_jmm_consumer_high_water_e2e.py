"""End-to-end JH/JMM filtered-search contract."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from job_hunter_agent import market_map_source


def _job(job_id: int) -> dict:
    return {
        "id": job_id,
        "identity_key": f"seek:id:{job_id}",
        "source": "seek",
        "source_job_id": str(job_id),
        "canonical_url": f"https://seek.example/jobs/{job_id}",
        "title": f"Business Analyst {job_id}",
        "employer": "Example Co",
        "location": "Sydney NSW",
        "workplace_type": "Hybrid",
        "employment_type": "Full time",
        "salary_text": "$100k",
        "apply_method": "quick_apply",
        "posted_at": "2026-09-14T00:00:00+00:00",
        "teaser_text": "A role",
        "field_states": {
            "title": "known",
            "company": "known",
            "location": "known",
            "geography_code": "unknown",
            "posted_at": "known",
            "classification": "unknown",
            "subclassification": "unknown",
            "employment_type": "known",
            "workplace_type": "known",
            "apply_method": "known",
            "salary": "known",
            "description": "unknown",
        },
        "salary_normalized": {
            "state": "known",
            "min_amount": 100000,
            "max_amount": 100000,
            "period": "year",
            "currency": "AUD",
            "qualifier": None,
            "bound": "exact",
        },
    }


class _JmmState:
    def __init__(self) -> None:
        self.jobs = [_job(1), _job(2)]
        self.search_calls: list[dict[str, list[str]]] = []


class _Handler(BaseHTTPRequestHandler):
    state: _JmmState

    def log_message(self, *_args) -> None:
        pass

    def _json(self, payload: dict, status: int = 200) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        if parsed.path.startswith("/v3/jobs/") and parsed.path.endswith("/jd"):
            job_id = int(parsed.path.split("/")[3])
            self._json(
                {
                    "api_version": "v3",
                    "schema_version": 8,
                    "job_id": job_id,
                    "full_description": f"Canonical JD {job_id}",
                    "jd_source": "test_jmm",
                    "jd_fetched_at": "2026-09-14T00:01:00+00:00",
                }
            )
            return
        if parsed.path == "/v3/jobs/search":
            self.state.search_calls.append(query)
            after_id = int(query.get("after_id", ["0"])[0])
            eligible = [job for job in self.state.jobs if job["id"] > after_id]
            items = eligible[:1]
            next_cursor = items[-1]["id"] if items else after_id
            self._json(
                {
                    "api_version": "v3",
                    "schema_version": 8,
                    "snapshot_max_id": max(job["id"] for job in self.state.jobs),
                    "total": len(self.state.jobs),
                    "items": items,
                    "next_cursor": next_cursor,
                    "has_more": len(eligible) > 1,
                }
            )
            return
        self._json({"detail": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        parsed = urlsplit(self.path)
        content_length = int(self.headers.get("Content-Length") or 0)
        json.loads(self.rfile.read(content_length) or b"{}")
        if parsed.path.startswith("/v3/jobs/") and parsed.path.endswith("/jd"):
            job_id = int(parsed.path.split("/")[3])
            self._json(
                {
                    "api_version": "v3",
                    "schema_version": 8,
                    "job_id": job_id,
                    "full_description": f"Canonical JD {job_id}",
                    "jd_source": "test_jmm",
                    "jd_fetched_at": "2026-09-14T00:01:00+00:00",
                }
            )
            return
        self._json({"detail": "not found"}, status=404)


def _context() -> SimpleNamespace:
    return SimpleNamespace(
        profile={},
        search_settings={"keywords": "Business Analyst", "locations": ["Sydney"]},
        enabled_sources=["seek"],
        job_history={},
        llm_cache={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-09-14T00:00:00+00:00",
        configured_date_range=3,
        identity_registry=None,
    )


def test_jh_run_uses_filtered_search_without_consumer_state(monkeypatch):
    state = _JmmState()
    handler = type("StatefulJmmHandler", (_Handler,), {"state": state})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv(
            "JOB_HUNTER_MARKET_MAP_BASE_URL",
            f"http://127.0.0.1:{server.server_port}/v3",
        )
        monkeypatch.setattr(
            market_map_source,
            "review_pre_detail_normalized_job",
            lambda record, _context: ({"decision": "KEEP"}, record, [], True),
        )
        monkeypatch.setattr(
            market_map_source,
            "review_post_detail_normalized_job",
            lambda record, _context: ({"decision": "KEEP"}, record, []),
        )

        first_kept, _, _ = market_map_source.run_market_map_source(_context())
        assert [record["market_map_job_id"] for record in first_kept] == [1, 2]
        assert [call["after_id"] for call in state.search_calls] == [["0"], ["1"]]
        assert all(call["source"] == ["seek"] for call in state.search_calls)
        assert all(call["q"] == ["Business Analyst"] for call in state.search_calls)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
