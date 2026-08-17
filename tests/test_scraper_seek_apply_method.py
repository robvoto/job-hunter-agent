"""Tests for SEEK apply_method classification and record wiring."""

import asyncio

from job_hunter_agent.record_schema import (
    APPLY_METHOD_EXTERNAL_APPLY,
    APPLY_METHOD_QUICK_APPLY,
    APPLY_METHOD_UNKNOWN,
    RECORD_APPLY_METHOD_KEY,
    RECORD_COMPANY_KEY,
    RECORD_JOB_KEY,
    RECORD_SOURCE_METADATA_KEY,
    RECORD_TITLE_KEY,
    RECORD_URL_KEY,
)
from job_hunter_agent.scrapers.seek import classify_seek_apply_method
from job_hunter_agent.scrapers.seek_runner import seek_quick_apply_filter_matches
from job_hunter_agent.scrapers import seek_runner


def test_classify_seek_apply_method_detects_quick_apply():
    assert classify_seek_apply_method("Quick apply") == APPLY_METHOD_QUICK_APPLY
    assert classify_seek_apply_method("QUICK APPLY") == APPLY_METHOD_QUICK_APPLY


def test_classify_seek_apply_method_treats_other_text_as_external():
    assert classify_seek_apply_method("Apply") == APPLY_METHOD_EXTERNAL_APPLY


def test_classify_seek_apply_method_unknown_when_blank():
    assert classify_seek_apply_method("") == APPLY_METHOD_UNKNOWN
    assert classify_seek_apply_method(None) == APPLY_METHOD_UNKNOWN


def test_fetch_seek_job_detail_async_stores_apply_method(monkeypatch):
    async def fake_fetch_job_details_payload_async(page, full_url, attempts=2):
        return {"status": "ok", "text": "details", "apply_method": APPLY_METHOD_QUICK_APPLY}

    monkeypatch.setattr(
        seek_runner, "fetch_job_details_payload_async", fake_fetch_job_details_payload_async
    )

    class _FakeLocator:
        async def count(self):
            return 0

    class _FakePage:
        async def evaluate(self, script):
            return None

        def locator(self, selector):
            return _FakeLocator()

    record = {
        RECORD_JOB_KEY: "job-1",
        RECORD_TITLE_KEY: "Analyst",
        RECORD_COMPANY_KEY: "Acme",
        RECORD_URL_KEY: "https://www.seek.com.au/job/1",
    }

    result = asyncio.run(seek_runner._fetch_seek_job_detail_async(record, _FakePage()))

    assert result[RECORD_APPLY_METHOD_KEY] == APPLY_METHOD_QUICK_APPLY


def test_fetch_seek_job_detail_async_stores_external_apply_url(monkeypatch):
    async def fake_fetch_job_details_payload_async(page, full_url, attempts=2):
        return {
            "status": "ok",
            "text": "details",
            "apply_method": APPLY_METHOD_EXTERNAL_APPLY,
            "apply_url": "https://programmed.example.com/jobs/123",
        }

    monkeypatch.setattr(
        seek_runner, "fetch_job_details_payload_async", fake_fetch_job_details_payload_async
    )

    class _FakeLocator:
        async def count(self):
            return 0

    class _FakePage:
        async def evaluate(self, script):
            return None

        def locator(self, selector):
            return _FakeLocator()

    record = {
        RECORD_JOB_KEY: "job-1",
        RECORD_TITLE_KEY: "Analyst",
        RECORD_COMPANY_KEY: "Acme",
        RECORD_URL_KEY: "https://www.seek.com.au/job/1",
    }

    result = asyncio.run(seek_runner._fetch_seek_job_detail_async(record, _FakePage()))

    assert result[RECORD_APPLY_METHOD_KEY] == APPLY_METHOD_EXTERNAL_APPLY
    assert result[RECORD_SOURCE_METADATA_KEY]["apply_url"] == "https://programmed.example.com/jobs/123"


def test_seek_quick_apply_filter_matches_all_modes():
    assert seek_quick_apply_filter_matches(None, "quick_apply") is True
    assert seek_quick_apply_filter_matches(None, "external_apply") is True
    assert seek_quick_apply_filter_matches(True, "quick_apply") is True
    assert seek_quick_apply_filter_matches(True, "external_apply") is False
    assert seek_quick_apply_filter_matches(False, "quick_apply") is False
    assert seek_quick_apply_filter_matches(False, "external_apply") is True
