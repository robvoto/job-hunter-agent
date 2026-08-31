"""Source document processing and onboarding orchestration.

This module handles the extraction of text from source files (such as CVs
in .docx or .txt format) and coordinates the multi-step onboarding process
to build an initial candidate profile. It manages the persistence of
uploaded source packs and ensures clean resets for fresh onboarding runs.
"""

import base64
import copy
import json
import logging
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from job_hunter_agent.global_settings import (
    get_cv_chars_per_page,
)
from job_hunter_agent.logging_utils import format_log_block
from job_hunter_agent.paths import (
    REPO_ROOT,
)
from job_hunter_agent.profile_learning import (
    build_role_history_patch,
    build_learning_patch,
    repair_text,
)
from job_hunter_agent.profile_store import (
    DEFAULT_ONBOARDING_SETTINGS,
    DEFAULT_PROFILE,
    KEY_CANDIDATE_CAPABILITIES,
    KEY_CANDIDATE_ELIGIBILITY,
    KEY_CANDIDATE_QUALIFICATIONS,
    KEY_CV_MAX_PAGES,
    KEY_EVIDENCE_TIERS,
    KEY_MUST_NOT_REQUIRED_SKILLS,
    KEY_ONBOARDING_COMPLETE,
    KEY_PRIMARY_PATTERNS,
    KEY_ROLE_EXPERIENCE,
    KEY_SECONDARY_PATTERNS,
    build_candidate_profile_tiers_from_sections,
    load_profile,
    normalize_engagement_type_preferences,
    patch_profile,
)
from job_hunter_agent.profile_learning import ROLE_SUGGESTIONS_KEY

logger = logging.getLogger(__name__)


ROOT_DIR = REPO_ROOT

# Fields reset to DEFAULT_PROFILE values at the start of every onboarding run.
# Role selections are intentionally excluded: they are confirmed user intent and
# remain authoritative until the review confirm endpoint explicitly replaces them.
ONBOARDING_RESET_FIELDS = (
    KEY_CANDIDATE_CAPABILITIES,
    KEY_ONBOARDING_COMPLETE,
    KEY_EVIDENCE_TIERS,
    "dominant_signal_clusters",
    KEY_MUST_NOT_REQUIRED_SKILLS,
    KEY_CANDIDATE_ELIGIBILITY,
    KEY_CANDIDATE_QUALIFICATIONS,
    KEY_ROLE_EXPERIENCE,
)

DEFAULT_SOURCE_MATERIALS = {
    "profile_sources": [],
    "cv_variants": [],
}

UPLOAD_SLOT_MAP = {
    "primary cv": "primary_cv",
}

_NON_FILENAME_CHARS_RE = re.compile(r"[^a-z0-9._-]+")
_WHITESPACE_RE = re.compile(r"\s+")


def _format_count(count: int, singular: str, plural: str) -> str:
    if count == 0:
        return f"no {plural}"
    if count == 1:
        return f"1 {singular}"
    return f"{count} {plural}"


def _format_duration_months(total_months: int) -> str:
    months = max(int(total_months or 0), 0)
    if months <= 0:
        return "0 months"
    years = months // 12
    remainder = months % 12
    parts: list[str] = []
    if years > 0:
        parts.append(f"{years} year" + ("" if years == 1 else "s"))
    if remainder > 0:
        parts.append(f"{remainder} month" + ("" if remainder == 1 else "s"))
    return " ".join(parts) or "0 months"


def _print_role_history_summary(role_experience: list[dict[str, Any]]) -> None:
    rows = [row for row in role_experience if isinstance(row, dict)]
    logger.debug(
        "Captured role history: %s", _format_count(len(rows), "role family", "role families")
    )
    for row in rows:
        title = str(row.get("normalized_title") or "").strip() or "untitled role"
        total_months = int(row.get("total_duration_months") or 0)
        most_recent_end_year = int(row.get("most_recent_end_year") or 0)
        line = f"  - {title}: {_format_duration_months(total_months)} total"
        if most_recent_end_year > 0:
            line += f", most recent end year {most_recent_end_year}"
        raw_variants = row.get("title_variants") or []
        if isinstance(raw_variants, list) and raw_variants:
            variant_parts: list[str] = []
            for variant in raw_variants:
                if not isinstance(variant, dict):
                    continue
                variant_title = str(variant.get("normalized_title") or "").strip()
                variant_months = int(variant.get("total_duration_months") or 0)
                if not variant_title or variant_months <= 0:
                    continue
                variant_parts.append(
                    f"{variant_title} ({_format_duration_months(variant_months)})"
                )
            if variant_parts:
                line += f" | variants: {', '.join(variant_parts)}"
        logger.debug(line)


