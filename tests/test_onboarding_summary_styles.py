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

    assert '<div class="review-grid review-grid--search-basics">' in step_3
    assert '<section class="onb-field">' in step_3
    assert '<section class="search-basics-container">' in step_3
    assert 'Search preferences' not in step_3
    assert 'search-basics-fields' in step_3
    assert step_3.count('class="onb-field"') >= 3
    assert step_3.count('<section class="search-basics-container">') == 1
    assert 'class="search-compensation-group"' in step_3
    assert '__JOB_HUNTER_ONBOARDING_PAGE_MINIMUM_COMPENSATION_LABEL__' in step_3
    assert 'id="salary_yearly_block" class="onb-field"' in step_3
    assert 'id="salary_daily_block" class="onb-field"' in step_3
    assert 'review-grid--search-basics' in onboarding_review_css
    assert 'grid-template-columns: minmax(0, 1fr);' in onboarding_review_css
    assert ".compensation-card" not in theme_widgets


def test_onboarding_and_settings_share_location_checkbox_component():
    repo_root = Path(__file__).resolve().parents[1]
    onboarding_html = (repo_root / "templates" / "onboarding.html").read_text(encoding="utf-8")
    settings_html = (
        repo_root / "templates" / "partials" / "settings" / "standard" / "settings-search.html"
    ).read_text(encoding="utf-8")
    common_location_js = (
        repo_root / "templates" / "static" / "common" / "location-options.js"
    ).read_text(encoding="utf-8")
    onboarding_js = (
        repo_root / "templates" / "static" / "onboarding" / "onboarding-page.js"
    ).read_text(encoding="utf-8")
    settings_js = (
        repo_root / "templates" / "static" / "settings" / "shared" / "settings-page.js"
    ).read_text(encoding="utf-8")

    shared_classes = 'class="checkbox-list-grid location-checkbox-grid"'
    assert shared_classes in onboarding_html
    assert shared_classes in settings_html
    assert "export function renderLocationCheckboxOptions" in common_location_js
    assert "onboardingLocationUi.renderLocationCheckboxOptions" in onboarding_js
    theme_widgets = (repo_root / "templates" / "static" / "theme" / "themes.widgets.css").read_text(encoding="utf-8")
    assert "grid-template-columns: repeat(auto-fit, minmax(min(100%, var(--layout-grid-min-group)), 1fr));" in theme_widgets
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in theme_widgets
    assert "max-width: 100%;" in theme_widgets
    assert "justify-items: start;" in theme_widgets
    assert "gap: var(--surface-gap-lg);" in theme_widgets
    assert "locationUi.renderLocationCheckboxOptions" in settings_js
    assert '<select id="location_search"' not in onboarding_html


def test_search_basics_uses_shared_preferences_and_compensation_columns():
    repo_root = Path(__file__).resolve().parents[1]
    onboarding_html = (repo_root / "templates" / "onboarding.html").read_text(encoding="utf-8")
    settings_html = (repo_root / "templates" / "partials" / "settings" / "standard" / "settings-search.html").read_text(encoding="utf-8")
    theme_widgets = (repo_root / "templates" / "static" / "theme" / "themes.widgets.css").read_text(encoding="utf-8")

    assert 'class="search-basics-fields"' in onboarding_html
    assert 'search-basics-fields' in settings_html
    assert 'class="search-compensation-group"' in onboarding_html
    assert 'class="search-compensation-group"' in settings_html
    assert 'id="salary_yearly_block" class="onb-field"' in onboarding_html
    assert 'id="salary_daily_block" class="onb-field"' in onboarding_html
    assert onboarding_html.count('currency-input-wrap currency-input-wrap--compact') >= 2
    assert settings_html.count('currency-input-wrap currency-input-wrap--compact') >= 2
    assert '.search-basics-fields {' in theme_widgets
    assert '.search-compensation-group {' in theme_widgets
    assert 'class="search-preference-groups"' in onboarding_html
    assert 'class="search-preference-groups"' in settings_html
    assert 'field-control-shell field-control-shell--compact-select' in settings_html
    assert '.field-control-shell--compact-select {' in theme_widgets
    assert 'width: min(100%, var(--setting-control-width));' in theme_widgets
    assert 'grid-template-columns: minmax(0, 1fr);' in theme_widgets
    assert 'justify-content: start;' in theme_widgets
    assert 'border-top: 1px solid var(--border-subtle);' in theme_widgets
    assert 'max-width: 11rem;' in theme_widgets
    assert 'salary-preference-card' not in onboarding_html
    assert 'class="compensation-card' not in onboarding_html
    assert 'class="salary-pair"' not in onboarding_html
    assert '__JOB_HUNTER_ONBOARDING_PAGE_MINIMUM_COMPENSATION_LABEL__ (excludes super)' in onboarding_html
    assert '<label for="review_minimum_salary_yearly">Annual base</label>' in onboarding_html
    assert '<label for="review_minimum_daily_rate">Daily rate</label>' in onboarding_html
    assert '<strong>Minimum compensation (excludes super)</strong>' in settings_html
    assert '<label for="minimum_salary_yearly">Annual base</label>' in settings_html
    assert '<label for="minimum_daily_rate">Daily rate</label>' in settings_html



