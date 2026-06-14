"""Conservative data-driven compaction of job description text before LLM input.

This module is the compaction engine only. Removable section rules, removable
content patterns, protected signal patterns, and safety thresholds live in
``data/knowledge/description_compaction_rules.json``.

No business scoring logic belongs here.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_RULES_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "knowledge" / "description_compaction_rules.json"
)


def _repo_rule_path() -> Path:
    return _RULES_PATH


@lru_cache(maxsize=1)
def load_description_compaction_rules() -> dict[str, Any]:
    """Load data-driven description compaction rules."""
    with _repo_rule_path().open("r", encoding="utf-8") as fh:
        rules = json.load(fh)

    if not isinstance(rules, dict):
        raise ValueError("description_compaction_rules.json must contain an object")

    for key in (
        "removable_header_patterns",
        "removable_content_patterns",
        "protected_signal_patterns",
        "safety",
    ):
        if key not in rules:
            raise ValueError(f"description_compaction_rules.json missing required key: {key}")

    return rules


def _compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        if not isinstance(pattern, str) or not pattern.strip():
            continue
        compiled.append(re.compile(pattern, re.IGNORECASE))
    return compiled


@lru_cache(maxsize=1)
def _compiled_patterns() -> dict[str, Any]:
    """Compile regex patterns from the rules JSON. Cached — patterns are stable at runtime."""
    rules = load_description_compaction_rules()
    return {
        "header_res": _compile_patterns(rules.get("removable_header_patterns") or []),
        "content_res": _compile_patterns(rules.get("removable_content_patterns") or []),
        "signal_res": _compile_patterns(rules.get("protected_signal_patterns") or []),
    }


def _strip_markdown_bold(line: str) -> str:
    """Remove lightweight Markdown emphasis markers from a candidate header line."""
    return re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", line).strip()


def _paragraph_is_strippable(para: str) -> tuple[bool, str]:
    """Return whether a paragraph matches configured removable boilerplate."""
    lines = para.strip().splitlines()
    if not lines:
        return False, ""

    compiled = _compiled_patterns()
    header_raw = lines[0].strip()
    header = _strip_markdown_bold(header_raw).rstrip(":").strip()

    for header_re in compiled["header_res"]:
        if header_re.fullmatch(header):
            return True, header_raw

    for content_re in compiled["content_res"]:
        if content_re.search(para):
            return True, content_re.pattern[:80]

    return False, ""


def _has_protected_signal(text: str) -> bool:
    return any(sig_re.search(text) for sig_re in _compiled_patterns()["signal_res"])


def _base_metadata(original_len: int) -> dict[str, Any]:
    return {
        "applied": False,
        "compaction_status": "not_needed",
        "original_char_count": original_len,
        "compacted_char_count": original_len,
        "removed_section_labels": [],
        "skip_reason": None,
    }


def compact_description(
    text: str, min_compacted_chars: int | None = None
) -> tuple[str, dict[str, Any]]:
    """Return a cheaper LLM input description plus audit metadata.

    Thresholds (enabled, min_compacted_chars, min_retention_ratio) are read from global
    settings so the admin UI can tune them without a code deploy. Regex patterns come from
    the rules JSON (description_compaction_rules.json) and are compiled once and cached.

    The original text is returned unchanged whenever compaction is disabled, unsafe, or
    not useful. metadata always records compaction_status and skip_reason.
    """
    from job_hunter_agent.global_settings import (
        get_description_compaction_enabled,
        get_description_compaction_min_chars,
        get_description_compaction_min_retention,
    )

    original = text or ""
    original_len = len(original)
    meta = _base_metadata(original_len)

    if not get_description_compaction_enabled():
        meta["compaction_status"] = "disabled"
        meta["skip_reason"] = "disabled"
        return original, meta

    min_chars = (
        int(min_compacted_chars)
        if min_compacted_chars is not None
        else get_description_compaction_min_chars()
    )
    min_retention = get_description_compaction_min_retention()

    if original_len < min_chars:
        meta["compaction_status"] = "not_needed"
        meta["skip_reason"] = "input_too_short"
        return original, meta

    paragraphs = re.split(r"\n\s*\n", original.strip())
    kept: list[str] = []
    stripped: list[str] = []
    labels: list[str] = []

    for para in paragraphs:
        should_strip, label = _paragraph_is_strippable(para)
        if should_strip:
            stripped.append(para)
            labels.append(label)
        else:
            kept.append(para)

    meta["removed_section_labels"] = labels

    if not labels:
        return original, meta

    compacted = "\n\n".join(kept).strip()
    compacted_len = len(compacted)

    if compacted_len < min_chars:
        meta["compaction_status"] = "skipped_too_risky"
        meta["skip_reason"] = f"compacted_too_short:{compacted_len}"
        return original, meta

    if original_len > 0 and compacted_len < original_len * min_retention:
        meta["compaction_status"] = "skipped_too_risky"
        meta["skip_reason"] = f"stripped_too_much:{original_len - compacted_len}/{original_len}"
        return original, meta

    stripped_text = "\n\n".join(stripped)
    if _has_protected_signal(stripped_text):
        meta["compaction_status"] = "skipped_too_risky"
        meta["skip_reason"] = "protected_signal_in_removed_content"
        return original, meta

    meta["applied"] = True
    meta["compaction_status"] = "applied"
    meta["compacted_char_count"] = compacted_len
    meta["skip_reason"] = None
    return compacted, meta
