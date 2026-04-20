"""Tests for the deterministic title block phrase extractor.
﻿"""Tests for the deterministic title block phrase extractor.

Run with: python -m pytest tests/test_title_block_extractor.py -v
Or:        python tests/test_title_block_extractor.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from job_hunter_agent.filters import suggest_title_block_phrase


CASES = [
    # (title, expected_suggestion_or_None)
    # Post-separator discriminators
    ("Senior Delivery Manager - Guidewire", "guidewire"),
    ("Senior Analyst - Payments", "payments"),
    ("Operations Analyst - Banking", "banking"),
    ("Operations Analyst - Cyber, Cloud", "cyber"),
    ("Senior Analyst - ERP", "erp"),
    # Pre-separator token fallback (no separator, leftover non-generic token)
    ("Wealth Operations Manager", "wealth"),
    # Two-char tech acronym
    ("Senior Delivery Manager | AI & 365", "ai"),
    # No safe discriminator â€” all tokens are generic
    # No safe discriminator — all tokens are generic
    ("Senior Delivery Manager", None),
    ("Senior Analyst", None),
    ("Senior Delivery Digital Manager", None),
    # Protected positive-fit terms must never be suggested
    ("Multiple Roles - Government", None),
    ("Operations Analyst - Government Digital", None),
    # Numeric-only fragments must be skipped
    ("Operations Analyst - 365", None),
    # ERP preferred over generic post-separator when that's the only fragment
    ("Senior SAP Tester - ERP", "erp"),   # v1: post-separator takes priority
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
    print(f"\n{passed}/{passed+failed} passed")
    return failed == 0


if __name__ == "__main__":
    ok = run_tests()
    raise SystemExit(0 if ok else 1)


# pytest-compatible tests
def test_guidewire():
    assert suggest_title_block_phrase("Senior Delivery Manager - Guidewire") == "guidewire"

def test_payments():
    assert suggest_title_block_phrase("Senior Analyst - Payments") == "payments"

def test_banking():
    assert suggest_title_block_phrase("Operations Analyst - Banking") == "banking"

def test_cyber_first():
    assert suggest_title_block_phrase("Operations Analyst - Cyber, Cloud") == "cyber"

def test_erp():
    assert suggest_title_block_phrase("Senior Analyst - ERP") == "erp"

def test_wealth_fallback():
    assert suggest_title_block_phrase("Wealth Operations Manager") == "wealth"

def test_ai_acronym():
    assert suggest_title_block_phrase("Senior Delivery Manager | AI & 365") == "ai"

def test_generic_no_suggestion():
    assert not suggest_title_block_phrase("Senior Delivery Manager")

def test_senior_analyst_no_suggestion():
    assert not suggest_title_block_phrase("Senior Analyst")

def test_fully_generic_no_suggestion():
    assert not suggest_title_block_phrase("Senior Delivery Digital Manager")

def test_government_protected():
    assert not suggest_title_block_phrase("Multiple Roles - Government")

def test_numeric_fragment_skipped():
    assert not suggest_title_block_phrase("Operations Analyst - 365")

