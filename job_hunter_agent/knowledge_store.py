"""Read/write access to the knowledge table.

All managed knowledge (rules, defaults, capability definitions, etc.) lives
in the knowledge table, keyed by the original JSON file stem.

Upgrade strategy (used by db_seed.py --upgrade):

  Files without a top-level "version" field are pure reference data (locations,
  salary config, etc.) — replaced wholesale every upgrade run.

  Files with "version" but whose entries are config (scoring_rules, ui_labels,
  parsing_rules, etc.) — replaced wholesale when file version > DB version.

  Files with "version" AND a top-level "entries" list where each item has a
  "value" field (capability_knowledge, hard_blocker_rules, cv_farming_rules,
  role_title_knowledge, government_context_knowledge) — additive merge: new
  entries from the file are appended; existing DB entries (including
  user-approved ones) are always preserved.
"""

import json
from pathlib import Path
from typing import Any

from job_hunter_agent.database import db_conn


def get_knowledge(key: str, db_path: Path | None = None) -> Any | None:
    """Return parsed knowledge for key, or None if not seeded."""
    with db_conn(db_path) as conn:
        row = conn.execute("SELECT data FROM knowledge WHERE key = ?", (key,)).fetchone()
    return json.loads(row["data"]) if row else None


def set_knowledge(key: str, data: Any, db_path: Path | None = None) -> None:
    """Insert or replace knowledge for key."""
    with db_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO knowledge (key, data, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET
                data       = excluded.data,
                updated_at = excluded.updated_at
            """,
            (key, json.dumps(data, ensure_ascii=False)),
        )


def _is_additive_knowledge(data: dict) -> bool:
    """True if this knowledge file uses an additive entries list keyed by 'value'."""
    entries = data.get("entries")
    return (
        isinstance(entries, list)
        and bool(entries)
        and isinstance(entries[0], dict)
        and "value" in entries[0]
    )


def _merge_additive(db_data: dict, file_data: dict) -> dict:
    """Append entries from file_data that are not already in db_data (by value)."""
    import copy

    merged = copy.deepcopy(db_data)
    db_values = {
        str(e.get("value", "")).strip().lower()
        for e in merged.get("entries", [])
        if isinstance(e, dict)
    }
    for entry in file_data.get("entries", []):
        if not isinstance(entry, dict):
            continue
        val = str(entry.get("value", "")).strip().lower()
        if val and val not in db_values:
            merged.setdefault("entries", []).append(entry)
            db_values.add(val)
    merged["version"] = file_data["version"]
    return merged


def upgrade_knowledge_from_dir(
    source_dir: Path,
    db_path: Path | None = None,
) -> list[str]:
    """Upgrade knowledge from source_dir using version-aware merge rules.

    - No version field → always replace (pure reference data).
    - Additive knowledge (entries list with value field) → merge new entries,
      preserve all existing DB entries including user-approved ones.
    - Config knowledge (versioned, not additive) → replace when file version
      is newer than DB version.

    Returns list of keys that were updated.
    """
    updated: list[str] = []
    for json_file in sorted(source_dir.glob("*.json")):
        key = json_file.stem
        file_data = json.loads(json_file.read_text(encoding="utf-8"))
        db_data = get_knowledge(key, db_path)

        if db_data is None:
            set_knowledge(key, file_data, db_path)
            updated.append(key)
            continue

        if not isinstance(file_data, dict):
            set_knowledge(key, file_data, db_path)
            updated.append(key)
            continue

        file_version = file_data.get("version")
        db_version = db_data.get("version") if isinstance(db_data, dict) else None

        if file_version is None:
            # No version — pure reference data, always replace.
            set_knowledge(key, file_data, db_path)
            updated.append(key)
        elif isinstance(file_version, int) and (
            db_version is None or (isinstance(db_version, int) and file_version > db_version)
        ):
            if _is_additive_knowledge(file_data) and isinstance(db_data, dict):
                merged = _merge_additive(db_data, file_data)
                set_knowledge(key, merged, db_path)
            else:
                set_knowledge(key, file_data, db_path)
            updated.append(key)
        # else: file_version <= db_version — skip, DB is current or ahead.

    return updated


def seed_knowledge_from_dir(
    source_dir: Path,
    db_path: Path | None = None,
    *,
    overwrite: bool = False,
) -> list[str]:
    """Seed knowledge table from all *.json files in source_dir.

    Uses INSERT OR IGNORE by default — existing entries are preserved.
    Pass overwrite=True to replace existing entries (hard reset to shipped defaults).
    For normal version upgrades use upgrade_knowledge_from_dir() instead.
    Returns list of keys that were written.
    """
    seeded: list[str] = []
    for json_file in sorted(source_dir.glob("*.json")):
        key = json_file.stem
        data = json.loads(json_file.read_text(encoding="utf-8"))
        with db_conn(db_path) as conn:
            if overwrite:
                conn.execute(
                    """
                    INSERT INTO knowledge (key, data, updated_at)
                    VALUES (?, ?, datetime('now'))
                    ON CONFLICT(key) DO UPDATE SET
                        data       = excluded.data,
                        updated_at = excluded.updated_at
                    """,
                    (key, json.dumps(data, ensure_ascii=False)),
                )
                seeded.append(key)
            else:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO knowledge (key, data) VALUES (?, ?)",
                    (key, json.dumps(data, ensure_ascii=False)),
                )
                if cursor.rowcount:
                    seeded.append(key)
    return seeded
