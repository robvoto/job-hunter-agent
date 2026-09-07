"""Tests for seek runner record shape."""

import logging
from types import SimpleNamespace

from job_hunter_agent.record_schema import (
    RECORD_CARD_SALARY_KEY,
    RECORD_COMPANY_KEY,
    RECORD_COMPETITIVE_SIGNALS_KEY,
    RECORD_CONTENT_REASON_KEY,
    RECORD_DECISION_KEY,
    RECORD_DESCRIPTION_SOURCE_KEY,
    RECORD_DETAILS_LENGTH_KEY,
    RECORD_DETAILS_STATUS_KEY,
    RECORD_DETAILS_TEXT_KEY,
    RECORD_FIT_CONFIDENCE_KEY,
    RECORD_FIT_HIGHLIGHTS_KEY,
    RECORD_FIT_SOURCE_TEXT_KEY,
    RECORD_FULL_DESCRIPTION_KEY,
    RECORD_HARD_BLOCK_REASONS_KEY,
    RECORD_JOB_KEY,
    RECORD_LLM_DECISION_KEY,
    RECORD_LLM_FIT_GRADE_KEY,
    RECORD_LOCATION_KEY,
    RECORD_MISSING_PROFILE_SUPPORT_KEY,
    RECORD_PAGE_KEY,
    RECORD_POSTED_AGE_DAYS_KEY,
    RECORD_POSTED_KEY,
    RECORD_POSTING_CHANNEL_EVIDENCE_KEY,
    RECORD_REJECT_REASON_KEY,
    RECORD_REVIEWED_SIGNAL_MATCHES_KEY,
    RECORD_ROLE_SNAPSHOT_KEY,
    RECORD_RUN_STARTED_AT_KEY,
    RECORD_SALARY_KEY,
    RECORD_SEARCH_KEYWORDS_KEY,
    RECORD_SEARCH_LOCATION_KEY,
    RECORD_SOFT_RISK_REASONS_KEY,
    RECORD_SOURCE_ATS_REQUISITION_ID_KEY,
    RECORD_SOURCE_KEY,
    RECORD_SOURCE_METADATA_KEY,
    RECORD_SOURCE_PLATFORM_JOB_ID_KEY,
    RECORD_TEASER_KEY,
    RECORD_TITLE_KEY,
    RECORD_TITLE_MATCH_METADATA_KEY,
    RECORD_TITLE_REASON_KEY,
    RECORD_URL_KEY,
    RECORD_WORK_MODE_EVIDENCE_KEY,
    RECORD_WORK_MODE_KEY,
    RECORD_WORK_MODE_NEEDS_REVIEW_KEY,
    RECORD_WORK_MODE_SOURCE_KEY,
    RECORD_WORK_TYPE_KEY,
)
from job_hunter_agent.scrapers.base import normalize_jobspy_record
from job_hunter_agent.scrapers.seek_runner import (
    _classify_seek_list_page_text,
    _classify_seek_list_page_failure,
    _handle_seek_list_page_failure,
    _log_seek_list_page_diagnostics,
    _seek_json_assignment_value,
    _seek_run_progress,
    _set_seek_run_progress,
    _seek_source_metadata,
    _wait_for_seek_bot_challenge_or_manual_verification,
    _wait_for_seek_user_verification,
    build_seek_card_record,
    BotChallengeDetected,
    SEEK_BOT_CHALLENGE,
    SEEK_HUMAN_VERIFICATION,
    SEEK_SIGN_IN_WALL,
    SEEK_TIMEOUT_NO_CARDS,
)


class _FakeElement:
    def __init__(self, text: str = "", href: str | None = None):
        self._text = text
        self._href = href

    def inner_text(self):
        return self._text

    def get_attribute(self, name):
        if name == "href":
            return self._href
        return None


class _FakeCard:
    def __init__(self):
        self._title = _FakeElement("Senior Analyst", "/jobs/1")
        self._company = _FakeElement("Acme")
        self._posted = _FakeElement("today")

    def query_selector(self, selector):
        if selector.endswith("jobTitle"):
            return self._title
        if selector.endswith("jobCompany"):
            return self._company
        if selector.endswith("jobListingDate"):
            return self._posted
        return None

    def inner_text(self):
        return "Senior Analyst at Acme"


