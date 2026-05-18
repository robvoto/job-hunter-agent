import base64
import copy
import json
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from job_hunter_agent.cv_pipeline import run_cv_pipeline
from job_hunter_agent.global_settings import get_allowed_source_document_suffixes
from job_hunter_agent.llm_gate import client as llm_client
from job_hunter_agent.paths import (
    DATA_DIR,
    OUTPUT_DIR,
    REPO_ROOT,
    get_review_data_path,
    get_run_stats_path,
    get_source_materials_path,
    get_source_pack_dir,
)
from job_hunter_agent.profile_learning import (
    build_learning_patch,
    build_role_title_review_signals,
    clear_capability_debug_log,
    extract_title_pattern_suggestions,
    repair_text,
)
from job_hunter_agent.profile_store import (
    DEFAULT_ONBOARDING_SETTINGS,
    DEFAULT_PROFILE,
    build_candidate_profile_tiers_from_sections,
    KEY_CAPABILITY_PROFILE_RULES,
    KEY_EVIDENCE_TIERS,
    KEY_ONBOARDING_COMPLETE,
    KEY_PRIMARY_PATTERNS,
    KEY_SECONDARY_PATTERNS,
    KEY_MUST_NOT_REQUIRED_SKILLS,
    load_profile,
    normalize_engagement_type_preferences,
    patch_profile,
)
from job_hunter_agent.signal_registry import register_signals


ROOT_DIR = REPO_ROOT
SOURCE_MATERIALS_TEMPLATE_PATH = DATA_DIR / "application_materials.template.json"

# Fields reset to DEFAULT_PROFILE values at the start of every onboarding run.
ONBOARDING_RESET_FIELDS = (
    KEY_PRIMARY_PATTERNS,
    KEY_SECONDARY_PATTERNS,
    KEY_CAPABILITY_PROFILE_RULES,
    KEY_ONBOARDING_COMPLETE,
    "cv_text",
    KEY_EVIDENCE_TIERS,
    "llm_profile_brief",
    "star_evidence_text",
    "dominant_signal_clusters",
    KEY_MUST_NOT_REQUIRED_SKILLS,
)

DEFAULT_SOURCE_MATERIALS = {
    "profile_sources": [],
    "cv_variants": [],
} 

UPLOAD_SLOT_MAP = {
    "primary cv": "primary_cv",
}
 

def _normalize_profile_sources(items: Any) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        path = str(item.get("path") or "").strip()
        if label and path:
            normalized.append({"label": label, "path": path})
    return normalized


