from pathlib import Path


def test_check_setup_summary_uses_shared_summary_field_pattern():
    repo_root = Path(__file__).resolve().parents[1]
    theme_widgets = (
        repo_root / "templates" / "static" / "theme" / "themes.widgets.css"
    ).read_text(encoding="utf-8")
    onboarding_html = (repo_root / "templates" / "onboarding.html").read_text(encoding="utf-8")
    onboarding_review_css = (
        repo_root / "templates" / "static" / "onboarding" / "onboarding-review.css"
    ).read_text(encoding="utf-8")

    assert ".summary-field-list {" in theme_widgets
    assert "gap: var(--field-body-gap);" in theme_widgets
    assert "font-size: var(--field-label-font-size);" in theme_widgets
    assert "font-size: var(--text-role-body-font-size);" in theme_widgets
    assert "font-weight: var(--text-role-status-font-weight);" in theme_widgets
    assert 'class="summary-field-list"' in onboarding_html
    assert 'class="summary-field__label"' in onboarding_html
    assert 'class="summary-field__value"' in onboarding_html
    assert ".summary-field__value {" not in onboarding_review_css
