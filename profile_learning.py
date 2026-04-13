import re
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
LOCAL_KNOWLEDGE_FILE = DATA_DIR / "capability_profile.txt"
KNOWLEDGE_TEMPLATE_FILE = DATA_DIR / "capability_profile.template.txt"
LEGACY_KNOWLEDGE_FILE = DATA_DIR / "rob_capability_profile.txt"
DEFAULT_KNOWLEDGE_FILE = LOCAL_KNOWLEDGE_FILE


def resolve_knowledge_file(create_if_missing: bool = False) -> Path:
    for candidate in [LOCAL_KNOWLEDGE_FILE, LEGACY_KNOWLEDGE_FILE]:
        if candidate.exists():
            return candidate

    if create_if_missing and KNOWLEDGE_TEMPLATE_FILE.exists():
        LOCAL_KNOWLEDGE_FILE.write_text(
            KNOWLEDGE_TEMPLATE_FILE.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return LOCAL_KNOWLEDGE_FILE

    if KNOWLEDGE_TEMPLATE_FILE.exists():
        return KNOWLEDGE_TEMPLATE_FILE

    return LOCAL_KNOWLEDGE_FILE


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


def _parse_capabilities(source_text: str) -> list[dict[str, Any]]:
    capabilities: list[dict[str, Any]] = []

    mapping = [
        (
            "BUSINESS ANALYSIS CAPABILITY (REAL CORE)",
            {
                "name": "business analysis delivery",
                "fit": "core",
                "aliases": [
                    "requirements elicitation",
                    "requirements gathering",
                    "process mapping",
                    "stakeholder engagement",
                    "workshops",
                    "user stories",
                    "acceptance criteria",
                    "business rules",
                    "workflow",
                    "workflows",
                    "uat",
                ],
            },
        ),
        (
            "STAKEHOLDER MANAGEMENT",
            {
                "name": "stakeholder management",
                "fit": "core",
                "aliases": [
                    "stakeholder engagement",
                    "stakeholder management",
                    "workshops",
                    "executives",
                    "vendors",
                    "communication style",
                ],
            },
        ),
        (
            "BPMN / PROCESS MODELLING",
            {
                "name": "bpmn and process modelling",
                "fit": "core",
                "aliases": [
                    "bpmn",
                    "process modelling",
                    "process mapping",
                    "workflow",
                    "workflows",
                    "as-is",
                    "to-be",
                ],
            },
        ),
        (
            "AGILE / DELIVERY",
            {
                "name": "agile delivery",
                "fit": "supporting",
                "aliases": [
                    "agile",
                    "user stories",
                    "acceptance criteria",
                    "gherkin",
                    "backlog refinement",
                    "sprint",
                    "uat",
                ],
            },
        ),
        (
            "APIs / Integration",
            {
                "name": "api and integration",
                "fit": "supporting",
                "aliases": [
                    "api",
                    "apis",
                    "rest api",
                    "json",
                    "postman",
                    "integration",
                    "integrations",
                    "api payload",
                ],
            },
        ),
        (
            "SQL / DATA",
            {
                "name": "data analysis and validation",
                "fit": "supporting",
                "aliases": [
                    "sql",
                    "excel",
                    "data mapping",
                    "data validation",
                    "data migration",
                    "database queries",
                    "query databases",
                ],
            },
        ),
        (
            "SYSTEM / TECHNICAL UNDERSTANDING",
            {
                "name": "system and technical analysis",
                "fit": "supporting",
                "aliases": [
                    "system behaviour",
                    "validation rules",
                    "processing logic",
                    "frontend",
                    "backend",
                    "data flows",
                    "system architecture",
                ],
            },
        ),
        (
            "CLOUD / INFRASTRUCTURE",
            {
                "name": "cloud and infrastructure",
                "fit": "contextual",
                "aliases": [
                    "aws",
                    "cloud",
                    "networking",
                    "infrastructure",
                ],
            },
        ),
        (
            "AI / INNOVATION (DIFFERENTIATOR)",
            {
                "name": "ai innovation and automation",
                "fit": "supporting",
                "aliases": [
                    "ai use cases",
                    "python",
                    "playwright",
                    "llm",
                    "automation",
                ],
            },
        ),
    ]

    for heading, template in mapping:
        section = _extract_named_section(source_text, heading)
        if not section:
            continue
        rating = _find_rating(section)
        entry = dict(template)
        entry["level"] = _level_from_rating(rating)
        if heading == "APIs / Integration":
            entry["level"] = "basic"
            entry["fit"] = "contextual"
        capabilities.append(entry)

    if _extract_named_section(source_text, "SQL / DATA"):
        capabilities.append(
            {
                "name": "advanced data analytics and bi",
                "level": "low",
                "fit": "contextual",
                "aliases": [
                    "data warehousing",
                    "etl",
                    "data modelling",
                    "power bi",
                    "tableau",
                    "snowflake",
                    "azure data factory",
                    "data governance",
                    "data quality",
                    "data lineage",
                ],
            }
        )

    return capabilities


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


def _parse_strengths(source_text: str) -> list[str]:
    strengths: list[str] = []
    for heading in [
        "BUSINESS ANALYSIS CAPABILITY (REAL CORE)",
        "STAKEHOLDER MANAGEMENT",
        "BPMN / PROCESS MODELLING",
        "AGILE / DELIVERY",
    ]:
        section = _extract_named_section(source_text, heading)
        strengths.extend(_extract_bullets(section))
    seen = set()
    result = []
    for item in strengths:
        cleaned = _clean_sentence(item)
        normalized = cleaned.lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(cleaned)
    return result[:20]


def _parse_notes(source_text: str) -> list[str]:
    notes: list[str] = []
    for heading in [
        "DELIVERY CONTEXT STRENGTH",
        "HOW TO POSITION (FOR AI)",
        "HARD RULES FOR AI",
        "CONFIDENCE SUMMARY",
    ]:
        section = _extract_section(source_text, heading)
        notes.extend(_extract_bullets(section))
    extra_lines = []
    for label in ["KNOWN RISK:", "LIMITS:", "WEAKER FIT:"]:
        for match in re.findall(rf"{re.escape(label)}\s*(.+)", source_text, flags=re.IGNORECASE):
            extra_lines.append(_clean_sentence(match))
    notes.extend(extra_lines)

    seen = set()
    result = []
    for item in notes:
        cleaned = _clean_sentence(item)
        normalized = cleaned.lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(cleaned)
    return result[:25]


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

    strengths = _parse_strengths(source_text)
    if strengths:
        patch["strengths"] = strengths

    capability_rules = _parse_capabilities(source_text)
    if capability_rules:
        patch["capability_profile_rules"] = capability_rules

    notes = _parse_notes(source_text)
    if notes:
        patch["llm_prompt_notes"] = notes

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
