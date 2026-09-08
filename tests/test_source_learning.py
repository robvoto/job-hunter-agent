"""Tests for source learning payload resolution."""

from job_hunter_agent import source_learning
from job_hunter_agent.record_schema import (
    RECORD_COMPANY_KEY,
    RECORD_FULL_DESCRIPTION_KEY,
    RECORD_JOB_KEY,
    RECORD_LLM_COST_USD_KEY,
    RECORD_LLM_INPUT_TOKENS_KEY,
    RECORD_LLM_OUTPUT_TOKENS_KEY,
    RECORD_REQUIREMENT_COVERAGE_BEHAVIOURAL_KEY,
    RECORD_REQUIREMENT_COVERAGE_HIDDEN_KEY,
    RECORD_REQUIREMENT_COVERAGE_KEY,
    RECORD_SOURCE_METADATA_KEY,
    RECORD_TITLE_KEY,
    SOURCE_POSTER_COMPANY_INDUSTRY_KEY,
)
from job_hunter_agent.signal_schema import TITLE_REASON_POTENTIAL_MATCH


def _build_record(
    title: str = "Title", company: str = "Company", description: str = "Description"
) -> dict:
    return {
        RECORD_JOB_KEY: "job-1",
        RECORD_TITLE_KEY: title,
        RECORD_COMPANY_KEY: company,
        RECORD_FULL_DESCRIPTION_KEY: description,
        "source": "seek",
    }


def test_resolve_llm_review_payload_fit_review_cache_hit_skips_llm(monkeypatch):
    record = _build_record()
    llm_fp = source_learning.build_llm_cache_key("Title\nSource-listed company/advertiser: Company\nDescription")
    llm_cache = {
        llm_fp: {
            "fit_review": {"decision": "KEEP", "grade": "SOLID"},
            "learning_candidates": [],
            "contextual_capability_matches": [],
            "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement",
                    "requirement_type": "capability",
                    "requirement_kind": "professional_capability",
                    "status": "supported",
                    "capability_name": "stakeholder engagement",
                    "matched_job_text": "stakeholder workshops",
                    "profile_support": ["stakeholder management"],
                    "matched_candidate_fact": "stakeholder engagement",
                },
                {
                    "requirement": "Process mapping",
                    "requirement_type": "capability",
                    "requirement_kind": "professional_capability",
                    "status": "partially_supported",
                    "capability_name": "process mapping",
                    "matched_job_text": "process mapping",
                    "profile_support": ["process mapping"],
                    "matched_candidate_fact": "process mapping",
                },
            ],
        }
    }

    monkeypatch.setattr(source_learning, "llm_is_enabled", lambda: True)
    monkeypatch.setattr(
        source_learning,
        "llm_should_consider_with_learning",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")),
    )
    monkeypatch.setattr(
        source_learning,
        "llm_should_consider_learning_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")),
    )

    payload = source_learning.resolve_llm_review_payload(record, llm_cache)

    assert payload["payload_source"] == "cache"
    assert payload["fit_review"] == {"decision": "KEEP", "grade": "SOLID"}


def test_resolve_llm_review_payload_learning_only_cache_hit_skips_llm(monkeypatch):
    record = _build_record()
    llm_fp = source_learning.build_llm_cache_key("Title\nDescription")
    llm_cache = {
        llm_fp: {
            "learning_candidates": [
                {
                    "signal": "python",
                    "suggested_category": "capability_concept",
                    "suggested_values": [],
                    "context_terms": [],
                    "confidence": "low",
                    "needs_review": True,
                    "original_texts": ["python"],
                }
            ],
        }
    }

    monkeypatch.setattr(source_learning, "llm_is_enabled", lambda: True)
    monkeypatch.setattr(
        source_learning,
        "llm_should_consider_with_learning",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")),
    )
    monkeypatch.setattr(
        source_learning,
        "llm_should_consider_learning_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")),
    )

    payload = source_learning.resolve_llm_review_payload(record, llm_cache, learning_only=True)

    assert payload["payload_source"] == "cache"
    assert payload["learning_candidates"][0]["signal"] == "python"


