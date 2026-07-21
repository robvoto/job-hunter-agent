#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Run Playwright e2e tests for Job Hunter.

Usage:
  ./scripts/run-e2e.sh [--headed|--headless] [--install-browser] [--llm] [test-path ...] [-- pytest-args...]

Examples:
  ./scripts/run-e2e.sh
  ./scripts/run-e2e.sh --headed tests/e2e/test_workspace_freshness_flow.py -q
  JOB_HUNTER_E2E_ALLOW_LLM=1 OPENAI_API_KEY=sk-... ./scripts/run-e2e.sh --llm tests/e2e/test_onboarding_llm_flow.py -v

Notes:
  - Headless is the default, so Chromium runs invisibly unless you pass --headed.
  - The script always adds --confcutdir=tests/e2e for the click-test harness.
  - Pass any extra pytest flags after --, or simply append them at the end.
EOF
}

headed=0
install_browser=0
llm_only=0
targets=()
pytest_args=()

while (($#)); do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --headed)
      headed=1
      shift
      ;;
    --headless)
      headed=0
      shift
      ;;
    --install-browser)
      install_browser=1
      shift
      ;;
    --llm)
      llm_only=1
      shift
      ;;
    --)
      shift
      pytest_args+=("$@")
      break
      ;;
    tests/e2e/*|*.py)
      targets+=("$1")
      shift
      ;;
    -*)
      pytest_args+=("$1")
      shift
      ;;
    *)
      targets+=("$1")
      shift
      ;;
  esac
done

if ((install_browser)); then
  uv run playwright install chromium
fi

if ((headed)) && [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
  echo "Headed Playwright needs a graphical desktop session (DISPLAY or WAYLAND_DISPLAY)." >&2
  echo "Run from a local desktop terminal, or omit --headed to stay headless." >&2
  exit 2
fi

if ((${#targets[@]} == 0)); then
  targets=("tests/e2e")
fi

cmd=(uv run pytest "${targets[@]}" --confcutdir=tests/e2e)
if ((headed)); then
  cmd+=(--headed)
fi
if ((llm_only)); then
  cmd+=(-m llm_e2e)
fi
cmd+=("${pytest_args[@]}")

printf 'Running:'
for arg in "${cmd[@]}"; do
  printf ' %q' "$arg"
done
printf '\n'

exec "${cmd[@]}"
