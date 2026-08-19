"""Enforcement test for the no-hardcoding rule in designated owner modules.

Guards against user-facing copy (labels, help text, warnings) being written
directly into Python business-logic files instead of `data/knowledge/ui_labels.json`.
Add a module to OWNER_MODULES once it has been cleaned up, so new debt in that
file is caught immediately instead of relying on someone noticing by chance.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

OWNER_MODULES = [
    REPO_ROOT / "job_hunter_agent" / "profile_store.py",
    REPO_ROOT / "job_hunter_agent" / "qualification_profile.py",
    REPO_ROOT / "job_hunter_agent" / "workspace_renderer.py",
    REPO_ROOT / "job_hunter_agent" / "signal_registry.py",
]

# A dict literal like {"value": X, "label": "Some Text"} — the label text should
# come from a ui_labels.json lookup call, not a string literal.
_INLINE_LABEL_LITERAL_RE = re.compile(r'"label"\s*:\s*"[^"]')

# A top-level ALL_CAPS constant assigned directly to a multi-word string literal,
# e.g. FOO_LABEL = "Some sentence of copy." — schema/token keys are single words
# (snake_case, no space) and are not flagged.
_TOP_LEVEL_SENTENCE_CONST_RE = re.compile(r'^[A-Z_][A-Z0-9_]*\s*=\s*\(?\s*"([^"]*\s[^"]*)"')


def _strip_comments(text: str) -> str:
    return re.sub(r"#.*", "", text)


def test_owner_modules_do_not_inline_user_facing_labels():
    violations: list[str] = []
    for path in OWNER_MODULES:
        text = path.read_text(encoding="utf-8")
        for lineno, raw_line in enumerate(text.splitlines(), start=1):
            line = _strip_comments(raw_line)
            if _INLINE_LABEL_LITERAL_RE.search(line):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: inline label literal — {line.strip()}")
            match = _TOP_LEVEL_SENTENCE_CONST_RE.match(line)
            if match:
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}: hardcoded sentence constant — {line.strip()}"
                )

    assert not violations, (
        "User-facing text must be sourced from data/knowledge/ui_labels.json via a "
        "label-lookup helper, not written directly in these owner modules. "
        "Violations:\n" + "\n".join(violations)
    )
