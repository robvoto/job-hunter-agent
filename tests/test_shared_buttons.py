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
    assert "min-height: var(--control-height-md);" in strength_block
    assert "padding: var(--control-pad-block-sm) var(--control-pad-inline-sm);" in strength_block
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


def test_choice_badge_and_action_families_are_reused_across_screens():
    widgets = (
        ROOT_DIR / "templates" / "static" / "theme" / "themes.widgets.css"
    ).read_text(encoding="utf-8-sig")
    helpers = (ROOT_DIR / "job_hunter_agent" / "server_helpers.py").read_text(encoding="utf-8")
    review_panel = (
        ROOT_DIR / "templates" / "static" / "settings" / "shared" / "settings-review-panel.js"
    ).read_text(encoding="utf-8")
    score_labels = (ROOT_DIR / "job_hunter_agent" / "score_labels.py").read_text(encoding="utf-8")
    renderer = (ROOT_DIR / "job_hunter_agent" / "workspace_renderer.py").read_text(encoding="utf-8")

    assert ".jh-choice-group {" in widgets
    assert ".jh-choice {" in widgets
    assert ".jh-badge {" in widgets
    assert 'choice-card jh-choice {escape(card_class)}' in helpers
    assert 'choice-strip jh-choice-group' in helpers
    assert '.workspace-controls .workspace-quick-filter {' not in widgets
    assert 'choice-card jh-choice choice-card--strength' in review_panel
    assert 'badge jh-badge {safe_html(class_name)}' in score_labels
    assert 'job-requirement-status jh-badge' not in renderer
    assert 'title-block-btn workspace-text-action workspace-text-action--muted' in renderer


def test_shared_choice_geometry_is_single_and_compact():
    widgets = (
        ROOT_DIR / "templates" / "static" / "theme" / "themes.widgets.css"
    ).read_text(encoding="utf-8-sig")
    block = widgets.split(".jh-choice {", 1)[1].split("}", 1)[0]
    assert "min-height: 1.9rem;" in block
    assert "padding: 4px 11px;" in block
    assert "border-radius: var(--control-radius-md);" in block


def test_ordinary_actions_do_not_use_legacy_visual_classes():
    files = [
        ROOT_DIR / "templates" / "results.html",
        ROOT_DIR / "templates" / "settings.html",
        ROOT_DIR / "templates" / "global-settings.html",
        ROOT_DIR / "templates" / "static" / "settings" / "shared" / "settings-review-panel.js",
        ROOT_DIR / "templates" / "static" / "settings" / "global" / "settings-admin.js",
        ROOT_DIR / "templates" / "static" / "common" / "wait-state.js",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8-sig") for path in files)

    assert 'class="secondary add-phrase-exclusion-btn"' not in combined
    assert 'class="secondary dismiss-rule-card-btn"' not in combined
    assert 'class="btn btn-secondary" data-system-warning-action' not in combined
    assert 'class="btn btn-secondary" id="ws_stop_search_btn"' not in combined
    assert 'style="font-size:0.9rem;padding:8px 16px;' not in combined
    assert 'jh-button jh-button--danger jh-button--compact add-phrase-exclusion-btn' in combined
    assert 'jh-button jh-button--neutral jh-button--compact dismiss-rule-card-btn' in combined


def test_micro_utility_action_is_smaller_than_compact_actions():
    primitives = (
        ROOT_DIR / "templates" / "static" / "theme" / "themes.primitives.css"
    ).read_text(encoding="utf-8-sig")
    widgets = (
        ROOT_DIR / "templates" / "static" / "theme" / "themes.widgets.css"
    ).read_text(encoding="utf-8-sig")
    renderer = (ROOT_DIR / "job_hunter_agent" / "workspace_renderer.py").read_text(encoding="utf-8")

    block = primitives.split(".jh-button--micro {", 1)[1].split("}", 1)[0]
    # Deliberately shrunk from 27px/3px 8px/0.74rem in "Job card capability UI
    # cleanup" (38a3ec3) so the micro action reads closer in scale to the
    # surrounding requirement-row text. Still strictly smaller than --compact.
    assert "min-height: 22px;" in block
    assert "padding: 2px 6px;" in block
    assert "font-size: 0.7rem;" in block
    assert "title-block-btn workspace-text-action workspace-text-action--muted" in renderer
    assert ".title-block-btn.jh-button {" not in widgets
    assert ".gap-btn.jh-button:not(.jh-button--micro) {" in primitives
    assert ".gap-btn.jh-button {" not in primitives
