"""Shape-only normalization for profile item names.

Semantic interpretation belongs to the owning LLM/schema contract. This module
must not decide what a human-language phrase means via keywords, regexes, or
phrase lists.
"""

from __future__ import annotations

from typing import Any

from job_hunter_agent.text_processing import compact_whitespace


def normalize_profile_item_name(value: Any) -> str:
    """Normalize a profile item name without making semantic judgements."""
    if not isinstance(value, str):
        return ""
    return compact_whitespace(value)
