import re
from collections import defaultdict
from typing import Any


SKILL_CATALOG = [
    "Salesforce",
    "HubSpot",
    "HubSpot CRM",
    "ServiceNow",
    "Workday",
    "SAP",
    "Oracle",
    "Pega",
    "D365",
    "Dynamics 365",
    "Snowflake",
    "Azure Data Factory",
    "SQL",
    "SQL Server",
    "Power BI",
    "Tableau",
    "ETL",
    "Data governance",
    "Data lineage",
    "Data quality",
    "Data warehousing",
    "Data modelling",
    "Workforce management",
    "Payroll",
    "HCM",
    "Human resources",
    "HR",
    "API",
    "REST API",
    "Postman",
    "AWS",
    "Azure",
    "GCP",
    "BPMN",
    "Jira",
    "Confluence",
    "SharePoint",
    "UAT",
    "Gherkin",
]


def _normalize_term(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").strip().lower()).strip()


def _collect_known_terms(profile: dict[str, Any]) -> set[str]:
    known_terms = set()
    for skill in profile.get("must_not_require_skills", []):
        normalized = _normalize_term(str(skill))
        if normalized:
            known_terms.add(normalized)

    for rule in profile.get("capability_profile_rules", []):
        normalized_name = _normalize_term(str(rule.get("name") or ""))
        if normalized_name:
            known_terms.add(normalized_name)
        for alias in rule.get("aliases", []):
            normalized_alias = _normalize_term(str(alias))
            if normalized_alias:
                known_terms.add(normalized_alias)
    return known_terms


def extract_detected_skills(details_text: str) -> list[str]:
    text = details_text or ""
    found = []
    lowered = text.lower()
    for term in SKILL_CATALOG:
        normalized_term = _normalize_term(term)
        if not normalized_term:
            continue
        pattern = rf"(?<!\w){re.escape(normalized_term)}(?!\w)"
        if re.search(pattern, _normalize_term(lowered)):
            found.append(term)
    return sorted(set(found), key=lambda item: item.lower())


def build_unknown_skill_review(skill_observations: list[dict], profile: dict[str, Any]) -> list[dict]:
    known_terms = _collect_known_terms(profile)
    grouped: dict[str, dict[str, Any]] = {}

    for observation in skill_observations:
        term = str(observation.get("skill") or "").strip()
        normalized = _normalize_term(term)
        if not term or not normalized or normalized in known_terms:
            continue
        entry = grouped.setdefault(
            normalized,
            {
                "skill": term,
                "count": 0,
                "examples": [],
            },
        )
        entry["count"] += 1
        if len(entry["examples"]) < 3:
            entry["examples"].append(
                {
                    "title": observation.get("title"),
                    "company": observation.get("company"),
                    "url": observation.get("url"),
                    "search_location": observation.get("search_location"),
                }
            )

    return sorted(grouped.values(), key=lambda item: (-item["count"], item["skill"].lower()))


def build_rejection_review(audit_rows: list[dict]) -> list[dict]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in audit_rows:
        decision = row.get("decision")
        reason = row.get("reject_reason")
        if decision == "KEEP" or not reason:
            continue
        entry = grouped.setdefault(
            reason,
            {
                "reason": reason,
                "count": 0,
                "samples": [],
            },
        )
        entry["count"] += 1
        if len(entry["samples"]) < 4:
            entry["samples"].append(
                {
                    "title": row.get("title"),
                    "company": row.get("company"),
                    "url": row.get("url"),
                    "search_location": row.get("search_location"),
                    "location": row.get("location"),
                }
            )

    return sorted(grouped.values(), key=lambda item: (-item["count"], item["reason"]))


def build_review_data(audit_rows: list[dict], skill_observations: list[dict], profile: dict[str, Any]) -> dict:
    return {
        "unknown_skills": build_unknown_skill_review(skill_observations, profile),
        "rejections_by_reason": build_rejection_review(audit_rows),
    }


def apply_skill_review_decisions(profile: dict[str, Any], decisions: list[dict[str, str]]) -> dict[str, Any]:
    capability_rules = list(profile.get("capability_profile_rules", []))
    existing_index = {
        _normalize_term(str(rule.get("name") or "")): idx
        for idx, rule in enumerate(capability_rules)
        if _normalize_term(str(rule.get("name") or ""))
    }

    for item in decisions:
        skill = str(item.get("skill") or "").strip()
        choice = str(item.get("choice") or "").strip().lower()
        normalized = _normalize_term(skill)
        if not normalized or not choice:
            continue

        if choice in {"no_knowledge", "avoid"}:
            level = "none"
            fit = "avoid"
        elif choice == "basic_only":
            level = "basic"
            fit = "contextual"
        elif choice == "working_knowledge":
            level = "working"
            fit = "supporting"
        elif choice == "strong":
            level = "strong"
            fit = "supporting"
        elif choice == "not_core_but_acceptable":
            level = "working"
            fit = "contextual"
        else:
            continue

        rule = {
            "name": skill,
            "level": level,
            "fit": fit,
            "aliases": [skill],
        }

        if normalized in existing_index:
            capability_rules[existing_index[normalized]] = rule
        else:
            capability_rules.append(rule)

    profile["capability_profile_rules"] = capability_rules
    return profile
