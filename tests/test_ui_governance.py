"""Enforcement tests for UI governance rules in AGENTS.md / dashboard-ui / css-design-system.

These guard against the specific drift pattern this suite was written for: a new
control that borrows part of an existing shared pattern (a class name, a label
string) but not the rest of it (the DOM structure, the central label source, the
CSS ownership). Each test allows a small, explicitly named baseline of pre-existing
debt that predates this guardrail so the suite can catch new drift without failing
on history it didn't create.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_LABELS_PATH = REPO_ROOT / "data" / "knowledge" / "ui_labels.json"

PAGE_CSS_FILES = [
    REPO_ROOT / "templates" / "static" / "settings" / "shared" / "settings-page.css",
    REPO_ROOT / "templates" / "static" / "onboarding" / "onboarding-page.css",
    REPO_ROOT / "templates" / "static" / "workspace" / "workspace-page.css",
    REPO_ROOT / "templates" / "static" / "results" / "results-page.css",
    REPO_ROOT / "templates" / "static" / "login" / "login-page.css",
]

THEME_DIR = REPO_ROOT / "templates" / "static" / "theme"

_RULE_HEAD_RE = re.compile(r"([^{}@]+)\{", re.MULTILINE)
_SIMPLE_SELECTOR_RE = re.compile(r"^([.#][\w-]+)")


def _strip_css_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def _strip_js_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def _selector_head_tokens(css_text: str) -> set[str]:
    """First class/id token of every selector in every rule (ignoring @-blocks' own headers)."""
    text = _strip_css_comments(css_text)
    tokens: set[str] = set()
    for match in _RULE_HEAD_RE.finditer(text):
        raw = match.group(1)
        for part in raw.split(","):
            m = _SIMPLE_SELECTOR_RE.match(part.strip())
            if m:
                tokens.add(m.group(1))
    return tokens


def _walk_label_strings(obj, path=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            sub_path = f"{path}.{key}" if path else key
            yield from _walk_label_strings(value, sub_path)
    elif isinstance(obj, str):
        yield path, obj


# ---------------------------------------------------------------------------
# 1. Duplicated centrally-owned UI labels hardcoded in JS
# ---------------------------------------------------------------------------

# Pre-existing hardcoded copies of a central ui_labels.json string, found in JS
# files that predate this test. These are real debt (the JS should read the
# label instead of embedding its own copy) but are out of scope for the task
# that added this guardrail. Do not add new entries here — fix the duplication
# at the source instead.
_LABEL_DUPLICATION_BASELINE = {
    ("onboarding_flow_labels.clean_search_error", "templates/static/common/account-bar.js"),
    (
        "workspace_card_labels.gap_confirm_not_have_label",
        "templates/static/settings/shared/settings-review-panel.js",
    ),
    (
        "workspace_page_labels.rejection_panel_copy",
        "templates/static/results/results-page.js",
    ),
    (
        "workspace_page_labels.rejection_save_button",
        "templates/static/results/results-page.js",
    ),
    (
        "workspace_page_labels.rejection_skip_button",
        "templates/static/results/results-page.js",
    ),
}


def test_no_new_hardcoded_duplicates_of_central_ui_labels_in_js():
    """A JS file must not embed its own literal copy of a data/knowledge/ui_labels.json string.

    Shared text belongs in ui_labels.json, loaded via a window.__JOB_HUNTER_*_LABELS__
    bootstrap global. A JS file that hardcodes the same string instead of reading the
    label is exactly the drift this suite exists to catch (see role_history_labels,
    added to fix this same mistake in settings-page.js).
    """
    data = json.loads(UI_LABELS_PATH.read_text(encoding="utf-8"))
    candidates = [
        (path, value)
        for path, value in _walk_label_strings(data)
        if len(value) >= 15 and " " in value
    ]

    js_files = sorted((REPO_ROOT / "templates" / "static").rglob("*.js"))

    found: set[tuple[str, str]] = set()
    for label_path, value in candidates:
        pattern = re.compile(r"(['\"`])" + re.escape(value) + r"\1")
        for js_file in js_files:
            text = _strip_js_comments(js_file.read_text(encoding="utf-8"))
            if pattern.search(text):
                rel = js_file.relative_to(REPO_ROOT).as_posix()
                found.add((label_path, rel))

    new_hits = found - _LABEL_DUPLICATION_BASELINE
    assert not new_hits, (
        "New JS files hardcode text that already lives in ui_labels.json; read the "
        f"label via its window.__JOB_HUNTER_*_LABELS__ global instead: {sorted(new_hits)}"
    )

    stale_baseline = _LABEL_DUPLICATION_BASELINE - found
    assert not stale_baseline, (
        "Baseline entries no longer reproduce (label text or file likely changed); "
        f"remove them from _LABEL_DUPLICATION_BASELINE: {sorted(stale_baseline)}"
    )


# ---------------------------------------------------------------------------
# 2. Reusable component styling added to page CSS
# ---------------------------------------------------------------------------

# Selectors for components that are fully centrally owned (themes.widgets.css /
# themes.primitives.css) and have no documented reason to appear in any page CSS
# file at all -- their positioning is controlled by parent containers, not by
# redeclaring the widget's own selector. See docs/UI_COMPONENT_MAP.md.
_CENTRAL_ONLY_COMPONENT_SELECTORS = [
    ".toggle-switch",
    ".toggle-switch-copy",
    ".toggle-switch-title",
    ".toggle-switch-control",
    ".toggle-switch-ui",
    ".toggle-switch-state",
    ".choice-card--work-mode",
    ".badge-editor",
    ".badge-editor-list",
    ".badge-editor-form",
    ".currency-input-wrap",
    ".currency-prefix",
    ".settings-subpanel-head",
    ".settings-subpanel-actions",
]


def test_central_component_selectors_are_not_redefined_in_page_css():
    """Page CSS must not restyle a selector that UI_COMPONENT_MAP.md lists as centrally owned.

    Page CSS is layout-only. A page file that redeclares one of these selectors is
    adding component visual styling in the wrong place -- it belongs in
    templates/static/theme/themes.widgets.css (or themes.primitives.css) instead.
    """
    central = set(_CENTRAL_ONLY_COMPONENT_SELECTORS)
    offenders = []
    for css_file in PAGE_CSS_FILES:
        tokens = _selector_head_tokens(css_file.read_text(encoding="utf-8"))
        hit = tokens & central
        if hit:
            offenders.append((css_file.relative_to(REPO_ROOT).as_posix(), sorted(hit)))

    assert not offenders, (
        "Page CSS redefines a centrally-owned component selector; move the rule to "
        f"themes.widgets.css instead: {offenders}"
    )


# ---------------------------------------------------------------------------
# 3. Duplicated selectors across page CSS files
# ---------------------------------------------------------------------------

# Selectors independently defined in two or more page CSS files today. Two pages
# that need the same visual pattern should share it centrally instead of each
# growing their own copy -- but these predate this guardrail and are pre-existing
# debt, not something introduced by the current change. `.page` is the one
# legitimate case: every page CSS file defines its own page-root wrapper
# (max-width/padding), and since only one page CSS file loads per page these
# never conflict at runtime -- it is not a shared component.
_KNOWN_CROSS_PAGE_SELECTOR_DUPLICATES = {
    ".page",
    ".actions",
    ".capability-card",
    ".hero",
    ".panel",
    ".job-card",
    ".job-header-row",
    ".job-link",
    ".match-tile",
}


def test_no_new_duplicated_selectors_across_page_css_files():
    """A selector defined independently in 2+ page CSS files signals an uncentralized pattern.

    New duplication beyond the documented baseline means two pages evolved the same
    control independently instead of sharing a themes.widgets.css rule -- add it
    centrally instead of copy-pasting into a second page file.
    """
    owners: dict[str, list[str]] = {}
    for css_file in PAGE_CSS_FILES:
        tokens = _selector_head_tokens(css_file.read_text(encoding="utf-8"))
        rel = css_file.relative_to(REPO_ROOT).as_posix()
        for token in tokens:
            owners.setdefault(token, []).append(rel)

    duplicated = {sel: files for sel, files in owners.items() if len(files) > 1}
    new_dupes = {
        sel: files
        for sel, files in duplicated.items()
        if sel not in _KNOWN_CROSS_PAGE_SELECTOR_DUPLICATES
    }
    assert not new_dupes, (
        "New selector duplicated across page CSS files instead of centralized in "
        f"themes.widgets.css: {new_dupes}"
    )


# ---------------------------------------------------------------------------
# 4. Controls that copy only part of an existing DOM pattern (toggle-switch)
# ---------------------------------------------------------------------------

_TOGGLE_LABEL_OPEN_RE = re.compile(
    r'<label\s+class="toggle-switch(?P<compact>\s+toggle-switch--compact)?"'
)


def _toggle_switch_blocks(text: str) -> list[tuple[bool, str]]:
    """Return (is_compact, block_text) for each toggle-switch label found.

    block_text spans from the opening <label> tag to the matching </label>
    (falling back to a bounded window if no closing tag is found, e.g. inside a
    JS template literal that builds the tag programmatically).
    """
    blocks = []
    for match in _TOGGLE_LABEL_OPEN_RE.finditer(text):
        is_compact = match.group("compact") is not None
        start = match.start()
        end = text.find("</label>", start)
        if end == -1:
            end = min(len(text), start + 600)
        else:
            end += len("</label>")
        blocks.append((is_compact, text[start:end]))
    return blocks


def test_toggle_switch_variants_are_not_half_copied():
    """A toggle-switch must be either the full or compact variant, never a hybrid.

    Full variant: toggle-switch-copy > toggle-switch-title lives inside the label.
    Compact variant (toggle-switch--compact): no toggle-switch-copy/title inside the
    label at all -- the title lives in the surrounding row instead. A label that
    mixes the compact class with an inline toggle-switch-title (or a full-variant
    label missing toggle-switch-copy) is a half-copied pattern, not a documented
    variant -- see docs/UI_COMPONENT_MAP.md and .skills/dashboard-ui/SKILL.md.
    """
    search_files = sorted((REPO_ROOT / "templates").rglob("*.html")) + sorted(
        (REPO_ROOT / "templates" / "static").rglob("*.js")
    )

    violations = []
    for path in search_files:
        text = path.read_text(encoding="utf-8")
        for is_compact, block in _toggle_switch_blocks(text):
            rel = path.relative_to(REPO_ROOT).as_posix()
            has_copy = "toggle-switch-copy" in block
            has_title = "toggle-switch-title" in block
            has_control = "toggle-switch-control" in block

            if not has_control:
                violations.append((rel, "missing toggle-switch-control", block[:120]))
                continue

            if is_compact:
                if has_copy or has_title:
                    violations.append(
                        (rel, "compact variant has inline copy/title", block[:120])
                    )
            else:
                if not has_copy or not has_title:
                    violations.append(
                        (rel, "full variant missing toggle-switch-copy/title", block[:120])
                    )

    assert not violations, f"Half-copied toggle-switch pattern found: {violations}"


# ---------------------------------------------------------------------------
# 5. Missing comments for genuine page-local exceptions
# ---------------------------------------------------------------------------

# Selectors documented in UI_COMPONENT_MAP.md / css-design-system as genuine
# page-local layout exceptions on top of a shared pattern. Each must carry a
# nearby comment naming the exception so a future editor doesn't mistake it for
# an accidental restyle of a shared component.
_DOCUMENTED_LOCAL_EXCEPTIONS = [
    (
        REPO_ROOT / "templates" / "static" / "settings" / "shared" / "settings-page.css",
        ".schedule-source-panels",
    ),
    (
        REPO_ROOT / "templates" / "static" / "settings" / "shared" / "settings-page.css",
        ".schedule-source-panel",
    ),
    (
        REPO_ROOT / "templates" / "static" / "settings" / "shared" / "settings-page.css",
        ".schedule-time-field",
    ),
]

_EXCEPTION_COMMENT_WINDOW = 3


def test_documented_local_exceptions_carry_an_exception_comment():
    """Each documented page-local layout exception must keep its explanatory comment.

    Losing the comment during an edit makes the override indistinguishable from an
    accidental restyle of a shared pattern -- the exact drift this suite guards
    against.
    """
    missing = []
    for css_file, selector in _DOCUMENTED_LOCAL_EXCEPTIONS:
        lines = css_file.read_text(encoding="utf-8").splitlines()
        rel = css_file.relative_to(REPO_ROOT).as_posix()
        found_selector = False
        for idx, line in enumerate(lines):
            if selector in line and "{" in line:
                found_selector = True
                window = lines[max(0, idx - _EXCEPTION_COMMENT_WINDOW) : idx]
                if not any("exception" in w.lower() for w in window):
                    missing.append((rel, selector))
                break
        if not found_selector:
            missing.append((rel, f"{selector} (selector no longer found)"))

    assert not missing, (
        "Documented local layout exception is missing its explanatory comment "
        f"(or the selector moved/was removed): {missing}"
    )
