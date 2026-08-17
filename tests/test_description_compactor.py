"""Tests for data-driven description compaction."""

from pathlib import Path

from job_hunter_agent.description_compactor import (
    compact_description,
    load_description_compaction_rules,
)

MIN = 400

SEEK_DESCRIPTION = """
We are looking for a Senior Business Analyst to join our digital transformation team.

About The Role
You will work with senior stakeholders to map current-state processes and define future-state
requirements. The role is based in Sydney CBD with hybrid work (3 days in office).
Salary: $140,000 + super. Permanent role.

Key Responsibilities
• Lead requirements workshops with C-suite and operational stakeholders
• Produce BRDs, user stories, and acceptance criteria
• Map as-is and to-be processes using BPMN
• Support UAT planning and execution

Requirements
• 5+ years experience as a Business Analyst in financial services
• Strong facilitation and stakeholder engagement skills
• Proficiency in JIRA, Confluence, and Visio
• Experience with Agile delivery frameworks

What We Offer
• Competitive salary and bonus structure
• 5 weeks annual leave
• Flexible and hybrid working arrangements

About Us
Acme Financial Services is a leading provider of banking and insurance solutions.
We have over 2,000 employees across Australia. We are proud of our inclusive culture.

How To Apply
Click Apply Now to submit your application. We will be in touch with shortlisted candidates.
Please include your resume and a brief cover letter.

Equal Opportunity Employer
Acme Financial Services is an equal opportunity employer and values diversity.
We do not discriminate on the basis of race, religion, gender, or sexual orientation.
""".strip()

LINKEDIN_DESCRIPTION = """
Contract Senior Software Engineer – Backend (6 month contract, $1,100/day)

About the role
We need an experienced backend engineer to scale our payments platform.
Remote work available; preference for Sydney or Melbourne based candidates.

What you'll do
• Design and implement high-throughput APIs in Python
• Collaborate with the platform team on architecture decisions
• Write unit and integration tests; review PRs

Skills & experience required
• 5+ years Python backend development
• PostgreSQL, Redis, and message queuing (Kafka or RabbitMQ)
• CI/CD experience (GitHub Actions or similar)

About Our Company
We are a fast-growing fintech headquartered in Sydney. Our mission is to simplify payments.
We were founded in 2017 and have raised $80M in Series C funding.

Privacy Notice
By submitting your application, you agree to our privacy policy available at example.com/privacy.
Your personal information will be used for recruitment purposes only.

To Apply
Submit your resume via LinkedIn Easy Apply or email careers@example.com.
Only shortlisted candidates will be contacted.
""".strip()


class TestDataDrivenRules:
    def test_rules_are_loaded_from_data_file(self):
        rules = load_description_compaction_rules()
        assert rules["name"] == "description_compaction_rules"
        assert "removable_header_patterns" in rules
        assert "protected_signal_patterns" in rules

    def test_compactor_does_not_embed_source_rule_lists(self):
        source = Path("job_hunter_agent/description_compactor.py").read_text(encoding="utf-8")
        forbidden = [
            "_STRIP_HEADER_RE",
            "_STRIP_CONTENT_RES",
            "_SIGNAL_RES",
            "how\\s+to\\s+apply",
            "only\\s+(?:shortlisted|successful)",
            "equal\\s+(?:opportunity",
        ]
        for token in forbidden:
            assert token not in source


