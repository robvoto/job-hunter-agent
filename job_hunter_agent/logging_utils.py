"""Helpers for logging utils."""

from __future__ import annotations


def format_log_block(title: str, fields: dict[str, object]) -> str:
    if not fields:
        return f"[{title}]"
    width = max(len(k) for k in fields)
    lines = [f"[{title}]"]
    for key, value in fields.items():
        lines.append(f"  {key:<{width}} = {value}")
    return "\n".join(lines)
