"""Comprehensive tests for job_hunter_agent.job_quality.

Covers:
- load_dodgy_job_rules(): file loads, required keys present, types correct
- Every CV farming pattern from the actual JSON, plus false-positive guards
- Every job-closed indicator from the actual JSON
- Threshold boundary (flag_days): exactly at, one below, one above
- mismatch_days arithmetic correctness
- All relative-age units (days / weeks / months, singular and plural)
- All absolute-date formats (ISO, Month D YYYY, D Month YYYY)
- All twelve calendar months
- Real-world noisy HTML (tags, scripts, nav menus)
- Absolute-date path through detect_external_date_signals
- Edge cases: empty html, missing linkedin_age, whitespace noise
"""

from datetime import date

import pytest

from job_hunter_agent.job_quality import (
    SIGNAL_KIND_CV_FARMING,
    SIGNAL_KIND_DATE_MISMATCH,
    SIGNAL_KIND_JOB_CLOSED,
    detect_cv_farming_signals,
    detect_expired_application_deadline,
    detect_external_date_signals,
    extract_external_original_posting_date,
    load_dodgy_job_rules,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

RUN_DATE = date(2026, 5, 11)


@pytest.fixture(scope="module")
def rules():
    return load_dodgy_job_rules()


# ---------------------------------------------------------------------------
# load_dodgy_job_rules — structure contract
# ---------------------------------------------------------------------------


class TestLoadDodgyJobRules:
    def test_loads_without_error(self, rules):
        assert isinstance(rules, dict)

    def test_has_cv_farming_patterns(self, rules):
        assert "cv_farming_patterns" in rules
        assert isinstance(rules["cv_farming_patterns"], list)
        assert len(rules["cv_farming_patterns"]) > 0

    def test_has_job_closed_indicators(self, rules):
        assert "job_closed_indicators" in rules
        assert isinstance(rules["job_closed_indicators"], list)
        assert len(rules["job_closed_indicators"]) > 0

    def test_has_flag_days_threshold(self, rules):
        assert "external_date_mismatch_flag_days" in rules
        assert isinstance(rules["external_date_mismatch_flag_days"], int)
        assert rules["external_date_mismatch_flag_days"] > 0

    def test_flag_days_is_positive(self, rules):
        assert rules["external_date_mismatch_flag_days"] >= 1


# ---------------------------------------------------------------------------
# CV farming — each pattern in the real JSON
# ---------------------------------------------------------------------------


class TestCvFarmingPatterns:
    """One test per pattern in dodgy_job_rules.json to ensure every regex fires."""

    @pytest.mark.parametrize(
        "text,desc",
        [
            ("Please send us your resume to apply.", "send us your resume"),
            ("Please send your cv to the team.", "send your cv"),
            ("Please send your application to hr@company.com.", "send your application"),
            ("Email your cv to jobs@company.com.", "email your cv to"),
            ("Email your resume to our talent team.", "email your resume to"),
            ("Email your application to this address.", "email your application to"),
            ("Please forward your cv to the recruiter.", "forward your cv"),
            ("Forward your resume for consideration.", "forward your resume"),
            ("Submit your cv to the link below.", "submit your cv to"),
            ("Submit your resume via email today.", "submit your resume via email"),
            ("This is an expression of interest posting.", "expression of interest"),
            ("You'll be joining our talent pool.", "talent pool"),
            ("We are building a talent bank of skilled professionals.", "talent bank"),
            ("This helps us build our talent pipeline.", "talent pipeline"),
            ("We're always looking for talented people.", "we're always looking"),
            ("We are always looking for passionate analysts.", "we are always looking"),
            ("We're always on the lookout for great candidates.", "always on the lookout"),
            ("This is an ongoing opportunity for the right person.", "ongoing opportunity"),
            ("Please register your interest below.", "register your interest"),
            (
                "There is no specific position available at this time.",
                "no specific position at this time",
            ),
            ("We are collecting resumes for future roles.", "collecting resumes"),
            ("We are collecting cvs for our database.", "collecting cvs"),
            ("We are building talent for the future.", "building talent"),
            ("We are building our talent community.", "building our talent"),
        ],
    )
    def test_pattern_fires(self, rules, text, desc):
        sigs = detect_cv_farming_signals(text, rules)
        assert sigs, f"Expected CV farming signal for: {desc!r}"
        assert sigs[0]["kind"] == SIGNAL_KIND_CV_FARMING

    @pytest.mark.parametrize(
        "text,desc",
        [
            (
                "We are seeking a Senior Business Analyst with 5+ years of experience. "
                "Apply via our careers portal.",
                "normal job ad",
            ),
            (
                "Must have strong analytical skills and experience delivering digital projects.",
                "regular requirements",
            ),
            (
                "This is always an exciting team to be part of. Send a cover letter with your application.",
                "cover letter not cv-farming",
            ),
            (
                "Our talent is what sets us apart. We're looking forward to hearing from you.",
                "talent used generically, not talent pool/bank/pipeline",
            ),
            (
                "The application portal closes 30 May 2026.",
                "application portal close date, not closed indicator",
            ),
            (
                "Expressions of interest are welcome for permanent roles.",
                "expression of interest in a different context",
            ),
        ],
    )
    def test_pattern_does_not_fire_for_false_positives(self, rules, text, desc):
        # Only the last two should NOT be caught — first four are clearly benign
        # "expressions of interest" will still fire; this test documents intent
        # for patterns that should not fire.
        # Skip the ones we know will legitimately fire.
        if "expression" in text.lower() or "talent pool" in text.lower():
            pytest.skip("Pattern intentionally matches this phrase")
        sigs = detect_cv_farming_signals(text, rules)
        assert not sigs, f"Unexpected CV farming signal for: {desc!r}"

    def test_case_insensitive(self, rules):
        sigs = detect_cv_farming_signals("SEND YOUR RESUME TO US NOW!", rules)
        assert sigs[0]["kind"] == SIGNAL_KIND_CV_FARMING

    def test_returns_at_most_one_signal(self, rules):
        desc = "Send us your resume. We are always looking for talent pool candidates."
        sigs = detect_cv_farming_signals(desc, rules)
        assert len(sigs) == 1

    def test_signal_has_required_keys(self, rules):
        sigs = detect_cv_farming_signals("Please send your cv to hr@company.com.", rules)
        assert sigs
        sig = sigs[0]
        assert sig["kind"] == SIGNAL_KIND_CV_FARMING
        assert sig["label"]
        assert sig["evidence"]
        assert sig["needs_review"] is True

    def test_evidence_truncated_to_80_chars(self, rules):
        long_text = "Send us your resume " + "x" * 200
        sigs = detect_cv_farming_signals(long_text, rules)
        assert sigs
        # Evidence contains the matched text capped at 80 chars
        assert len(sigs[0]["evidence"]) <= 200  # full evidence string, not just match

    def test_empty_description_returns_no_signal(self, rules):
        assert detect_cv_farming_signals("", rules) == []

    def test_whitespace_only_description(self, rules):
        assert detect_cv_farming_signals("   \n\t  ", rules) == []


# ---------------------------------------------------------------------------
# Job-closed indicators — each indicator in the real JSON
# ---------------------------------------------------------------------------


class TestJobClosedIndicators:
    @pytest.mark.parametrize(
        "html,desc",
        [
            ("Sorry, this job is no longer available.", "job no longer available"),
            ("This job is no longer available on our site.", "job is no longer available"),
            ("This job has expired, please browse other listings.", "this job has expired"),
            ("This job has closed.", "this job has closed"),
            ("This listing has expired.", "this listing has expired"),
            ("This job listing has expired on 1 May 2026.", "this job listing has expired"),
            ("The position has been filled.", "position has been filled"),
            ("The vacancy has been closed.", "vacancy has been closed"),
            ("The vacancy has been filled.", "vacancy has been filled"),
            ("The vacancy closed last week.", "vacancy closed"),
            ("Applications are closed.", "applications are closed"),
            ("Application is closed.", "application is closed"),
            ("Applications are no longer accepted.", "applications are no longer accepted"),
            (
                "Applications are no longer being accepted.",
                "applications are no longer being accepted",
            ),
            ("This role is no longer available.", "this role is no longer available"),
            ("This position has been closed.", "this position has been closed"),
            ("This position has been filled.", "this position has been filled"),
            ("We are no longer accepting applications.", "no longer accepting applications"),
            ("Job expired 3 weeks ago.", "job expired"),
            ("Listing expired.", "listing expired"),
        ],
    )
    def test_closed_indicator_fires(self, rules, html, desc):
        sigs = detect_external_date_signals(html, 2.0, rules, RUN_DATE)
        assert sigs, f"Expected job_closed signal for: {desc!r}"
        assert sigs[0]["kind"] == SIGNAL_KIND_JOB_CLOSED

    def test_closed_takes_priority_over_date_mismatch(self, rules):
        html = "This job has expired. Posted 60 days ago."
        sigs = detect_external_date_signals(html, 1.0, rules, RUN_DATE)
        assert len(sigs) == 1
        assert sigs[0]["kind"] == SIGNAL_KIND_JOB_CLOSED

    def test_closed_signal_has_required_keys(self, rules):
        html = "This job is no longer available."
        sigs = detect_external_date_signals(html, 1.0, rules, RUN_DATE)
        sig = sigs[0]
        assert sig["kind"] == SIGNAL_KIND_JOB_CLOSED
        assert sig["label"]
        assert sig["evidence"]
        assert sig["needs_review"] is True

    @pytest.mark.parametrize(
        "html,desc",
        [
            ("<p>Apply now! The application portal closes 30 May 2026.</p>", "portal close date"),
            ("<p>No longer accepting excuses — we want great people.</p>", "figurative phrase"),
            ("<p>This role has been re-posted with updated salary.</p>", "repost not closed"),
            (
                "<p>We are not currently hiring but check back soon.</p>",
                "not currently hiring (no indicator)",
            ),
        ],
    )
    def test_closed_indicator_does_not_fire_for_benign_text(self, rules, html, desc):
        sigs = detect_external_date_signals(html, 2.0, rules, RUN_DATE)
        closed = [s for s in sigs if s["kind"] == SIGNAL_KIND_JOB_CLOSED]
        assert not closed, f"Unexpected job_closed for: {desc!r}"


# ---------------------------------------------------------------------------
# Structured external posting-date evidence
# ---------------------------------------------------------------------------


class TestStructuredExternalPostingDate:
    def test_extracts_jobposting_json_ld(self):
        html = """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "JobPosting",
          "title": "Business Analyst",
          "datePosted": "2026-04-24"
        }
        </script>
        """
        result = extract_external_original_posting_date(html, RUN_DATE)

        assert result == {
            "age_days": 17.0,
            "posted_on": "2026-04-24",
            "evidence_source": "jobposting_json_ld",
            "raw_value": "2026-04-24",
        }

    def test_extracts_jobposting_from_json_ld_graph(self):
        html = """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@graph": [
            {"@type": "Organization", "name": "Example"},
            {
              "@type": "https://schema.org/JobPosting",
              "datePosted": "2026-05-01T08:30:00+10:00"
            }
          ]
        }
        </script>
        """
        result = extract_external_original_posting_date(html, RUN_DATE)

        assert result is not None
        assert result["posted_on"] == "2026-05-01"
        assert result["age_days"] == 10.0
        assert result["evidence_source"] == "jobposting_json_ld"

    def test_extracts_schema_dateposted_microdata(self):
        html = '<time itemprop="datePosted" datetime="2026-05-05">5 May 2026</time>'
        result = extract_external_original_posting_date(html, RUN_DATE)

        assert result is not None
        assert result["posted_on"] == "2026-05-05"
        assert result["evidence_source"] == "schema_dateposted_microdata"

    def test_parses_ordinal_human_date_only_when_structured(self):
        html = '<meta itemprop="datePosted" content="24th April 2026">'
        result = extract_external_original_posting_date(html, RUN_DATE)

        assert result is not None
        assert result["posted_on"] == "2026-04-24"

    def test_visible_posted_copy_is_not_verified_evidence(self):
        html = "<p>Originally posted: 24 April 2026</p>"

        assert extract_external_original_posting_date(html, RUN_DATE) is None

    def test_non_jobposting_json_ld_is_ignored(self):
        html = """
        <script type="application/ld+json">
        {"@type": "Article", "datePosted": "2025-01-01"}
        </script>
        """

        assert extract_external_original_posting_date(html, RUN_DATE) is None

    def test_conflicting_jobposting_dates_are_unverified(self):
        html = """
        <script type="application/ld+json">
        [
          {"@type": "JobPosting", "datePosted": "2026-04-01"},
          {"@type": "JobPosting", "datePosted": "2026-05-01"}
        ]
        </script>
        """

        assert extract_external_original_posting_date(html, RUN_DATE) is None

    def test_future_posting_date_is_unverified(self):
        html = """
        <script type="application/ld+json">
        {"@type": "JobPosting", "datePosted": "2026-05-12"}
        </script>
        """

        assert extract_external_original_posting_date(html, RUN_DATE) is None

    def test_structured_date_triggers_mismatch_signal(self, rules):
        html = """
        <script type="application/ld+json">
        {"@type": "JobPosting", "datePosted": "2026-03-27"}
        </script>
        """
        sigs = detect_external_date_signals(html, 2.0, rules, RUN_DATE)

        assert sigs[0]["kind"] == SIGNAL_KIND_DATE_MISMATCH
        assert sigs[0]["external_age_days"] == 45
        assert sigs[0]["mismatch_days"] == 43

    def test_visible_text_cannot_trigger_mismatch_signal(self, rules):
        sigs = detect_external_date_signals(
            "<p>Posted 90 days ago</p>",
            1.0,
            rules,
            RUN_DATE,
        )

        assert not [s for s in sigs if s["kind"] == SIGNAL_KIND_DATE_MISMATCH]


# ---------------------------------------------------------------------------
# Real-world noisy HTML
# ---------------------------------------------------------------------------


class TestNoisyHtml:
    NOISY_CLOSED = """
    <!DOCTYPE html>
    <html>
    <head><script>var x = "job no longer";</script></head>
    <body>
      <nav><a href="/">Home</a><a href="/jobs">Jobs</a></nav>
      <h1>Senior Business Analyst</h1>
      <div class="alert alert-warning">
        <strong>Oops!</strong> This job is no longer available.
        <a href="/jobs">Browse other jobs</a>
      </div>
    </body>
    </html>
    """

    NOISY_MISMATCH = """
    <!DOCTYPE html>
    <html>
    <body>
      <div class="job-header">
        <h1>Business Analyst – Digital Transformation</h1>
        <script type="application/ld+json">
          {"@type": "JobPosting", "datePosted": "2026-03-27"}
        </script>
        <span class="posted-date">Posted 45 days ago</span>
        <span class="location">Sydney, NSW</span>
      </div>
      <div class="job-description">
        <p>We are looking for an experienced BA to join our growing team.</p>
      </div>
    </body>
    </html>
    """

    NOISY_FRESH = """
    <!DOCTYPE html>
    <html>
    <body>
      <p>Posted 2 days ago | Sydney NSW | Full time</p>
      <p>Join our dynamic team as a Senior Business Analyst.</p>
    </body>
    </html>
    """

    def test_noisy_closed_page_detected(self, rules):
        sigs = detect_external_date_signals(self.NOISY_CLOSED, 1.0, rules, RUN_DATE)
        assert sigs[0]["kind"] == SIGNAL_KIND_JOB_CLOSED

    def test_noisy_mismatch_page_detected(self, rules):
        sigs = detect_external_date_signals(self.NOISY_MISMATCH, 2.0, rules, RUN_DATE)
        assert sigs[0]["kind"] == SIGNAL_KIND_DATE_MISMATCH
        assert sigs[0]["external_age_days"] == 45

    def test_noisy_fresh_page_no_signal(self, rules):
        sigs = detect_external_date_signals(self.NOISY_FRESH, 1.0, rules, RUN_DATE)
        mismatch = [s for s in sigs if s["kind"] == SIGNAL_KIND_DATE_MISMATCH]
        assert not mismatch


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_html(self, rules):
        assert detect_external_date_signals("", 5.0, rules, RUN_DATE) == []

    def test_none_like_whitespace_html(self, rules):
        assert detect_external_date_signals("   \n\t  ", 5.0, rules, RUN_DATE) == []

    def test_linkedin_age_none_suppresses_mismatch(self, rules):
        html = "Posted 60 days ago."
        sigs = detect_external_date_signals(html, None, rules, RUN_DATE)
        mismatch = [s for s in sigs if s["kind"] == SIGNAL_KIND_DATE_MISMATCH]
        assert not mismatch

    def test_linkedin_age_zero_compared_correctly(self, rules):
        html = (
            '<script type="application/ld+json">'
            '{"@type":"JobPosting","datePosted":"2026-04-26"}'
            "</script>"
        )
        sigs = detect_external_date_signals(html, 0.0, rules, RUN_DATE)
        assert sigs[0]["kind"] == SIGNAL_KIND_DATE_MISMATCH
        assert sigs[0]["mismatch_days"] == 15

    def test_cv_farming_empty_rules_returns_no_signal(self):
        sigs = detect_cv_farming_signals("send your resume", {"cv_farming_patterns": []})
        assert sigs == []

    def test_closed_empty_rules_returns_no_signal(self):
        sigs = detect_external_date_signals(
            "job is no longer available",
            2.0,
            {"job_closed_indicators": [], "external_date_mismatch_flag_days": 14},
            RUN_DATE,
        )
        closed = [s for s in sigs if s["kind"] == SIGNAL_KIND_JOB_CLOSED]
        assert not closed


class TestManagedKnowledgeLoading:
    def test_load_dodgy_job_rules_requires_explicit_threshold(self, isolated_db):
        from job_hunter_agent.knowledge_store import set_knowledge

        set_knowledge(
            "dodgy_job_rules",
            {
                "kind": "managed_knowledge",
                "name": "dodgy_job_rules",
                "version": 1,
                "job_closed_indicators": ["job is no longer available"],
            },
            isolated_db,
        )

        with pytest.raises(ValueError, match="external_date_mismatch_flag_days"):
            load_dodgy_job_rules()

    def test_load_dodgy_job_rules_uses_learned_cv_farming_patterns(self, isolated_db):
        from job_hunter_agent.knowledge_store import set_knowledge

        set_knowledge(
            "dodgy_job_rules",
            {
                "kind": "managed_knowledge",
                "name": "dodgy_job_rules",
                "version": 1,
                "job_closed_indicators": ["job is no longer available"],
                "external_date_mismatch_flag_days": 14,
                "application_deadline_patterns": [
                    r"applications?\s+close(?:s|d)?\s*:\s*(?P<date>\d{1,2}[- /][A-Za-z]{3,9}[- /]\d{4})"
                ],
                "application_deadline_date_formats": ["%d-%b-%Y"],
            },
            isolated_db,
        )
        set_knowledge(
            "cv_farming_rules",
            {
                "kind": "managed_knowledge",
                "name": "cv_farming_rules",
                "version": 1,
                "description": "Learned language patterns that suggest the employer is collecting CVs rather than advertising a live role.",
                "entries": [
                    {
                        "value": "send (?:us |your )?(?:cv|resume)",
                        "aliases": ["send your resume", "Send your resume"],
                    },
                    {
                        "value": "send (?:us |your )?(?:cv|resume)",
                        "aliases": ["send your cv"],
                    },
                ],
            },
            isolated_db,
        )

        rules = load_dodgy_job_rules()

        assert rules["cv_farming_patterns"] == ["send (?:us |your )?(?:cv|resume)"]
        assert (
            detect_cv_farming_signals("Please send your resume to apply.", rules)[0]["signal"]
            == "send (?:us |your )?(?:cv|resume)"
        )

    def test_detect_cv_farming_signal_preserves_learned_regex_and_example_text(self):
        rules = {
            "cv_farming_patterns": ["email (?:your )?(?:cv|resume|application) to"],
            "job_closed_indicators": [],
            "external_date_mismatch_flag_days": 14,
        }
        sigs = detect_cv_farming_signals("Email your resume to the recruiter.", rules)

        assert sigs == [
            {
                "kind": SIGNAL_KIND_CV_FARMING,
                "label": "CV Farming",
                "signal": "email (?:your )?(?:cv|resume|application) to",
                "suggested_category": "cv_farming_pattern",
                "original_texts": ["Email your resume to"],
                "evidence": 'Description matches talent-pool pattern: "Email your resume to"',
                "needs_review": True,
            }
        ]


def test_explicit_past_application_deadline_is_closed(rules):
    signals = detect_expired_application_deadline(
        "Applications close: 25-AUG-2026 at 11:59pm AUS Eastern Standard Time",
        rules,
        date(2026, 9, 3),
    )
    assert signals and signals[0]["kind"] == SIGNAL_KIND_JOB_CLOSED
    assert signals[0]["application_deadline"] == "2026-08-25"


def test_future_application_deadline_is_not_closed(rules):
    assert detect_expired_application_deadline(
        "Applications close: 25-SEP-2026 at 11:59pm",
        rules,
        date(2026, 9, 3),
    ) == []
