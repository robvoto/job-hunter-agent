"""Profile learning helpers.

Main goals:
- repair imported text
- extract summaries, strengths, notes, and capability rules from human material
- provide a local knowledge-note fallback for profile enrichment

Notes:
- capability_profile.txt is a local editable knowledge note
- capability_profile.template.txt is the committed starter template for new users
"""

import json
import re
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"


def repair_text(text: str) -> str:
    if not text:
        return ""
    repaired = text.replace("\r\n", "\n")
    if "â" in repaired or "Ã" in repaired:
        try:
            candidate = repaired.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
            if candidate.count("â") < repaired.count("â"):
                repaired = candidate
        except Exception:
            pass
    replacements = {
        "\u2014": "-",
        "\u2013": "-",
        "\u2192": "->",
    }
    for source, target in replacements.items():
        repaired = repaired.replace(source, target)
    return repaired.strip()


def _find_rating(text: str) -> float | None:
    match = re.search(r"Level:\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*10", text, flags=re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1))


def _level_from_rating(rating: float | None) -> str:
    if rating is None:
        return "basic"
    if rating >= 8.0:
        return "strong"
    if rating >= 6.0:
        return "working"
    if rating >= 4.5:
        return "basic"
    if rating > 0:
        return "low"
    return "none"


def _extract_section(text: str, header: str) -> str:
    pattern = rf"##\s+{re.escape(header)}\s*\n(.*?)(?=\n##\s+|\Z)"
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_subsection(text: str, header: str) -> str:
    pattern = rf"###\s+{re.escape(header)}\s*\n(.*?)(?=\n###\s+|\n##\s+|\Z)"
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_named_section(text: str, header: str) -> str:
    return _extract_subsection(text, header) or _extract_section(text, header)


def _extract_bullets(text: str) -> list[str]:
    return [match.strip() for match in re.findall(r"^\*\s+(.+)$", text, flags=re.MULTILINE)]


def _clean_sentence(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" -\n")


_VALID_LEVELS = {"strong", "working", "basic", "low", "none"}
_VALID_FITS = {"core", "supporting", "contextual", "avoid"}


def _parse_capabilities(source_text: str) -> list[dict[str, Any]]:
    """Extract capability rules from any CV using the LLM.

    Works for any profession and CV format — no hardcoded headings.
    Returns [] if LLM is unavailable (no API key); caller handles the fallback.
    """
    from llm_gate import client, _get_llm_model, MAX_TOKENS_CV_EXTRACTION

    if client is None:
        print("[CAPABILITIES] Skipped — no LLM client (OPENAI_API_KEY not set)")
        return []
    if not (source_text or "").strip():
        return []

    prompt = (
        "Read this CV and extract the candidate's professional capabilities.\n\n"
        "Return a JSON array. Each item must have exactly these keys:\n"
        '  "name"    — short capability label in lowercase (e.g. "business analysis", "python development")\n'
        '  "level"   — one of: strong | working | basic | low | none\n'
        '              (based on recency and depth of use, not just whether it appears)\n'
        '  "fit"     — one of: core | supporting | contextual | avoid\n'
        '              core = daily job, supporting = used regularly, contextual = occasionally, avoid = not wanted\n'
        '  "aliases" — list of 4–10 lowercase phrases a job ad would use for this skill\n\n'
        "Rules:\n"
        "- Include 6–15 capabilities that represent the full professional picture\n"
        "- Aliases must be job-ad language, not CV language (e.g. 'stakeholder management' not 'managed stakeholders')\n"
        "- Do NOT include soft skills (communication, teamwork) — only professional capabilities\n"
        "- Only return the JSON array, no explanation\n\n"
        "CV:\n" + source_text[:5000]
    )

    try:
        resp = client.responses.create(
            model=_get_llm_model(),
            input=[{"role": "user", "content": prompt}],
            max_output_tokens=MAX_TOKENS_CV_EXTRACTION,
        )
        raw = (resp.output_text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        items = json.loads(raw)
        if not isinstance(items, list):
            print(f"[CAPABILITIES] LLM returned non-list: {type(items)}")
            return []

        result: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip().lower()
            level = str(item.get("level") or "").strip().lower()
            fit = str(item.get("fit") or "").strip().lower()
            aliases = [
                str(a).strip().lower()
                for a in (item.get("aliases") or [])
                if str(a).strip()
            ]
            if not name or level not in _VALID_LEVELS or fit not in _VALID_FITS:
                continue
            result.append({"name": name, "level": level, "fit": fit, "aliases": aliases[:10]})

        print(f"[CAPABILITIES] Extracted {len(result)} capability rules via LLM")
        return result[:15]

    except Exception as exc:
        print(f"[CAPABILITIES] LLM extraction failed: {exc}")
        return []


def _parse_summary(source_text: str) -> str:
    experience = _extract_section(source_text, "EXPERIENCE SUMMARY (REALITY BASELINE)")
    roles = _extract_bullets(_extract_section(source_text, "EXPERIENCE SUMMARY (REALITY BASELINE)"))
    primary_strength_match = re.search(r"Primary strength:\s*(.+)", _extract_section(source_text, "CORE STRENGTH IDENTITY"), flags=re.IGNORECASE)
    years_match = re.search(r"Years in IT:\s*([^\n]+)", experience, flags=re.IGNORECASE)

    parts = []
    if years_match:
        parts.append(f"{_clean_sentence(years_match.group(1))} in IT")
    if roles:
        parts.append("Primary roles: " + ", ".join(roles[:3]))
    if primary_strength_match:
        parts.append(_clean_sentence(primary_strength_match.group(1)).replace("->", "").replace(">", ""))
    return ". ".join(part.strip(". ") for part in parts if part).strip()




def build_learning_patch(text: str) -> dict[str, Any]:
    source_text = repair_text(text)
    if not source_text:
        return {}

    patch: dict[str, Any] = {
        "cv_text": source_text,
    }

    summary = _parse_summary(source_text)
    if summary:
        patch["candidate_summary"] = summary

    capability_rules = _parse_capabilities(source_text)
    if capability_rules:
        patch["capability_profile_rules"] = capability_rules

    return patch


def merge_capability_rules(existing: list[dict[str, Any]], learned: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for rule in existing or []:
        name = str(rule.get("name") or "").strip().lower()
        if name:
            merged[name] = dict(rule)
    for rule in learned or []:
        name = str(rule.get("name") or "").strip().lower()
        if name:
            merged[name] = dict(rule)
    return list(merged.values())
