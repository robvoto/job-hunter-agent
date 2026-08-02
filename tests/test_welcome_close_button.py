import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(*parts: str) -> str:
    return (REPO_ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def test_welcome_modal_uses_shared_close_button_class():
    workspace_html = _read("templates", "workspace.html")
    assert 'class="jh-icon-button jh-icon-button--close ws-flash-close"' in workspace_html
    assert '<h2 class="jh-panel-title">Quick start</h2>' in workspace_html
    assert '<svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">' in workspace_html


def test_welcome_modal_close_button_has_dialog_specific_aria_label():
    workspace_html = _read("templates", "workspace.html")
    assert 'aria-label="Close welcome dialog"' in workspace_html


def test_shared_icon_button_meets_minimum_touch_target():
    theme_widgets = _read("templates", "static", "theme", "themes.widgets.css")
    match = re.search(r"\.jh-icon-button\s*\{([^}]*)\}", theme_widgets)
    assert match, ".jh-icon-button rule not found in themes.widgets.css"
    body = match.group(1)
    assert "width: var(--control-height-md);" in body
    assert "height: var(--control-height-md);" in body


def test_shared_icon_button_has_focus_visible_state():
    theme_widgets = _read("templates", "static", "theme", "themes.widgets.css")
    assert re.search(r"\.jh-icon-button:focus-visible\s*\{[^}]*outline", theme_widgets)


def test_workspace_css_does_not_duplicate_shared_icon_button_styling():
    workspace_css = _read("templates", "static", "workspace", "workspace-page.css")
    match = re.search(r"\.ws-flash-close\s*\{([^}]*)\}", workspace_css)
    assert match, ".ws-flash-close rule not found in workspace-page.css"
    body = match.group(1)

    disallowed_properties = ("width", "height", "background", "color", "font-size", "border-radius", "border:")
    for prop in disallowed_properties:
        assert prop not in body, f"workspace-page.css duplicates shared visual property: {prop}"

    assert ".ws-flash-close:hover" not in workspace_css
