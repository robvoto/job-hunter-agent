"""Tests for APSJobs scraper helpers."""

from datetime import date

import pytest

from job_hunter_agent.scrapers import apsjobs as apsjobs_module


class _FakeAnchor:
    def __init__(self, href: str, text: str):
        self._href = href
        self._text = text

    def get_attribute(self, name: str):
        if name == "href":
            return self._href
        return None

    def inner_text(self):
        return self._text


class _FakeAnchorLocator:
    def __init__(self, anchors: list[_FakeAnchor]):
        self._anchors = anchors

    def count(self):
        return len(self._anchors)

    def nth(self, index: int):
        return self._anchors[index]


class _FakeTextLocator:
    def __init__(self, text: str, count: int = 1):
        self._text = text
        self._count = count

    def count(self):
        return self._count

    def inner_text(self):
        return self._text


class _FakePage:
    def __init__(self, *, url: str, body_text: str, title_text: str, anchors: list[_FakeAnchor]):
        self._url = url
        self._body_text = body_text
        self._title_text = title_text
        self._anchors = anchors

    @property
    def url(self):
        return self._url

    def locator(self, selector: str):
        if selector == "body":
            return _FakeTextLocator(self._body_text)
        if selector == "a[href]":
            return _FakeAnchorLocator(self._anchors)
        if selector in apsjobs_module.APSJOBS_TITLE_SELECTORS:
            return _FakeTextLocator(self._title_text)
        return _FakeTextLocator("", count=0)

    def text_content(self, selector: str):
        if selector == "body":
            return self._body_text
        return ""

    def content(self):
        return f"<html><body>{self._body_text}</body></html>"


def test_collect_candidate_links_prefers_jobish_anchors():
    page = _FakePage(
        url="https://www.apsjobs.gov.au/s/",
        body_text="",
        title_text="",
        anchors=[
            _FakeAnchor("/s/home", "Home"),
            _FakeAnchor("/s/job-details/123", "Senior Analyst"),
            _FakeAnchor("/s/job-details/456", "View vacancy"),
        ],
    )

    links = apsjobs_module._collect_candidate_links(page, page.url, 2)

    assert links[0]["url"] == "https://www.apsjobs.gov.au/s/job-details/123"
    assert links[0]["text"] == "Senior Analyst"
    assert links[1]["url"] == "https://www.apsjobs.gov.au/s/job-details/456"


def test_extract_posted_text_and_age_from_visible_listing_text():
    posted_text = apsjobs_module._extract_posted_text("Senior Analyst\nPosted 3 hours ago")

    assert posted_text == "posted 3 hours ago"
    assert apsjobs_module.parse_visible_posted_age_days(posted_text, date(2026, 6, 23)) == pytest.approx(
        3 / 24
    )


def test_extract_job_payload_uses_visible_text_and_shared_key_logic(monkeypatch):
    monkeypatch.setattr(apsjobs_module, "job_type_rules", {"ongoing": "Ongoing"})

    page = _FakePage(
        url="https://www.apsjobs.gov.au/s/job-details/123",
        body_text=(
            "Senior Technical Business Analyst\n"
            "Agency: Department of Home Affairs\n"
            "Location: Canberra ACT\n"
            "Posted 3 hours ago\n"
            "Employment type: Ongoing"
        ),
        title_text="Senior Technical Business Analyst",
        anchors=[],
    )

    payload = apsjobs_module._extract_job_payload(
        page,
        job_url=page.url,
        anchor_text="Senior Technical Business Analyst",
        run_iso="2026-06-23T09:00:00+10:00",
    )

    assert payload["job_key"].startswith("apsjobs:")
    assert payload["title"] == "Senior Technical Business Analyst"
    assert payload["company"] == "Department of Home Affairs"
    assert payload["location"] == "Canberra ACT"
    assert payload["posted_text"] == "posted 3 hours ago"
    assert payload["posted_age_days"] == pytest.approx(3 / 24)
    assert payload["source_metadata"]["platform"] == "apsjobs"


def test_build_apsjobs_search_targets_uses_configured_default_when_unset():
    keywords, targets = apsjobs_module.build_apsjobs_search_targets(
        {"keywords": "data analyst", "locations": []}
    )

    assert keywords == "data analyst"
    assert targets == [
        {
            "search_term": "data analyst",
            "location": "",
            "results_wanted": apsjobs_module.DEFAULT_SEARCH_SETTINGS[
                apsjobs_module.KEY_APSJOBS_RESULTS_PER_SEARCH
            ],
        }
    ]


def test_build_apsjobs_search_targets_honours_override_per_location():
    keywords, targets = apsjobs_module.build_apsjobs_search_targets(
        {
            "keywords": "policy officer",
            "locations": ["Canberra", "Sydney"],
            apsjobs_module.KEY_APSJOBS_RESULTS_PER_SEARCH: 40,
        }
    )

    assert keywords == "policy officer"
    assert targets == [
        {"search_term": "policy officer", "location": "Canberra", "results_wanted": 40},
        {"search_term": "policy officer", "location": "Sydney", "results_wanted": 40},
    ]
