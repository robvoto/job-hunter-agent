"""Canonical candidate qualification profile items."""

from __future__ import annotations

from typing import Any

from job_hunter_agent.profile_item_names import canonical_profile_item_name
from job_hunter_agent.text_processing import compact_whitespace

KEY_NAME = "name"
KEY_VALUE = "value"
KEY_ALIASES = "aliases"
KEY_EVIDENCE = "evidence"


def normalize_qualifications(items: Any) -> list[dict[str, Any]]:
    """Keep qualifications reusable while retaining candidate evidence."""

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in items if isinstance(items, list) else []:
        if not isinstance(raw, dict):
            continue
        # The LLM-provided name is the canonical concept. This helper only
        # rejects unsafe persisted values; it must not supply or rewrite the
        # qualification concept.
        name = compact_whitespace(raw.get(KEY_NAME) or raw.get("label"))
        if not canonical_profile_item_name(name):
            continue
        name_key = name.casefold()
        if not name_key or name_key in seen:
            continue
        aliases = raw.get(KEY_ALIASES) or []
        if isinstance(aliases, str):
            aliases = [aliases]
        clean_aliases: list[str] = []
        seen_aliases: set[str] = set()
        for alias in aliases if isinstance(aliases, list) else []:
            clean_alias = compact_whitespace(alias)
            alias_key = clean_alias.casefold()
            if not clean_alias or alias_key == name_key or alias_key in seen_aliases:
                continue
            if not canonical_profile_item_name(clean_alias):
                continue
            seen_aliases.add(alias_key)
            clean_aliases.append(clean_alias)
        evidence = raw.get(KEY_EVIDENCE) or []
        if isinstance(evidence, str):
            evidence = [evidence]
        clean_evidence = [
            compact_whitespace(value)
            for value in evidence if compact_whitespace(value)
        ] if isinstance(evidence, list) else []
        normalized.append(
            {
                KEY_NAME: name,
                KEY_VALUE: raw.get(KEY_VALUE) is not False,
                KEY_ALIASES: clean_aliases,
                KEY_EVIDENCE: clean_evidence,
                "needs_review": bool(raw.get("needs_review")),
            }
        )
        seen.add(name_key)
    return normalized
