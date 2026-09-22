from pathlib import Path


def test_shared_typography_roles_are_canonical():
    repo_root = Path(__file__).resolve().parents[1]
    tokens = (repo_root / "templates" / "static" / "theme" / "themes.tokens.css").read_text(encoding="utf-8")
    widgets = (repo_root / "templates" / "static" / "theme" / "themes.widgets.css").read_text(encoding="utf-8")

    for token in (
        "--text-role-page-title-font-size",
        "--text-role-section-title-font-size",
        "--text-role-panel-title-font-size",
        "--text-role-field-label-font-size",
        "--text-role-control-value-font-size",
        "--text-role-helper-font-size",
        "--text-role-chip-font-size",
        "--text-role-status-font-size",
    ):
        assert token in tokens

    assert "--field-label-font-size: var(--text-role-field-label-font-size);" in tokens
    assert "--control-font-size: var(--text-role-control-value-font-size);" in tokens
    assert "--help-copy-font-size: var(--text-role-helper-font-size);" in tokens
    assert "--settings-section-title-font-size: var(--text-role-section-title-font-size);" in tokens
    assert "--settings-card-title-font-size: var(--text-role-panel-title-font-size);" in tokens

    assert ".checkbox-list-option {" in widgets
    assert "font-size: var(--control-font-size);" in widgets
    assert ".location-checkbox-option {" not in widgets
    assert "#engagement_type_choices.choice-strip > .choice-card--work-mode" in widgets
    assert "#seek_max_pages_choices.choice-strip > .choice-card--seek-pages" in widgets
    assert widgets.count("font-size: var(--text-role-control-value-font-size);") >= 3
