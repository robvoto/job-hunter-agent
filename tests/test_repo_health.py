"""Tests for repo health."""

import importlib
from pathlib import Path

from job_hunter_agent import profile_store
from job_hunter_agent.global_settings import KEY_LINKEDIN_EASY_APPLY_ONLY
from job_hunter_agent.profile_store import (
    DEFAULT_PROFILE,
    DEFAULT_SEARCH_SETTINGS,
    normalize_search_settings,
    normalize_work_mode_preferences,
)

ROOT_DIR = Path(__file__).resolve().parent.parent


def test_no_legacy_directory_remains():

    assert not (ROOT_DIR / "legacy").exists()


def test_default_search_settings_are_candidate_agnostic():

    assert DEFAULT_SEARCH_SETTINGS["keywords"] == ""

    assert DEFAULT_SEARCH_SETTINGS["locations"] == []

    assert DEFAULT_SEARCH_SETTINGS["classification_ids"] == []

    assert DEFAULT_SEARCH_SETTINGS["seek_max_pages"] > 0


def test_search_settings_clamp_source_fetch_limits():

    normalized = normalize_search_settings(
        {
            "seek_max_pages": 100,
            "linkedin_hours_old": 999,
            "linkedin_results_per_search": 1,
            KEY_LINKEDIN_EASY_APPLY_ONLY: "false",
        }
    )

    assert (
        normalized["seek_max_pages"]
        == profile_store.load_global_settings()["limits"]["search"]["seek_max_pages"]["max"]
    )

    assert (
        normalized["linkedin_hours_old"]
        == profile_store.load_global_settings()["limits"]["search"]["linkedin_hours_old"]["max"]
    )

    assert normalized["linkedin_results_per_search"] == 5

    assert normalized[KEY_LINKEDIN_EASY_APPLY_ONLY] is False


def test_search_settings_follow_managed_search_limits(monkeypatch):

    monkeypatch.setattr(
        profile_store,
        "load_global_settings",
        lambda: {
            "limits": {
                "search": {
                    "date_range_days": {"min": 1, "max": 9},
                    "seek_max_pages": {"min": 1, "max": 12},
                    "linkedin_hours_old": {"min": 1, "max": 72},
                    "linkedin_results_per_search": {"min": 5, "max": 40},
                }
            }
        },
    )

    normalized = profile_store.normalize_search_settings(
        {
            "seek_max_pages": 100,
            "date_range_days": 99,
            "linkedin_hours_old": 999,
            "linkedin_results_per_search": 1,
        }
    )

    assert normalized["seek_max_pages"] == 12

    assert normalized["date_range_days"] == 9

    assert normalized["linkedin_hours_old"] == 72

    assert normalized["linkedin_results_per_search"] == 5


def test_default_match_preferences_are_neutral():

    prefs = DEFAULT_PROFILE["match_preferences"]

    assert prefs["home_location"] == ""

    assert prefs["secondary_location"] == ""

    assert prefs["work_mode_preference"] == ["remote", "hybrid", "onsite"]

    assert prefs["prefer_sector"] == []

    assert prefs["prefer_permanent"] is False

    assert normalize_work_mode_preferences([]) == []


def test_candidate_application_history_defaults_do_not_ship_personal_sheet_config():

    import json

    settings_path = ROOT_DIR / "data" / "config" / "global_settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    history_settings = settings["candidate_application_history"]

    assert history_settings["enabled"] is True
    assert history_settings["source_type"] == "local_runtime_json"
    assert history_settings["sync_before_run"] is False
    assert history_settings["spreadsheet_id"] == ""
    assert history_settings["tab_name"] == ""


def test_showcase_notes_are_indexed_and_proof_oriented():
    doc_index = (ROOT_DIR / "docs" / "DOC_INDEX.md").read_text(encoding="utf-8")
    showcase_notes = (ROOT_DIR / "docs" / "SHOWCASE_NOTES.md").read_text(encoding="utf-8")

    assert "docs/SHOWCASE_NOTES.md" in doc_index
    assert "Proof / demo note" in showcase_notes
    assert "Keep claims tied to visible behaviour or tests in the repo." in showcase_notes


