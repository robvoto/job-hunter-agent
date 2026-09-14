"""End-to-end JH/JMM consumer paging contract for one run-scoped high-water."""

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
    }


class _JmmState:
    def __init__(self) -> None:
        self.jobs = [_job(1), _job(2)]
        self.checkpoint = 0
        self.feed_through_ids: list[int | None] = []
        self.checkpoint_bodies: list[dict] = []
        self.inserted_mid_run = False


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
        if parsed.path.startswith("/v3/consumers/") and parsed.path.endswith("/feed"):
            raw_through = query.get("through_id", [None])[0]
            through_id = int(raw_through) if raw_through is not None else None
            self.state.feed_through_ids.append(through_id)
            snapshot_max_id = max(job["id"] for job in self.state.jobs) if through_id is None else through_id
            eligible = [
                job
                for job in self.state.jobs
                if self.state.checkpoint < job["id"] <= snapshot_max_id
            ]
            # One item per page makes the test exercise checkpoint + second-page paging.
            items = eligible[:1]
            next_cursor = items[-1]["id"] if items else self.state.checkpoint
            self._json(
                {
                    "api_version": "v3",
                    "schema_version": 8,
                    "snapshot_max_id": snapshot_max_id,
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
        body = json.loads(self.rfile.read(content_length) or b"{}")
        if parsed.path.startswith("/v3/consumers/") and parsed.path.endswith("/checkpoint"):
            self.state.checkpoint_bodies.append(body)
            self.state.checkpoint = int(body["last_job_id"])
            if self.state.checkpoint == 1 and not self.state.inserted_mid_run:
                self.state.jobs.append(_job(3))
                self.state.inserted_mid_run = True
            self._json(
                {
                    "consumer_key": "job-hunter:rob",
                    "last_job_id": self.state.checkpoint,
                }
            )
            return
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
        job_history={},
        llm_cache={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-09-14T00:00:00+00:00",
        configured_date_range=3,
        identity_registry=None,
    )


def test_jh_run_keeps_one_snapshot_boundary_and_next_run_sees_new_job(monkeypatch):
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

        first_kept, _, _ = market_map_source.run_market_map_source(_context(), user_id="rob")
        assert [record["market_map_job_id"] for record in first_kept] == [1, 2]
        assert state.feed_through_ids == [None, 2]
        assert [body["last_job_id"] for body in state.checkpoint_bodies] == [1, 2]
        assert all("through_id" not in body for body in state.checkpoint_bodies)

        second_kept, _, _ = market_map_source.run_market_map_source(_context(), user_id="rob")
        assert [record["market_map_job_id"] for record in second_kept] == [3]
        assert state.feed_through_ids == [None, 2, None]
        assert state.checkpoint_bodies[-1]["last_job_id"] == 3
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
