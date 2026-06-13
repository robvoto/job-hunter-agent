"""Tests for work-type inference from description text."""

from job_hunter_agent.job_types import infer_work_type_from_description, save_job_type
from job_hunter_agent.knowledge_store import get_knowledge

# Minimal rules fixture matching the shape in data/knowledge/job_type.json.
_RULES = [
    {
        "id": "full_time_to_permanent_or_contract",
        "enabled": True,
        "trigger_work_types": ["Full time"],
        "no_signal_infers": "Permanent",
        "contract_signal_infers": "Full Time Contract",
        "contract_signal_keywords": [
            "contract role",
            "contract position",
            "fixed term",
            "fixed-term",
            "ftc",
            "12 month contract",
            "12-month contract",
        ],
    }
]


# ── no-contract descriptions → Permanent ─────────────────────────────────────


def test_full_time_no_contract_signal_infers_permanent():
    desc = "This is a great business analyst opportunity. You will work with stakeholders."
    result = infer_work_type_from_description("Full time", desc, _rules=_RULES)
    assert result is not None
    assert result["inferred_type"] == "Permanent"
    assert result["rule_id"] == "full_time_to_permanent_or_contract"
    assert result["evidence"] == "no contract keywords in description"


def test_full_time_case_variant_no_contract_signal_infers_permanent():
    desc = "This is a great business analyst opportunity. You will work with stakeholders."
    result = infer_work_type_from_description("Full Time", desc, _rules=_RULES)
    assert result is not None
    assert result["inferred_type"] == "Permanent"


def test_full_time_empty_description_returns_none():
    result = infer_work_type_from_description("Full time", "", _rules=_RULES)
    assert result is None


# ── contract-signal descriptions → Full Time Contract ─────────────────────────


def test_full_time_contract_role_keyword_infers_full_time_contract():
    desc = "This is a contract role for an experienced BA to join our team."
    result = infer_work_type_from_description("Full time", desc, _rules=_RULES)
    assert result is not None
    assert result["inferred_type"] == "Full Time Contract"
    assert result["evidence"] == "contract role"


def test_full_time_fixed_term_infers_full_time_contract():
    desc = "We are seeking a Fixed Term appointment for 12 months to support delivery."
    result = infer_work_type_from_description("Full time", desc, _rules=_RULES)
    assert result is not None
    assert result["inferred_type"] == "Full Time Contract"
    assert result["evidence"] == "fixed term"


def test_full_time_ftc_keyword_infers_full_time_contract():
    desc = "This FTC opportunity is ideal for a senior analyst."
    result = infer_work_type_from_description("Full time", desc, _rules=_RULES)
    assert result is not None
    assert result["inferred_type"] == "Full Time Contract"
    assert result["evidence"] == "ftc"


def test_full_time_12_month_contract_infers_full_time_contract():
    desc = "12 month contract with a large government agency in Sydney."
    result = infer_work_type_from_description("Full time", desc, _rules=_RULES)
    assert result is not None
    assert result["inferred_type"] == "Full Time Contract"


def test_keyword_matching_is_case_insensitive():
    desc = "This is a FIXED-TERM engagement for 6 months."
    result = infer_work_type_from_description("Full time", desc, _rules=_RULES)
    assert result is not None
    assert result["inferred_type"] == "Full Time Contract"


# ── non-trigger work types → no inference ─────────────────────────────────────


def test_contract_work_type_not_in_trigger_list_returns_none():
    desc = "This is a great role with no contract mentions at all."
    result = infer_work_type_from_description("Contract", desc, _rules=_RULES)
    assert result is None


def test_part_time_not_in_trigger_list_returns_none():
    desc = "Permanent part-time opportunity in the CBD."
    result = infer_work_type_from_description("Part time", desc, _rules=_RULES)
    assert result is None


def test_empty_work_type_returns_none():
    desc = "Fantastic full time permanent opportunity."
    result = infer_work_type_from_description("", desc, _rules=_RULES)
    assert result is None


# ── disabled rule → no inference ──────────────────────────────────────────────


def test_disabled_rule_is_ignored():
    disabled_rules = [{**_RULES[0], "enabled": False}]
    desc = "Great permanent opportunity with no contract language."
    result = infer_work_type_from_description("Full time", desc, _rules=disabled_rules)
    assert result is None


def test_save_job_type_preserves_work_type_inference(isolated_db):
    before = get_knowledge("job_type", isolated_db)
    assert isinstance(before, dict)
    assert "work_type_inference" in before

    save_job_type({"fulltime": "Full time"})

    after = get_knowledge("job_type", isolated_db)
    assert after["work_type_inference"] == before["work_type_inference"]
