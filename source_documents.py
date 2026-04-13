import base64
import json
import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from profile_learning import build_learning_patch, merge_capability_rules, repair_text
from profile_store import DEFAULT_PROFILE, load_profile, patch_profile


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
APPLICATION_INPUTS_DIR = DATA_DIR / "application_inputs"
SOURCE_PACK_DIR = APPLICATION_INPUTS_DIR / "source_pack"
SOURCE_MATERIALS_PATH = DATA_DIR / "application_materials.json"
SOURCE_MATERIALS_TEMPLATE_PATH = DATA_DIR / "application_materials.template.json"

DEFAULT_SOURCE_MATERIALS = {
    "profile_sources": [],
    "instructions_file": "",
    "cv_variants": [],
    "cover_letter_preferences_file": "",
    "notes": "",
}

STRENGTH_KEYWORDS = [
    ("business analysis", ["business analyst", "business analysis", "requirements elicitation", "requirements gathering"]),
    ("stakeholder engagement", ["stakeholder engagement", "stakeholder management", "workshops", "facilitated stakeholder workshops"]),
    ("process mapping", ["process mapping", "process modelling", "bpmn", "workflow", "workflows"]),
    ("agile delivery", ["agile", "scrum", "user stories", "backlog refinement", "sprint planning"]),
    ("data analysis", ["sql", "data mapping", "data validation", "data migration", "database"]),
    ("integration analysis", ["api", "apis", "integration", "integrations", "json", "postman"]),
    ("testing and uat", ["uat", "user acceptance testing", "testing", "test cases", "acceptance criteria"]),
    ("government delivery", ["government", "federal", "state government", "public sector", "baseline clearance"]),
    ("digital transformation", ["digital delivery", "transformation", "service improvement", "change delivery"]),
]

UPLOAD_SLOT_MAP = {
    "primary cv": "primary_cv",
    "supporting background": "supporting_background",
}


def _deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        merged = dict(base)
        for key, value in patch.items():
            merged[key] = _deep_merge(merged.get(key), value)
        return merged
    return patch


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
    base["instructions_file"] = str(payload.get("instructions_file") or "").strip()
    base["cv_variants"] = _normalize_cv_variants(payload.get("cv_variants", []))
    base["cover_letter_preferences_file"] = str(payload.get("cover_letter_preferences_file") or "").strip()
    base["notes"] = str(payload.get("notes") or "").strip()
    return base


