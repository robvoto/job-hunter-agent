"""Tests for APSJobs scraper helpers."""

from datetime import date
from urllib.parse import parse_qs, urlparse

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


class _FakeVisibilityElement:
    def __init__(self, visible: bool):
        self._visible = visible

    def is_visible(self):
        return self._visible


class _FakeVisibilityLocator:
    def __init__(self, elements: list[_FakeVisibilityElement]):
        self._elements = elements

    def count(self):
        return len(self._elements)

    def nth(self, index: int):
        return self._elements[index]


class _FakeVisibilityPage:
    def __init__(self, selector_elements: dict[str, list[_FakeVisibilityElement]]):
        self._selector_elements = selector_elements

    def locator(self, selector: str):
        return _FakeVisibilityLocator(self._selector_elements.get(selector, []))


def test_first_visible_locator_skips_hidden_matches_before_visible_one():
    page = _FakeVisibilityPage(
        {
            "input[type='search']": [
                _FakeVisibilityElement(False),
                _FakeVisibilityElement(False),
                _FakeVisibilityElement(True),
            ],
        }
    )

    result = apsjobs_module._first_visible_locator(page, ("input[type='search']",))

    assert result is not None
    assert result.is_visible() is True


def test_first_visible_locator_falls_through_to_next_selector():
    page = _FakeVisibilityPage(
        {
            "input[type='search']": [_FakeVisibilityElement(False)],
            "input[name*='keyword' i]": [_FakeVisibilityElement(True)],
        }
    )

    result = apsjobs_module._first_visible_locator(
        page, ("input[type='search']", "input[name*='keyword' i]")
    )

    assert result is not None
    assert result.is_visible() is True


def test_first_visible_locator_returns_none_when_nothing_visible():
    page = _FakeVisibilityPage(
        {
            "input[type='search']": [_FakeVisibilityElement(False), _FakeVisibilityElement(False)],
        }
    )

    result = apsjobs_module._first_visible_locator(page, ("input[type='search']",))

    assert result is None


def test_normalize_apsjobs_location_filter_maps_supported_locations_to_states():
    assert apsjobs_module._normalize_apsjobs_location_filter("Sydney") == "NSW"
    assert apsjobs_module._normalize_apsjobs_location_filter("Canberra ACT") == "ACT"
    assert apsjobs_module._normalize_apsjobs_location_filter("Melbourne, Victoria") == "VIC"


def test_normalize_apsjobs_location_filter_returns_empty_for_unknown_location():
    assert apsjobs_module._normalize_apsjobs_location_filter("") == ""
    assert apsjobs_module._normalize_apsjobs_location_filter("Auckland") == ""


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


def test_collect_candidate_links_rejects_navigation_pages():
    page = _FakePage(
        url="https://www.apsjobs.gov.au/s/",
        body_text="",
        title_text="",
        anchors=[
            _FakeAnchor("/s", "Home"),
            _FakeAnchor("/s-registration", "Register"),
            _FakeAnchor("/s-log-in", "Sign In"),
            _FakeAnchor("/working-aps/hr-practitioners/recruitment/aps-ai-recruitment", "AI in recruitment"),
            _FakeAnchor("/s/job-details/123", "Senior Analyst"),
        ],
    )

    links = apsjobs_module._collect_candidate_links(page, page.url, 10)

    assert links == [
        {
            "url": "https://www.apsjobs.gov.au/s/job-details/123",
            "text": "Senior Analyst",
        }
    ]


def test_collect_candidate_links_keeps_real_job_titles_containing_register():
    page = _FakePage(
        url="https://www.apsjobs.gov.au/s/job-search?searchString=business%20analyst&state=NSW",
        body_text="",
        title_text="",
        anchors=[
            _FakeAnchor("/s/registration", "Register"),
            _FakeAnchor(
                "/s/job-details?title=temporary-employment-register&Id=a05OY00000MGFeLYAX",
                "AFMA 2026/27 Fisheries Observer Temporary Employment Register",
            ),
        ],
    )

    links = apsjobs_module._collect_candidate_links(page, page.url, 10)

    assert links == [
        {
            "url": "https://www.apsjobs.gov.au/s/job-details?title=temporary-employment-register&Id=a05OY00000MGFeLYAX",
            "text": "AFMA 2026/27 Fisheries Observer Temporary Employment Register",
        }
    ]


def test_extract_posted_text_and_age_from_visible_listing_text():
    posted_text = apsjobs_module._extract_posted_text("Senior Analyst\nPosted 3 hours ago")

    assert posted_text == "posted 3 hours ago"
    assert apsjobs_module.parse_visible_posted_age_days(posted_text, date(2026, 6, 23)) == pytest.approx(
        3 / 24
    )


def test_extract_job_type_text_from_multiline_aps_metadata():
    assert (
        apsjobs_module._extract_job_type_text(
            "Opportunity Type\nFull-Time\nOpportunity Status\nOngoing"
        )
        == "Full-Time"
    )


def test_extract_job_type_text_from_collapsed_aps_metadata():
    assert (
        apsjobs_module._extract_job_type_text(
            "...Opportunity TypeFull-TimeOpportunity StatusOngoingClosing Date..."
        )
        == "Full-Time"
    )