def test_resolve_llm_review_payload_cache_hit_uses_role_experience_for_years_requirements(monkeypatch):
    record = _build_record()
    llm_fp = source_learning.build_llm_cache_key("Title\nSource-listed company/advertiser: Company\nDescription")
    llm_cache = {
        llm_fp: {
            "fit_review": {"decision": "KEEP", "grade": "EXCELLENT"},
            "learning_candidates": [],
            "requirement_coverage": [
                {
                    "requirement": "5+ years experience as a Business Analyst",
                    "requirement_type": "capability",
                    "requirement_kind": "professional_capability",
                    "status": "supported",
                        "capability_name": "business analysis",
                        "matched_job_text": "Minimum 5+ years experience as a Business Analyst",
                        "profile_support": ["Ran BA activities across delivery teams."],
                        "experience_components": [
                            {"kind": "duration", "text": "5+ years"},
                            {"kind": "role_or_activity", "text": "Business Analyst"},
                        ],
                    "matched_candidate_fact": "business analysis",
                }
            ],
        }
    }

    monkeypatch.setattr(source_learning, "llm_is_enabled", lambda: True)
    monkeypatch.setattr(
        source_learning,
        "llm_should_consider_with_learning",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")),
    )
    monkeypatch.setattr(
        source_learning,
        "llm_should_consider_learning_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")),
    )
    monkeypatch.setattr(
        source_learning,
        "load_profile",
        lambda: {
            "role_experience": [
                {
                    "normalized_title": "business analyst",
                    "total_duration_months": 24,
                    "most_recent_end_year": 2024,
                }
            ]
        },
    )

    payload = source_learning.resolve_llm_review_payload(record, llm_cache)

    assert payload["payload_source"] == "cache"
    assert payload["requirement_coverage"][0]["status"] == "partially_supported"
    assert payload["requirement_coverage"][0]["required_experience_months"] == 60


def test_resolve_llm_review_payload_cache_miss_calls_llm(monkeypatch):
    record = _build_record()
    llm_fp = source_learning.build_llm_cache_key("Title\nSource-listed company/advertiser: Company\nDescription")
    llm_cache = {}
    called = {"count": 0, "input": ""}

    def fake_llm(review_input, *_args, **_kwargs):
        called["count"] += 1
        called["input"] = review_input
        return {
            "fit_review": {"decision": "KEEP", "grade": "SOLID"},
            "learning_candidates": [],
            "contextual_capability_matches": [],
            "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement",
                    "status": "supported",
                    "capability_name": "stakeholder engagement",
                    "matched_job_text": "stakeholder workshops",
                    "profile_support": ["stakeholder management"],
                    "matched_candidate_fact": "stakeholder engagement",
                },
                {
                    "requirement": "Process mapping",
                    "status": "partially_supported",
                    "capability_name": "process mapping",
                    "matched_job_text": "process mapping",
                    "profile_support": ["process mapping"],
                    "matched_candidate_fact": "process mapping",
                },
            ],
        }

    monkeypatch.setattr(source_learning, "llm_is_enabled", lambda: True)
    monkeypatch.setattr(source_learning, "llm_should_consider_with_learning", fake_llm)

    payload = source_learning.resolve_llm_review_payload(record, llm_cache)

    assert called["count"] == 1
    assert called["input"] == "Title\nSource-listed company/advertiser: Company\nDescription"
    assert payload["payload_source"] == "llm"
    assert payload["fit_review"] == {"decision": "KEEP", "grade": "SOLID"}
    # A cache MISS must be written back so a later equivalent job hits the cache.
    assert llm_fp in llm_cache
    assert llm_cache[llm_fp]["fit_review"] == {"decision": "KEEP", "grade": "SOLID"}


def test_resolve_llm_review_payload_includes_canonical_publisher_industry(monkeypatch):
    record = _build_record(
        title="2 Business Analysts",
        company="Peoplebank",
        description="We are expert recruiters. Our Federal Government Client is seeking a Business Analyst.",
    )
    record[RECORD_SOURCE_METADATA_KEY] = {
        "poster_company": "Peoplebank",
        SOURCE_POSTER_COMPANY_INDUSTRY_KEY: "Staffing and Recruiting",
        "hiring_company": "",
    }
    called = {"input": ""}

    def fake_llm(review_input, *_args, **_kwargs):
        called["input"] = review_input
        return {
            "fit_review": {"decision": "MAYBE", "grade": "WEAK"},
            "learning_candidates": [],
            "contextual_capability_matches": [],
            "requirement_coverage": [],
            "posting_channel": {
                "kind": "agency_or_recruiter",
                "confident": True,
                "evidence": "Our Federal Government Client is seeking...",
            },
        }

    monkeypatch.setattr(source_learning, "llm_is_enabled", lambda: True)
    monkeypatch.setattr(source_learning, "llm_should_consider_with_learning", fake_llm)

    source_learning.resolve_llm_review_payload(record, {})

    assert called["input"] == (
        "2 Business Analysts\n"
        "Source-listed company/advertiser: Peoplebank\n"
        "Source-listed poster industry: Staffing and Recruiting\n"
        "We are expert recruiters. Our Federal Government Client is seeking a Business Analyst."
    )