def load_source_materials(create_if_missing: bool = False) -> dict[str, Any]:
    if SOURCE_MATERIALS_PATH.exists():
        try:
            payload = json.loads(SOURCE_MATERIALS_PATH.read_text(encoding="utf-8"))
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
    SOURCE_MATERIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SOURCE_MATERIALS_PATH.write_text(
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


def _read_docx_bytes(data: bytes) -> str:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(BytesIO(data)) as archive:
        document_xml = archive.read("word/document.xml")
    return _extract_docx_xml_text(document_xml, ns)


def read_source_document(path_value: str) -> str:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    if not path.exists():
        raise FileNotFoundError(f"Could not find source document: {path}")
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return repair_text(_read_docx_text(path))
    if suffix in {".txt", ".md"}:
        return repair_text(path.read_text(encoding="utf-8", errors="ignore"))
    raise ValueError(f"Unsupported source document type: {path.suffix}")


def _slugify_filename(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "source_document"


def persist_uploaded_source_pack(files_payload: list[dict[str, Any]], extra_text: str = "") -> dict[str, Any]:
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
        raw_bytes = base64.b64decode(content_base64)
        suffix = Path(filename).suffix.lower() or ".txt"
        slot_name = UPLOAD_SLOT_MAP.get(label.lower(), _slugify_filename(label))
        target_name = f"{slot_name}{suffix}"
        target_path = SOURCE_PACK_DIR / target_name
        target_path.write_bytes(raw_bytes)
        profile_sources.append({
            "label": label,
            "path": str(target_path.relative_to(ROOT_DIR)),
        })

    extra_clean = repair_text(extra_text)
    if extra_clean:
        notes_path = SOURCE_PACK_DIR / "extra_notes.txt"
        notes_path.write_text(extra_clean, encoding="utf-8")
        profile_sources.append({
            "label": "Extra Notes",
            "path": str(notes_path.relative_to(ROOT_DIR)),
        })

    materials = {
        "profile_sources": profile_sources,
        "instructions_file": "",
        "cv_variants": [],
        "cover_letter_preferences_file": "",
        "notes": "Managed by onboarding. Internal local evidence pack.",
    }
    return save_source_materials(materials)


def _collect_import_sources(materials: dict[str, Any]) -> list[dict[str, str]]:
    sources = list(materials.get("profile_sources", []))
    if materials.get("instructions_file"):
        sources.append({
            "label": "Project Instructions",
            "path": str(materials.get("instructions_file") or "").strip(),
        })
    if not sources:
        for variant in materials.get("cv_variants", []):
            sources.append({
                "label": str(variant.get("label") or variant.get("key") or "CV Variant"),
                "path": str(variant.get("path") or "").strip(),
            })
    return [item for item in sources if item.get("label") and item.get("path")]


def _build_profile_import_result(
    imported_sources: list[dict[str, Any]],
    missing_sources: list[str],
    combined_text: str,
) -> dict[str, Any]:
    patch = build_learning_patch(combined_text)
    patch["cv_text"] = combined_text

    existing_profile = load_profile()

    imported_summary = patch.get("candidate_summary") or _extract_summary_from_text(combined_text)
    existing_summary = str(existing_profile.get("candidate_summary") or "").strip()
    default_summary = str(DEFAULT_PROFILE.get("candidate_summary") or "").strip()
    if imported_summary and (not existing_summary or existing_summary == default_summary):
        patch["candidate_summary"] = imported_summary
    else:
        patch.pop("candidate_summary", None)

    imported_strengths = _extract_strengths_from_text(combined_text)
    merged_strengths = list(dict.fromkeys([
        *existing_profile.get("strengths", []),
        *patch.get("strengths", []),
        *imported_strengths,
    ]))
    if merged_strengths:
        patch["strengths"] = merged_strengths[:20]

    if patch.get("capability_profile_rules"):
        patch["capability_profile_rules"] = merge_capability_rules(
            merge_capability_rules(
                DEFAULT_PROFILE.get("capability_profile_rules", []),
                existing_profile.get("capability_profile_rules", []),
            ),
            patch.get("capability_profile_rules", []),
        )

    if patch.get("llm_prompt_notes"):
        patch["llm_prompt_notes"] = list(dict.fromkeys([
            *existing_profile.get("llm_prompt_notes", []),
            *patch.get("llm_prompt_notes", []),
        ]))[:30]

    profile = patch_profile(patch)
    return {
        "ok": True,
        "message": f"Imported {len(imported_sources)} source document(s) into profile.json.",
        "profile": profile,
        "imported_sources": imported_sources,
        "missing_sources": missing_sources,
    }


def _extract_summary_from_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    headers = {
        "executive summary",
        "professional summary",
        "summary",
        "profile",
        "experience summary",
    }
    for index, line in enumerate(lines):
        if line.lower().rstrip(":") in headers:
            parts: list[str] = []
            for candidate in lines[index + 1:]:
                normalized = candidate.strip()
                if len(normalized.split()) <= 8 and normalized.upper() == normalized:
                    break
                parts.append(normalized)
                if len(" ".join(parts)) >= 420:
                    break
            if parts:
                return " ".join(parts)[:500].strip()
    return " ".join(lines[:4])[:500].strip()


def _extract_strengths_from_text(text: str) -> list[str]:
    lowered = text.lower()
    strengths: list[str] = []
    for label, keywords in STRENGTH_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            strengths.append(label)
    return strengths[:12]


def import_source_materials_to_profile(materials: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved_materials = normalize_source_materials(materials or load_source_materials(create_if_missing=True))
    import_sources = _collect_import_sources(resolved_materials)
    if not import_sources:
        raise ValueError("No profile source documents configured yet.")

    imported_sources: list[dict[str, Any]] = []
    combined_sections: list[str] = []
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
        imported_sources.append({
            "label": label,
            "path": path,
            "characters": len(text),
        })
        combined_sections.append(f"## {label}\n{text}")

    if not combined_sections:
        raise ValueError("Could not read any configured source documents.")

    combined_text = "\n\n".join(combined_sections).strip()
    result = _build_profile_import_result(imported_sources, missing_sources, combined_text)
    result["materials"] = resolved_materials
    return result


def import_uploaded_documents_to_profile(files_payload: list[dict[str, Any]], extra_text: str = "") -> dict[str, Any]:
    imported_sources: list[dict[str, Any]] = []
    missing_sources: list[str] = []
    combined_sections: list[str] = []

    for item in files_payload or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("filename") or "Source Document").strip()
        filename = str(item.get("filename") or "").strip()
        content_base64 = str(item.get("content_base64") or "").strip()
        if not filename or not content_base64:
            continue
        try:
            raw_bytes = base64.b64decode(content_base64)
            suffix = Path(filename).suffix.lower()
            if suffix == ".docx":
                text = repair_text(_read_docx_bytes(raw_bytes))
            elif suffix in {".txt", ".md"}:
                text = repair_text(raw_bytes.decode("utf-8", errors="ignore"))
            else:
                raise ValueError(f"Unsupported file type: {suffix}")
        except Exception:
            missing_sources.append(filename)
            continue
        if not text:
            missing_sources.append(filename)
            continue
        imported_sources.append({
            "label": label,
            "path": filename,
            "characters": len(text),
        })
        combined_sections.append(f"## {label}\n{text}")

    extra_clean = repair_text(extra_text)
    if extra_clean:
        imported_sources.append({
            "label": "Extra Notes",
            "path": "pasted_text",
            "characters": len(extra_clean),
        })
        combined_sections.append(f"## Extra Notes\n{extra_clean}")

    if not combined_sections:
        raise ValueError("No readable onboarding documents were provided.")

    combined_text = "\n\n".join(combined_sections).strip()
    return _build_profile_import_result(imported_sources, missing_sources, combined_text)
