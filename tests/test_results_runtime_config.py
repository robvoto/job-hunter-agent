from pathlib import Path


def test_results_page_uses_runtime_workspace_config():
    root = Path(__file__).resolve().parent.parent
    results_js = (root / "templates" / "static" / "results-page.js").read_text(encoding="utf-8")
    results_html = (root / "templates" / "results.html").read_text(encoding="utf-8")

    assert "window.__JOB_HUNTER_WORKSPACE__" in results_html
    assert 'href="/settings#section-search"' in results_html
    assert "Common Search" in results_html
    assert "Work type" in results_html
    assert "Sector preference" in results_html
    assert "SEEK Settings" not in results_html
    assert "LinkedIn Settings" not in results_html
    assert "Run Search Now" not in results_html
    assert "Edit Configuration" not in results_html
    assert "$WORKSPACE_RUN_ID_JSON" not in results_js
    assert "$VIEWED_BADGE_HTML_JSON" not in results_js
    assert "search_settings_" not in results_js
    assert "Run Search Now" not in results_js
