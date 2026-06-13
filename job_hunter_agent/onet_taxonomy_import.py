"""Build local O*NET occupation taxonomy reference JSON files.

Supports two O*NET source formats:

1. OccupationalListings.zip (HR/job-posting product, limited alternate titles)
   - OccupationalListings/Taxonomies/2019_Occupations.xlsx
   - OccupationalListings/2019_Structure/2019_Alt_Titles.xlsx

2. Full O*NET database zip (db_XX_X_text.zip, ~19k alternate titles)
   - Occupation Data.txt
   - Alternate Titles.txt

The format is auto-detected from zip contents. Output files are identical.
"""

from __future__ import annotations

import argparse
import csv
import io
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

# OccupationalListings zip members
_LISTINGS_OCCUPATIONS_MEMBER = "OccupationalListings/Taxonomies/2019_Occupations.xlsx"
_LISTINGS_ALT_TITLES_MEMBER = "OccupationalListings/2019_Structure/2019_Alt_Titles.xlsx"

# Full O*NET database zip members
_FULLDB_OCCUPATIONS_MEMBER = "Occupation Data.txt"
_FULLDB_ALT_TITLES_MEMBER = "Alternate Titles.txt"


def normalize_title(value: str | None) -> str:
    """Normalize a role title for deterministic taxonomy lookup keys."""
    text = str(value or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# OccupationalListings xlsx readers
# ---------------------------------------------------------------------------


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


def _read_listings_format(zip_path: Path) -> tuple[list[dict], list[dict]]:
    occupation_rows = _read_xlsx_from_zip(zip_path, _LISTINGS_OCCUPATIONS_MEMBER)
    alternate_title_rows = _read_xlsx_from_zip(zip_path, _LISTINGS_ALT_TITLES_MEMBER)

    occupations = [
        {
            "code": str(row["O*NET-SOC 2019 Code"]).strip(),
            "title": str(row["O*NET-SOC 2019 Title"]).strip(),
            "description": str(row.get("O*NET-SOC 2019 Description") or "").strip(),
        }
        for row in occupation_rows
    ]
    alternate_titles = [
        {
            "occupation_code": str(row["O*NET-SOC 2019 Code"]).strip(),
            "occupation_title": str(row["O*NET-SOC 2019 Title"]).strip(),
            "alternate_title": str(row["Alternate Title"]).strip(),
        }
        for row in alternate_title_rows
    ]
    return occupations, alternate_titles


# ---------------------------------------------------------------------------
# Full O*NET database txt readers
# ---------------------------------------------------------------------------


def _read_txt_from_zip(zip_path: Path, member: str) -> list[dict[str, str]]:
    with zipfile.ZipFile(zip_path) as archive:
        raw = archive.read(member).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw), delimiter="\t")
    return [row for row in reader if row]


def _read_fulldb_format(zip_path: Path) -> tuple[list[dict], list[dict]]:
    occupation_rows = _read_txt_from_zip(zip_path, _FULLDB_OCCUPATIONS_MEMBER)
    alternate_title_rows = _read_txt_from_zip(zip_path, _FULLDB_ALT_TITLES_MEMBER)

    # Build a code→title map so alternate title rows can include occupation_title
    code_to_title: dict[str, str] = {
        str(row.get("O*NET-SOC Code", "")).strip(): str(row.get("Title", "")).strip()
        for row in occupation_rows
    }

    occupations = [
        {
            "code": str(row.get("O*NET-SOC Code", "")).strip(),
            "title": str(row.get("Title", "")).strip(),
            "description": str(row.get("Description", "")).strip(),
        }
        for row in occupation_rows
        if row.get("O*NET-SOC Code")
    ]
    alternate_titles = [
        {
            "occupation_code": str(row.get("O*NET-SOC Code", "")).strip(),
            "occupation_title": code_to_title.get(str(row.get("O*NET-SOC Code", "")).strip(), ""),
            "alternate_title": str(row.get("Alternate Title", "")).strip(),
        }
        for row in alternate_title_rows
        if row.get("Alternate Title") and row.get("O*NET-SOC Code")
    ]
    return occupations, alternate_titles


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------


def _detect_format(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
    if _FULLDB_OCCUPATIONS_MEMBER in names and _FULLDB_ALT_TITLES_MEMBER in names:
        return "fulldb"
    if _LISTINGS_OCCUPATIONS_MEMBER in names:
        return "listings"
    raise ValueError(
        f"Unrecognised O*NET zip format. Expected either:\n"
        f"  Full database: '{_FULLDB_OCCUPATIONS_MEMBER}' and '{_FULLDB_ALT_TITLES_MEMBER}'\n"
        f"  OccupationalListings: '{_LISTINGS_OCCUPATIONS_MEMBER}'\n"
        f"Found: {names[:10]}"
    )


# ---------------------------------------------------------------------------
# Index builder (shared)
# ---------------------------------------------------------------------------


def build_taxonomy(zip_path: Path) -> dict[str, Any]:
    """Return occupations, alternate titles, and normalized lookup index."""
    fmt = _detect_format(zip_path)
    if fmt == "fulldb":
        raw_occupations, raw_alternate_titles = _read_fulldb_format(zip_path)
        source_label = "O*NET database txt (full)"
    else:
        raw_occupations, raw_alternate_titles = _read_listings_format(zip_path)
        source_label = "O*NET OccupationalListings.zip"

    occupations: list[dict[str, str]] = [
        {
            "code": o["code"],
            "title": o["title"],
            "normalized_title": normalize_title(o["title"]),
            "description": o["description"],
        }
        for o in raw_occupations
        if o["code"] and o["title"]
    ]

    alternate_titles: list[dict[str, str]] = [
        {
            "occupation_code": a["occupation_code"],
            "occupation_title": a["occupation_title"],
            "alternate_title": a["alternate_title"],
            "normalized_title": normalize_title(a["alternate_title"]),
        }
        for a in raw_alternate_titles
        if a["occupation_code"] and a["alternate_title"]
    ]

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
        "source": source_label,
        "taxonomy_version": TAXONOMY_VERSION,
        "format": fmt,
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

    counts = taxonomy["metadata"]["record_counts"]
    print(
        f"Generated O*NET taxonomy files in {output_dir}\n"
        f"  Format:          {taxonomy['metadata']['format']}\n"
        f"  Occupations:     {counts['occupations']}\n"
        f"  Alternate titles:{counts['alternate_titles']}\n"
        f"  Index keys:      {counts['normalized_title_keys']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "zip_path", type=Path, help="Path to O*NET zip (OccupationalListings or full database)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for generated O*NET JSON reference files",
    )
    args = parser.parse_args()
    write_taxonomy_files(args.zip_path, args.output_dir)


if __name__ == "__main__":
    main()
