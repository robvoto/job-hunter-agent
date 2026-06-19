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


@router.get("/docs/view")
def docs_viewer(doc: str = "docs/ARCHITECTURE.md"):  # type: ignore[no-untyped-def]
    from job_hunter_agent.config import ALLOWED_DOC_REL_PATHS
    from job_hunter_agent.paths import ROOT_DIR

    rel = doc.strip("/")
    if rel not in ALLOWED_DOC_REL_PATHS:
        return json_response({"error": "Doc not found"}, 404)

    file_path = (ROOT_DIR / rel).resolve()
    if not file_path.is_file():
        return json_response({"error": "Doc not found"}, 404)

    content = file_path.read_text(encoding="utf-8")
    content_escaped = html_escape(content)
    title_html = html_escape(file_path.stem.replace("_", " ").title())

    doc_links = "".join(
        f'<a class="doc-link" href="/docs/view?doc={html_escape(p)}">{html_escape(p.split("/")[-1])}</a>'
        for p in ALLOWED_DOC_REL_PATHS
    )

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
      --accent: #e8631a;
      --shadow: 0 18px 60px rgba(15,23,42,0.10);
      --code-bg: #f1f5f9;
    }}
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background: linear-gradient(180deg, #f8fbff 0%, #edf2ff 100%);
      font-family: Inter, "Segoe UI", Arial, sans-serif;
      color: var(--text);
    }}
    .shell {{
      max-width: 860px;
      margin: 0 auto;
      padding: 24px 24px 64px;
    }}
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 20px;
      flex-wrap: wrap;
    }}
    .header h1 {{ margin: 0; font-size: 22px; }}
    .nav {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .doc-link {{
      display: inline-flex;
      align-items: center;
      padding: 5px 12px;
      border: 1px solid var(--border);
      border-radius: 999px;
      background: rgba(255,255,255,.8);
      color: var(--muted);
      font-size: 12px;
      text-decoration: none;
      white-space: nowrap;
    }}
    .doc-link:hover {{ color: var(--accent); border-color: var(--accent); }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 16px;
      box-shadow: var(--shadow);
      padding: 32px 40px;
    }}
    /* Markdown output */
    #md-output h1 {{ font-size: 1.7em; margin-top: 0; }}
    #md-output h2 {{ font-size: 1.25em; margin-top: 2em; border-bottom: 1px solid var(--border); padding-bottom: 4px; }}
    #md-output h3 {{ font-size: 1.05em; margin-top: 1.5em; }}
    #md-output code {{ background: var(--code-bg); padding: 1px 5px; border-radius: 4px; font-size: .88em; }}
    #md-output pre {{ background: var(--code-bg); border-radius: 8px; padding: 14px 18px; overflow-x: auto; }}
    #md-output pre code {{ background: none; padding: 0; }}
    #md-output a {{ color: var(--accent); }}
    #md-output ul, #md-output ol {{ padding-left: 1.5em; }}
    #md-output li {{ margin-bottom: .3em; }}
    #md-output hr {{ border: none; border-top: 1px solid var(--border); margin: 2em 0; }}
    #md-output blockquote {{ border-left: 3px solid var(--border); margin: 0; padding-left: 1em; color: var(--muted); }}
    #md-output table {{ border-collapse: collapse; width: 100%; }}
    #md-output th, #md-output td {{ border: 1px solid var(--border); padding: 6px 10px; text-align: left; }}
    #md-output th {{ background: var(--code-bg); }}
  </style>
</head>
<body>
  <div class="shell">
    <div class="header">
      <h1>{title_html}</h1>
      <nav class="nav">{doc_links}</nav>
    </div>
    <div class="panel">
      <div id="md-output"></div>
    </div>
  </div>
  <textarea id="md-source" style="display:none">{content_escaped}</textarea>
  <script src="https://cdn.jsdelivr.net/npm/marked@13/marked.min.js"></script>
  <script>
    const source = document.getElementById("md-source").value;
    document.getElementById("md-output").innerHTML = marked.parse(source);
    if (location.hash) {{
      const el = document.getElementById(location.hash.slice(1));
      if (el) el.scrollIntoView({{block: "start"}});
    }}
  </script>
</body>
</html>
"""
    return html_response(html)


@router.get("/docs")
@router.get("/api/docs")
def api_docs():  # type: ignore[no-untyped-def]

    return json_response({"docs": srv.get_docs()})