def _normalize_cv_variants(items: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        label = str(item.get("label") or "").strip()
        path = str(item.get("path") or "").strip()
        use_for = [str(value).strip() for value in item.get("use_for", []) if str(value).strip()]
        if key and label and path:
            normalized.append({
                "key": key,
                "label": label,
                "path": path,
                "use_for": use_for,
            })
    return normalized


def normalize_source_materials(payload: Any) -> dict[str, Any]:
    base = dict(DEFAULT_SOURCE_MATERIALS)
    if not isinstance(payload, dict):
        return base
    base["profile_sources"] = _normalize_profile_sources(payload.get("profile_sources", []))
    base["cv_variants"] = _normalize_cv_variants(payload.get("cv_variants", []))
    return base


def load_source_materials(create_if_missing: bool = False) -> dict[str, Any]:
    source_materials_path = get_source_materials_path()
    if source_materials_path.exists():
        try:
            payload = json.loads(source_materials_path.read_text(encoding="utf-8"))
            return normalize_source_materials(payload)
        except Exception:
            return dict(DEFAULT_SOURCE_MATERIALS)

    if create_if_missing and SOURCE_MATERIALS_TEMPLATE_PATH.exists():
        try:
            payload = json.loads(SOURCE_MATERIALS_TEMPLATE_PATH.read_text(encoding="utf-8"))
            normalized = normalize_source_materials(payload)
            save_source_materials(normalized)
            return normalized
        except Exception:
            pass
    return dict(DEFAULT_SOURCE_MATERIALS)


def save_source_materials(payload: Any) -> dict[str, Any]:
    normalized = normalize_source_materials(payload)
    source_materials_path = get_source_materials_path()
    source_materials_path.parent.mkdir(parents=True, exist_ok=True)
    source_materials_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return normalized


def _read_docx_text(path: Path) -> str:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        document_xml = archive.read("word/document.xml")
    return _extract_docx_xml_text(document_xml, ns)


def _extract_docx_xml_text(document_xml: bytes, ns: dict[str, str]) -> str:
    root = ET.fromstring(document_xml)
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", ns):
        text = "".join((node.text or "") for node in paragraph.findall(".//w:t", ns)).strip()
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def read_source_document(path_value: str) -> str:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    if not path.exists():
        raise FileNotFoundError(f"Could not find source document: {path}")
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return repair_text(_read_docx_text(path))
    if suffix in get_allowed_source_document_suffixes():
        return repair_text(path.read_text(encoding="utf-8", errors="ignore"))
    raise ValueError(f"Unsupported source document type: {path.suffix}")


def _slugify_filename(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "source_document"


def persist_uploaded_source_pack(files_payload: list[dict[str, Any]], extra_text: str = "") -> dict[str, Any]:
    SOURCE_PACK_DIR = get_source_pack_dir()
    SOURCE_PACK_DIR.mkdir(parents=True, exist_ok=True)
    profile_sources: list[dict[str, str]] = []

    for index, item in enumerate(files_payload or [], start=1):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("filename") or f"Source Document {index}").strip()
        filename = str(item.get("filename") or "").strip()
        content_base64 = str(item.get("content_base64") or "").strip()
        if not filename or not content_base64:
            continue
        try:
            raw_bytes = base64.b64decode(content_base64)
            suffix = Path(filename).suffix.lower() or ".txt"
            slot_name = UPLOAD_SLOT_MAP.get(label.lower(), _slugify_filename(label))
            target_name = f"{slot_name}{suffix}"
            target_path = SOURCE_PACK_DIR / target_name
            target_path.write_bytes(raw_bytes)
        except Exception:
            continue
        profile_sources.append({
            "label": label,
            "path": str(target_path.relative_to(ROOT_DIR)),
        })

    materials = {
        "profile_sources": profile_sources,
        "cv_variants": [],
    }
    return save_source_materials(materials)


def _collect_import_sources(materials: dict[str, Any]) -> list[dict[str, str]]:
    sources = list(materials.get("profile_sources", []))
    return [item for item in sources if item.get("label") and item.get("path")]


def build_onboarding_reset_patch(onboarding_settings: dict[str, Any] | None = None) -> dict[str, Any]:
    patch: dict[str, Any] = {
        field: copy.deepcopy(DEFAULT_PROFILE[field])
        for field in ONBOARDING_RESET_FIELDS
        if field in DEFAULT_PROFILE
    }
    if onboarding_settings is not None:
        patch["onboarding_settings"] = copy.deepcopy(onboarding_settings)
    return patch


def clear_onboarding_runtime_outputs() -> None:
    reset_items = [
        (get_review_data_path(), "review_data.json"),
        (get_run_stats_path(), "run_stats.json"),
    ]
    for reset_path, label in reset_items:
        try:
            reset_path.parent.mkdir(parents=True, exist_ok=True)
            reset_path.write_text(json.dumps({}, ensure_ascii=False), encoding="utf-8")
            print(f"[ONBOARDING] {label} reset")
        except Exception as exc:
            print(f"[ONBOARDING] Could not reset {label}: {exc}")


def run_onboarding(source_materials: dict[str, Any], search_preferences: dict | None = None, onboarding_settings: dict | None = None) -> dict[str, Any]:
    """Collect source documents, reset onboarding fields, re-extract everything, save.

    This is the single shared path for both initial onboarding and the Danger Rebuild.
    Non-onboarding fields (search settings, salary, preferences, review controls, etc.)
    are preserved unchanged.
    """
    resolved = normalize_source_materials(source_materials or load_source_materials(create_if_missing=True))
    import_sources = _collect_import_sources(resolved)
    prefs = search_preferences or {}
    if not import_sources:
        raise ValueError("No onboarding input provided. Please upload your CV first.")

    imported_sources: list[dict[str, Any]] = []
    combined_sections: list[str] = []
    source_sections: list[dict[str, str]] = []
    missing_sources: list[str] = []

    for source in import_sources:
        label = str(source.get("label") or "").strip()
        path = str(source.get("path") or "").strip()
        if not label or not path:
            continue
        try:
            text = read_source_document(path)
        except Exception:
            missing_sources.append(path)
            continue
        if not text:
            missing_sources.append(path)
            continue
        imported_sources.append({"label": label, "path": path, "characters": len(text)})
        combined_sections.append(f"## {label}\n{text}")
        source_sections.append({"label": label, "text": text})

    if not combined_sections:
        if import_sources:
            raise ValueError("Could not read any configured source documents.")
        raise ValueError("No onboarding input provided. Upload files, paste CV text, or configure profile source documents first.")

    combined_text = "\n\n".join(combined_sections).strip()

    # Load current profile to preserve non-onboarding fields and read onboarding_settings.
    current_profile = load_profile()
    active_onboarding_settings = onboarding_settings or current_profile.get("onboarding_settings") or dict(DEFAULT_ONBOARDING_SETTINGS)

    # --- Reset persisted onboarding-owned fields before fresh extraction starts ---
    patch_profile(build_onboarding_reset_patch(active_onboarding_settings))
    clear_onboarding_runtime_outputs()
    clear_capability_debug_log()

    # --- Build a fresh onboarding patch from clean defaults ---
    patch = build_onboarding_reset_patch(active_onboarding_settings)

    # --- Extract fresh from combined_text ---
    patch["cv_text"] = combined_text
    # Evidence buckets are derived from source section headings during onboarding.
    patch[KEY_EVIDENCE_TIERS] = build_candidate_profile_tiers_from_sections(source_sections)

    pipeline_patch = run_cv_pipeline(combined_text, llm_client, onboarding_settings=active_onboarding_settings)
    learning_patch = build_learning_patch(
        combined_text,
        onboarding_settings=active_onboarding_settings,
        source_sections=source_sections,
    )
    patch.update(pipeline_patch)
    for key, value in learning_patch.items():
        if key in {"cv_text", KEY_CAPABILITY_PROFILE_RULES}:
            continue
        patch[key] = value
    patch[KEY_CAPABILITY_PROFILE_RULES] = list(learning_patch.get(KEY_CAPABILITY_PROFILE_RULES, []))

    brief = build_llm_profile_brief(capability_rules=patch.get(KEY_CAPABILITY_PROFILE_RULES) or [])
    if brief:
        patch["llm_profile_brief"] = brief

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
    match_preferences["engagement_type"] = normalize_engagement_type_preferences(prefs.get("engagement_type"))

    search_settings["locations"] = [str(value).strip() for value in search_settings.get("locations", []) if str(value).strip()][:1]

    patch["search_settings"] = search_settings
    patch["match_preferences"] = match_preferences

    # Title patterns - always rebuilt from parsed role headers during onboarding
    try:
        suggestion = extract_title_pattern_suggestions(combined_text, active_onboarding_settings)
        patch[KEY_PRIMARY_PATTERNS] = suggestion.get(KEY_PRIMARY_PATTERNS) or []
        patch[KEY_SECONDARY_PATTERNS] = suggestion.get(KEY_SECONDARY_PATTERNS) or []
        print(f"[TITLE_PATTERNS] Extracted {len(patch[KEY_PRIMARY_PATTERNS])} target and {len(patch[KEY_SECONDARY_PATTERNS])} secondary patterns")
        review_signals = build_role_title_review_signals(
            patch[KEY_SECONDARY_PATTERNS],
            source_sections=source_sections,
        )
        if review_signals:
            register_signals(review_signals)
        target_roles = list(patch.get(KEY_PRIMARY_PATTERNS) or [])
        if target_roles:
            current_kw = current_profile.get("search_settings", {}).get("keywords", "").strip()
            if not current_kw and not manual_keywords:
                from job_hunter_agent.title_normalization_rules import derive_base_title_from_seniority
                base = derive_base_title_from_seniority(target_roles[0])
                patch["search_settings"]["keywords"] = base or target_roles[0]
                print(f"[TITLE_PATTERNS] Pre-filled search keywords: {patch['search_settings']['keywords']}")
    except Exception as exc:
        print(f"[TITLE_PATTERNS] Deterministic parser failed: {exc}")

    profile = patch_profile(patch)

    extraction_counts = {
        "target_titles": len(patch.get(KEY_PRIMARY_PATTERNS) or []),
        "secondary_titles": len(patch.get(KEY_SECONDARY_PATTERNS) or []),
        "capabilities": len(patch.get(KEY_CAPABILITY_PROFILE_RULES) or []),
        "dominant_signal_clusters": len(patch.get("dominant_signal_clusters") or []),
    }

    return {
        "ok": True,
        "message": (
            "Fresh onboarding run started. "
            f"Imported {len(imported_sources)} source document(s) and extracted "
            f"{extraction_counts['target_titles']} primary title(s), "
            f"{extraction_counts['secondary_titles']} secondary title(s), and "
            f"{extraction_counts['capabilities']} capability row(s) from the current run only."
        ),
        "profile": profile,
        "imported_sources": imported_sources,
        "missing_sources": missing_sources,
        "fresh_onboarding_run_started": True,
        "extraction_counts": extraction_counts,
    }


def build_llm_profile_brief(
    capability_rules: Any,
) -> str:
    lines: list[str] = []

    preferred_rules = []
    rules = capability_rules if isinstance(capability_rules, list) else []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        name = str(rule.get("name") or "").strip()
        level = str(rule.get("level") or "").strip()
        if not name or not level:
            continue
        preferred_rules.append(f"{name} ({level})")

    if preferred_rules:
        lines.append("Capability profile: " + "; ".join(preferred_rules[:20]))

    return "\n".join(lines).strip()[:3000]
 
