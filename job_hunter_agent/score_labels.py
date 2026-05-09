from typing import List, Optional

from job_hunter_agent.match_labels import score_to_match_label, score_to_match_level
from job_hunter_agent.preferences import salary_fit_adjustment
from job_hunter_agent.io_utils import load_ui_labels
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
    if "contract" in label.lower() or "permanent" in label.lower():
        return "Engagement"
    if "government" in label.lower():
        return "Government"
    if "remote" in label.lower() or "hybrid" in label.lower() or label == "On-site role":
        return "Work mode"
    return label


def format_score_breakdown_for_console(breakdown: List[dict]) -> str:
    return " | ".join(
        f"{compact_score_label(str(item.get('label', '')))} {int(item.get('value', 0)):+d}"
        for item in breakdown
    )


def render_badge(label: str, class_name: str, explanation: str) -> str:
    return (
        f'<span class="badge {safe_html(class_name)}" title="{safe_html(explanation)}" '
        f'aria-label="{safe_html(explanation)}">{safe_html(label)}</span>'
    )


def viewed_badge_html() -> str:
    return render_badge("Viewed", "badge-viewed", "You have already opened this role from the dashboard.")