def test_extract_job_type_text_from_collapsed_aps_multi_value():
    assert (
        apsjobs_module._extract_job_type_text(
            "...Opportunity TypeFull-Time;Part-TimeOpportunity StatusOngoing..."
        )
        == "Full-Time;Part-Time"
    )


def test_extract_job_type_text_does_not_return_an_unbounded_page_tail():
    assert (
        apsjobs_module._extract_job_type_text(
            "Opportunity TypeFull-Time role details and application information: contact us"
        )
        == ""
    )


def test_extract_job_type_text_does_not_use_generic_type_label():
    assert apsjobs_module._extract_job_type_text("Type: page text") == ""


def test_format_apsjobs_run_progress_keeps_elapsed_separate():
    progress = apsjobs_module._format_apsjobs_run_progress(
        1,
        2,
        scanned_titles=["Senior Analyst", "Assistant Director"],
    )

    assert progress == (
        "APSJobs search 1/2\n"
        "Senior Analyst\n"
        "Assistant Director"
    )


def test_apsjobs_progress_producer_emits_latest_title(monkeypatch):
    captured: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        apsjobs_module,
        "set_run_progress_state",
        lambda text, **detail: captured.append((text, detail)),
    )

    apsjobs_module._set_apsjobs_run_progress(
        1,
        3,
        ["Senior Analyst", "Policy Officer"],
    )

    text, detail = captured[-1]
    assert text == "APSJobs search 1/3\nSenior Analyst\nPolicy Officer"
    assert detail == {
        "stage": "source_collection",
        "source": "apsjobs",
        "headline": "APS Jobs search 1 of 3",
        "detail": "Policy Officer",
        "current": 1,
        "total": 3,
    }


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


def test_extract_job_payload_marks_browser_interstitial_as_challenge_page(monkeypatch):
    monkeypatch.setattr(apsjobs_module, "job_type_rules", {"ongoing": "Ongoing"})

    page = _FakePage(
        url="https://www.apsjobs.gov.au/s/job-details/123",
        body_text=(
            "Loading×Sorry to interruptCSS ErrorRefresh (function() { "
            "if (!navigator.cookieEnabled) { var cookieMessage = document.createElement('div'); "
            "cookieMessage.innerHTML = \"<section role='alert'>\"; } })"
        ),
        title_text="",
        anchors=[],
    )

    payload = apsjobs_module._extract_job_payload(
        page,
        job_url=page.url,
        anchor_text="Analyst (Multiple Positions)",
        run_iso="2026-06-23T09:00:00+10:00",
    )

    assert payload["title"] == "Analyst (Multiple Positions)"
    assert payload["details_status"] == "challenge_page"
    assert payload["details_text"] == ""
    assert payload["teaser"] == ""


def test_build_apsjobs_search_url_applies_term_and_state_directly():
    url = apsjobs_module._build_apsjobs_search_url("Business Analyst", "NSW")

    query = parse_qs(urlparse(url).query)
    assert query["searchString"] == ["Business Analyst"]
    assert query["state"] == ["NSW"]


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


def test_build_apsjobs_search_targets_uses_all_distinct_profile_role_terms():
    keywords, targets = apsjobs_module.build_apsjobs_search_targets(
        {"keywords": "legacy keyword", "locations": ["NSW"]},
        {
            "target_roles": ["Senior Systems Analyst", "Business Analyst"],
            "also_consider_roles": ["AI Business Analyst"],
            "target_occupation_queries": [
                "Senior Business Analyst",
                "business analyst",
                "Systems Analyst",
            ],
        },
    )

    assert keywords == "Senior Systems Analyst"
    assert [target["search_term"] for target in targets] == [
        "Senior Systems Analyst",
        "Business Analyst",
        "AI Business Analyst",
        "Senior Business Analyst",
        "Systems Analyst",
    ]


def test_new_candidate_links_deduplicates_same_aps_job_across_search_targets():
    seen_job_keys: set[str] = set()
    first = apsjobs_module._new_candidate_links(
        [
            {
                "url": "https://www.apsjobs.gov.au/s/job-details?title=it-business-analyst&Id=a05OY00000QBti9YAD",
                "text": "IT Business Analyst",
            }
        ],
        seen_job_keys,
    )
    second = apsjobs_module._new_candidate_links(
        [
            {
                "url": "https://www.apsjobs.gov.au/s/job-details?title=it-business-analyst&Id=a05OY00000QBti9YAD",
                "text": "IT Business Analyst",
            }
        ],
        seen_job_keys,
    )

    assert len(first) == 1
    assert second == []
    assert seen_job_keys == {"apsjobs:a05oy00000qbti9yad"}


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
        {"search_term": "policy officer", "location": "ACT", "results_wanted": 40},
        {"search_term": "policy officer", "location": "NSW", "results_wanted": 40},
    ]


def test_build_apsjobs_search_targets_dedupes_shared_locations_to_distinct_states():
    keywords, targets = apsjobs_module.build_apsjobs_search_targets(
        {
            "keywords": "policy officer",
            "locations": ["Sydney", "Newcastle", "Canberra"],
            apsjobs_module.KEY_APSJOBS_RESULTS_PER_SEARCH: 40,
        }
    )

    assert keywords == "policy officer"
    assert targets == [
        {"search_term": "policy officer", "location": "NSW", "results_wanted": 40},
        {"search_term": "policy officer", "location": "ACT", "results_wanted": 40},
    ]
