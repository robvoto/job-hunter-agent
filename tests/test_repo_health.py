"""Tests for repo health."""

import ast
import importlib
import re
import subprocess
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
_MOJIBAKE_MARKERS = ("â€™", "â€œ", "â€�", "â€˜", "â€ž", "â€“", "â€”", "â€¦", "Ã¢", "Ãƒ", "�")

_ACTIVE_MODULES = [
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
            "linkedin_jobspy_stall_timeout_seconds": 999,
            "linkedin_parallel_review_workers": 9,
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
    assert "linkedin_jobspy_stall_timeout_seconds" not in normalized
    assert "linkedin_parallel_review_workers" not in normalized

    assert normalized[KEY_LINKEDIN_EASY_APPLY_ONLY] is False


def test_search_settings_normalize_locations_dedupes_and_caps_to_managed_limit():

    normalized = normalize_search_settings(
        {
            "locations": [" Sydney ", "NSW", "Sydney", "Canberra", "Melbourne"],
        }
    )

    assert normalized["locations"] == ["Sydney", "NSW", "Canberra"]


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
            "linkedin_jobspy_stall_timeout_seconds": 999,
        }
    )

    assert normalized["seek_max_pages"] == 12

    assert normalized["date_range_days"] == 9

    assert normalized["linkedin_hours_old"] == 72

    assert normalized["linkedin_results_per_search"] == 5
    assert "linkedin_jobspy_stall_timeout_seconds" not in normalized


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
    assert history_settings["spreadsheet_id"] == ""
    assert history_settings["tab_name"] == ""


def test_docs_index_routes_to_core_and_integration_docs():
    docs_index = (ROOT_DIR / "docs" / "INDEX.md").read_text(encoding="utf-8")
    readme = (ROOT_DIR / "README.md").read_text(encoding="utf-8")

    assert "[README.md](../README.md)" in docs_index
    assert "[USER_GUIDE.md](USER_GUIDE.md)" in docs_index
    assert "[OPERATIONS.md](OPERATIONS.md)" in docs_index
    assert "[ARCHITECTURE.md](ARCHITECTURE.md)" in docs_index
    assert "[DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md)" in docs_index
    assert "[INTEGRATIONS.md](INTEGRATIONS.md)" in docs_index
    assert "[SOURCE_REGISTER.md](SOURCE_REGISTER.md)" in docs_index
    assert "[SCORING_RATIONALE.md](SCORING_RATIONALE.md)" in docs_index
    assert "[aws-ec2-setup.md](aws-ec2-setup.md)" in docs_index
    assert "[docs/INDEX.md](docs/INDEX.md)" in readme
    assert "[docs/INTEGRATIONS.md](docs/INTEGRATIONS.md)" in readme


def test_doc_index_points_to_canonical_docs_index():
    doc_index = (ROOT_DIR / "docs" / "DOC_INDEX.md").read_text(encoding="utf-8")

    assert "Canonical navigation starts at [docs/INDEX.md](INDEX.md)." in doc_index
    assert "`docs/INDEX.md`" in doc_index


def test_agents_routes_durable_rules_through_skills():
    agents = (ROOT_DIR / "AGENTS.md").read_text(encoding="utf-8")
    skills_index = (ROOT_DIR / ".agents/skills" / "INDEX.md").read_text(encoding="utf-8")

    assert ".agents/skills/INDEX.md" in agents
    assert ".agents/skills/instruction-maintenance/SKILL.md" in agents
    assert ".agents/skills/mcp-tooling/SKILL.md" in agents
    assert "before the first repository/tool command" in agents
    assert "create a focused skill" in agents
    assert "Detailed rules belong inside each skill" in skills_index


def test_legacy_skills_root_does_not_return():
    assert not (ROOT_DIR / ".skills").exists(), "Use the canonical .agents/skills repository skill root"
    assert (ROOT_DIR / ".agents" / "skills" / "INDEX.md").exists()


