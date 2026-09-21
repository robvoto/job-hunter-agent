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
    assert step_3.count('<section class="review-block') == 5
    assert 'class="review-block review-block--full compensation-card"' in step_3
    assert "search-basics-grid" not in step_3
    assert "search-basics-card" not in step_3
    assert "search-basics-card-body" not in step_3
    assert ".search-basics-grid" not in onboarding_review_css
    assert ".search-basics-card" not in onboarding_review_css
    assert ".review-block--full {" in theme_widgets


def test_compensation_card_uses_shared_review_surface_without_legacy_pair_wrapper():
    repo_root = Path(__file__).resolve().parents[1]
    onboarding_html = (repo_root / "templates" / "onboarding.html").read_text(encoding="utf-8")
    theme_widgets = (
        repo_root / "templates" / "static" / "theme" / "themes.widgets.css"
    ).read_text(encoding="utf-8")

    assert 'class="review-block review-block--full compensation-card"' in onboarding_html
    assert 'class="compensation-card__field"' in onboarding_html
    assert 'class="salary-pair"' not in onboarding_html
    assert ".compensation-card {" in theme_widgets
    assert ".salary-pair {" not in theme_widgets
