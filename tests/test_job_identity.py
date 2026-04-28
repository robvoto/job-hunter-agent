from job_hunter_agent.job_identity import (
    are_jobs_semantically_similar,
    deduplicate_across_sources,
    find_similar_job,
)


def test_are_jobs_semantically_similar_requires_same_company_and_high_title_overlap():
    assert are_jobs_semantically_similar(
        {"company": "Acme", "title": "Senior Business Analyst"},
        {"company": "Acme", "title": "Business Analyst Senior"},
    )
    assert not are_jobs_semantically_similar(
        {"company": "Acme", "title": "Senior Business Analyst"},
        {"company": "Beta", "title": "Senior Business Analyst"},
    )


def test_find_similar_job_returns_first_matching_applied_record():
    pool = [
        {"job_key": "seek:1", "company": "Acme", "title": "Senior Business Analyst", "source": "seek"},
        {"job_key": "linkedin:2", "company": "Acme", "title": "Project Manager", "source": "linkedin"},
    ]
    match = find_similar_job(
        {"company": "Acme", "title": "Business Analyst Senior"},
        pool,
    )
    assert match == pool[0]


def test_deduplicate_across_sources_prefers_seek_when_duplicate_appears_later():
    records = [
        {"job_key": "linkedin:1", "company": "Acme", "title": "Senior Business Analyst", "source": "linkedin"},
        {"job_key": "seek:2", "company": "Acme", "title": "Business Analyst Senior", "source": "seek"},
    ]
    deduped = deduplicate_across_sources(records)
    assert len(deduped) == 1
    assert deduped[0]["job_key"] == "seek:2"