class _FakeDetailPage:
    def evaluate(self, script):
        return None


class _FakeLocator:
    def __init__(self, count: int):
        self._count = count

    def count(self):
        return self._count


class _FakeListPage:
    def __init__(self, *, title: str, url: str, body_text: str, card_count: int):
        self._title = title
        self._url = url
        self._body_text = body_text
        self._card_count = card_count

    def title(self):
        return self._title

    @property
    def url(self):
        return self._url

    def inner_text(self, selector):
        if selector == "body":
            return self._body_text
        raise AssertionError(f"unexpected selector: {selector}")

    def locator(self, selector):
        assert selector == 'article[data-automation="normalJob"], article[data-automation="premiumJob"]'
        return _FakeLocator(self._card_count)


def test_seek_card_record_keeps_expected_shape_and_review_buckets(monkeypatch):
    monkeypatch.setattr(
        "job_hunter_agent.scrapers.seek_runner.extract_card_metadata",
        lambda card, filter_state=None: {
            "location": "Sydney",
            "work_mode": "Hybrid",
            "work_mode_source": "card",
            "work_mode_evidence": ["hybrid"],
            "work_mode_needs_review": False,
            "work_type": "Full time",
            "teaser": "Role teaser",
            "card_salary": "$120k",
        },
    )
    monkeypatch.setattr(
        "job_hunter_agent.scrapers.seek_runner.extract_posted_text_from_card",
        lambda text: "today",
    )
    monkeypatch.setattr(
        "job_hunter_agent.scrapers.seek_runner.build_full_seek_url",
        lambda relative_url: "https://www.seek.com.au/jobs/1",
    )
    monkeypatch.setattr(
        "job_hunter_agent.scrapers.seek_runner.stable_job_key",
        lambda url: f"seek:{url}",
    )

    seek_record = build_seek_card_record(
        _FakeCard(),
        {"location": "Sydney", "keywords": "analyst"},
        "2026-05-07T09:00:00+10:00",
        2,
    )
    jobspy_record = normalize_jobspy_record(
        row=SimpleNamespace(
            date_posted="2026-05-06",
            min_amount=None,
            max_amount=None,
            interval="yearly",
            currency="AUD",
            job_type="Full Time",
            description="Role description",
            id="1",
            title="Senior Analyst",
            company="Acme",
            location="Sydney",
            job_url="https://www.seek.com.au/jobs/1",
        ),
        source="seek",
        search_keywords="analyst",
        search_location="Sydney",
        run_iso="2026-05-07T09:00:00+10:00",
        salary_rules={
            "interval_divisor": {"yearly": 1000},
            "interval_suffix": {"yearly": "p.a."},
            "currencies_with_dollar": ["AUD"],
        },
        job_type_rules={"fulltime": "Full time"},
    )

    expected_keys = {
        RECORD_RUN_STARTED_AT_KEY,
        RECORD_SEARCH_LOCATION_KEY,
        RECORD_SEARCH_KEYWORDS_KEY,
        RECORD_PAGE_KEY,
        RECORD_SOURCE_KEY,
        RECORD_JOB_KEY,
        RECORD_TITLE_KEY,
        RECORD_COMPANY_KEY,
        RECORD_POSTED_KEY,
        RECORD_POSTED_AGE_DAYS_KEY,
        RECORD_URL_KEY,
        RECORD_LOCATION_KEY,
        RECORD_WORK_MODE_KEY,
        RECORD_WORK_MODE_SOURCE_KEY,
        RECORD_WORK_MODE_EVIDENCE_KEY,
        RECORD_WORK_MODE_NEEDS_REVIEW_KEY,
        RECORD_WORK_TYPE_KEY,
        RECORD_TEASER_KEY,
        RECORD_CARD_SALARY_KEY,
        RECORD_DECISION_KEY,
        RECORD_REJECT_REASON_KEY,
        RECORD_TITLE_REASON_KEY,
        RECORD_TITLE_MATCH_METADATA_KEY,
        RECORD_CONTENT_REASON_KEY,
        RECORD_LLM_DECISION_KEY,
        RECORD_LLM_FIT_GRADE_KEY,
        RECORD_DETAILS_LENGTH_KEY,
        RECORD_DETAILS_TEXT_KEY,
        RECORD_SALARY_KEY,
        RECORD_FIT_HIGHLIGHTS_KEY,
        RECORD_SOFT_RISK_REASONS_KEY,
        RECORD_MISSING_PROFILE_SUPPORT_KEY,
        RECORD_COMPETITIVE_SIGNALS_KEY,
        RECORD_REVIEWED_SIGNAL_MATCHES_KEY,
        RECORD_SOURCE_METADATA_KEY,
        RECORD_POSTING_CHANNEL_EVIDENCE_KEY,
        RECORD_DETAILS_STATUS_KEY,
        RECORD_DESCRIPTION_SOURCE_KEY,
        RECORD_FIT_CONFIDENCE_KEY,
        RECORD_FIT_SOURCE_TEXT_KEY,
        RECORD_FULL_DESCRIPTION_KEY,
        RECORD_HARD_BLOCK_REASONS_KEY,
        RECORD_ROLE_SNAPSHOT_KEY,
    }

    assert expected_keys.issubset(set(seek_record))
    assert (
        seek_record[RECORD_REVIEWED_SIGNAL_MATCHES_KEY]
        == jobspy_record[RECORD_REVIEWED_SIGNAL_MATCHES_KEY]
    )
    assert (
        seek_record[RECORD_POSTING_CHANNEL_EVIDENCE_KEY]
        == jobspy_record[RECORD_POSTING_CHANNEL_EVIDENCE_KEY]
    )