def test_user_guide_documents_cv_structure_and_search_placement():
    user_guide = (ROOT_DIR / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")

    assert "CV Structure For Better Extraction" in user_guide
    assert "roles listed in reverse chronological order" in user_guide
    assert "dates for each role, ideally month and year" in user_guide
    assert "Search placement rule:" in user_guide
    assert "configure search terms, location, enabled sources, and preference settings in `Settings`" in user_guide
    assert "start or stop an actual search from the `Workspace`" in user_guide


def test_scoring_rationale_documents_location_scoring_decision():
    scoring_rationale = (ROOT_DIR / "docs" / "SCORING_RATIONALE.md").read_text(
        encoding="utf-8"
    )

    assert "Location scoring decision" in scoring_rationale
    assert "weak preference signal rather than strong fit evidence" in scoring_rationale
    assert "Future radius support should make the decision explicit" in scoring_rationale


def test_scoring_rationale_documents_missing_cv_evidence_default():
    scoring_rationale = (ROOT_DIR / "docs" / "SCORING_RATIONALE.md").read_text(
        encoding="utf-8"
    )

    assert "Missing CV evidence default" in scoring_rationale
    assert "the system must not claim the candidate has it" in scoring_rationale
    assert "missing evidence is treated as `not_shown`" in scoring_rationale
    assert "not automatically become a hard rejection" in scoring_rationale


def test_architecture_and_user_guide_document_raw_cv_retention_decision():
    architecture = (ROOT_DIR / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    user_guide = (ROOT_DIR / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")

    assert "Raw uploaded CV retention decision:" in architecture
    assert "uploaded CV files are onboarding input, not long-term user-facing records" in architecture
    assert "future application-pack features must ask for or manage source documents explicitly" in architecture
    assert "the raw uploaded CV is not treated as the ongoing source of truth" in user_guide
    assert "packaged/shared builds must not include developer CVs" in user_guide


def test_developer_guide_documents_prompt_context_loading_rule():
    developer_guide = (ROOT_DIR / "docs" / "DEVELOPER_GUIDE.md").read_text(
        encoding="utf-8"
    )

    assert "LLM Prompt Context Loading" in developer_guide
    assert "`build_system_prompt()` calls `build_profile_prompt_context()` internally" in developer_guide
    assert "do not call both in the same prompt assembly path" in developer_guide
    assert "request-scoped prompt context object" in developer_guide


def test_showcase_notes_are_available_in_docs_api_allow_list():
    from job_hunter_agent.config import ALLOWED_DOC_REL_PATHS

    assert "docs/SHOWCASE_NOTES.md" in ALLOWED_DOC_REL_PATHS


def test_workspace_title_block_copy_is_managed_and_explains_impact():
    import json

    labels = json.loads((ROOT_DIR / "data" / "knowledge" / "ui_labels.json").read_text(encoding="utf-8"))
    card_labels = labels["workspace_card_labels"]
    renderer = (ROOT_DIR / "job_hunter_agent" / "workspace_renderer.py").read_text(
        encoding="utf-8"
    )

    assert card_labels["title_block_button_label"] == "Hide similar titles"
    assert "before Job Hunter spends time reading the full ad" in card_labels["title_block_button_tooltip"]
    assert "avoids spending time or AI tokens on repeated noise" in card_labels["title_block_guidance_copy"]
    assert "_workspace_label(\"workspace_card_labels\", \"title_block_guidance_copy\"" in renderer


def test_recent_roles_label_no_longer_exists_in_runtime_ui():
    checked_paths = [
        ROOT_DIR / "data" / "knowledge" / "ui_labels.json",
        ROOT_DIR / "job_hunter_agent" / "workspace_renderer.py",
        ROOT_DIR / "templates" / "results.html",
        ROOT_DIR / "templates" / "settings.html",
        ROOT_DIR / "templates" / "onboarding.html",
    ]

    for path in checked_paths:
        assert "Recent roles" not in path.read_text(encoding="utf-8")


def test_no_module_uses_logger_without_defining_it():
    """Catch any module that calls logger.X() without logger = logging.getLogger(__name__)."""
    import ast

    pkg_root = ROOT_DIR / "job_hunter_agent"
    offenders = []

    for path in sorted(pkg_root.rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src, filename=str(path))
        except SyntaxError:
            continue

        # Collect line numbers of module-level `logger = ...` assignments.
        logger_assigned_at = set()
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "logger":
                        logger_assigned_at.add(node.lineno)
            elif isinstance(node, (ast.AnnAssign,)):
                if isinstance(getattr(node, "target", None), ast.Name) and node.target.id == "logger":
                    logger_assigned_at.add(node.lineno)

        if logger_assigned_at:
            continue  # module defines logger — OK

        # Check for any attribute access on a bare `logger` name.
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "logger"
            ):
                rel = path.relative_to(ROOT_DIR)
                offenders.append(f"{rel}:{node.lineno} — logger.{node.attr}() used but logger not defined")
                break  # one report per file is enough

    assert not offenders, (
        "These modules use `logger` without defining it:\n  " + "\n  ".join(offenders)
    )


def test_active_modules_import():

    modules = [
        "job_hunter_agent.agent_runner",
        "job_hunter_agent.capability_matching",
        "job_hunter_agent.config",
        "job_hunter_agent.cv_pipeline",
        "job_hunter_agent.description_trust",
        "job_hunter_agent.fastapi_app",
        "job_hunter_agent.filters",
        "job_hunter_agent.fit_scoring",
        "job_hunter_agent.history",
        "job_hunter_agent.llm_gate",
        "job_hunter_agent.preferences",
        "job_hunter_agent.profile_learning",
        "job_hunter_agent.profile_store",
        "job_hunter_agent.review_insights",
        "job_hunter_agent.salary",
        "job_hunter_agent.scrape_finalize",
        "job_hunter_agent.scrapers.base",
        "job_hunter_agent.scrapers.linkedin",
        "job_hunter_agent.scrapers.seek",
        "job_hunter_agent.scrapers.seek_runner",
        "job_hunter_agent.server_helpers",
        "job_hunter_agent.signal_registry",
        "job_hunter_agent.source_connector",
        "job_hunter_agent.source_documents",
        "job_hunter_agent.user_settings",
        "job_hunter_agent.utils",
        "job_hunter_agent.workspace_rebuild_service",
        "job_hunter_agent.workspace_refresh_service",
        "job_hunter_agent.workspace_service",
        "job_hunter_agent.routes.onboarding_api",
        "job_hunter_agent.routes.pages",
        "job_hunter_agent.routes.signals",
        "job_hunter_agent.routes.workspace_api",
    ]

    for module in modules:
        importlib.import_module(module)
