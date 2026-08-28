"""Regression tests for the shared application footer component."""

from __future__ import annotations

from pathlib import Path

from job_hunter_agent import server_helpers

REPO_ROOT = Path(__file__).resolve().parents[1]
FOOTER_TOKEN = "__JOB_HUNTER_APP_FOOTER__"
FULL_PAGE_TEMPLATES = (
    "aws-browser-session.html",
    "global-settings.html",
    "login.html",
    "onboarding.html",
    "settings.html",
    "workspace.html",
)


def test_every_full_app_page_uses_shared_footer_once():
    for template_name in FULL_PAGE_TEMPLATES:
        html = (REPO_ROOT / "templates" / template_name).read_text(encoding="utf-8")
        assert html.count(FOOTER_TOKEN) == 1, template_name


def test_results_fragment_does_not_render_duplicate_app_footer():
    html = (REPO_ROOT / "templates" / "results.html").read_text(encoding="utf-8")
    assert FOOTER_TOKEN not in html


def test_shared_footer_renderer_resolves_managed_labels():
    html = server_helpers.render_app_footer_html()

    assert 'class="job-hunter-app-footer"' in html
    assert "© 2025–2026 Roberto Hernan Voto. All rights reserved." in html
    assert "robvoto.com" in html
    assert "Built by Rob Voto" not in html
    assert 'href="https://robvoto.com/"' in html
    assert 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html
    assert "__JOB_HUNTER_APP_FOOTER_" not in html


def test_login_has_no_legacy_login_only_copyright():
    login_html = (REPO_ROOT / "templates" / "login.html").read_text(encoding="utf-8")
    login_css = (REPO_ROOT / "templates" / "static" / "login" / "login-page.css").read_text(
        encoding="utf-8"
    )

    assert "login-copyright" not in login_html
    assert "login-copyright" not in login_css
    assert "© 2025 Rob Voto" not in login_html
    assert "All rights reserved." not in login_html


def test_login_has_no_promotional_invite_panel():
    login_html = (REPO_ROOT / "templates" / "login.html").read_text(encoding="utf-8")
    login_css = (REPO_ROOT / "templates" / "static" / "login" / "login-page.css").read_text(
        encoding="utf-8"
    )

    assert "login-invite" not in login_html
    assert "login-invite" not in login_css
    assert "Want to try it out?" not in login_html
    assert "review on LinkedIn" not in login_html


def test_login_footer_is_page_level_sibling_of_auth_content():
    login_html = (REPO_ROOT / "templates" / "login.html").read_text(encoding="utf-8")

    assert '<div class="login-auth__content">' in login_html
    assert "        <div id=\"error-container\"></div>\n      </div>\n      __JOB_HUNTER_APP_FOOTER__" in login_html


def test_shared_footer_is_documented_as_central_component():
    component_map = (REPO_ROOT / "docs" / "UI_COMPONENT_MAP.md").read_text(encoding="utf-8")
    theme_css = (REPO_ROOT / "templates" / "static" / "theme" / "themes.widgets.css").read_text(
        encoding="utf-8"
    )

    assert "| Shared application footer |" in component_map
    assert ".job-hunter-app-footer {" in theme_css
    assert ".job-hunter-app-footer__separator {" in theme_css
