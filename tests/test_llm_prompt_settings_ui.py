"""Regression checks for the human-friendly LLM prompt settings editor."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADMIN_HTML = ROOT / "templates" / "partials" / "settings" / "global" / "settings-admin.html"
ADMIN_JS = ROOT / "templates" / "static" / "settings" / "global" / "settings-admin.js"


def test_prompt_settings_form_uses_individual_textareas() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")

    assert 'id="llm_prompt_settings"' not in html
    assert 'id="llm_prompt_compensation_target_yearly"' in html
    assert 'id="llm_prompt_compensation_target_daily"' in html
    assert 'id="llm_prompt_home_location"' in html
    assert 'id="llm_prompt_prefer_permanent"' in html
    assert "Annual compensation template" in html
    assert "Daily rate template" in html
    assert "Home base template" in html
    assert "Permanent preference template" in html
    assert "plain text templates inserted into the LLM system prompt" in html
    assert 'Playwright selector timeout (seconds)' in html
    assert 'id="playwright_selector_timeout" type="number" min="1" max="60" step="1"' in html


def test_prompt_settings_script_maps_individual_fields() -> None:
    js = ADMIN_JS.read_text(encoding="utf-8")

    assert "const PROMPT_TEMPLATE_FIELDS = [" in js
    assert "const PLAYWRIGHT_TIMEOUT_MS_PER_SECOND = 1000;" in js
    assert "llm_prompt_settings: ['llm_settings.llm_prompt_settings', null]" not in js
    assert "JSON.stringify(llmSettings.llm_prompt_settings" not in js
    assert "JSON.parse(document.getElementById('llm_prompt_settings')" not in js
    assert "match_preference_templates" in js
    assert "llm_prompt_compensation_target_yearly" in js
    assert "llm_prompt_compensation_target_daily" in js
    assert "llm_prompt_home_location" in js
    assert "llm_prompt_prefer_permanent" in js
    assert "function requireElement(controlId)" in js
    assert "const readSecondsAsMilliseconds = (id, fallbackMilliseconds) => {" in js
    assert "Missing global settings element:" in js
    assert "Missing global settings label:" in js
