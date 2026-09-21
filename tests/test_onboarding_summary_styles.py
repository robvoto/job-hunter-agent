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


def test_search_basics_reuses_review_layout_primitives():
    repo_root = Path(__file__).resolve().parents[1]
    onboarding_html = (repo_root / "templates" / "onboarding.html").read_text(encoding="utf-8")
    onboarding_review_css = (
        repo_root / "templates" / "static" / "onboarding" / "onboarding-review.css"
    ).read_text(encoding="utf-8")
    theme_widgets = (
        repo_root / "templates" / "static" / "theme" / "themes.widgets.css"
    ).read_text(encoding="utf-8")

    step_3 = onboarding_html.split('data-step="3" hidden>', 1)[1].split('data-step="4" hidden>', 1)[0]

    assert '<div class="review-grid">' in step_3
    assert 'class="review-block onb-field settings-form-field--full"' in step_3
    assert '<select id="location_search" class="jh-select" multiple size="8"' in step_3
    assert 'class="review-block settings-form-field--full"' in step_3
    assert '<h3 class="summary-card-title">Search preferences</h3>' in step_3
    assert 'class="settings-form-grid settings-form-grid--search-basics"' in step_3
    assert 'class="onb-field settings-form-field--full"' in step_3
    assert 'id="salary_yearly_block" class="review-block onb-field"' in step_3
    assert 'id="salary_daily_block" class="review-block onb-field"' in step_3
    assert "search-basics-grid" not in step_3
    assert "search-basics-card" not in step_3
    assert ".search-basics-grid" not in onboarding_review_css
    assert ".search-basics-card" not in onboarding_review_css
    assert ".compensation-card" not in theme_widgets


def test_onboarding_keeps_compact_location_selector():
    repo_root = Path(__file__).resolve().parents[1]
    onboarding_html = (repo_root / "templates" / "onboarding.html").read_text(encoding="utf-8")

    assert '<select id="location_search" class="jh-select" multiple size="8"' in onboarding_html
    assert 'id="location_search" class="checkbox-list-grid location-checkbox-grid"' not in onboarding_html


def test_salary_preferences_are_normal_review_cards_using_shared_controls():
    repo_root = Path(__file__).resolve().parents[1]
    onboarding_html = (repo_root / "templates" / "onboarding.html").read_text(encoding="utf-8")

    assert 'id="salary_yearly_block" class="review-block onb-field"' in onboarding_html
    assert 'id="salary_daily_block" class="review-block onb-field"' in onboarding_html
    assert '__JOB_HUNTER_SALARY_ANNUAL_HELP__' in onboarding_html
    assert '__JOB_HUNTER_SALARY_DAILY_HELP__' in onboarding_html
    assert 'class="currency-input-wrap"' in onboarding_html
    assert 'class="compensation-card' not in onboarding_html
    assert 'class="salary-pair"' not in onboarding_html
