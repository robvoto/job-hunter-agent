"""Helpers for score labels."""

from typing import List, Optional

from job_hunter_agent.io_utils import load_ui_labels
from job_hunter_agent.match_labels import score_to_match_label, score_to_match_level
from job_hunter_agent.preferences import salary_fit_adjustment
from job_hunter_agent.profile_store import get_match_levels, load_profile
from job_hunter_agent.text_processing import compact_whitespace
from job_hunter_agent.utils import safe_html


def salary_fit_label(record: dict, profile: Optional[dict] = None) -> str:

    salary_text = str(record.get("salary") or "").strip()

    if not salary_text or salary_text == "N/A":
        return "missing"

    adjustment = salary_fit_adjustment(record, profile)

    if adjustment > 0:
        return "meets"

    if adjustment < 0:
        return "below"

    return "listed"


def score_to_tone_class(score: int, profile: Optional[dict] = None) -> str:

    match_levels = get_match_levels(profile or load_profile())

    match_level = score_to_match_level(score, match_levels)

    if match_levels and match_level == match_levels[0]:
        return "tone-strong"

    if len(match_levels) > 1 and match_level == match_levels[1]:
        return "tone-good"

    if len(match_levels) > 2 and match_level == match_levels[2]:
        return "tone-borderline"

    return "tone-low"


def compact_score_label(label: str) -> str:

    rules = load_ui_labels()

    direct_map = rules.get("core_label_compact_map", {})

    if label in direct_map:
        return direct_map[label]

    if label.startswith("Posted within") or label == "Still relatively recent":
        return "Freshness"

    if "location" in label.lower() or "onsite" in label.lower() or "travel" in label.lower():
        return "Location"

    if label.startswith("Competitive signal"):
        return "Competitive"

    if label.startswith("Work type") or "contract" in label.lower() or "permanent" in label.lower():
        return "Work type"

    if (
        label.startswith("Sector")
        or "government" in label.lower()
        or "public sector" in label.lower()
        or "private sector" in label.lower()
    ):
        return "Sector"

    if label.startswith("Work mode") or "remote" in label.lower() or "hybrid" in label.lower():
        return "Work mode"

    return label


def format_score_breakdown_for_console(breakdown: List[dict]) -> str:

    return " | ".join(
        f"{compact_score_label(str(item.get('label', '')))} {int(item.get('value', 0)):+d}"
        for item in breakdown
    )


_SECTION_ORDER = [
    "title",
    "llm_fit",
    "content",
    "capability",
    "location",
    "work_type",
    "work_mode",
    "salary",
    "freshness",
    "risk",
]
_SECTION_NAMES = {
    "title": "Title match",
    "llm_fit": "LLM fit",
    "content": "Content",
    "capability": "Capabilities",
    "location": "Location",
    "work_type": "Work type",
    "work_mode": "Work mode",
    "salary": "Salary / rate",
    "freshness": "Freshness",
    "risk": "Blockers",
}


def format_score_breakdown_console(breakdown: List[dict]) -> List[str]:
    """Format breakdown as a numbered block for console output."""
    by_section: dict[str, list[dict]] = {s: [] for s in _SECTION_ORDER}
    for entry in breakdown:
        section = str(entry.get("section") or "")
        if section in by_section:
            by_section[section].append(entry)

    lines: list[str] = ["  Score breakdown:", "  " + "─" * 70]
    display_index = 0
    for key in _SECTION_ORDER:
        cat = _SECTION_NAMES[key]
        entries = by_section[key]

        if key == "capability":
            credited = [e for e in entries if int(e.get("value") or 0) > 0]
            total = sum(int(e.get("value") or 0) for e in entries)
            count = len(credited)
            if count == 0:
                continue
            display_index += 1
            detail = f"{count} match{'es' if count != 1 else ''} found"
            lines.append(f"  {display_index:2d}. {cat:<14}  {detail:<40}  {total:+d}")
        elif key == "risk":
            display_index += 1
            if not entries:
                lines.append(f"  {display_index:2d}. {cat:<14}  —")
            else:
                for entry in entries:
                    raw = str(entry.get("label") or "")
                    detail = raw[:55] + "…" if len(raw) > 55 else raw
                    lines.append(
                        f"  {display_index:2d}. {cat:<14}  {detail:<40}  {int(entry.get('value') or 0):+d}"
                    )
        elif key == "salary" and entries and int(entries[0].get("value") or 0) == 0:
            display_index += 1
            lines.append(f"  {display_index:2d}. {cat:<14}  {entries[0].get('label', '—'):<40}   —")
        elif not entries:
            display_index += 1
            lines.append(f"  {display_index:2d}. {cat:<14}  —")
        else:
            display_index += 1
            total = sum(int(e.get("value") or 0) for e in entries)
            raw = str(entries[0].get("label") or "")
            detail = raw[:55] + "…" if len(raw) > 55 else raw
            lines.append(f"  {display_index:2d}. {cat:<14}  {detail:<40}  {total:+d}")

    lines.append("  " + "─" * 70)
    return lines


def render_badge(label: str, class_name: str, explanation: str) -> str:

    return (
        f'<span class="badge {safe_html(class_name)}" title="{safe_html(explanation)}" '
        f'aria-label="{safe_html(explanation)}">{safe_html(label)}</span>'
    )


def viewed_badge_html() -> str:

    return render_badge(
        "Viewed", "badge-viewed", "You have already opened this role from the workspace."
    )
