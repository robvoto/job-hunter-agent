import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "templates" / "static"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_shared_trash_action_owns_markup_and_managed_labels():
    source = _read("templates/static/common/action-buttons.js")
    labels = json.loads(_read("data/knowledge/ui_labels.json"))["shared_ui_labels"]

    assert "renderTrashActionButton" in source
    assert 'class="jh-icon-button jh-icon-button--destructive jh-icon-button--trash"' in source
    assert "window.__JOB_HUNTER_SHARED_UI_LABELS__" in source
    assert "remove_item_label" in source
    assert "remove_item_fallback_label" in source
    assert "{name}" in labels["remove_item_label"]
    assert labels["remove_item_fallback_label"].strip()


def test_all_current_per_item_destructive_actions_reuse_shared_trash_renderer():
    owners = [
        "templates/static/settings/shared/settings-capability-editor.js",
        "templates/static/settings/shared/settings-eligibility-editor.js",
        "templates/static/settings/shared/settings-qualification-editor.js",
        "templates/static/onboarding/onboarding-flow.js",
        "templates/static/settings/learning/signal-registry.js",
    ]

    for owner in owners:
        source = _read(owner)
        assert "renderTrashActionButton" in source, owner

    qualification = _read("templates/static/settings/shared/settings-qualification-editor.js")
    assert "jh-button--danger jh-button--compact" not in qualification


def test_page_css_does_not_reinvent_per_item_destructive_action():
    settings_css = _read("templates/static/settings/shared/settings-page.css")
    onboarding_css = _read("templates/static/onboarding/onboarding-page.css")

    for selector in ("capability-remove-btn", "cap-remove-icon", "signal-remove"):
        assert selector not in settings_css
    for selector in ("review-capability-action-danger", "review-capability-action-icon"):
        assert selector not in onboarding_css


def test_eligibility_and_qualification_share_editor_stack_spacing():
    html = _read("templates/partials/settings/standard/settings-matrix.html")
    theme_css = _read("templates/static/theme/themes.widgets.css")

    assert re.search(
        r'class="jh-editor-stack">.*id="eligibility_name_add".*id="eligibility_editor"',
        html,
        re.DOTALL,
    )
    assert re.search(
        r'class="jh-editor-stack">.*id="qualification_name_add".*id="qualification_editor"',
        html,
        re.DOTALL,
    )
    assert ".jh-editor-stack {" in theme_css
    assert ".jh-editor-entry {" in theme_css
    assert "gap: var(--field-stack-gap);" in theme_css
    assert ".jh-editor-entry > .field-help:empty" in theme_css


def test_eligibility_and_qualification_actions_are_vertically_centered():
    settings_css = _read("templates/static/settings/shared/settings-page.css")
    eligibility = _read("templates/static/settings/shared/settings-eligibility-editor.js")
    qualification = _read("templates/static/settings/shared/settings-qualification-editor.js")

    block = re.search(r"\.eligibility-card \{(?P<body>.*?)\n    \}", settings_css, re.DOTALL)
    assert block, "Shared eligibility-card layout rule is missing"
    assert "align-items: center;" in block.group("body")
    assert 'class="capability-card eligibility-card"' in eligibility
    assert 'class="capability-card eligibility-card"' in qualification


def test_direct_remove_button_markup_is_limited_to_documented_exceptions():
    allowed_direct_patterns = (
        'data-review-bulk-action="remove"',
        'data-remove-selected-capabilities=',
        'data-remove-chip=',
        'cap-alias-chip-remove',
        '${removeAttribute}',
        '${removeLabel}',
    )
    offenders = []
    button_pattern = re.compile(r'<button\b[^>]*(?:remove|delete)[^>]*>.*?</button>', re.IGNORECASE | re.DOTALL)

    for path in (ROOT / "templates").rglob("*"):
        if path.suffix not in {".js", ".html"}:
            continue
        source = path.read_text(encoding="utf-8")
        for match in button_pattern.finditer(source):
            block = " ".join(match.group(0).split())
            if any(pattern in block for pattern in allowed_direct_patterns):
                continue
            offenders.append((path.relative_to(ROOT).as_posix(), block[:240]))

    assert not offenders, (
        "Direct remove/delete button markup bypasses the shared per-item trash action. "
        f"Use renderTrashActionButton(), or document a true bulk/chip exception: {offenders}"
    )


def test_remove_delete_accessible_labels_are_not_hardcoded_in_templates():
    pattern = re.compile(r'(?:aria-label|title)=[\\\"](?:Remove|Delete)(?:[ \\\"$<{])', re.IGNORECASE)
    offenders = []
    for path in (ROOT / "templates").rglob("*"):
        if path.suffix not in {".js", ".html"}:
            continue
        source = path.read_text(encoding="utf-8")
        if pattern.search(source):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert not offenders, f"Hardcoded remove/delete labels found instead of managed UI copy: {offenders}"


def test_chip_remove_labels_use_shared_managed_copy():
    settings_chip_editor = _read("templates/static/settings/shared/settings-chip-editor.js")
    onboarding_flow = _read("templates/static/onboarding/onboarding-flow.js")
    results_page = _read("templates/static/results/results-page.js")
    workspace_service = _read("job_hunter_agent/workspace_service.py")

    assert "formatRemoveItemLabel" in settings_chip_editor
    assert "formatRemoveItemLabel" in onboarding_flow
    assert 'title="Remove ${' not in settings_chip_editor
    assert 'aria-label="Remove"' not in results_page
    assert "_rejRemoveItemLabel" in results_page
    assert 'load_ui_labels().get("shared_ui_labels", {})' in workspace_service
    assert 'shared_ui_labels.get("remove_item_label")' in workspace_service
    assert '"removeItemLabel": remove_item_label' in workspace_service
    assert 'from job_hunter_agent.server_helpers import load_shared_ui_labels' not in workspace_service