def test_resolve_llm_review_payload_second_equivalent_call_hits_cache(monkeypatch):
    """Regression: a MISS used to compute a fresh payload but never write it into
    llm_cache, so a second call for the same job description always missed again
    and re-called the LLM. The write-back must make the second call a cache HIT."""
    record = _build_record()
    llm_cache: dict = {}
    called = {"count": 0}

    def fake_llm(*_args, **_kwargs):
        called["count"] += 1
        return {
            "fit_review": {"decision": "KEEP", "grade": "SOLID"},
            "learning_candidates": [],
            "contextual_capability_matches": [],
            "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement",
                    "requirement_type": "capability",
                    "requirement_kind": "professional_capability",
                    "status": "supported",
                    "capability_name": "stakeholder engagement",
                    "matched_job_text": "stakeholder workshops",
                    "profile_support": ["stakeholder management"],
                    "matched_candidate_fact": "stakeholder engagement",
                },
            ],
        }

    monkeypatch.setattr(source_learning, "llm_is_enabled", lambda: True)
    monkeypatch.setattr(source_learning, "llm_should_consider_with_learning", fake_llm)

    first = source_learning.resolve_llm_review_payload(record, llm_cache)
    second = source_learning.resolve_llm_review_payload(record, llm_cache)

    assert called["count"] == 1
    assert first["payload_source"] == "llm"
    assert second["payload_source"] == "cache"
    assert second["fit_review"]["decision"] == "KEEP"


def test_resolve_llm_review_payload_partial_cache_calls_llm(monkeypatch):
    record = _build_record()
    llm_fp = source_learning.build_llm_cache_key("Title\nSource-listed company/advertiser: Company\nDescription")
    llm_cache = {
        llm_fp: {
            "learning_candidates": [
                {
                    "signal": "python",
                    "suggested_category": "capability_concept",
                    "suggested_values": [],
                    "context_terms": [],
                    "confidence": "low",
                    "needs_review": True,
                    "original_texts": ["python"],
                }
            ],
        }
    }
    called = {"count": 0}

    def fake_llm(*_args, **_kwargs):
        called["count"] += 1
        return {
            "fit_review": {"decision": "KEEP", "grade": "STRONG"},
            "learning_candidates": [],
            "contextual_capability_matches": [],
            "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement",
                    "status": "supported",
                    "capability_name": "stakeholder engagement",
                    "matched_job_text": "stakeholder workshops",
                    "profile_support": ["stakeholder management"],
                    "matched_candidate_fact": "stakeholder engagement",
                },
                {
                    "requirement": "Process mapping",
                    "status": "supported",
                    "capability_name": "process mapping",
                    "matched_job_text": "process mapping",
                    "profile_support": ["process mapping"],
                    "matched_candidate_fact": "process mapping",
                },
                {
                    "requirement": "UAT support",
                    "status": "partially_supported",
                    "capability_name": "acceptance testing",
                    "matched_job_text": "uat support",
                    "profile_support": ["user acceptance testing"],
                    "matched_candidate_fact": "acceptance testing",
                },
            ],
        }

    monkeypatch.setattr(source_learning, "llm_is_enabled", lambda: True)
    monkeypatch.setattr(source_learning, "llm_should_consider_with_learning", fake_llm)

    payload = source_learning.resolve_llm_review_payload(record, llm_cache)

    assert called["count"] == 1
    assert payload["payload_source"] == "llm"
    assert payload["fit_review"] == {"decision": "KEEP", "grade": "STRONG"}
    # The freshly computed fit_review is written back into the cache entry.
    assert llm_cache[llm_fp]["fit_review"] == {"decision": "KEEP", "grade": "STRONG"}


