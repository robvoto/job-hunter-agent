#!/usr/bin/env python3
"""Regenerate checked-in standalone diagram HTML pages from Mermaid sources."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from job_hunter_agent.diagram_docs import regenerate_standalone_diagram_htmls
from job_hunter_agent.paths import DOCS_DIR


def main() -> int:
    diagrams_root = DOCS_DIR / "diagrams"
    written_paths = regenerate_standalone_diagram_htmls(diagrams_root)
    for path in written_paths:
        print(path.relative_to(DOCS_DIR.parent).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
