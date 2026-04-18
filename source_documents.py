import base64
import copy
import json
import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from profile_learning import (
    build_learning_patch,
    extract_title_pattern_suggestions,
    merge_capability_rules,
    repair_text,
)
from profile_store import (
    DEFAULT_ONBOARDING_SETTINGS,
    DEFAULT_PROFILE,
    build_evidence_tiers_from_sections,
    load_profile,
    patch_profile,
)


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
REVIEW_DATA_PATH = OUTPUT_DIR / "review_data.json"
RUN_STATS_PATH = OUTPUT_DIR / "run_stats.json"
APPLICATION_INPUTS_DIR = DATA_DIR / "application_inputs"
SOURCE_PACK_DIR = APPLICATION_INPUTS_DIR / "source_pack"
SOURCE_MATERIALS_PATH = DATA_DIR / "application_materials.json"
SOURCE_MATERIALS_TEMPLATE_PATH = DATA_DIR / "application_materials.template.json"

# Fields reset to DEFAULT_PROFILE values at the start of every onboarding run.
ONBOARDING_RESET_FIELDS = (
    "target_title_patterns",
    "adjacent_title_patterns",
    "reject_title_rules",
    "evidence_signals",
    "capability_profile_rules",
    "candidate_summary",
    "cv_text",
    "evidence_tiers",
    "llm_profile_brief",
    "star_evidence_text",
    "dominant_signal_clusters",
    "must_not_require_skills",
    "cheap_keep_counter_patterns",
    "cheap_reject_metadata_rules",
)

DEFAULT_SOURCE_MATERIALS = {
    "profile_sources": [],
    "cv_variants": [],
}

STAR_LABEL_KEYWORDS = ("star", "achievement", "example", "selection criteria", "impact")

