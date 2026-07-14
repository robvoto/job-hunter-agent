from pathlib import Path

from job_hunter_agent.diagram_docs import (
    regenerate_standalone_diagram_htmls,
    render_standalone_diagram_html,
)


def test_checked_in_diagram_html_matches_generator():
    repo_root = Path(__file__).resolve().parent.parent
    diagram_path = repo_root / "docs" / "diagrams" / "scoring_process_flow.mmd"
    html_path = diagram_path.with_suffix(".html")

    assert html_path.read_text(encoding="utf-8") == render_standalone_diagram_html(diagram_path)


def test_regenerate_standalone_diagram_htmls_writes_html_siblings(tmp_path):
    diagrams_root = tmp_path / "diagrams"
    diagrams_root.mkdir()
    diagram_path = diagrams_root / "mini_flow.mmd"
    diagram_path.write_text("flowchart TD\n    A --> B\n", encoding="utf-8")

    written_paths = regenerate_standalone_diagram_htmls(diagrams_root)

    html_path = diagram_path.with_suffix(".html")
    assert written_paths == [html_path]
    html = html_path.read_text(encoding="utf-8")
    assert "<title>Mini Flow</title>" in html
    assert '"nodeSpacing": 30' in html
    assert "Open Mermaid source" in html