def test_seek_server_state_parser_preserves_nested_employer_metadata():
    script_text = '''
        window.SEEK_CONFIG = {};
        window.SEEK_REDUX_DATA = {
          "jobdetails": {
            "result": {
              "__typename": "JobDetails",
              "job": {
                "advertiser": {
                  "__typename": "Advertiser",
                  "id": "44935084",
                  "name": "Volkswagen Financial Services Australia Pty Limited"
                }
              },
              "companySearchUrl": "https://au.seek.com/Volkswagen-Financial-Services-Australia-Pty-Limited-jobs/at-this-company",
              "seoInfo": {
                "normalisedOrganisationName": "Volkswagen Financial Services Australia Pty Limited"
              }
            }
          }
        };
        window.SEEK_APP_CONFIG = {};
    '''

    redux_payload = _seek_json_assignment_value(script_text, "SEEK_REDUX_DATA")
    metadata, _ = _seek_source_metadata(
        None,
        {"apply_url": "https://www.seek.com.au/job/93915767/apply"},
        redux_payload=redux_payload,
        url="https://www.seek.com.au/job/93915767?tracking=abc",
    )

    assert metadata["advertiser_id"] == "44935084"
    assert metadata["poster_company"] == "Volkswagen Financial Services Australia Pty Limited"
    # SEEK's advertiser/company profile identifies the publisher. It must not be
    # promoted to hiring_company unless SEEK provides an explicit hirer fact.
    assert metadata["hiring_company"] == ""
    assert metadata["company_profile_url"].startswith("https://au.seek.com/Volkswagen-")
    assert metadata[RECORD_SOURCE_PLATFORM_JOB_ID_KEY] == "93915767"


def test_seek_source_metadata_uses_url_job_id_and_preserves_ats_id():
    metadata, _ = _seek_source_metadata(
        _FakeDetailPage(),
        {
            "seekPostingSourceCode": "PLAT-1",
            "seekHirerJobReference": "REQ-9",
            "shareLink": "https://www.seek.com.au/job/1",
        },
        url="https://www.seek.com.au/job/1?tracking=abc",
    )

    assert metadata[RECORD_SOURCE_PLATFORM_JOB_ID_KEY] == "1"
    assert metadata["raw_source_fields"]["seekPostingSourceCode"] == "PLAT-1"
    assert metadata[RECORD_SOURCE_ATS_REQUISITION_ID_KEY] == "REQ-9"


