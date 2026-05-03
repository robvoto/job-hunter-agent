from pathlib import Path


def test_results_page_uses_runtime_dashboard_config():
    root = Path(__file__).resolve().parent.parent
    results_js = (root / "templates" / "static" / "results-page.js").read_text(encoding="utf-8")
    results_html = (root / "templates" / "results.html").read_text(encoding="utf-8")

    assert "window.__JOB_HUNTER_DASHBOARD__" in results_html
    assert "$DASHBOARD_RUN_ID_JSON" not in results_js
    assert "$SEARCH_SETTINGS_JSON" not in results_js
    assert "$DEFAULT_SCORE_FILTER_MIN_JSON" not in results_js
    assert "$VIEWED_BADGE_HTML_JSON" not in results_js