def test_resolve_llm_review_payload_counts_truncations(monkeypatch):
    record = _build_record(description="x" * 100)
    llm_cache = {}

    source_learning.reset_llm_truncation_count()
    monkeypatch.setattr(source_learning, "llm_is_enabled", lambda: True)
    monkeypatch.setattr(source_learning, "get_llm_max_chars", lambda: 10)
    monkeypatch.setattr(
        source_learning,
        "llm_should_consider_with_learning",
        lambda *_: {
            "fit_review": {"decision": "KEEP", "grade": "SOLID"},
            "learning_candidates": [],
        },
    )

    source_learning.resolve_llm_review_payload(record, llm_cache)

    assert source_learning.get_llm_truncation_count() == 1


def test_resolve_llm_review_payload_resolved_posting_channel_skips_dedicated_llm(monkeypatch):
    record = _build_record()
    llm_cache = {}

    monkeypatch.setattr(source_learning, "llm_is_enabled", lambda: True)
    monkeypatch.setattr(
        source_learning,
        "llm_should_consider_with_learning",
        lambda *_args, **_kwargs: {
            "fit_review": {"decision": "KEEP", "grade": "SOLID"},
            "learning_candidates": [],
            "posting_channel": {
                "kind": "direct_employer",
                "confident": True,
                "evidence": "The organisation describes its own team.",
            },
        },
    )
    monkeypatch.setattr(
        source_learning,
        "llm_classify_posting_channel",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("dedicated posting LLM should not be called")
        ),
    )

    payload = source_learning.resolve_llm_review_payload(record, llm_cache)

    assert payload["posting_channel"]["kind"] == "direct_employer"


def test_resolve_llm_review_payload_unknown_uses_dedicated_posting_llm(monkeypatch):
    record = _build_record()
    llm_cache = {}
    posting_input = "Title\nSource-listed company/advertiser: Company\nDescription"
    calls = {"count": 0, "input": ""}

    monkeypatch.setattr(source_learning, "llm_is_enabled", lambda: True)
    monkeypatch.setattr(
        source_learning,
        "llm_should_consider_with_learning",
        lambda *_args, **_kwargs: {
            "fit_review": {"decision": "KEEP", "grade": "SOLID"},
            "learning_candidates": [],
            "posting_channel": {"kind": "unknown", "confident": True, "evidence": ""},
            RECORD_LLM_INPUT_TOKENS_KEY: 100,
            RECORD_LLM_OUTPUT_TOKENS_KEY: 20,
            RECORD_LLM_COST_USD_KEY: 0.001,
        },
    )

    def fake_posting_llm(review_input, *_args, **_kwargs):
        calls["count"] += 1
        calls["input"] = review_input
        return {
            "kind": "direct_employer",
            "confident": True,
            "evidence": "The organisation describes its own workplace.",
            RECORD_LLM_INPUT_TOKENS_KEY: 30,
            RECORD_LLM_OUTPUT_TOKENS_KEY: 5,
            RECORD_LLM_COST_USD_KEY: 0.0002,
        }

    monkeypatch.setattr(source_learning, "llm_classify_posting_channel", fake_posting_llm)

    payload = source_learning.resolve_llm_review_payload(record, llm_cache)

    fit_fp = source_learning.build_llm_cache_key(posting_input)
    posting_fp = source_learning.build_posting_channel_cache_key(posting_input)
    assert calls == {"count": 1, "input": posting_input}
    assert payload["posting_channel"]["kind"] == "direct_employer"
    assert payload[RECORD_LLM_INPUT_TOKENS_KEY] == 130
    assert payload[RECORD_LLM_OUTPUT_TOKENS_KEY] == 25
    assert payload[RECORD_LLM_COST_USD_KEY] == 0.0012
    assert llm_cache[fit_fp]["posting_channel"]["kind"] == "direct_employer"
    assert llm_cache[fit_fp][RECORD_LLM_INPUT_TOKENS_KEY] == 130
    assert llm_cache[fit_fp][RECORD_LLM_OUTPUT_TOKENS_KEY] == 25
    assert llm_cache[fit_fp][RECORD_LLM_COST_USD_KEY] == 0.0012
    assert llm_cache[posting_fp]["kind"] == "direct_employer"
    assert RECORD_LLM_COST_USD_KEY not in llm_cache[posting_fp]