def test_all_active_skills_are_indexed_and_discoverable():
    skills_root = ROOT_DIR / ".agents/skills"
    skills_index = (skills_root / "INDEX.md").read_text(encoding="utf-8")

    for skill_path in sorted(skills_root.glob("*/SKILL.md")):
        text = skill_path.read_text(encoding="utf-8")
        skill_name = skill_path.parent.name
        assert text.startswith("---\n"), f"{skill_path} must start with YAML frontmatter"
        assert f"name: {skill_name}" in text, f"{skill_path} frontmatter name must match its folder"
        assert "description:" in text, f"{skill_path} must include a routing description"
        assert f"`{skill_name}/SKILL.md`" in skills_index, f"{skill_name} is missing from .agents/skills/INDEX.md"


def test_top_level_docs_are_routed_from_docs_index():
    docs_root = ROOT_DIR / "docs"
    docs_index = (docs_root / "INDEX.md").read_text(encoding="utf-8")
    excluded = {"INDEX.md", "CLINE_MEMORY.md"}

    missing = [
        path.name
        for path in sorted(docs_root.glob("*.md"))
        if path.name not in excluded and path.name not in docs_index
    ]
    assert not missing, "Top-level docs must be routed from docs/INDEX.md: " + ", ".join(missing)


def test_jobhunter_status_defaults_to_concise_summary():
    script = (ROOT_DIR / "scripts" / "ec2" / "jobhunter-status.sh").read_text(encoding="utf-8")

    assert 'jobhunter-status --verbose' in script
    assert 'jobhunter-status --follow' in script
    assert 'echo "Service: ${SERVICE}.service"' in script
    assert 'echo "Local:   $(status_line "$HEALTH_URL")"' in script
    assert 'sudo systemctl status "$SERVICE" --no-pager || true' in script
    assert 'sudo journalctl -u "$SERVICE" -n 30 --no-pager || true' in script
    assert 'if [[ "$MODE" == "--verbose" || "$MODE" == "-v" ]]; then' in script


def test_integrations_doc_captures_local_override_and_runtime_seed_boundary():
    integrations = (ROOT_DIR / "docs" / "INTEGRATIONS.md").read_text(encoding="utf-8")

    assert "rob_candidate_application_history_import.local.json" in integrations
    assert "approved repo-managed JSON seed manifest" in integrations
    assert "Google Sheet backlog is project-management infrastructure" in integrations
    assert "user-owned credentials only" in integrations


def _onet_algorithm_signature(source_text: str) -> tuple[str, str]:
    tree = ast.parse(source_text)
    segments: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "LOOKUP_MATCHER_VERSION":
                    segments["LOOKUP_MATCHER_VERSION"] = ast.get_source_segment(source_text, node) or ""
        elif isinstance(node, ast.FunctionDef) and node.name in {
            "_compute_profile_hash",
            "_derive_target_occupation_codes",
            "_select_embedded_phrase_match",
            "_classify_codes",
            "_classify_embedded_phrase_codes",
            "classify_title",
        }:
            segments[node.name] = ast.get_source_segment(source_text, node) or ""

    version_assignment = segments.pop("LOOKUP_MATCHER_VERSION")
    normalized_logic = "\n".join(value.strip() for key, value in sorted(segments.items()))
    return version_assignment.strip(), normalized_logic.strip()


def test_onet_matcher_version_changes_when_algorithm_logic_changes():
    occupation_taxonomy_path = ROOT_DIR / "job_hunter_agent" / "occupation_taxonomy.py"
    current_text = occupation_taxonomy_path.read_text(encoding="utf-8")
    head_text = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT_DIR),
            "show",
            f"HEAD:{occupation_taxonomy_path.relative_to(ROOT_DIR).as_posix()}",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout

    current_version, current_logic = _onet_algorithm_signature(current_text)
    head_version, head_logic = _onet_algorithm_signature(head_text)

    if current_logic != head_logic:
        assert current_version != head_version, (
            "O*NET classification logic changed but LOOKUP_MATCHER_VERSION did not. "
            "Bump the matcher/cache version when material classification logic changes."
        )


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


