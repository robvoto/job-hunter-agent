from pathlib import Path


def test_check_setup_summary_separates_labels_from_values():
    repo_root = Path(__file__).resolve().parents[1]
    css = (
        repo_root / "templates" / "static" / "onboarding" / "onboarding-review.css"
    ).read_text(encoding="utf-8")

    assert '.wizard-step[data-step="4"] .check-list > div {' in css
    assert "gap: var(--field-body-gap);" in css
    assert "color: var(--text-muted);" in css
    assert "font-weight: var(--control-font-weight);" in css
    assert "font-size: var(--font-size-7xl);" in css
    assert "font-weight: var(--field-label-font-weight);" in css