def test_seek_source_metadata_omits_blank_ats_id():
    metadata, _ = _seek_source_metadata(
        _FakeDetailPage(),
        {
            "seekPostingSourceCode": "PLAT-1",
            "seekHirerJobReference": "",
            "shareLink": "https://www.seek.com.au/job/1",
        },
        url="https://www.seek.com.au/job/1",
    )

    assert metadata[RECORD_SOURCE_PLATFORM_JOB_ID_KEY] == "1"
    assert metadata["raw_source_fields"]["seekPostingSourceCode"] == "PLAT-1"
    assert RECORD_SOURCE_ATS_REQUISITION_ID_KEY not in metadata


def test_seek_list_page_text_classification_flags_challenge_page():
    text = "Help us keep SEEK secure, confirm you are human."

    assert _classify_seek_list_page_text(text) == "challenge_page"


def test_seek_list_page_failure_classification_uses_marker_priority():
    assert (
        _classify_seek_list_page_failure(
            "SEEK jobs",
            "Help us keep SEEK secure, please verify.",
            selector_count=0,
        )
        == SEEK_HUMAN_VERIFICATION
    )
    assert (
        _classify_seek_list_page_failure("Just a moment", "", selector_count=0)
        == SEEK_BOT_CHALLENGE
    )
    assert (
        _classify_seek_list_page_failure("SEEK jobs", "confirm you are human", selector_count=0)
        == SEEK_BOT_CHALLENGE
    )
    assert (
        _classify_seek_list_page_failure("SEEK jobs", "No cards yet", selector_count=0)
        == SEEK_TIMEOUT_NO_CARDS
    )


def test_seek_sign_in_wall_is_classified_as_expected_public_boundary():
    assert _classify_seek_list_page_text("Sign in to see more jobs") == "sign_in_wall"
    assert (
        _classify_seek_list_page_failure(
            "SEEK jobs",
            "Sign in to see more jobs Continue with Google Continue with Email",
            selector_count=0,
        )
        == SEEK_SIGN_IN_WALL
    )


def test_seek_sign_in_wall_stops_target_without_error_progress(monkeypatch, caplog):
    progress_calls = []
    monkeypatch.setattr(
        "job_hunter_agent.scrapers.seek_runner._set_seek_status_progress",
        lambda message, **kwargs: progress_calls.append((message, kwargs.get("stage"))),
    )
    caplog.set_level(logging.INFO, logger="job_hunter_agent.scrapers.seek_runner")

    recovered = _handle_seek_list_page_failure(
        "[SEEK p4/5]",
        object(),
        TimeoutError("no public cards"),
        {
            "title": "SEEK jobs",
            "url": "https://seek.example/?page=4",
            "body_text": "Sign in to see more jobs",
            "selector_count": 0,
            "page_status": "sign_in_wall",
            "failure_class": SEEK_SIGN_IN_WALL,
        },
        page_status="sign_in_wall",
        failure_class=SEEK_SIGN_IN_WALL,
        headless=False,
        use_persistent_browser=False,
        assisted_verification_enabled=False,
        playwright_selector_timeout=5000,
    )

    assert recovered is False
    assert progress_calls == [
        (
            "SEEK reached its public sign-in boundary; continuing with the remaining searches.",
            "source_collection",
        )
    ]
    assert "[SEEK][SIGN_IN_WALL]" in caplog.text


def test_seek_user_verification_wait_succeeds_when_cards_appear(monkeypatch):
    calls = []

    class _WaitPage:
        def wait_for_selector(self, selector, timeout):
            calls.append((selector, timeout))

    monkeypatch.setattr(
        "job_hunter_agent.scrapers.seek_runner._set_seek_status_progress", lambda message, **kwargs: None
    )

    assert _wait_for_seek_user_verification(_WaitPage(), "[SEEK p1/3]", 5000) is True
    assert calls == [(
        'article[data-automation="normalJob"], article[data-automation="premiumJob"]',
        5000,
    )]