def test_scoring_and_operations_docs_cover_fit_evidence_and_run_summary_semantics():
    scoring_rationale = (ROOT_DIR / "docs" / "SCORING_RATIONALE.md").read_text(
        encoding="utf-8"
    )
    user_guide = (ROOT_DIR / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    operations = (ROOT_DIR / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")

    assert "requirement coverage only" in scoring_rationale
    assert "matched source text, capability mapping, and reviewed-signal evidence" in scoring_rationale
    assert "primary user-facing evidence is requirement coverage" in user_guide
    assert "location, freshness, Easy Apply / Quick Apply, viewed status, salary, and action recommendations" in user_guide
    assert "Run summary semantics:" in operations
    assert "source/platform `read` counts must reconcile with the total `descriptions read`" in operations
    assert "do not treat every LinkedIn row as a page" in operations


def test_repository_runtime_commands_use_uv_and_classify_missing_binaries_correctly():
    tooling_skill = (ROOT_DIR / ".agents/skills" / "mcp-tooling" / "SKILL.md").read_text(encoding="utf-8")
    operations = (ROOT_DIR / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    aws_launcher = (
        ROOT_DIR / "scripts" / "ec2" / "start-aws-browser-session.sh"
    ).read_text(encoding="utf-8")

    assert "Never invoke bare `python`, `python3`, `pytest`, or `ruff`" in tooling_skill
    assert "never reach into another worktree's `.venv`" in tooling_skill
    assert "Do not invent or pass a `timeout` argument" in tooling_skill
    assert "node --input-type=module --check < path/to/file.js" in tooling_skill
    assert "Never use plain `node --check path/to/file.js`" in tooling_skill
    assert "never run the entire pytest suite in one connector call" in tooling_skill
    assert "do not background it" in tooling_skill
    assert "./scripts/run-pytest-mcp.sh 1 3" in tooling_skill
    assert "not a database, application, repository-access, or dependency failure" in tooling_skill
    assert "uv run python -m job_hunter_agent.source_connector" in operations
    assert "\npython -m job_hunter_agent.source_connector" not in operations
    assert "set -- uv run python -m job_hunter_agent.fastapi_app --rebuild" in aws_launcher


def test_mcp_pytest_runner_uses_contiguous_serial_slices():
    script_path = ROOT_DIR / "scripts" / "run-pytest-mcp.sh"
    script = script_path.read_text(encoding="utf-8")

    assert script_path.stat().st_mode & 0o111
    assert "find tests -maxdepth 1 -type f -name 'test_*.py' | sort" in script
    assert "chunk=$(( (count + total - 1) / total ))" in script
    assert 'selected=("${files[@]:start:chunk}")' in script
    assert 'exec uv run pytest -q --tb=short "${selected[@]}"' in script
    assert "-n 6" not in script


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


def test_workspace_title_block_copy_is_managed_and_explains_impact():
    import json

    labels = json.loads((ROOT_DIR / "data" / "knowledge" / "ui_labels.json").read_text(encoding="utf-8"))
    card_labels = labels["workspace_card_labels"]
    renderer = (ROOT_DIR / "job_hunter_agent" / "workspace_renderer.py").read_text(
        encoding="utf-8"
    )

    assert card_labels["title_block_button_label"] == "Hide similar titles"
    assert "exact phrases you choose" in card_labels["title_block_button_tooltip"]
    assert "checks this phrase against job titles" in card_labels["title_block_guidance_copy"]
    assert "_workspace_label(\"workspace_card_labels\", \"title_block_guidance_copy\"" in renderer


def test_results_panel_styles_use_shared_outer_panel_and_inset_job_cards():
    workspace_css = (
        ROOT_DIR / "templates" / "static" / "workspace" / "workspace-page.css"
    ).read_text(encoding="utf-8")
    results_css = (
        ROOT_DIR / "templates" / "static" / "results" / "results-page.css"
    ).read_text(encoding="utf-8")

    assert ".results-section-body {\n  padding: 16px;\n}" in workspace_css
    assert ".section--results-panel .job-grid {\n  gap: 16px;\n}" in workspace_css
    job_card_block = re.search(r"\.job-card \{(?P<body>.*?)\n\}", results_css, re.S)
    assert job_card_block is not None
    body = job_card_block.group("body")
    assert "border: 1px solid color-mix(in srgb, var(--accent) 38%, var(--border-subtle));" in body
    assert "border-radius: 14px;" in body
    assert "border-bottom:" not in body


def test_requirement_importance_badge_stays_visually_attached_to_requirement_text():
    results_css = (
        ROOT_DIR / "templates" / "static" / "results" / "results-page.css"
    ).read_text(encoding="utf-8")

    assert ".job-requirement-list {\n  list-style: none;\n  padding-left: 0 !important;\n  display: flex;" in results_css
    assert ".job-requirement-item {\n  display: block;" in results_css
    assert "flex-wrap: wrap;" in results_css
    assert ".job-requirement-title-line {\n  display: flex;" in results_css
    assert ".job-req-importance {" in results_css
    assert ".job-requirement-status" not in results_css


def test_capability_strength_controls_use_shared_semantic_tone_classes():
    capability_editor_js = (
        ROOT_DIR / "templates" / "static" / "settings" / "shared" / "settings-capability-editor.js"
    ).read_text(encoding="utf-8")
    review_panel_js = (
        ROOT_DIR / "templates" / "static" / "settings" / "shared" / "settings-review-panel.js"
    ).read_text(encoding="utf-8")
    settings_css = (
        ROOT_DIR / "templates" / "static" / "settings" / "shared" / "settings-page.css"
    ).read_text(encoding="utf-8")
    theme_widgets = (
        ROOT_DIR / "templates" / "static" / "theme" / "themes.widgets.css"
    ).read_text(encoding="utf-8")

    assert "capability-strength-meter ${escapeHtml(selectedStrengthMeta.tone || '')}" in capability_editor_js
    assert "selectedStrengthMeta.summary" in capability_editor_js
    assert ".capability-strength-meter.strength-strong" in settings_css
    assert ".capability-strength-meter.strength-working" in settings_css
    assert ".capability-strength-meter.strength-basic" in settings_css
    assert "choice-card jh-choice choice-card--strength ${escapeHtml(meta.tone || '')}" in review_panel_js
    assert ".choice-strip > .choice-card--strength.strength-strong" in theme_widgets
    assert ".choice-strip > .choice-card--strength.strength-working" in theme_widgets
    assert ".choice-strip > .choice-card--strength.strength-basic" in theme_widgets


def test_capability_matrix_uses_quiet_two_column_default_layout():
    capability_editor_js = (
        ROOT_DIR / "templates" / "static" / "settings" / "shared" / "settings-capability-editor.js"
    ).read_text(encoding="utf-8")
    settings_css = (
        ROOT_DIR / "templates" / "static" / "settings" / "shared" / "settings-page.css"
    ).read_text(encoding="utf-8")

    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in settings_css
    assert 'class="capability-alias-row"' in capability_editor_js
    assert "cap-alias-chip--more" not in capability_editor_js
    assert "data-enter-capability-bulk-edit" in capability_editor_js
    assert "data-exit-capability-bulk-edit" in capability_editor_js


def test_stop_state_copy_stays_intentional_and_non_failure():
    import json

    labels = json.loads((ROOT_DIR / "data" / "knowledge" / "ui_labels.json").read_text(encoding="utf-8"))
    shared = labels["shared_ui_labels"]

    assert shared["search_stopping_title"] == "Run stopped by request"
    assert "stopped on purpose" in shared["search_stopping_copy"]
    assert "not a failure" in shared["search_stopping_subcopy"]


def test_architecture_doc_has_core_file_map():
    architecture = (ROOT_DIR / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")

    assert "Core File Map" in architecture
    assert "workspace_renderer.py" in architecture
    assert "profile_store.py" in architecture
    assert "llm_gate.py" in architecture


def test_ui_labels_json_does_not_contain_mojibake_markers():
    import json

    labels = json.loads((ROOT_DIR / "data" / "knowledge" / "ui_labels.json").read_text(encoding="utf-8"))
    offenders = []

    def walk(value, path=""):
        if isinstance(value, dict):
            for key, item in value.items():
                child = f"{path}.{key}" if path else str(key)
                walk(item, child)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                child = f"{path}[{index}]" if path else f"[{index}]"
                walk(item, child)
        elif isinstance(value, str):
            if any(marker in value for marker in _MOJIBAKE_MARKERS):
                offenders.append(f"{path}: {value!r}")

    walk(labels)

    assert not offenders, f"ui_labels.json contains mojibake markers: {offenders}"


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
    for module in _ACTIVE_MODULES:
        importlib.import_module(module)


def _active_module_paths() -> dict[str, Path]:
    return {
        module: ROOT_DIR / (module.replace(".", "/") + ".py")
        for module in _ACTIVE_MODULES
    }


def _resolve_import_base(current_module: str, level: int, module: str | None) -> str:
    if level == 0:
        return module or ""
    parts = current_module.split(".")[:-level]
    if module:
        parts.extend(module.split("."))
    return ".".join(parts)


def _build_active_import_graph() -> dict[str, set[str]]:
    module_paths = _active_module_paths()
    graph: dict[str, set[str]] = {module: set() for module in module_paths}

    for module, path in module_paths.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in graph:
                        graph[module].add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                base = _resolve_import_base(module, node.level, node.module)
                if base in graph:
                    graph[module].add(base)
                for alias in node.names:
                    candidate = f"{base}.{alias.name}" if base else alias.name
                    if candidate in graph:
                        graph[module].add(candidate)
    return graph


def _find_import_cycles(graph: dict[str, set[str]]) -> set[tuple[str, ...]]:
    cycles: set[tuple[str, ...]] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def _visit(module: str) -> None:
        visited.add(module)
        stack.append(module)
        for dependency in sorted(graph[module]):
            if dependency not in visited:
                _visit(dependency)
            elif dependency in stack:
                start = stack.index(dependency)
                nodes = stack[start:]
                rotations = [tuple(nodes[i:] + nodes[:i]) for i in range(len(nodes))]
                cycles.add(min(rotations))
        stack.pop()

    for module in sorted(graph):
        if module not in visited:
            _visit(module)
    return cycles


def test_active_module_import_cycles_are_known_and_allowlisted():
    graph = _build_active_import_graph()
    cycles = _find_import_cycles(graph)
    allowed_cycles = {
        (
            "job_hunter_agent.llm_gate",
            "job_hunter_agent.profile_store",
        ),
    }

    assert cycles == allowed_cycles, (
        "Unexpected active-module import cycles detected.\n"
        f"Allowed: {sorted(allowed_cycles)}\n"
        f"Found: {sorted(cycles)}"
    )


def test_requirement_group_headings_and_summary_disclosure_have_clear_hierarchy():
    results_css = (
        ROOT_DIR / "templates" / "static" / "results" / "results-page.css"
    ).read_text(encoding="utf-8")

    assert ".job-requirement-group--partial .job-requirement-group-heading" in results_css
    assert ".job-requirement-group--attention .job-requirement-group-heading" in results_css
    assert ".job-requirement-group--matched .job-requirement-group-heading" in results_css
    assert ".job-requirement-group-heading::before" in results_css
    assert ".job-summary-toggle-label {" in results_css
    assert "clip-path: inset(50%);" in results_css


def test_tracked_text_files_use_lf_line_endings():
    """Keep the physical worktree aligned with the repository's LF-only policy."""
    result = subprocess.run(
        ["git", "ls-files", "--eol"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    bad = [
        line
        for line in result.stdout.splitlines()
        if "w/crlf" in line or "w/mixed" in line
    ]
    assert not bad, (
        "Tracked text files must use LF line endings. Normalize these files before committing:\n"
        + "\n".join(bad)
    )
