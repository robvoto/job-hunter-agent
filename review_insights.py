import re
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


def _friendly_reason_suffix(value: str) -> str:
    cleaned = str(value or "").replace("_", " ").strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else ""


def _capability_rule_lookup(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for rule in profile.get("capability_profile_rules", []):
        if not isinstance(rule, dict):
            continue
        aliases = [rule.get("name"), *(rule.get("aliases") or [])]
        for alias in aliases:
            normalized = _normalize_term(str(alias))
            if normalized:
                lookup[normalized] = rule
    return lookup


def _capability_rule_index_lookup(capability_rules: list[dict[str, Any]]) -> dict[str, int]:
    lookup: dict[str, int] = {}
    for idx, rule in enumerate(capability_rules):
        if not isinstance(rule, dict):
            continue
        aliases = [rule.get("name"), *(rule.get("aliases") or [])]
        for alias in aliases:
            normalized = _normalize_term(str(alias))
            if normalized:
                lookup[normalized] = idx
    return lookup


def _choice_label(choice: str) -> str:
    labels = {
        "no_knowledge": "No knowledge",
        "basic_only": "Basic only",
        "working_knowledge": "Working knowledge",
        "strong": "Strong",
        "avoid": "Avoid",
        "not_core_but_acceptable": "Not core but acceptable",
    }
    return labels.get(choice, choice.replace("_", " ").strip().title())


def _current_rule_label(rule: dict[str, Any] | None) -> str:
    if not isinstance(rule, dict):
        return "Unclassified"
    level = str(rule.get("level") or "").strip().lower()
    fit = str(rule.get("fit") or "").strip().lower()
    if not level and not fit:
        return "Unclassified"
    parts = []
    if fit:
        parts.append(fit)
    if level:
        parts.append(level)
    return " / ".join(parts)


def build_capability_tuning_suggestions(
    skill_observations: list[dict],
    audit_rows: list[dict],
    profile: dict[str, Any],
) -> list[dict]:
    row_by_url = {
        str(row.get("url") or "").strip(): row
        for row in audit_rows
        if str(row.get("url") or "").strip()
    }
    rule_lookup = _capability_rule_lookup(profile)
    grouped: dict[str, dict[str, Any]] = {}

    for observation in skill_observations:
        url = str(observation.get("url") or "").strip()
        row = row_by_url.get(url)
        if not isinstance(row, dict) or row.get("decision") != "KEEP":
            continue

        skill = str(observation.get("skill") or "").strip()
        normalized = _normalize_term(skill)
        if not normalized:
            continue

        entry = grouped.setdefault(
            normalized,
            {
                "skill": skill,
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

    suggestions: list[dict[str, Any]] = []
    for normalized, entry in grouped.items():
        count = int(entry["count"] or 0)
        if count < 2:
            continue

        current_rule = rule_lookup.get(normalized)
        current_fit = str((current_rule or {}).get("fit") or "").strip().lower()
        current_level = str((current_rule or {}).get("level") or "").strip().lower()
        skill = str(entry["skill"] or normalized).strip()

        if current_rule:
            # Already classified — skip regardless of level/fit.
            # Once a user confirms a skill, don't keep nudging them to upgrade it.
            continue
        if count >= 5:
            recommended_choice = "working_knowledge"
        else:
            recommended_choice = "not_core_but_acceptable"
        headline = f"Classify {skill} as a known capability signal"
        detail = f"Seen in {count} kept role(s) and still unclassified."

        suggestions.append(
            {
                "kind": "capability",
                "skill": skill,
                "count": count,
                "headline": headline,
                "detail": detail,
                "target": "Capability matrix",
                "recommended_choice": recommended_choice,
                "recommended_label": _choice_label(recommended_choice),
                "current_treatment": _current_rule_label(current_rule),
                "examples": entry["examples"],
            }
        )

    return sorted(
        suggestions,
        key=lambda item: (-int(item["count"]), str(item["skill"]).lower()),
    )


def _build_rule_tuning_suggestions_from_reviews(review_items: list[dict[str, Any]]) -> list[dict]:
    suggestions: list[dict[str, Any]] = []
    for item in review_items:
        reason = str(item.get("reason") or "").strip()
        count = int(item.get("count") or 0)
        samples = item.get("samples") or []
        if reason == "TITLE_NOT_TARGET":
            if count < 20:
                continue
            suggestions.append(
                {
                    "kind": "rule",
                    "reason": reason,
                    "count": count,
                    "headline": "Broad capture is producing a lot of non-target titles",
                    "detail": f"{count} roles were filtered by title before deeper review.",
                    "target": "Search keywords and title matching",
                    "recommendation": "Keep search broad unless deeper review volume rises. Tighten title rules before tightening search keywords.",
                    "samples": samples,
                }
            )
            continue

        prefix, _, suffix = reason.partition(":")
        if prefix == "CARD_SPECIALIST" and count >= 2:
            domain = _friendly_reason_suffix(suffix)
            suggestions.append(
                {
                    "kind": "rule",
                    "reason": reason,
                    "count": count,
                    "headline": f"Specialist {domain.lower()} roles are being filtered early",
                    "detail": f"{count} role(s) looked specialist-heavy enough to stop at the card gate.",
                    "target": "Specialist reject signals",
                    "recommendation": "Keep or refine this specialist-domain block if these remain off-target.",
                    "samples": samples,
                }
            )
        elif prefix == "DESC_CAPABILITY_LOW" and count >= 2:
            area = _friendly_reason_suffix(suffix)
            suggestions.append(
                {
                    "kind": "rule",
                    "reason": reason,
                    "count": count,
                    "headline": f"Low-fit specialist area repeated: {area}",
                    "detail": f"{count} role(s) leaned heavily into this capability track.",
                    "target": "Capability matrix or description exclusions",
                    "recommendation": "Keep this area as contextual or avoid, and strengthen exclusions only if the noise keeps repeating.",
                    "samples": samples,
                }
            )
        elif prefix == "TITLE_BAD_KEYWORD" and count >= 2:
            keyword = _friendly_reason_suffix(suffix)
            suggestions.append(
                {
                    "kind": "rule",
                    "reason": reason,
                    "count": count,
                    "headline": f"Title keyword filter is doing useful work: {keyword}",
                    "detail": f"{count} role(s) were blocked by this title keyword.",
                    "target": "Reject title rules",
                    "recommendation": "Keep this exclusion. Only widen it if close variants keep leaking through.",
                    "samples": samples,
                }
            )
        elif prefix == "DESC_MANDATORY_SKILL" and count >= 2:
            skill = _friendly_reason_suffix(suffix)
            suggestions.append(
                {
                    "kind": "rule",
                    "reason": reason,
                    "count": count,
                    "headline": f"Mandatory skill signal repeated: {skill}",
                    "detail": f"{count} role(s) required {skill} strongly enough to reject.",
                    "target": "Mandatory skills you do not have",
                    "recommendation": "Add this only if it becomes a recurring blocker for otherwise relevant roles.",
                    "samples": samples,
                }
            )

    return suggestions


def build_rule_tuning_suggestions(audit_rows: list[dict]) -> list[dict]:
    return _build_rule_tuning_suggestions_from_reviews(build_rejection_review(audit_rows))


def build_suggested_tuning(
    audit_rows: list[dict],
    skill_observations: list[dict],
    profile: dict[str, Any],
) -> dict[str, Any]:
    capability_suggestions = build_capability_tuning_suggestions(skill_observations, audit_rows, profile)
    rule_suggestions = build_rule_tuning_suggestions(audit_rows)
    return {
        "summary": {
            "capability_count": len(capability_suggestions),
            "rule_count": len(rule_suggestions),
        },
        "capability_suggestions": capability_suggestions,
        "rule_suggestions": rule_suggestions,
    }


def build_suggested_tuning_from_saved_review(payload: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    kept_job_urls = {
        str(value).strip()
        for value in payload.get("kept_job_urls", [])
        if str(value).strip()
    }
    audit_rows = [{"url": url, "decision": "KEEP"} for url in sorted(kept_job_urls)]
    skill_observations = [
        item for item in payload.get("skill_observations", [])
        if isinstance(item, dict)
    ]
    capability_suggestions = build_capability_tuning_suggestions(skill_observations, audit_rows, profile)
    rule_reviews = [
        item for item in payload.get("rejections_by_reason", [])
        if isinstance(item, dict)
    ]
    rule_suggestions = _build_rule_tuning_suggestions_from_reviews(rule_reviews)
    return {
        "summary": {
            "capability_count": len(capability_suggestions),
            "rule_count": len(rule_suggestions),
        },
        "capability_suggestions": capability_suggestions,
        "rule_suggestions": rule_suggestions,
    }


def build_review_data(audit_rows: list[dict], skill_observations: list[dict], profile: dict[str, Any]) -> dict:
    kept_job_urls = sorted(
        {
            str(row.get("url") or "").strip()
            for row in audit_rows
            if row.get("decision") == "KEEP" and str(row.get("url") or "").strip()
        }
    )
    return {
        "suggested_tuning": build_suggested_tuning(audit_rows, skill_observations, profile),
        "kept_job_urls": kept_job_urls,
        "skill_observations": skill_observations,
        "unknown_skills": build_unknown_skill_review(skill_observations, profile),
        "rejections_by_reason": build_rejection_review(audit_rows),
    }

def _default_aliases_for_skill(skill: str) -> list[str]:
    skill_clean = str(skill or "").strip()
    normalized = _normalize_term(skill_clean)

    alias_map = {
        "data modelling": ["data modeling", "logical data model"],
        "power bi": ["powerbi"],
        "bpmn": ["business process modelling", "process modeling"],
        "sql server": ["microsoft sql server"],
        "rest api": ["rest apis", "api integration"],
    }

    aliases = alias_map.get(normalized, [])
    deduped: list[str] = []
    for alias in aliases:
        cleaned = str(alias).strip()
        if not cleaned:
            continue
        if _normalize_term(cleaned) == normalized:
            continue
        if cleaned not in deduped:
            deduped.append(cleaned)
    return deduped

def apply_capability_tuning_decisions(profile: dict[str, Any], decisions: list[dict[str, str]]) -> dict[str, Any]:
    capability_rules = list(profile.get("capability_profile_rules", []))
    existing_index = _capability_rule_index_lookup(capability_rules)

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
            "aliases": _default_aliases_for_skill(skill),
        }

        if normalized in existing_index:
            existing_rule = capability_rules[existing_index[normalized]]
            merged_aliases: list[str] = []
            canonical_name = str(existing_rule.get("name") or skill).strip() or skill
            canonical_name_norm = _normalize_term(canonical_name)

            for alias in (existing_rule.get("aliases") or []):
                cleaned_alias = str(alias or "").strip()
                if not cleaned_alias:
                    continue
                if _normalize_term(cleaned_alias) == canonical_name_norm:
                    continue
                if cleaned_alias not in merged_aliases:
                    merged_aliases.append(cleaned_alias)

            capability_rules[existing_index[normalized]] = {
                "name": canonical_name,
                "level": level,
                "fit": fit,
                "aliases": merged_aliases,
            }
        else:
            capability_rules.append(rule)
            existing_index[normalized] = len(capability_rules) - 1

    profile["capability_profile_rules"] = capability_rules
    return profile


def apply_skill_review_decisions(profile: dict[str, Any], decisions: list[dict[str, str]]) -> dict[str, Any]:
    return apply_capability_tuning_decisions(profile, decisions)