def test_seek_visible_cloudflare_challenge_surfaces_action_before_it_clears(monkeypatch, caplog):
    progress_calls = []

    class _ChallengePage:
        cleared = False

        def title(self):
            return "SEEK jobs" if self.cleared else "Just a moment"

        def inner_text(self, selector):
            assert selector == "body"
            return "jobs loaded" if self.cleared else "confirm you are human"

        def wait_for_function(self, _expression, timeout):
            assert timeout == 15000
            self.cleared = True

    monkeypatch.setattr(
        "job_hunter_agent.scrapers.seek_runner._set_seek_status_progress",
        lambda message, **kwargs: progress_calls.append((message, kwargs.get("stage"))),
    )
    caplog.set_level(logging.INFO, logger="job_hunter_agent.scrapers.seek_runner")

    assert (
        _wait_for_seek_bot_challenge_or_manual_verification(
            _ChallengePage(),
            "[SEEK p5/5]",
            headless=False,
            use_persistent_browser=False,
            assisted_verification_enabled=False,
            playwright_selector_timeout=5000,
        )
        is False
    )

    assert progress_calls[0][1] == "verification"
    assert progress_calls[0][0].startswith("Action required: SEEK verification")
    assert "browser window" in progress_calls[0][0]
    assert progress_calls[-1] == (
        "SEEK verification cleared; continuing search.",
        "source_collection",
    )
    assert "Cloudflare challenge cleared" in caplog.text
    assert "auto-resolved" not in caplog.text


def test_seek_bot_challenge_wait_succeeds_when_cards_appear(monkeypatch):
    calls = []

    class _ChallengePage:
        def title(self):
            return "Just a moment"

        def inner_text(self, selector):
            assert selector == "body"
            return "confirm you are human"

        def wait_for_selector(self, selector, timeout):
            calls.append((selector, timeout))

    monkeypatch.setattr(
        "job_hunter_agent.scrapers.seek_runner._set_seek_status_progress", lambda message, **kwargs: None
    )

    assert (
        _wait_for_seek_bot_challenge_or_manual_verification(
            _ChallengePage(),
            "[SEEK p1/3]",
            headless=False,
            use_persistent_browser=True,
            assisted_verification_enabled=True,
            playwright_selector_timeout=5000,
        )
        is True
    )
    assert calls == [(
        'article[data-automation="normalJob"], article[data-automation="premiumJob"]',
        5000,
    )]


def test_seek_bot_challenge_wait_succeeds_in_visible_browser_without_assisted_flag(monkeypatch):
    calls = []

    class _ChallengePage:
        def title(self):
            return "Just a moment"

        def inner_text(self, selector):
            assert selector == "body"
            return "confirm you are human"

        def wait_for_selector(self, selector, timeout):
            calls.append((selector, timeout))

    monkeypatch.setattr(
        "job_hunter_agent.scrapers.seek_runner._set_seek_status_progress", lambda message, **kwargs: None
    )

    assert (
        _wait_for_seek_bot_challenge_or_manual_verification(
            _ChallengePage(),
            "[SEEK p1/3]",
            headless=False,
            use_persistent_browser=True,
            assisted_verification_enabled=False,
            playwright_selector_timeout=5000,
        )
        is True
    )
    assert calls == [(
        'article[data-automation="normalJob"], article[data-automation="premiumJob"]',
        5000,
    )]


def test_seek_bot_challenge_timeout_raises_classified_bot_challenge(monkeypatch):
    class _TimeoutPage:
        def title(self):
            return "Just a moment"

        def inner_text(self, selector):
            assert selector == "body"
            return "confirm you are human"

        def wait_for_selector(self, selector, timeout):
            raise TimeoutError("still blocked")

    monkeypatch.setattr(
        "job_hunter_agent.scrapers.seek_runner._set_seek_status_progress", lambda message, **kwargs: None
    )

    try:
        _wait_for_seek_bot_challenge_or_manual_verification(
            _TimeoutPage(),
            "[SEEK p1/3]",
            headless=False,
            use_persistent_browser=True,
            assisted_verification_enabled=True,
            playwright_selector_timeout=5000,
        )
    except BotChallengeDetected as exc:
        assert exc.failure_class == SEEK_BOT_CHALLENGE
    else:  # pragma: no cover - defensive guard
        raise AssertionError("expected BotChallengeDetected")


