"""Helpers for score labels."""

from typing import List, Optional

from job_hunter_agent.match_labels import score_to_match_level
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


_SECTION_ORDER = [
    "requirement_fit",
    "requirement_fit_warning",
    "risk",
]
_SECTION_NAMES = {
    "requirement_fit": "Requirement Fit",
    "requirement_fit_warning": "Warnings",
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

        if key in {"requirement_fit_warning", "risk"}:
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
