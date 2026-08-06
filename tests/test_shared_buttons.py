"""Contract tests for the shared ordinary application button component."""

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]


def test_shared_application_button_contract_is_documented_and_used():
    primitives = (
        ROOT_DIR / "templates" / "static" / "theme" / "themes.primitives.css"
    ).read_text(encoding="utf-8-sig")
    component_map = (ROOT_DIR / "docs" / "UI_COMPONENT_MAP.md").read_text(encoding="utf-8")
    renderer = (ROOT_DIR / "job_hunter_agent" / "workspace_renderer.py").read_text(
        encoding="utf-8"
    )
    alerts = (
        ROOT_DIR
        / "templates"
        / "partials"
        / "settings"
        / "standard"
        / "settings-alerts.html"
    ).read_text(encoding="utf-8")

    for css_class in (
        ".jh-button {",
        ".jh-button--primary {",
        ".jh-button--secondary {",
        ".jh-button--danger {",
        ".jh-button--neutral {",
        ".jh-button--compact {",
    ):
        assert css_class in primitives
    assert "## Shared application button" in component_map
    assert "review-applied jh-button jh-button--primary jh-button--compact" in renderer
    assert "review-not-for-me jh-button jh-button--danger jh-button--compact" in renderer
    assert 'class="jh-button jh-button--secondary jh-button--compact" id="open_telegram_connect"' in alerts


def test_special_cta_buttons_are_not_migrated_to_shared_application_button():
    workspace = (ROOT_DIR / "templates" / "workspace.html").read_text(encoding="utf-8")
    onboarding = (ROOT_DIR / "templates" / "onboarding.html").read_text(
        encoding="utf-8-sig"
    )

    assert 'class="btn btn-primary" id="ws_sidebar_run_btn"' in workspace
    assert 'class="btn btn-primary" id="continue_to_search_basics"' in onboarding
    assert 'class="btn btn-primary" id="confirm_review"' in onboarding


def test_compact_actions_are_rectangular_and_strength_choices_are_separate():
    primitives = (
        ROOT_DIR / "templates" / "static" / "theme" / "themes.primitives.css"
    ).read_text(encoding="utf-8-sig")
    widgets = (
        ROOT_DIR / "templates" / "static" / "theme" / "themes.widgets.css"
    ).read_text(encoding="utf-8-sig")

    compact_block = primitives.split(".jh-button--compact {", 1)[1].split("}", 1)[0]
    assert "min-height: 32px;" in compact_block
    assert "padding: 6px 12px;" in compact_block
    assert "border-radius: var(--radius-sm);" in compact_block
    assert ".capability-strength-strip.choice-strip {" in widgets
    assert "gap: 8px;" in widgets
    assert "border: 0;" in widgets
    assert "overflow: visible;" in widgets
    strength_block = widgets.rsplit(".choice-strip > .choice-card--strength {", 1)[1].split("}", 1)[0]
    assert "min-height: 36px;" in strength_block
    assert "padding: 6px 14px;" in strength_block
    assert "border-radius: var(--radius-sm);" in strength_block


def test_settings_actions_use_compact_shared_buttons_without_inline_sizing():
    alerts = (
        ROOT_DIR
        / "templates"
        / "partials"
        / "settings"
        / "standard"
        / "settings-alerts.html"
    ).read_text(encoding="utf-8")
    review_panel = (
        ROOT_DIR
        / "templates"
        / "static"
        / "settings"
        / "shared"
        / "settings-review-panel.js"
    ).read_text(encoding="utf-8")
    settings_css = (
        ROOT_DIR
        / "templates"
        / "static"
        / "settings"
        / "shared"
        / "settings-page.css"
    ).read_text(encoding="utf-8")

    assert 'jh-button--secondary jh-button--compact" id="open_telegram_connect"' in alerts
    assert 'jh-button--secondary jh-button--compact" id="send_telegram_test"' in alerts
    assert "jh-button--primary jh-button--compact confirm-skill-btn" in review_panel
    assert "jh-button--secondary jh-button--compact decline-skill-btn" in review_panel
    assert 'class="primary confirm-skill-btn"' not in review_panel
    assert 'class="secondary decline-skill-btn"' not in review_panel
    assert "min-height: 40px;" not in settings_css.split(
        ".alerts-shell .telegram-connect-actions > button", 1
    )[1].split("}", 1)[0]