class TestSeekDescription:
    def test_requirements_preserved(self):
        text, _ = compact_description(SEEK_DESCRIPTION, MIN)
        assert "5+ years experience as a Business Analyst" in text
        assert "JIRA, Confluence" in text

    def test_role_description_preserved(self):
        text, _ = compact_description(SEEK_DESCRIPTION, MIN)
        assert "map current-state processes" in text
        assert "Key Responsibilities" in text

    def test_salary_work_mode_and_work_type_preserved(self):
        text, _ = compact_description(SEEK_DESCRIPTION, MIN)
        assert "$140,000" in text
        assert "hybrid" in text.lower()
        assert "permanent" in text.lower()

    def test_protected_sections_preserved(self):
        text, _ = compact_description(SEEK_DESCRIPTION, MIN)
        assert "What We Offer" in text
        assert "Acme Financial Services is a leading provider" in text

    def test_boilerplate_removed_and_metadata_recorded(self):
        text, meta = compact_description(SEEK_DESCRIPTION, MIN)
        assert "Click Apply Now" not in text
        assert "does not discriminate" not in text
        assert meta["applied"] is True
        assert meta["compaction_status"] == "applied"
        assert meta["skip_reason"] is None
        assert meta["compacted_char_count"] < meta["original_char_count"]
        assert any("how to apply" in label.lower() for label in meta["removed_section_labels"])


class TestLinkedInDescription:
    def test_requirements_preserved(self):
        text, _ = compact_description(LINKEDIN_DESCRIPTION, MIN)
        assert "5+ years Python" in text
        assert "PostgreSQL" in text

    def test_contract_rate_work_mode_and_location_preserved(self):
        text, _ = compact_description(LINKEDIN_DESCRIPTION, MIN)
        assert "6 month contract" in text
        assert "$1,100/day" in text
        assert "remote" in text.lower()
        assert "Sydney" in text

    def test_about_company_preserved(self):
        text, _ = compact_description(LINKEDIN_DESCRIPTION, MIN)
        assert "fast-growing fintech" in text

    def test_boilerplate_removed_and_metadata_recorded(self):
        text, meta = compact_description(LINKEDIN_DESCRIPTION, MIN)
        assert "By submitting your application" not in text
        assert "Submit your resume via LinkedIn Easy Apply" not in text
        assert "Only shortlisted candidates" not in text
        assert meta["applied"] is True
        assert meta["compaction_status"] == "applied"
        assert meta["skip_reason"] is None


class TestSkippedCompaction:
    def test_short_input_returns_unchanged(self):
        short = "Senior BA role in Sydney."
        text, meta = compact_description(short, MIN)
        assert text == short
        assert meta["applied"] is False
        assert meta["compaction_status"] == "not_needed"
        assert meta["skip_reason"] == "input_too_short"

    def test_no_boilerplate_returns_unchanged(self):
        clean = (
            "About The Role\nLead stakeholder workshops.\n\n"
            "Requirements\n5+ years BA experience.\n\n"
            "What We Offer\n$130k + super, hybrid work."
        ) * 5
        text, meta = compact_description(clean, MIN)
        assert text == clean
        assert meta["applied"] is False
        assert meta["compaction_status"] == "not_needed"
        assert meta["removed_section_labels"] == []

    def test_protected_signal_in_removed_content_skips_compaction(self):
        desc = (
            "About The Role\nGreat opportunity in Sydney.\n\n"
            "Requirements\n" + ("5+ years experience in Python. " * 20) + "\n\n"
            "How To Apply\nSalary is $120,000 per year. Click apply now to submit."
        )
        text, meta = compact_description(desc, MIN)
        assert text == desc
        assert meta["applied"] is False
        assert meta["compaction_status"] == "skipped_too_risky"
        assert meta["skip_reason"] == "protected_signal_in_removed_content"

    def test_too_short_after_strip_skips_compaction(self):
        boilerplate = "\n\nHow To Apply\n" + "Click apply now. " * 50
        real_content = "About The Role\nGreat role."
        desc = real_content + boilerplate
        text, meta = compact_description(desc, min_compacted_chars=300)
        assert text == desc
        assert meta["applied"] is False
        assert meta["compaction_status"] == "skipped_too_risky"
        assert meta["skip_reason"] is not None

    def test_metadata_shape_always_present(self):
        _, meta = compact_description("", MIN)
        assert "applied" in meta
        assert "compaction_status" in meta
        assert "original_char_count" in meta
        assert "compacted_char_count" in meta
        assert "removed_section_labels" in meta
        assert "skip_reason" in meta