def _normalize_uploaded_filename(filename: str) -> str:
    value = Path(str(filename or "").strip()).name
    if not value:
        return ""
    path = Path(value)
    suffix = "".join(path.suffixes).lower()
    stem = path.name[: -len(suffix)] if suffix else path.name
    stem = _NON_FILENAME_CHARS_RE.sub("_", stem.lower()).strip("_")
    suffix = _NON_FILENAME_CHARS_RE.sub("", suffix)
    if not stem:
        stem = "file"
    return f"{stem}{suffix}"


def _normalize_source_label(label: str, filename: str, fallback: str) -> str:
    value = str(label or "").strip()
    if value:
        return _WHITESPACE_RE.sub(" ", value)
    normalized_filename = _normalize_uploaded_filename(filename)
    if normalized_filename:
        return Path(normalized_filename).stem.replace("_", " ")
    return fallback


def _normalize_profile_sources(items: Any) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        filename = _normalize_uploaded_filename(item.get("filename") or "")
        label = _normalize_source_label(item.get("label") or "", filename, filename or "Source")
        content = str(item.get("content") or "").strip()
        if label and content:
            normalized.append({"label": label, "filename": filename, "content": content})
    return normalized


def _normalize_cv_variants(items: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        filename = _normalize_uploaded_filename(item.get("filename") or "")
        label = _normalize_source_label(item.get("label") or "", filename, key or "CV variant")
        content = str(item.get("content") or "").strip()
        use_for = [str(value).strip() for value in item.get("use_for", []) if str(value).strip()]
        if key and label and content:
            normalized.append(
                {
                    "key": key,
                    "label": label,
                    "filename": filename,
                    "content": content,
                    "use_for": use_for,
                }
            )
    return normalized


def normalize_source_materials(payload: Any) -> dict[str, Any]:
    base = dict(DEFAULT_SOURCE_MATERIALS)
    if not isinstance(payload, dict):
        return base
    base["profile_sources"] = _normalize_profile_sources(payload.get("profile_sources", []))
    base["cv_variants"] = _normalize_cv_variants(payload.get("cv_variants", []))
    return base


def load_source_materials(create_if_missing: bool = False) -> dict[str, Any]:
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT data FROM profile_documents WHERE user_id = ?", (user_id,)
        ).fetchone()
    if row is not None:
        try:
            return normalize_source_materials(json.loads(row["data"]))
        except Exception as exc:
            logger.warning("Failed to load source materials from DB: %s", exc)
    return dict(DEFAULT_SOURCE_MATERIALS)


