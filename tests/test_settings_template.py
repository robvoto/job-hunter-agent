from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
SETTINGS_TEMPLATE_PATH = ROOT_DIR / "templates" / "settings.html"


def test_source_document_suffixes_are_rendered_read_only():
    html = SETTINGS_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert 'id="source_document_allowed_suffixes"' in html
    assert 'readonly aria-readonly="true"' in html
    assert "Read-only. One suffix per line" in html
