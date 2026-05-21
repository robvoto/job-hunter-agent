from __future__ import annotations


def format_log_block(title: str, fields: dict[str, object]) -> str:
    lines = [f"[{title}]"]
    for key, value in fields.items():
        lines.append(f"  {key}: {value}")
    return "\n".join(lines)
