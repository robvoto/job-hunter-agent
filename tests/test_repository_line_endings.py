"""Repository hygiene guard for committed text-file line endings."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_tracked_text_files_are_normalized_to_lf() -> None:
    result = subprocess.run(
        ["git", "ls-files", "--eol"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    offenders: list[str] = []
    for line in result.stdout.splitlines():
        metadata, separator, path = line.partition("\t")
        if not separator or "eol=lf" not in metadata:
            continue
        index_eol = metadata.split()[0]
        if index_eol in {"i/crlf", "i/mixed"}:
            offenders.append(f"{index_eol} {path}")

    assert not offenders, (
        "Tracked text files must be normalized to LF. Run `git add --renormalize <path>` "
        "for intentional edits or perform a dedicated normalization commit. Offenders:\n"
        + "\n".join(offenders)
    )