UPLOAD_SLOT_MAP = {
    "primary cv": "primary_cv",
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
        if label.lower() == "supporting background":
            continue
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


def run_onboarding(source_materials: dict[str, Any], extra_text: str = "") -> dict[str, Any]:
    """Collect source documents, reset onboarding fields, re-extract everything, save.

    This is the single shared path for both initial onboarding and the Danger Rebuild.
    Non-onboarding fields (search settings, salary, preferences, review controls, etc.)
    are preserved unchanged.
    """
    resolved = normalize_source_materials(source_materials or load_source_materials(create_if_missing=True))
    import_sources = _collect_import_sources(resolved)
    pasted_text = repair_text(extra_text)
    if not import_sources and not pasted_text:
        raise ValueError("No onboarding input provided. Upload files, paste CV text, or configure profile source documents first.")

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

    if pasted_text:
        imported_sources.append({"label": "Pasted CV", "path": "(pasted text)", "characters": len(pasted_text)})
        combined_sections.append(f"## Pasted CV\n{pasted_text}")
        source_sections.append({"label": "Pasted CV", "text": pasted_text})

    if not combined_sections:
        if import_sources:
            raise ValueError("Could not read any configured source documents.")
        raise ValueError("No onboarding input provided. Upload files, paste CV text, or configure profile source documents first.")

    combined_text = "\n\n".join(combined_sections).strip()

    # Load current profile to preserve non-onboarding fields and read onboarding_settings.
    current_profile = load_profile()
    onboarding_settings = current_profile.get("onboarding_settings") or dict(DEFAULT_ONBOARDING_SETTINGS)

    # --- Reset: start with DEFAULT_PROFILE values for all onboarding-owned fields ---
    patch: dict[str, Any] = {
        field: copy.deepcopy(DEFAULT_PROFILE[field])
        for field in ONBOARDING_RESET_FIELDS
        if field in DEFAULT_PROFILE
    }

    # --- Extract fresh from combined_text ---
    patch["cv_text"] = combined_text
    patch["evidence_tiers"] = build_evidence_tiers_from_sections(source_sections)

    learned = build_learning_patch(combined_text)

    imported_summary = learned.get("candidate_summary") or _extract_summary_from_text(combined_text)
    if imported_summary:
        patch["candidate_summary"] = imported_summary

    imported_evidence_signals = _normalize_evidence_signal_candidates(
        learned.get("evidence_signals", learned.get("strengths", []))
    )
    if not imported_evidence_signals:
        imported_evidence_signals = _normalize_evidence_signal_candidates(
            _extract_evidence_signals_from_text(combined_text)
        )
    all_evidence_signals = list(dict.fromkeys(imported_evidence_signals))
    if all_evidence_signals:
        patch["evidence_signals"] = all_evidence_signals[:20]

    if learned.get("capability_profile_rules"):
        patch["capability_profile_rules"] = merge_capability_rules(
            copy.deepcopy(DEFAULT_PROFILE.get("capability_profile_rules", [])),
            learned["capability_profile_rules"],
        )

    brief = build_llm_profile_brief(
        capability_rules=patch.get("capability_profile_rules") or [],
    )
    if brief:
        patch["llm_profile_brief"] = brief

    # Title patterns — always re-extracted during onboarding (no guard needed here)
    try:
        suggestion = extract_title_pattern_suggestions(combined_text, onboarding_settings)
        if suggestion.get("target_title_patterns"):
            patch["target_title_patterns"] = suggestion["target_title_patterns"]
            if suggestion.get("adjacent_title_patterns"):
                patch["adjacent_title_patterns"] = suggestion["adjacent_title_patterns"]
            print(f"[TITLE_PATTERNS] Saved {len(suggestion['target_title_patterns'])} target and {len(suggestion.get('adjacent_title_patterns', []))} adjacent patterns")
        else:
            print("[TITLE_PATTERNS] Deterministic parser returned no target patterns")
    except Exception as exc:
        print(f"[TITLE_PATTERNS] Deterministic parser failed: {exc}")

    profile = patch_profile(patch)

    # Reset stale output files so tuning suggestions and run stats don't persist after a full rebuild.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for reset_path, label in ((REVIEW_DATA_PATH, "review_data.json"), (RUN_STATS_PATH, "run_stats.json")):
        try:
            reset_path.write_text(json.dumps({}, ensure_ascii=False), encoding="utf-8")
            print(f"[ONBOARDING] {label} reset")
        except Exception as exc:
            print(f"[ONBOARDING] Could not reset {label}: {exc}")

    return {
        "ok": True,
        "message": f"Onboarding complete. Imported {len(imported_sources)} source document(s) into profile.json.",
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

    titles: list[str] = []
    seen_titles: set[str] = set()
    for line in lines:
        match = re.search(r"-\s*([A-Za-z][A-Za-z /&-]{2,80}?)\s*\((?:19|20)\d{2}", line)
        if not match:
            continue
        title = re.sub(r"\s+", " ", match.group(1)).strip(" -")
        normalized = title.lower()
        if normalized in seen_titles:
            continue
        seen_titles.add(normalized)
        titles.append(title)
        if len(titles) >= 3:
            break
    if titles:
        if len(titles) == 1:
            return f"Recent experience in {titles[0]} roles."
        return f"Recent experience in {titles[0]} and {titles[1]} roles."

    filtered = [
        line
        for line in lines
        if not line.startswith("##")
        and not (len(line.split()) <= 8 and line.upper() == line)
    ]
    return " ".join(filtered[:3])[:500].strip()


def _extract_evidence_signals_from_text(text: str) -> list[str]:
    """Generic noun-phrase fallback extraction if LLM is unavailable."""
    phrases = re.findall(r"\b(?:[A-Z][a-z]+\s+){1,2}[A-Z][a-z]+\b", text)
    seen: set[str] = set()
    evidence_signals: list[str] = []
    for phrase in phrases:
        lowered = phrase.lower()
        if lowered not in seen and len(lowered) > 8:
            seen.add(lowered)
            evidence_signals.append(phrase)
    return evidence_signals[:12]


def build_llm_profile_brief(
    capability_rules: list[dict[str, Any]],
) -> str:
    lines: list[str] = []

    preferred_rules = []
    avoid_rules = []
    for rule in capability_rules or []:
        if not isinstance(rule, dict):
            continue
        name = str(rule.get("name") or "").strip()
        level = str(rule.get("level") or "").strip()
        fit = str(rule.get("fit") or "").strip()
        if not name or not level:
            continue
        line = f"{name} ({level}{', ' + fit if fit else ''})"
        if fit == "avoid" or level == "none":
            avoid_rules.append(line)
        else:
            preferred_rules.append(line)

    if preferred_rules:
        lines.append("Capability profile: " + "; ".join(preferred_rules[:8]))
    if avoid_rules:
        lines.append("Avoid or weak-fit areas: " + "; ".join(avoid_rules[:6]))

    return "\n".join(lines).strip()[:3000]


def _normalize_evidence_signal_candidates(items: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    business_words = {
        "analysis",
        "analyst",
        "business",
        "process",
        "data",
        "project",
        "sql",
        "api",
        "agile",
        "bpmn",
        "product",
        "delivery",
        "requirements",
        "integration",
        "stakeholder",
        "testing",
        "azure",
        "java",
        "python",
    }
    for item in items or []:
        text = (
            str(item or "")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\\r\\n", "\n")
            .replace("\\n", "\n")
            .replace("\\r", "\n")
        )
        for part in text.split("\n"):
            value = re.sub(r"\s+", " ", part).strip(" -")
            if not value:
                continue
            if value.startswith("#"):
                continue
            if value.upper() == value and len(value.split()) > 1:
                continue
            if len(value.split()) > 8:
                continue
            if len(value) > 60 or "," in value:
                continue
            if re.search(r"\b(?:19|20)\d{2}\b", value):
                continue
            words = value.split()
            if 2 <= len(words) <= 4 and all(re.fullmatch(r"[A-Z][a-z]+", word) for word in words):
                if not any(word.lower() in business_words for word in words):
                    continue
            normalized = value.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            cleaned.append(value)
    return cleaned[:20]


def import_source_materials_to_profile(materials: dict[str, Any] | None = None) -> dict[str, Any]:
    """Thin wrapper — normalises materials then delegates to run_onboarding."""
    resolved = normalize_source_materials(materials or load_source_materials(create_if_missing=True))
    result = run_onboarding(resolved)
    result["materials"] = resolved
    return result


def import_uploaded_documents_to_profile(files_payload: list[dict[str, Any]], extra_text: str = "") -> dict[str, Any]:
    imported_sources: list[dict[str, Any]] = []
    missing_sources: list[str] = []
    combined_sections: list[str] = []
    source_sections: list[dict[str, str]] = []

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
        source_sections.append({"label": label, "text": text})

    if not combined_sections:
        raise ValueError("No readable onboarding documents were provided.")

    combined_text = "\n\n".join(combined_sections).strip()
    return _build_profile_import_result(imported_sources, missing_sources, combined_text, source_sections)