def save_source_materials(payload: Any) -> dict[str, Any]:
    from job_hunter_agent.database import db_conn, ensure_user_row
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    normalized = normalize_source_materials(payload)
    ensure_user_row(user_id)
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO profile_documents (user_id, data, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at""",
            (user_id, json.dumps(normalized, ensure_ascii=False)),
        )
    return normalized


def _read_docx_text_from_bytes(raw_bytes: bytes) -> str:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    import io

    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
        document_xml = archive.read("word/document.xml")
    root = ET.fromstring(document_xml)
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", ns):
        text = "".join((node.text or "") for node in paragraph.findall(".//w:t", ns)).strip()
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def persist_uploaded_source_pack(
    files_payload: list[dict[str, Any]], extra_text: str = ""
) -> dict[str, Any]:
    profile_sources: list[dict[str, str]] = []

    for index, item in enumerate(files_payload or [], start=1):
        if not isinstance(item, dict):
            continue
        filename = _normalize_uploaded_filename(item.get("filename") or "")
        label = _normalize_source_label(
            item.get("label") or "",
            filename,
            f"CV File {index}",
        )
        content_base64 = str(item.get("content_base64") or "").strip()
        if not filename or not content_base64:
            continue
        try:
            raw_bytes = base64.b64decode(content_base64)
            suffix = Path(filename).suffix.lower()
            if suffix == ".docx":
                content = repair_text(_read_docx_text_from_bytes(raw_bytes))
            else:
                content = repair_text(raw_bytes.decode("utf-8", errors="ignore"))
        except Exception as exc:
            logger.warning("Failed to extract text from %s: %s", filename, exc)
            continue
        if not content.strip():
            logger.warning("No text extracted from %s", filename)
            continue
        profile_sources.append({"label": label, "filename": filename, "content": content})

    materials = {"profile_sources": profile_sources, "cv_variants": []}
    return save_source_materials(materials)


def _collect_import_sources(materials: dict[str, Any]) -> list[dict[str, str]]:
    sources = list(materials.get("profile_sources", []))
    return [item for item in sources if item.get("label") and item.get("content")]


def build_onboarding_reset_patch(
    onboarding_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the extraction reset without touching user-confirmed role intent.

    Role suggestions are returned separately by ``run_onboarding`` and become
    persisted selections only through the explicit review-confirm endpoint.
    """
    patch: dict[str, Any] = {
        field: copy.deepcopy(DEFAULT_PROFILE[field])
        for field in ONBOARDING_RESET_FIELDS
        if field in DEFAULT_PROFILE
    }
    if onboarding_settings is not None:
        patch["onboarding_settings"] = copy.deepcopy(onboarding_settings)
    return patch


def clear_onboarding_runtime_outputs() -> None:
    from job_hunter_agent.io_utils import clear_review_data, clear_run_stats

    for label, fn in [("review_data", clear_review_data), ("run_stats", clear_run_stats)]:
        try:
            fn()
            logger.debug("Onboarding reset: %s", label)
        except Exception as exc:
            logger.warning("Onboarding could not reset %s: %s", label, exc)


def _norm_term(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def run_onboarding(
    source_materials: dict[str, Any],
    search_preferences: dict | None = None,
    onboarding_settings: dict | None = None,
) -> dict[str, Any]:
    """Collect source documents, refresh onboarding-owned data, and save.

    This is the single shared path for both initial onboarding and the Danger Rebuild.
    Non-onboarding fields (search settings, salary, preferences, review controls, etc.)
    are preserved unchanged. Existing confirmed role selections remain persisted while
    CV-derived role suggestions are reviewed and are replaced only on explicit confirm.
    """
    resolved = normalize_source_materials(
        source_materials or load_source_materials(create_if_missing=True)
    )
    import_sources = _collect_import_sources(resolved)
    prefs = search_preferences or {}
    if not import_sources:
        raise ValueError("No onboarding input provided. Please upload your CV first.")

    active_settings = onboarding_settings or {}
    cv_max_pages = max(
        1,
        int(
            active_settings.get(KEY_CV_MAX_PAGES)
            or DEFAULT_ONBOARDING_SETTINGS.get(KEY_CV_MAX_PAGES)
            or 5
        ),
    )
    cv_max_chars = cv_max_pages * get_cv_chars_per_page()
    cv_chars_per_page = get_cv_chars_per_page()
    logger.info(
        format_log_block(
            "ONBOARDING_SOURCE_READ",
            {
                "capability_strength_preset": str(
                    active_settings.get("capability_strength_preset")
                    or DEFAULT_ONBOARDING_SETTINGS.get("capability_strength_preset")
                    or ""
                ).strip(),
                "cv_max_pages": cv_max_pages,
                "cv_chars_per_page": cv_chars_per_page,
                "cv_max_chars": cv_max_chars,
                "import_sources": len(import_sources),
            },
        )
    )

    imported_sources: list[dict[str, Any]] = []
    combined_sections: list[str] = []
    source_sections: list[dict[str, str]] = []
    missing_sources: list[str] = []
    page_limit_notice: str = ""

    for source in import_sources:
        label = str(source.get("label") or "").strip()
        text = str(source.get("content") or "").strip()
        if not label or not text:
            continue
        raw_chars = len(text)
        approx_pages = max(1, (raw_chars + cv_chars_per_page - 1) // cv_chars_per_page)
        if len(text) > cv_max_chars:
            text = text[:cv_max_chars]
            page_limit_notice = (
                f"CV was truncated to approximately {cv_max_pages} page(s) for processing."
            )
            logger.info(
                format_log_block(
                    "ONBOARDING_SOURCE_READ",
                    {
                        "source": label,
                        "read_chars": raw_chars,
                        "approx_pages": approx_pages,
                        "truncated_to_chars": len(text),
                        "limit_pages": cv_max_pages,
                    },
                )
            )
        else:
            logger.info(
                "[ONBOARDING][SOURCE_READ] %s read_chars=%s approx_pages=%s",
                label,
                raw_chars,
                approx_pages,
            )
        imported_sources.append(
            {"label": label, "filename": source.get("filename", ""), "characters": len(text)}
        )
        combined_sections.append(f"## {label}\n{text}")
        source_sections.append({"label": label, "text": text})

    if not combined_sections:
        if import_sources:
            raise ValueError("Could not read any configured CV files.")
        raise ValueError(
            "No onboarding input provided. Upload files, paste CV text, or configure profile CV files first."
        )

    combined_text = "\n\n".join(combined_sections).strip()
    logger.info(
        "[ONBOARDING][SOURCE_READ] combined_chars=%s combined_approx_pages=%s page_limit_notice=%s",
        len(combined_text),
        max(1, (len(combined_text) + cv_chars_per_page - 1) // cv_chars_per_page),
        page_limit_notice or "(none)",
    )

    # Load current profile to preserve non-onboarding fields and read onboarding_settings.
    current_profile = load_profile()
    active_onboarding_settings = (
        onboarding_settings
        or current_profile.get("onboarding_settings")
        or dict(DEFAULT_ONBOARDING_SETTINGS)
    )

    # --- Reset persisted onboarding-owned fields before fresh extraction starts ---
    patch_profile(build_onboarding_reset_patch(active_onboarding_settings))
    clear_onboarding_runtime_outputs()

    # --- Build a fresh onboarding patch from clean defaults ---
    patch = build_onboarding_reset_patch(active_onboarding_settings)

    # Evidence buckets are derived from source section headings during onboarding.
    patch[KEY_EVIDENCE_TIERS] = build_candidate_profile_tiers_from_sections(source_sections)

    learning_patch = build_learning_patch(
        combined_text, active_onboarding_settings, source_sections
    )
    role_suggestions = learning_patch.pop(ROLE_SUGGESTIONS_KEY)
    patch.update(learning_patch)
    _print_role_history_summary(list(patch.get(KEY_ROLE_EXPERIENCE) or []))

    # --- Apply Search and Engagement Preferences ---
    search_settings = dict(current_profile.get("search_settings") or {})
    learned_match_preferences = dict(patch.get("match_preferences") or {})
    match_preferences = dict(current_profile.get("match_preferences") or {})
    if learned_match_preferences:
        match_preferences.update(learned_match_preferences)

    # 1. Keywords
    manual_keywords = str(prefs.get("keywords") or "").strip()
    if manual_keywords:
        search_settings["keywords"] = manual_keywords

    # 2. Locations
    manual_locations = [str(l).strip() for l in prefs.get("locations", []) if str(l).strip()][:1]
    if manual_locations:
        search_settings["locations"] = manual_locations
    else:
        llm_location = match_preferences.get("home_location", "").strip()
        if llm_location and not search_settings.get("locations"):
            search_settings["locations"] = [llm_location]

    # 3. Engagement
    match_preferences["engagement_type"] = normalize_engagement_type_preferences(
        prefs.get("engagement_type")
    )

    search_settings["locations"] = [
        str(value).strip() for value in search_settings.get("locations", []) if str(value).strip()
    ][:1]

    patch["search_settings"] = search_settings
    patch["match_preferences"] = match_preferences

    logger.info(
        "LLM extracted %d target and %d secondary title(s)",
        len(role_suggestions.get(KEY_PRIMARY_PATTERNS) or []),
        len(role_suggestions.get(KEY_SECONDARY_PATTERNS) or []),
    )

    profile = patch_profile(patch)

    extraction_counts = {
        "target_titles": len(role_suggestions.get(KEY_PRIMARY_PATTERNS) or []),
        "secondary_titles": len(role_suggestions.get(KEY_SECONDARY_PATTERNS) or []),
        "capabilities": len(patch.get(KEY_CANDIDATE_CAPABILITIES) or []),
        "qualifications": len(patch.get(KEY_CANDIDATE_QUALIFICATIONS) or []),
    }

    return {
        "ok": True,
        "message": (
            "Fresh onboarding run started. "
            f"Imported {len(imported_sources)} source document(s) and extracted "
            f"{_format_count(extraction_counts['target_titles'], 'target role', 'target roles')}, "
            f"{_format_count(extraction_counts['secondary_titles'], 'also-consider role', 'also-consider roles')}, and "
            f"{_format_count(extraction_counts['capabilities'], 'capability row', 'capability rows')} from this run only."
        ),
        "profile": profile,
        "role_suggestions": role_suggestions,
        "imported_sources": imported_sources,
        "missing_sources": missing_sources,
        "fresh_onboarding_run_started": True,
        "extraction_counts": extraction_counts,
        "page_limit_notice": page_limit_notice,
    }


def refresh_role_history_from_saved_cv() -> dict[str, Any]:
    """Refresh the role-history section only from the saved CV source pack.

    This first-pass settings action is intentionally simple: it replaces the entire
    persisted ``role_experience`` section with a fresh extraction from the saved CV
    materials. It does not merge with existing rows or preserve manual edits yet.
    """
    resolved = normalize_source_materials(load_source_materials(create_if_missing=True))
    import_sources = _collect_import_sources(resolved)
    if not import_sources:
        raise ValueError("No saved CV found. Upload your CV first.")

    current_profile = load_profile()
    active_onboarding_settings = (
        current_profile.get("onboarding_settings") or dict(DEFAULT_ONBOARDING_SETTINGS)
    )
    cv_max_pages = max(
        1,
        int(
            active_onboarding_settings.get(KEY_CV_MAX_PAGES)
            or DEFAULT_ONBOARDING_SETTINGS.get(KEY_CV_MAX_PAGES)
            or 5
        ),
    )
    cv_chars_per_page = get_cv_chars_per_page()
    cv_max_chars = cv_max_pages * cv_chars_per_page
    combined_sections: list[str] = []
    page_limit_notice = ""

    for source in import_sources:
        label = str(source.get("label") or "").strip()
        text = str(source.get("content") or "").strip()
        if not label or not text:
            continue
        raw_chars = len(text)
        approx_pages = max(1, (raw_chars + cv_chars_per_page - 1) // cv_chars_per_page)
        if len(text) > cv_max_chars:
            text = text[:cv_max_chars]
            page_limit_notice = (
                f"CV was truncated to approximately {cv_max_pages} page(s) for processing."
            )
            logger.info(
                format_log_block(
                    "ROLE_HISTORY_SOURCE_READ",
                    {
                        "source": label,
                        "read_chars": raw_chars,
                        "approx_pages": approx_pages,
                        "truncated_to_chars": len(text),
                        "limit_pages": cv_max_pages,
                    },
                )
            )
        else:
            logger.info(
                "[ROLE_HISTORY][SOURCE_READ] %s read_chars=%s approx_pages=%s",
                label,
                raw_chars,
                approx_pages,
            )
        combined_sections.append(f"## {label}\n{text}")

    if not combined_sections:
        raise ValueError("Could not read any saved CV files.")

    role_history_patch = build_role_history_patch(
        "\n\n".join(combined_sections).strip(),
        active_onboarding_settings,
    )
    role_experience = list(role_history_patch.get(KEY_ROLE_EXPERIENCE) or [])
    _print_role_history_summary(role_experience)
    updated = patch_profile({KEY_ROLE_EXPERIENCE: role_experience})
    return {
        "ok": True,
        "message": (
            "Role history refreshed from saved CV. "
            f"Extracted {_format_count(len(role_experience), 'role family', 'role families')}."
        ),
        "page_limit_notice": page_limit_notice,
        KEY_ROLE_EXPERIENCE: role_experience,
        "profile": updated,
    }
