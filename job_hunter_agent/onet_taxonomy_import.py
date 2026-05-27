"""Build local O*NET occupation taxonomy reference JSON files.

Input source: O*NET OccupationalListings.zip.
Output files live in data/knowledge/occupation_taxonomy/ and are intended to be
versioned reference data, not runtime database rows.
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from openpyxl import load_workbook

from job_hunter_agent.paths import REPO_ROOT

TAXONOMY_VERSION = "O*NET-SOC 2019"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "knowledge" / "occupation_taxonomy"
OCCUPATIONS_MEMBER = "OccupationalListings/Taxonomies/2019_Occupations.xlsx"
ALTERNATE_TITLES_MEMBER = "OccupationalListings/2019_Structure/2019_Alt_Titles.xlsx"


def normalize_title(value: str | None) -> str:
    """Normalize a role title for deterministic taxonomy lookup keys."""
    text = str(value or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _read_xlsx_from_zip(zip_path: Path, member: str) -> list[dict[str, Any]]:
    with zipfile.ZipFile(zip_path) as archive, TemporaryDirectory() as tmp_dir:
        extracted = Path(tmp_dir) / Path(member).name
        extracted.write_bytes(archive.read(member))
        workbook = load_workbook(extracted, read_only=True, data_only=True)
        try:
            sheet = workbook[workbook.sheetnames[0]]
            rows = list(sheet.iter_rows(min_row=4, values_only=True))
        finally:
            workbook.close()

    if not rows:
        return []

    headers = [str(cell).strip() for cell in rows[0]]
    records: list[dict[str, Any]] = []
    for row in rows[1:]:
        if not row or not row[0]:
            continue
        records.append(dict(zip(headers, row)))
    return records


def build_taxonomy(zip_path: Path) -> dict[str, Any]:
    """Return occupations, alternate titles, and normalized lookup index."""
    occupation_rows = _read_xlsx_from_zip(zip_path, OCCUPATIONS_MEMBER)
    alternate_title_rows = _read_xlsx_from_zip(zip_path, ALTERNATE_TITLES_MEMBER)

    occupations: list[dict[str, str]] = []
    for row in occupation_rows:
        code = str(row["O*NET-SOC 2019 Code"]).strip()
        title = str(row["O*NET-SOC 2019 Title"]).strip()
        description = str(row.get("O*NET-SOC 2019 Description") or "").strip()
        occupations.append(
            {
                "code": code,
                "title": title,
                "normalized_title": normalize_title(title),
                "description": description,
            }
        )

    alternate_titles: list[dict[str, str]] = []
    for row in alternate_title_rows:
        occupation_code = str(row["O*NET-SOC 2019 Code"]).strip()
        occupation_title = str(row["O*NET-SOC 2019 Title"]).strip()
        alternate_title = str(row["Alternate Title"]).strip()
        alternate_titles.append(
            {
                "occupation_code": occupation_code,
                "occupation_title": occupation_title,
                "alternate_title": alternate_title,
                "normalized_title": normalize_title(alternate_title),
            }
        )

    by_normalized_title: dict[str, list[dict[str, str]]] = {}
    for occupation in occupations:
        by_normalized_title.setdefault(occupation["normalized_title"], []).append(
            {
                "occupation_code": occupation["code"],
                "occupation_title": occupation["title"],
                "source": "occupation_title",
            }
        )
    for alternate in alternate_titles:
        by_normalized_title.setdefault(alternate["normalized_title"], []).append(
            {
                "occupation_code": alternate["occupation_code"],
                "occupation_title": alternate["occupation_title"],
                "matched_title": alternate["alternate_title"],
                "source": "alternate_title",
            }
        )

    for key, matches in list(by_normalized_title.items()):
        seen: set[tuple[str, str, str]] = set()
        deduped: list[dict[str, str]] = []
        for match in matches:
            dedupe_key = (
                match["occupation_code"],
                match["source"],
                match.get("matched_title") or match["occupation_title"],
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            deduped.append(match)
        by_normalized_title[key] = deduped

    metadata = {
        "source": "O*NET OccupationalListings.zip",
        "taxonomy_version": TAXONOMY_VERSION,
        "generated_from": [OCCUPATIONS_MEMBER, ALTERNATE_TITLES_MEMBER],
        "record_counts": {
            "occupations": len(occupations),
            "alternate_titles": len(alternate_titles),
            "normalized_title_keys": len(by_normalized_title),
        },
    }

    return {
        "metadata": metadata,
        "occupations": occupations,
        "alternate_titles": alternate_titles,
        "by_normalized_title": dict(sorted(by_normalized_title.items())),
    }


def write_taxonomy_files(zip_path: Path, output_dir: Path = DEFAULT_OUTPUT_DIR) -> None:
    taxonomy = build_taxonomy(zip_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "onet_occupations.json": {
            "metadata": taxonomy["metadata"],
            "occupations": taxonomy["occupations"],
        },
        "onet_alternate_titles.json": {
            "metadata": taxonomy["metadata"],
            "alternate_titles": taxonomy["alternate_titles"],
        },
        "onet_index.json": {
            "metadata": taxonomy["metadata"],
            "normalization": "lowercase; ampersand to and; non-alphanumeric collapsed to spaces",
            "by_normalized_title": taxonomy["by_normalized_title"],
        },
    }

    for filename, payload in files.items():
        (output_dir / filename).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path", type=Path, help="Path to OccupationalListings.zip")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for generated O*NET JSON reference files",
    )
    args = parser.parse_args()
    write_taxonomy_files(args.zip_path, args.output_dir)
    print(f"Generated O*NET taxonomy files in {args.output_dir}")


if __name__ == "__main__":
    main()
