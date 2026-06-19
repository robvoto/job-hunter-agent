"""Synchronize shared learned knowledge between SQLite databases."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any, Iterable

from job_hunter_agent.database import db_conn, init_db
from job_hunter_agent.knowledge_store import get_knowledge, set_knowledge
from job_hunter_agent.managed_knowledge_store import merge_knowledge_entries
from job_hunter_agent.parsing_schema import (
    KEY_P_ROUTING,
    KEY_P_ROUTING_DEFAULT,
    KEY_P_ROUTING_PRIMARY,
    KEY_P_ROUTING_SECONDARY,
    KEY_P_ROUTING_SUPPLEMENTARY,
)
from job_hunter_agent.text_processing import compact_whitespace

_SHARED_KNOWLEDGE_KEYS = (
    "capability_knowledge",
    "cv_farming_rules",
    "hard_blocker_rules",
    "job_type",
    "parsing_rules",
)

_ROUTING_LIST_KEYS = (
    KEY_P_ROUTING_PRIMARY,
    KEY_P_ROUTING_SECONDARY,
    KEY_P_ROUTING_SUPPLEMENTARY,
)
_JOB_TYPE_LIST_KEYS = ("trigger_work_types", "contract_signal_keywords")


def _clean_text(value: Any) -> str:
    return compact_whitespace(value)


def _normalize_job_type_key(value: Any) -> str:
    return _clean_text(value).lower().replace(" ", "")


def _normalize_value_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _clean_text(value)
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
    return cleaned


def _merge_string_lists(*values: Any) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in _normalize_value_list(value):
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def _updated_at_key(value: str | None) -> str:
    return value or ""


def _read_knowledge(db_path: Path, key: str) -> tuple[Any | None, str]:
    payload = get_knowledge(key, db_path)
    with db_conn(db_path) as conn:
        row = conn.execute(
            "SELECT updated_at FROM knowledge WHERE key = ?",
            (key,),
        ).fetchone()
    return payload, _updated_at_key(row["updated_at"] if row else None)


def _write_knowledge(db_path: Path, key: str, payload: Any) -> None:
    set_knowledge(key, payload, db_path)


def _merge_additive_payloads(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    base = copy.deepcopy(right if right else left)
    left_entries = left.get("entries") if isinstance(left, dict) else []
    right_entries = right.get("entries") if isinstance(right, dict) else []
    base["entries"] = merge_knowledge_entries([*(left_entries or []), *(right_entries or [])])

    left_version = left.get("version") if isinstance(left, dict) else None
    right_version = right.get("version") if isinstance(right, dict) else None
    versions = [value for value in (left_version, right_version) if isinstance(value, int)]
    if versions:
        base["version"] = max(versions)
    return base


def _merge_job_type_payloads(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    base = copy.deepcopy(right if right else left)

    merged_mapping: dict[str, str] = {}
    for source in (left.get("mapping"), right.get("mapping")):
        if not isinstance(source, dict):
            continue
        for raw_key, raw_value in source.items():
            key = _normalize_job_type_key(raw_key)
            value = _clean_text(raw_value)
            if key and value:
                merged_mapping[key] = value
    base["mapping"] = merged_mapping

    merged_groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for source in (left.get("filter_groups"), right.get("filter_groups")):
        if not isinstance(source, list):
            continue
        for group in source:
            if not isinstance(group, dict):
                continue
            label = _clean_text(group.get("label"))
            if not label:
                continue
            label_key = label.lower()
            values = _normalize_value_list(group.get("values"))
            bucket = merged_groups.get(label_key)
            if bucket is None:
                bucket = copy.deepcopy(group)
                bucket["label"] = label
                bucket["values"] = []
                merged_groups[label_key] = bucket
                order.append(label_key)
            bucket["values"] = _merge_string_lists(bucket.get("values"), values)

    base["filter_groups"] = [merged_groups[key] for key in order]

    merged_inference: dict[str, Any] = {}
    left_inference = left.get("work_type_inference")
    right_inference = right.get("work_type_inference")
    if isinstance(left_inference, dict):
        merged_inference.update(copy.deepcopy(left_inference))
    if isinstance(right_inference, dict):
        merged_inference.update(copy.deepcopy(right_inference))

    rules_by_id: dict[str, dict[str, Any]] = {}
    rule_order: list[str] = []
    for source in (left_inference, right_inference):
        if not isinstance(source, dict):
            continue
        rules = source.get("rules")
        if not isinstance(rules, list):
            continue
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            rule_id = _clean_text(rule.get("id"))
            if not rule_id:
                continue
            existing = rules_by_id.get(rule_id)
            if existing is None:
                rules_by_id[rule_id] = copy.deepcopy(rule)
                rule_order.append(rule_id)
                continue
            merged_rule = copy.deepcopy(existing)
            merged_rule.update(copy.deepcopy(rule))
            for list_key in _JOB_TYPE_LIST_KEYS:
                merged_rule[list_key] = _merge_string_lists(existing.get(list_key), rule.get(list_key))
            rules_by_id[rule_id] = merged_rule

    merged_inference["rules"] = [rules_by_id[rule_id] for rule_id in rule_order]
    base["work_type_inference"] = merged_inference
    return base


def _merge_parsing_rules_payloads(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    base = copy.deepcopy(right if right else left)
    left_routing = left.get(KEY_P_ROUTING) if isinstance(left, dict) else None
    right_routing = right.get(KEY_P_ROUTING) if isinstance(right, dict) else None

    if not isinstance(left_routing, dict) and not isinstance(right_routing, dict):
        return base

    merged_routing: dict[str, Any] = {}
    if isinstance(left_routing, dict):
        merged_routing.update(copy.deepcopy(left_routing))
    if isinstance(right_routing, dict):
        merged_routing.update(copy.deepcopy(right_routing))

    for key in _ROUTING_LIST_KEYS:
        merged_routing[key] = _merge_string_lists(
            left_routing.get(key) if isinstance(left_routing, dict) else None,
            right_routing.get(key) if isinstance(right_routing, dict) else None,
            merged_routing.get(key),
        )

    left_default = _clean_text(left_routing.get(KEY_P_ROUTING_DEFAULT)) if isinstance(left_routing, dict) else ""
    right_default = (
        _clean_text(right_routing.get(KEY_P_ROUTING_DEFAULT)) if isinstance(right_routing, dict) else ""
    )
    if right_default:
        merged_routing[KEY_P_ROUTING_DEFAULT] = right_default
    elif left_default:
        merged_routing[KEY_P_ROUTING_DEFAULT] = left_default

    base[KEY_P_ROUTING] = merged_routing
    return base


def _merge_payloads(
    key: str,
    left: Any,
    right: Any,
    *,
    left_updated_at: str,
    right_updated_at: str,
) -> Any:
    if left is None:
        return copy.deepcopy(right)
    if right is None:
        return copy.deepcopy(left)
    if left == right:
        return copy.deepcopy(left)

    if key in {"capability_knowledge", "cv_farming_rules", "hard_blocker_rules"}:
        if isinstance(left, dict) and isinstance(right, dict):
            return _merge_additive_payloads(left, right)
        return copy.deepcopy(right if right_updated_at >= left_updated_at else left)

    if key == "job_type":
        if isinstance(left, dict) and isinstance(right, dict):
            return _merge_job_type_payloads(left, right)
        return copy.deepcopy(right if right_updated_at >= left_updated_at else left)

    if key == "parsing_rules":
        if isinstance(left, dict) and isinstance(right, dict):
            return _merge_parsing_rules_payloads(left, right)
        return copy.deepcopy(right if right_updated_at >= left_updated_at else left)

    return copy.deepcopy(right if right_updated_at >= left_updated_at else left)


def sync_shared_knowledge(
    left_db: Path,
    right_db: Path,
    *,
    keys: Iterable[str] = _SHARED_KNOWLEDGE_KEYS,
) -> list[str]:
    """Merge shared learned knowledge between two databases, writing the result to both."""
    init_db(left_db)
    init_db(right_db)

    updated: list[str] = []
    for key in keys:
        left_payload, left_updated_at = _read_knowledge(left_db, key)
        right_payload, right_updated_at = _read_knowledge(right_db, key)
        merged = _merge_payloads(
            key,
            left_payload,
            right_payload,
            left_updated_at=left_updated_at,
            right_updated_at=right_updated_at,
        )
        if merged is None:
            continue
        if merged != left_payload:
            _write_knowledge(left_db, key, merged)
        if merged != right_payload:
            _write_knowledge(right_db, key, merged)
        if merged != left_payload or merged != right_payload:
            updated.append(key)
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Merge shared learned knowledge between two Job Hunter SQLite databases."
    )
    parser.add_argument("--left-db", required=True, help="First SQLite database path.")
    parser.add_argument("--right-db", required=True, help="Second SQLite database path.")
    args = parser.parse_args(argv)

    left_db = Path(args.left_db).expanduser().resolve()
    right_db = Path(args.right_db).expanduser().resolve()
    changed = sync_shared_knowledge(left_db, right_db)
    print(f"Merged shared knowledge keys: {changed or '(none - already in sync)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
