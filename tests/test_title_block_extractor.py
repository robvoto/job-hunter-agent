"""Tests for the deterministic title block phrase extractor."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from job_hunter_agent.filters import suggest_title_block_phrase

CASES = [
    ("Senior Delivery Manager - Guidewire", "guidewire"),
    ("Senior Analyst - Payments", "payments"),
    ("Operations Analyst - Banking", "banking"),
    ("Senior Advisor - Procurement", "procurement"),
    ("Program Coordinator - Healthcare", "healthcare"),
    ("Operations Analyst - Cyber, Cloud", "cyber"),
    ("Senior Analyst - ERP", "erp"),
    ("Wealth Operations Manager", None),
    ("Senior Delivery Manager | AI & 365", "ai"),
    ("Senior Delivery Manager", None),
    ("Senior Analyst", None),
    ("Senior Delivery Digital Manager", None),
    ("Senior Officer", None),
    ("Multiple Roles - Government", "government"),
    ("Operations Analyst - Government Digital", "government digital"),
    ("Operations Analyst - 365", None),
    ("Senior SAP Tester - ERP", "erp"),
]


def run_tests():
    passed = 0
    failed = 0
    for title, expected in CASES:
        result = suggest_title_block_phrase(title)
        ok = (result == expected) or (expected is None and not result)
        status = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
            print(f"  {status}  {title!r}")
            print(f"         expected={expected!r}  got={result!r}")
        else:
            passed += 1
            print(f"  {status}  {title!r}  -> {result!r}")
    print(f"\n{passed}/{passed + failed} passed")
    return failed == 0


if __name__ == "__main__":
    ok = run_tests()
    raise SystemExit(0 if ok else 1)


def test_guidewire():
    assert suggest_title_block_phrase("Senior Delivery Manager - Guidewire") == "guidewire"


def test_payments():
    assert suggest_title_block_phrase("Senior Analyst - Payments") == "payments"


def test_banking():
    assert suggest_title_block_phrase("Operations Analyst - Banking") == "banking"


def test_procurement():
    assert suggest_title_block_phrase("Senior Advisor - Procurement") == "procurement"


def test_healthcare():
    assert suggest_title_block_phrase("Program Coordinator - Healthcare") == "healthcare"


def test_cyber_first():
    assert suggest_title_block_phrase("Operations Analyst - Cyber, Cloud") == "cyber"


def test_erp():
    assert suggest_title_block_phrase("Senior Analyst - ERP") == "erp"


def test_wealth_fallback():
    assert not suggest_title_block_phrase("Wealth Operations Manager")


def test_ai_acronym():
    assert suggest_title_block_phrase("Senior Delivery Manager | AI & 365") == "ai"


def test_generic_no_suggestion():
    assert not suggest_title_block_phrase("Senior Delivery Manager")


def test_senior_analyst_no_suggestion():
    assert not suggest_title_block_phrase("Senior Analyst")


def test_fully_generic_no_suggestion():
    assert not suggest_title_block_phrase("Senior Delivery Digital Manager")


def test_generic_officer_no_suggestion():
    assert not suggest_title_block_phrase("Senior Officer")


def test_government_protected():
    assert suggest_title_block_phrase("Multiple Roles - Government") == "government"


def test_government_digital_segment():
    assert (
        suggest_title_block_phrase("Operations Analyst - Government Digital")
        == "government digital"
    )


def test_numeric_fragment_skipped():
    assert not suggest_title_block_phrase("Operations Analyst - 365")
