#!/usr/bin/env bash
set -euo pipefail

# Run one contiguous slice of the normal top-level pytest suite. Human MCP has
# a hard per-command cap, so full validation is three separate serial calls.
# Serial execution avoids xdist cross-test interference seen in this repository.
#
# Usage: ./scripts/run-pytest-mcp.sh <batch-number> [total-batches]

batch="${1:-}"
total="${2:-3}"

if ! [[ "$batch" =~ ^[0-9]+$ && "$total" =~ ^[0-9]+$ ]] || (( batch < 1 || total < 1 || batch > total )); then
  sed -n '4,8p' "$0" >&2
  exit 2
fi

mapfile -t files < <(find tests -maxdepth 1 -type f -name 'test_*.py' | sort)
count=${#files[@]}
chunk=$(( (count + total - 1) / total ))
start=$(( (batch - 1) * chunk ))

if (( start >= count )); then
  echo "No tests selected for batch ${batch}/${total}" >&2
  exit 3
fi

selected=("${files[@]:start:chunk}")
echo "Running MCP-safe pytest batch ${batch}/${total}: ${#selected[@]} files"
exec uv run pytest -q --tb=short "${selected[@]}"
