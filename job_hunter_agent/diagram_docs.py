"""Shared Mermaid HTML rendering for app docs and checked-in diagram pages."""

import json
from html import escape as html_escape
from pathlib import Path
from string import Template


MERMAID_RENDER_CONFIG = {
    "startOnLoad": False,
    "securityLevel": "loose",
    "theme": "base",
    "flowchart": {
        "useMaxWidth": True,
        "curve": "basis",
        "nodeSpacing": 30,
        "rankSpacing": 50,
    },
    "themeVariables": {
        "fontFamily": 'Inter, "Segoe UI", Arial, sans-serif',
    },
}


_DIAGRAM_HTML_TEMPLATE = Template(
    """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>$title</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f8fbff;
      --panel: #ffffff;
      --text: #0f172a;
      --muted: #64748b;
      --border: #dbe4f0;
      --shadow: 0 18px 60px rgba(15, 23, 42, 0.10);
    }
    html, body {
      margin: 0;
      min-height: 100%;
      background: linear-gradient(180deg, #f8fbff 0%, #eef2ff 100%);
      color: var(--text);
      font-family: Inter, "Segoe UI", Arial, sans-serif;
    }
    .shell {
      max-width: 1600px;
      margin: 0 auto;
      padding: 24px;
    }
    .header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: end;
      flex-wrap: wrap;
      margin-bottom: 16px;
    }
    h1 {
      margin: 0;
      font-size: 28px;
      line-height: 1.1;
    }
    .meta {
      margin-top: 6px;
      color: var(--muted);
      font-size: 13px;
    }
    .meta code {
      color: var(--text);
    }
    .chip {
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,.8);
      color: var(--muted);
      text-decoration: none;
      font-size: 13px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 20px;
      box-shadow: var(--shadow);
      overflow: auto;
      padding: 28px 24px;
    }
    .mermaid {
      display: flex;
      justify-content: center;
      align-items: flex-start;
      min-width: max-content;
    }
    .help {
      margin-top: 12px;
      color: var(--muted);
      font-size: 13px;
    }
    textarea {
      display: none;
    }
  </style>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
  <script>
    window.addEventListener("DOMContentLoaded", () => {
      const source = document.getElementById("diagram-source").value.trim();
      const diagram = document.getElementById("diagram");
      diagram.textContent = source;

      mermaid.initialize($mermaid_config);
      mermaid.run({ nodes: [diagram] });
    });
  </script>
</head>
<body>
  <div class="shell">
    <div class="header">
      <div>
        <h1>$title</h1>
        <div class="meta">$meta_html</div>
      </div>
      <a class="chip" href="$chip_href">$chip_label</a>
    </div>
    <div class="panel">
      <div id="diagram" class="mermaid"></div>
    </div>
    <div class="help">$help_text</div>
  </div>

  <textarea id="diagram-source">$source_html</textarea>
</body>
</html>
"""
)


def render_diagram_html(
    *,
    title: str,
    source: str,
    meta_html: str,
    chip_href: str,
    chip_label: str,
    help_text: str,
) -> str:
    return _DIAGRAM_HTML_TEMPLATE.substitute(
        title=html_escape(title),
        meta_html=meta_html,
        chip_href=html_escape(chip_href, quote=True),
        chip_label=html_escape(chip_label),
        help_text=html_escape(help_text),
        source_html=html_escape(source),
        mermaid_config=json.dumps(MERMAID_RENDER_CONFIG, indent=8),
    )


def render_standalone_diagram_html(diagram_path: Path) -> str:
    source = diagram_path.read_text(encoding="utf-8")
    title = diagram_path.stem.replace("_", " ").title()
    return render_diagram_html(
        title=title,
        source=source,
        meta_html=(
            "Human-friendly sibling view for "
            f"<code>{html_escape(diagram_path.name)}</code>"
        ),
        chip_href=f"./{diagram_path.name}",
        chip_label="Open Mermaid source",
        help_text=(
            "This view is meant to sit next to the Mermaid source and render it directly "
            "in your browser."
        ),
    )


def regenerate_standalone_diagram_htmls(diagrams_root: Path) -> list[Path]:
    written_paths: list[Path] = []
    for diagram_path in sorted(diagrams_root.glob("*.mmd")):
        html_path = diagram_path.with_suffix(".html")
        html_path.write_text(render_standalone_diagram_html(diagram_path), encoding="utf-8")
        written_paths.append(html_path)
    return written_paths
