"""Structural checks for concise, single-owned agent instructions."""

from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_instruction_files_do_not_repeat_long_bullets_verbatim():
    paths = [
        ROOT / "AGENTS.md",
        ROOT / "docs" / "PROJECT_CONTEXT.md",
        *(ROOT / ".agents" / "skills").glob("*/SKILL.md"),
    ]
    occurrences: dict[str, list[str]] = defaultdict(list)

    for path in paths:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            text = " ".join(line.strip().split())
            if text.startswith("- ") and len(text) >= 45:
                occurrences[text].append(f"{path.relative_to(ROOT)}:{line_number}")

    duplicates = {text: refs for text, refs in occurrences.items() if len(refs) > 1}
    assert not duplicates, f"Duplicate long instruction bullets must have one owner: {duplicates}"
