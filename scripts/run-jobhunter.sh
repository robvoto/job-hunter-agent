#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'HELP'
Job Hunter WSL runner.

Usage:
  ./scripts/run-jobhunter.sh [command]

Commands:
  app          Sync dependencies, then run FastAPI normally.
  debug        Sync dependencies, then run FastAPI with --debug.
  sync         Install/update the project .venv from pyproject.toml.
  update-uv    Install uv if missing, then try to update uv itself.
  playwright   Install Playwright Chromium into the uv-managed environment.
  scrape       Run the source connector.
  no-llm       Run the source connector with live LLM review disabled.
  rebuild      Rebuild workspace only from saved runtime state.
  agent        Run the scheduled-agent wrapper once.
  agent-loop   Run the scheduled-agent wrapper loop.
  test         Run pytest.
  lint         Run ruff check.

Examples:
  ./scripts/run-jobhunter.sh debug
  ./scripts/run-jobhunter.sh no-llm
  ./scripts/run-jobhunter.sh test
HELP
}

ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi

  echo "uv was not found. Installing uv using Astral's official Linux installer..."
  if ! command -v curl >/dev/null 2>&1; then
    echo "ERROR: curl is required to install uv. Install curl first, then rerun this script." >&2
    exit 1
  fi

  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"

  if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv install completed but uv is still not on PATH." >&2
    echo "Try: export PATH=\"$HOME/.local/bin:$PATH\"" >&2
    exit 1
  fi
}

sync_project() {
  ensure_uv
  echo "==> uv version"
  uv --version
  echo "==> Sync project dependencies from pyproject.toml"
  uv sync --group dev
}

install_playwright() {
  ensure_uv
  echo "==> Install Playwright Chromium"
  uv run playwright install chromium
}

command="${1:-app}"
case "$command" in
  -h|--help|help)
    usage
    ;;
  sync)
    sync_project
    ;;
  update-uv)
    ensure_uv
    echo "==> Current uv"
    uv --version
    echo "==> Try uv self update"
    uv self update || {
      echo "uv self update is not available for this installation method. Use your package manager to update uv."
    }
    ;;
  playwright)
    sync_project
    install_playwright
    ;;
  app)
    sync_project
    install_playwright
    uv run python -m job_hunter_agent.fastapi_app
    ;;
  debug)
    sync_project
    install_playwright
    uv run python -m job_hunter_agent.fastapi_app --debug
    ;;
  scrape)
    sync_project
    install_playwright
    uv run python -m job_hunter_agent.source_connector
    ;;
  no-llm)
    sync_project
    install_playwright
    uv run python -m job_hunter_agent.source_connector --no-llm
    ;;
  rebuild)
    sync_project
    uv run python -m job_hunter_agent.source_connector --rebuild-workspace
    ;;
  agent)
    sync_project
    install_playwright
    uv run python -m job_hunter_agent.agent_runner
    ;;
  agent-loop)
    sync_project
    install_playwright
    uv run python -m job_hunter_agent.agent_runner --loop
    ;;
  test)
    sync_project
    uv run pytest
    ;;
  lint)
    sync_project
    uv run ruff check .
    ;;
  *)
    echo "ERROR: Unknown command: $command" >&2
    echo >&2
    usage >&2
    exit 2
    ;;
esac
