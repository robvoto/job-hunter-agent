"""Read/write access to the knowledge table.

All managed knowledge (rules, defaults, capability definitions, etc.) lives
in the knowledge table, keyed by the original JSON file stem.
"""

import json
from pathlib import Path
from typing import Any

from job_hunter_agent.database import db_conn


def get_knowledge(key: str, db_path: Path | None = None) -> Any | None:
    """Return parsed knowledge for key, or None if not seeded."""
    with db_conn(db_path) as conn:
        row = conn.execute(
            "SELECT data FROM knowledge WHERE key = ?", (key,)
        ).fetchone()
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


def seed_knowledge_from_dir(
    source_dir: Path,
    db_path: Path | None = None,
    *,
    overwrite: bool = False,
) -> list[str]:
    """Seed knowledge table from all *.json files in source_dir.

    Uses INSERT OR IGNORE by default — existing entries are preserved.
    Pass overwrite=True to replace existing entries (e.g. app upgrade).
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
