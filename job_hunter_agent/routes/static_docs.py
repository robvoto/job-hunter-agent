"""Route handlers for static docs."""

from html import escape as html_escape

from fastapi import APIRouter
from starlette.responses import Response

from job_hunter_agent import server_helpers as srv
from job_hunter_agent.paths import DATA_DIR, DOCS_DIR, STATIC_DIR
from job_hunter_agent.routes.responses import guess_media_type, html_response, json_response

router = APIRouter()


@router.get("/static/diagrams/{diagram_name}")
def diagram_viewer(diagram_name: str):  # type: ignore[no-untyped-def]

    filename = diagram_name.strip("/")
    if not filename:
        return json_response({"error": "Diagram not found"}, 404)
    if not filename.endswith(".mmd"):
        filename = f"{filename}.mmd"

    diagrams_root = (DOCS_DIR / "diagrams").resolve()
    candidate = (diagrams_root / filename).resolve()

    if diagrams_root not in candidate.parents and candidate != diagrams_root:
        return json_response({"error": "Diagram not found"}, 404)

    if not candidate.is_file():
        return json_response({"error": "Diagram not found"}, 404)

    source = candidate.read_text(encoding="utf-8")
    title = candidate.stem.replace("_", " ").title()
    source_html = html_escape(source)
    title_html = html_escape(title)
    rel_name_html = html_escape(candidate.relative_to(DOCS_DIR).as_posix())

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title_html}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f8fafc;
      --panel: #ffffff;
      --text: #0f172a;
      --muted: #64748b;
      --border: #dbe4f0;
      --shadow: 0 18px 60px rgba(15, 23, 42, 0.10);
    }}
    body {{
      margin: 0;
      min-height: 100vh;
      background: linear-gradient(180deg, #f8fbff 0%, #edf2ff 100%);
      font-family: Inter, "Segoe UI", Arial, sans-serif;
      color: var(--text);
    }}
    .shell {{
      max-width: 1600px;
      margin: 0 auto;
      padding: 24px;
    }}
    .header {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: end;
      margin-bottom: 16px;
      flex-wrap: wrap;
    }}
    .header h1 {{
      margin: 0;
      font-size: 28px;
      line-height: 1.1;
    }}
    .header .meta {{
      color: var(--muted);
      font-size: 13px;
      margin-top: 6px;
    }}
    .chip {{
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border: 1px solid var(--border);
      border-radius: 999px;
      background: rgba(255,255,255,.8);
      color: var(--muted);
      font-size: 13px;
      text-decoration: none;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 20px;
      box-shadow: var(--shadow);
      padding: 24px;
      overflow: auto;
    }}
    .mermaid {{
      display: flex;
      justify-content: center;
      align-items: flex-start;
      min-width: max-content;
    }}
    .help {{
      margin-top: 12px;
      font-size: 13px;
      color: var(--muted);
    }}
    textarea {{
      display: none;
    }}
  </style>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
  <script>
    window.addEventListener("DOMContentLoaded", () => {{
      mermaid.initialize({{
        startOnLoad: false,
        securityLevel: "loose",
        theme: "base",
        flowchart: {{
          useMaxWidth: true,
          curve: "basis"
        }},
        themeVariables: {{
          fontFamily: 'Inter, "Segoe UI", Arial, sans-serif'
        }}
      }});
      const diagram = document.getElementById("diagram");
      const source = document.getElementById("diagram-source").value.trim();
      diagram.textContent = source;
      mermaid.run({{ nodes: [diagram] }});
    }});
  </script>
</head>
<body>
  <div class="shell">
    <div class="header">
      <div>
        <h1>{title_html}</h1>
        <div class="meta">Rendered from <code>{rel_name_html}</code></div>
      </div>
      <a class="chip" href="/docs">Docs JSON API</a>
    </div>
    <div class="panel">
      <div id="diagram" class="mermaid"></div>
    </div>
    <div class="help">This view renders the Mermaid source directly, so the `.mmd` file stays authoritative.</div>
  </div>
  <textarea id="diagram-source">{source_html}</textarea>
</body>
</html>
"""
    return html_response(html)


@router.get("/static/{resource_path:path}")
def static_file(resource_path: str):  # type: ignore[no-untyped-def]

    relative = resource_path.strip("/")

    candidate = (STATIC_DIR / relative).resolve()

    static_root = STATIC_DIR.resolve()

    if static_root not in candidate.parents and candidate != static_root:
        return json_response({"error": "Static asset not found"}, 404)

    if not candidate.is_file():
        return json_response({"error": "Static asset not found"}, 404)

    return Response(
        content=candidate.read_bytes(),
        media_type=guess_media_type(candidate),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get("/data/{resource_path:path}")
def data_file(resource_path: str):  # type: ignore[no-untyped-def]

    relative = resource_path.strip("/")

    candidate = (DATA_DIR / relative).resolve()

    data_root = DATA_DIR.resolve()

    if data_root not in candidate.parents and candidate != data_root:
        return json_response({"error": "Data asset not found"}, 404)

    if not candidate.is_file():
        return json_response({"error": "Data asset not found"}, 404)

    return Response(
        content=candidate.read_bytes(),
        media_type=guess_media_type(candidate),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get("/docs")
@router.get("/api/docs")
def api_docs():  # type: ignore[no-untyped-def]

    return json_response({"docs": srv.get_docs()})