def test_search_preferences_order_and_responsive_layout():
    repo_root = Path(__file__).resolve().parents[1]
    onboarding_html = (repo_root / "templates" / "onboarding.html").read_text(encoding="utf-8")
    onboarding_css = (
        repo_root / "templates" / "static" / "onboarding" / "onboarding-page.css"
    ).read_text(encoding="utf-8")

    step_3 = onboarding_html.split('data-step="3" hidden>', 1)[1].split('data-step="4" hidden>', 1)[0]
    work_pos = step_3.index('id="engagement_type_label"')
    sector_pos = step_3.index('id="prefer_sector_label"')
    mode_pos = step_3.index('id="work_mode_preference_label"')
    settings_html = (repo_root / "templates" / "partials" / "settings" / "standard" / "settings-search.html").read_text(encoding="utf-8")
    theme_widgets = (repo_root / "templates" / "static" / "theme" / "themes.widgets.css").read_text(encoding="utf-8")

    assert work_pos < sector_pos < mode_pos
    assert 'Search preferences' not in step_3
    assert 'class="search-basics-fields"' in step_3
    assert 'search-basics-fields' in settings_html
    assert settings_html.index('id="engagement_type_label"') < settings_html.index('id="prefer_sector_label"') < settings_html.index('id="work_mode_preference_label"')
    assert '.search-basics-fields {' in theme_widgets
    assert 'class="search-preference-groups"' in step_3
    assert 'search-preference-groups' in settings_html
    assert 'container-type: inline-size;' in theme_widgets
    assert '@container (max-width: 72rem)' not in theme_widgets
    assert 'search-preference-fields' not in onboarding_css
    assert 'onboarding-search-preferences-grid' not in onboarding_css


def test_onboarding_uses_shared_wide_shell_contract():
    repo_root = Path(__file__).resolve().parents[1]
    tokens = (repo_root / "templates" / "static" / "theme" / "themes.tokens.css").read_text(encoding="utf-8")
    assert '--wide-shell-max-width: 1560px;' in tokens
    assert '--onboarding-shell-max-width: var(--wide-shell-max-width);' in tokens


def test_location_dense_groups_fill_columns_in_reading_order():
    repo_root = Path(__file__).resolve().parents[1]
    location_js = (repo_root / "templates" / "static" / "common" / "location-options.js").read_text(encoding="utf-8")
    theme_widgets = (repo_root / "templates" / "static" / "theme" / "themes.widgets.css").read_text(encoding="utf-8")

    assert 'const useTwoColumns = groupOptions.length >= 6;' in location_js
    assert "groupsWrap.className = 'location-checkbox-groups';" in location_js
    assert '--checkbox-list-row-count' in location_js
    assert 'container-type: inline-size;' in theme_widgets
    assert 'grid-template-columns: repeat(auto-fit, minmax(min(100%, var(--layout-grid-min-group)), 1fr));' in theme_widgets
    assert '@container (max-width: 48rem)' in theme_widgets
    assert '@container (max-width: 64rem)' not in theme_widgets
    assert '@container (max-width: 30rem)' in theme_widgets
    assert 'grid-template-rows: repeat(var(--checkbox-list-row-count), auto);' in theme_widgets
    assert 'grid-auto-flow: column;' in theme_widgets
    assert 'white-space: normal;' in theme_widgets


def test_selected_capability_uses_card_state_without_selected_badge():
    repo_root = Path(__file__).resolve().parents[1]
    onboarding_js = (repo_root / "templates" / "static" / "onboarding" / "onboarding-flow.js").read_text(encoding="utf-8")
    onboarding_css = (repo_root / "templates" / "static" / "onboarding" / "onboarding-page.css").read_text(encoding="utf-8")

    assert 'capability-card${selectedClass}' in onboarding_js
    assert 'review-capability-selected-badge' not in onboarding_js
    assert '.capability-card.is-selected {' in onboarding_css
    assert '.review-capability-selected-badge' not in onboarding_css


def test_shared_full_span_fields_are_not_cancelled_at_mobile_widths():
    repo_root = Path(__file__).resolve().parents[1]
    theme_widgets = (repo_root / "templates" / "static" / "theme" / "themes.widgets.css").read_text(encoding="utf-8")

    assert ".settings-form-field--full {\n  grid-column: 1 / -1;" in theme_widgets
    assert ".settings-form-field--full {\n    grid-column: auto;" not in theme_widgets