def test_resolve_llm_review_payload_cached_unknown_still_uses_dedicated_posting_llm(monkeypatch):
    record = _build_record()
    posting_input = "Title\nSource-listed company/advertiser: Company\nDescription"
    fit_fp = source_learning.build_llm_cache_key(posting_input)
    llm_cache = {
        fit_fp: {
            "fit_review": {"decision": "MAYBE", "grade": "WEAK"},
            "learning_candidates": [],
            "posting_channel": {"kind": "unknown", "confident": True, "evidence": ""},
            RECORD_LLM_INPUT_TOKENS_KEY: 999,
            RECORD_LLM_OUTPUT_TOKENS_KEY: 999,
            RECORD_LLM_COST_USD_KEY: 9.99,
        }
    }
    calls = {"count": 0}

    monkeypatch.setattr(source_learning, "llm_is_enabled", lambda: True)
    monkeypatch.setattr(
        source_learning,
        "llm_should_consider_with_learning",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("combined fit LLM should not be called")
        ),
    )

    def fake_posting_llm(*_args, **_kwargs):
        calls["count"] += 1
        return {
            "kind": "agency_or_recruiter",
            "confident": True,
            "evidence": "The poster represents a separate client.",
            RECORD_LLM_INPUT_TOKENS_KEY: 40,
            RECORD_LLM_OUTPUT_TOKENS_KEY: 6,
            RECORD_LLM_COST_USD_KEY: 0.0003,
        }

    monkeypatch.setattr(source_learning, "llm_classify_posting_channel", fake_posting_llm)

    payload = source_learning.resolve_llm_review_payload(record, llm_cache)

    assert calls["count"] == 1
    assert payload["payload_source"] == "cache"
    assert payload["posting_channel"]["kind"] == "agency_or_recruiter"
    assert payload[RECORD_LLM_INPUT_TOKENS_KEY] == 40
    assert payload[RECORD_LLM_OUTPUT_TOKENS_KEY] == 6
    assert payload[RECORD_LLM_COST_USD_KEY] == 0.0003
    assert llm_cache[fit_fp]["posting_channel"]["kind"] == "agency_or_recruiter"
    # The raw fit cache keeps historical provider metrics, but cache-hit normalization
    # never returns them as new spend. The fallback call is charged only in this payload.
    assert llm_cache[fit_fp][RECORD_LLM_INPUT_TOKENS_KEY] == 999
    assert llm_cache[fit_fp][RECORD_LLM_OUTPUT_TOKENS_KEY] == 999
    assert llm_cache[fit_fp][RECORD_LLM_COST_USD_KEY] == 9.99

    second = source_learning.resolve_llm_review_payload(record, llm_cache)
    assert second["posting_channel"]["kind"] == "agency_or_recruiter"
    assert RECORD_LLM_INPUT_TOKENS_KEY not in second
    assert RECORD_LLM_OUTPUT_TOKENS_KEY not in second
    assert RECORD_LLM_COST_USD_KEY not in second


def test_resolve_llm_review_payload_dedicated_unknown_remains_unknown(monkeypatch):
    record = _build_record(company="Private Advertiser", description="Six month contract. Apply now.")
    llm_cache = {}

    monkeypatch.setattr(source_learning, "llm_is_enabled", lambda: True)
    monkeypatch.setattr(
        source_learning,
        "llm_should_consider_with_learning",
        lambda *_args, **_kwargs: {
            "fit_review": {"decision": "MAYBE", "grade": "WEAK"},
            "learning_candidates": [],
            "posting_channel": {"kind": "unknown", "confident": True, "evidence": ""},
        },
    )
    monkeypatch.setattr(
        source_learning,
        "llm_classify_posting_channel",
        lambda *_args, **_kwargs: {"kind": "unknown", "confident": True, "evidence": ""},
    )

    payload = source_learning.resolve_llm_review_payload(record, llm_cache)

    assert payload["posting_channel"] == {"kind": "unknown", "confident": True, "evidence": ""}


