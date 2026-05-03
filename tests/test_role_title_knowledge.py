from __future__ import annotations

import json

from job_hunter_agent import role_title_knowledge


def test_load_role_title_knowledge_normalizes_to_value_only(tmp_path, monkeypatch):
    path = tmp_path / "role_title_knowledge.json"
    path.write_text(
        json.dumps(
            {
                "kind": "managed_knowledge",
                "name": "role_title_knowledge",
                "entries": [
                    {"value": " analyst ", "aliases": ["reporting analyst", "analyst"]},
                    {"value": "manager", "aliases": []},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(role_title_knowledge, "ROLE_TITLE_KNOWLEDGE_PATH", path)

    entries = role_title_knowledge.load_role_title_knowledge()

    assert entries == [
        {"value": "analyst"},
        {"value": "manager"},
    ]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["entries"] == [
        {"value": "analyst"},
        {"value": "manager"},
    ]
