"""Role title cleanup helpers.

Only performs mechanical cleanup: trim, lowercase, collapse whitespace.
Does not expand abbreviations, guess role families, or read from managed knowledge.
If a title is unclear, O*NET handles occupation matching; unclear titles return uncertain.
"""

from __future__ import annotations

import re
from typing import Any


def normalize_title_text(value: Any, source_text: Any = "") -> str:
    """Trim, lowercase, and collapse whitespace. Does not expand abbreviations.

    'Sr BA'   -> 'sr ba'
    'PM'      -> 'pm'
    'SRVA'    -> 'srva'
    ' Senior Business Analyst ' -> 'senior business analyst'
    """
    return re.sub(r"\s+", " ", str(value or "").strip().lower()).strip()