def test_unresolved_posting_channel_reuses_dedicated_cache(monkeypatch):
    record = _build_record()
    payload = {
        "posting_channel": {"kind": "unknown", "confident": True, "evidence": ""},
    }
    llm_cache = {}
    calls = {"count": 0}

    def fake_posting_llm(*_args, **_kwargs):
        calls["count"] += 1
        return {
            "kind": "direct_employer",
            "confident": True,
            "evidence": "The organisation describes its own workplace.",
        }

    monkeypatch.setattr(source_learning, "llm_classify_posting_channel", fake_posting_llm)
    first = source_learning._resolve_unresolved_posting_channel(record, payload, llm_cache)

    monkeypatch.setattr(
        source_learning,
        "llm_classify_posting_channel",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("dedicated posting cache should avoid a second provider call")
        ),
    )
    second = source_learning._resolve_unresolved_posting_channel(record, payload, llm_cache)

    assert calls["count"] == 1
    assert first["posting_channel"]["kind"] == "direct_employer"
    assert second["posting_channel"]["kind"] == "direct_employer"


def test_unresolved_posting_channel_llm_failure_leaves_unknown(monkeypatch):
    record = _build_record()
    payload = {
        "posting_channel": {"kind": "unknown", "confident": False, "evidence": ""},
    }
    llm_cache = {}
    monkeypatch.setattr(source_learning, "llm_classify_posting_channel", lambda *_args, **_kwargs: None)

    resolved = source_learning._resolve_unresolved_posting_channel(record, payload, llm_cache)

    assert resolved == payload
    assert len(llm_cache) == 0


def test_resolve_llm_review_payload_explicit_recruiter_metadata_skips_dedicated_llm(monkeypatch):
    record = _build_record()
    record[RECORD_SOURCE_METADATA_KEY] = {
        "raw_source_fields": {"recruiter_badge": "Recruiter"},
    }

    monkeypatch.setattr(source_learning, "llm_is_enabled", lambda: True)
    monkeypatch.setattr(
        source_learning,
        "llm_should_consider_with_learning",
        lambda *_args, **_kwargs: {
            "fit_review": {"decision": "KEEP", "grade": "SOLID"},
            "learning_candidates": [],
            "posting_channel": {"kind": "unknown", "confident": True, "evidence": ""},
        },
    )
    monkeypatch.setattr(
        source_learning,
        "llm_classify_posting_channel",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("explicit recruiter metadata should resolve without another LLM call")
        ),
    )

    payload = source_learning.resolve_llm_review_payload(record, {})

    assert payload["posting_channel"]["kind"] == "unknown"


def test_behavioural_expectation_rows_never_mint_pending_capability_concept(monkeypatch):
    # JH-298: build_ad_learning_signals reads requirement_coverage (+ hidden),
    # never requirement_coverage_behavioural. Generic conduct wording — including
    # "willingness to embrace AI" — must produce no pending capability_concept.
    monkeypatch.setattr(
        source_learning,
        "signal_in_approved_knowledge",
        lambda category, signal, aliases=None: (False, ""),
    )
    behavioural_rows = [
        {
            "requirement": text,
            "importance": "preferred",
            "requirement_type": "capability",
            "requirement_kind": "behavioural_expectation",
            "behavioural_expectation": True,
            "status": "not_assessed",
            "capability_name": "",
            "canonical_requirement": "",
            "matched_job_text": text,
            "decomposition": {
                "operator": "single",
                "elements": [
                    {
                        "text": text,
                        "capability_judgement": "uncertain",
                        "canonical_concept": text,
                        "canonical_fact_resolved": False,
                        "status": "not_shown",
                    }
                ],
            },
        }
        for text in (
            "Works autonomously with minimal supervision",
            "A genuine willingness to embrace AI in day-to-day work",
        )
    ]
    record = {
        RECORD_TITLE_KEY: "Business Analyst",
        RECORD_COMPANY_KEY: "Acme",
        RECORD_REQUIREMENT_COVERAGE_KEY: [],
        RECORD_REQUIREMENT_COVERAGE_HIDDEN_KEY: [],
        RECORD_REQUIREMENT_COVERAGE_BEHAVIOURAL_KEY: behavioural_rows,
    }

    signals = source_learning.build_ad_learning_signals(
        record,
        "Works autonomously. A genuine willingness to embrace AI in day-to-day work.",
        profile={},
    )
    assert [s for s in signals if s["suggested_category"] == "capability_concept"] == []


def test_deterministic_review_does_not_reject_potential_title_before_llm():
    result = source_learning.deterministic_review_outcome(
        {"title_reason": TITLE_REASON_POTENTIAL_MATCH},
        {},
        ["Strong capability match: Delivery teams"],
        ["Missing explicit digital-health evidence"],
        ["Domain fit needs review", "Qualification fit needs review"],
    )

    assert result is None
