from pathlib import Path


def test_wait_state_uses_quiet_disclosure_and_shared_structured_progress():
    repo_root = Path(__file__).resolve().parents[1]
    primitive_css = (
        repo_root / "templates" / "static" / "theme" / "themes.primitives.css"
    ).read_text(encoding="utf-8")
    widget_css = (
        repo_root / "templates" / "static" / "theme" / "themes.widgets.css"
    ).read_text(encoding="utf-8")
    wait_state_js = (
        repo_root / "templates" / "static" / "common" / "wait-state.js"
    ).read_text(encoding="utf-8")
    results_js = (
        repo_root / "templates" / "static" / "results" / "results-page.js"
    ).read_text(encoding="utf-8")

    assert ".wait-state__explainer > summary {" in primitive_css
    assert "padding: var(--control-pad-block-sm) 0;" in primitive_css
    assert ".wait-state__explainer:not([open])" not in primitive_css
    assert ".wait-state__activity" not in primitive_css
    assert ".wait-state__status--elapsed" not in primitive_css

    assert ".source-status-badge--linkedin" in widget_css
    assert ".source-status-badge--seek" in widget_css
    assert ".source-status-badge--apsjobs" in widget_css
    assert ".source-status-badge--job-market-map" in widget_css
    assert ".jh-progress--indeterminate::after" in widget_css
    assert ".jh-button.is-working::before" in widget_css
    assert "animation: workingSpin 0.9s linear infinite;" in widget_css
    assert "var(--brand-linkedin-bg)" in widget_css
    assert "var(--brand-seek-bg)" in widget_css

    assert 'role="progressbar"' in wait_state_js
    assert "aria-valuenow" in wait_state_js
    assert "progressDetail" in wait_state_js
    assert "job_market_map" in wait_state_js
    assert "legacyProgressCopy" not in wait_state_js
    assert "legacy =" not in wait_state_js
    assert "Current step:" not in wait_state_js
    assert "wait-state__activity" not in wait_state_js
    assert "activeButton.classList.add('is-working')" in results_js
    assert "activeButton.setAttribute('aria-busy', 'true')" in results_js
    assert "submitProfileGap(level, choice)" in results_js
