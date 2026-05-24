from __future__ import annotations

from job_hunter_agent import role_title_knowledge


def test_load_role_title_knowledge_normalizes_to_value_only(isolated_db):
    from job_hunter_agent.knowledge_store import set_knowledge, get_knowledge

    set_knowledge("role_title_knowledge", {
        "kind": "managed_knowledge",
        "name": "role_title_knowledge",
        "entries": [
            {"value": " analyst ", "aliases": ["reporting analyst", "analyst"]},
            {"value": "manager", "aliases": []},
        ],
    }, isolated_db)

    entries = role_title_knowledge.load_role_title_knowledge()

    assert entries == [
        {"value": "analyst"},
        {"value": "manager"},
    ]
    saved = get_knowledge("role_title_knowledge", isolated_db)
    assert saved["entries"] == [
        {"value": "analyst"},
        {"value": "manager"},
    ]
