from pathlib import Path


def test_wait_state_explainer_uses_compact_closed_state_and_card_open_state():
    repo_root = Path(__file__).resolve().parents[1]
    css = (
        repo_root / "templates" / "static" / "theme" / "themes.primitives.css"
    ).read_text(encoding="utf-8")

    assert ".wait-state__explainer {" in css
    assert "width: min(100%, 360px);" in css
    assert "border-radius: var(--radius-md);" in css
    assert ".wait-state__explainer:not([open]) {" in css
    assert "width: fit-content;" in css
    assert "border-radius: var(--control-radius-pill);" in css
    assert ".wait-state__explainer[open] .wait-state__explainer-body {" in css
    assert "padding-top: var(--surface-pad-block-xs);" in css
    assert "border-top: 1px solid color-mix(in srgb, var(--text-muted) 12%, var(--border-subtle));" in css
