"""Safety boundary for canonical profile item names.

Job-ad wording may be verbose. Anything persisted as candidate knowledge must be
one stable, reusable concept rather than a requirement sentence or alternatives.
"""

from __future__ import annotations

import re
from typing import Any

from job_hunter_agent.text_processing import compact_whitespace

_REQUIREMENT_WORDING_RE = re.compile(
    r"\b(required|mandatory|essential|desirable|preferred|must|should|you will|we require|we are seeking)\b",
    re.IGNORECASE,
)
_COMPOUND_ALTERNATIVE_RE = re.compile(r"[,;]|\s+\bor\b\s+", re.IGNORECASE)


def canonical_profile_item_name(value: Any) -> str:
    """Return a reusable canonical concept name, or empty when unsafe to persist."""
    name = compact_whitespace(value)
    if not name or len(name) > 80:
        return ""
    if "\n" in str(value or ""):
        return ""
    if _REQUIREMENT_WORDING_RE.search(name):
        return ""
    if _COMPOUND_ALTERNATIVE_RE.search(name):
        return ""
    if name.endswith((".", ":")):
        return ""
    return name
