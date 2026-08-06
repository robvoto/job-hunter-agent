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
    assert 'class="jh-button jh-button--secondary" id="open_telegram_connect"' in alerts


def test_special_cta_buttons_are_not_migrated_to_shared_application_button():
    workspace = (ROOT_DIR / "templates" / "workspace.html").read_text(encoding="utf-8")
    onboarding = (ROOT_DIR / "templates" / "onboarding.html").read_text(
        encoding="utf-8-sig"
    )

    assert 'class="btn btn-primary" id="ws_sidebar_run_btn"' in workspace
    assert 'class="btn btn-primary" id="continue_to_search_basics"' in onboarding
    assert 'class="btn btn-primary" id="confirm_review"' in onboarding