def test_seek_human_verification_recovery_continues_without_bot_challenge(monkeypatch):
    class _RecoverPage:
        def wait_for_selector(self, selector, timeout):
            return None

    monkeypatch.setattr(
        "job_hunter_agent.scrapers.seek_runner._set_seek_status_progress", lambda message, **kwargs: None
    )

    assert (
        _handle_seek_list_page_failure(
            "[SEEK p1/3]",
            _RecoverPage(),
            TimeoutError("human verification"),
            {"title": "Help us keep SEEK secure", "selector_count": 0},
            page_status="challenge_page",
            failure_class=SEEK_HUMAN_VERIFICATION,
            headless=False,
            use_persistent_browser=True,
            assisted_verification_enabled=True,
            playwright_selector_timeout=5000,
        )
        is True
    )


def test_seek_human_verification_timeout_raises_classified_bot_challenge(monkeypatch):
    class _TimeoutPage:
        def wait_for_selector(self, selector, timeout):
            raise TimeoutError("still blocked")

    monkeypatch.setattr(
        "job_hunter_agent.scrapers.seek_runner._set_seek_status_progress", lambda message, **kwargs: None
    )

    try:
        _handle_seek_list_page_failure(
            "[SEEK p1/3]",
            _TimeoutPage(),
            TimeoutError("human verification"),
            {"title": "Help us keep SEEK secure", "selector_count": 0},
            page_status="challenge_page",
            failure_class=SEEK_HUMAN_VERIFICATION,
            headless=False,
            use_persistent_browser=True,
            assisted_verification_enabled=True,
            playwright_selector_timeout=5000,
        )
    except BotChallengeDetected as exc:
        assert exc.failure_class == SEEK_HUMAN_VERIFICATION
    else:  # pragma: no cover - defensive guard
        raise AssertionError("expected BotChallengeDetected")


def test_seek_list_page_diagnostics_classifies_sign_in_wall_beyond_log_snippet():
    page = _FakeListPage(
        title="SEEK jobs",
        url="https://www.seek.com.au/jobs?page=4",
        body_text=("public listing text " * 40) + " Sign in to see more jobs",
        card_count=0,
    )

    from job_hunter_agent.scrapers.seek_runner import _seek_list_page_diagnostics

    snapshot = _seek_list_page_diagnostics(page)

    assert snapshot["page_status"] == "sign_in_wall"
    assert snapshot["failure_class"] == SEEK_SIGN_IN_WALL
    assert "Sign in to see more jobs" not in snapshot["body_text"]
    assert len(snapshot["body_text"]) <= 500


def test_seek_list_page_diagnostics_logs_challenge_state(caplog):
    page = _FakeListPage(
        title="SEEK - Australia's no. 1 jobs, employment, career and recruitment site",
        url="https://www.seek.com.au/jobs?keywords=data+analyst&where=Sydney&daterange=3",
        body_text="Help us keep SEEK secure, confirm you are human.",
        card_count=0,
    )

    with caplog.at_level(logging.DEBUG, logger="job_hunter_agent.scrapers.seek_runner"):
        status = _log_seek_list_page_diagnostics(
            "[SEEK p1/3]",
            page,
            TimeoutError("wait timed out"),
            selector_timeout=8000,
        )

    assert status == "challenge_page"
    assert "card_selector_count=0" in caplog.text
    assert "body_status=challenge_page" in caplog.text
    assert "wait_for_selector failed with TimeoutError" in caplog.text
    assert "SEEK list page looks like a SEEK bot challenge page" in caplog.text


def test_seek_run_progress_keeps_elapsed_and_job_detail_out_of_text():
    assert _seek_run_progress(1, 3) == "SEEK page 1/3"


def test_seek_progress_producer_emits_page_and_normalized_detail(monkeypatch):
    from job_hunter_agent.scrapers import seek_runner

    captured: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        seek_runner,
        "set_run_progress_state",
        lambda text, **detail: captured.append((text, detail)),
    )

    _set_seek_run_progress(1, 3, detail="Senior Analyst at Acme")

    text, detail = captured[-1]
    assert text == "SEEK page 1/3"
    assert detail == {
        "stage": "source_collection",
        "source": "seek",
        "headline": "SEEK page 1 of 3",
        "detail": "Senior Analyst at Acme",
        "current": 1,
        "total": 3,
    }
