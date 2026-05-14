"""Shared path helpers for package modules."""

from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "output"
TEMPLATES_DIR = REPO_ROOT / "templates"
DOCS_DIR = REPO_ROOT / "docs"
DASHBOARD_FILENAME = "dashboard.html"

# Per-user data lives under this directory.
USERS_DIR = DATA_DIR / "users"

# Server-level output (not per-user)
SERVER_LOG_PATH = OUTPUT_DIR / "server.log"
DEBUG_SOURCE_PAYLOADS_DIR = REPO_ROOT / "debug" / "source_payloads"
# Persistent Playwright profile so local testing can reuse login state.
PLAYWRIGHT_USER_DATA_DIR = DATA_DIR / "playwright_user_data"

# Web Assets (global, not per-user)
STATIC_DIR = TEMPLATES_DIR / "static"
WORKSPACE_HTML_PATH = TEMPLATES_DIR / "workspace.html"
SETTINGS_HTML_PATH = TEMPLATES_DIR / "settings.html"
ONBOARDING_HTML_PATH = TEMPLATES_DIR / "onboarding.html"
SHOWCASE_PATH = DOCS_DIR / "SHOWCASE.html"


def _active_user_dir() -> Path | None:
    from job_hunter_agent.user_context import get_user_id
    uid = get_user_id()
    return (USERS_DIR / uid) if uid else None


def get_profile_path() -> Path:
    d = _active_user_dir()
    return (d / "profile.json") if d else DATA_DIR / "profile.json"


def get_job_history_path() -> Path:
    d = _active_user_dir()
    return (d / "job_history.json") if d else DATA_DIR / "job_history.json"


def get_review_data_path() -> Path:
    d = _active_user_dir()
    return (d / "review_data.json") if d else OUTPUT_DIR / "review_data.json"


def get_run_stats_path() -> Path:
    d = _active_user_dir()
    return (d / "run_stats.json") if d else OUTPUT_DIR / "run_stats.json"


def get_dashboard_path() -> Path:
    d = _active_user_dir()
    return (d / DASHBOARD_FILENAME) if d else OUTPUT_DIR / DASHBOARD_FILENAME


def get_audit_records_path() -> Path:
    d = _active_user_dir()
    return (d / "audit_records.json") if d else OUTPUT_DIR / "audit_records.json"


def get_source_materials_path() -> Path:
    d = _active_user_dir()
    return (d / "application_materials.json") if d else DATA_DIR / "application_materials.json"


def get_source_pack_dir() -> Path:
    d = _active_user_dir()
    return (d / "source_pack") if d else DATA_DIR / "application_inputs" / "source_pack"
ADVANCE_SETTINGS_PATH = DATA_DIR / "advance_settings.json"
SCORING_RULES_PATH = DATA_DIR / "scoring_rules.json" 
MATCH_LEVEL_DEFAULTS_PATH = DATA_DIR / "match_level_defaults.json"
FIT_REVIEW_DEFAULTS_PATH = DATA_DIR / "llm_fit_review_defaults.json" 
HARD_BLOCKER_RULES_PATH = DATA_DIR / "hard_blocker_rules.json"
CAPABILITY_KNOWLEDGE_PATH = DATA_DIR / "capability_knowledge.json"
ROLE_TITLE_KNOWLEDGE_PATH = DATA_DIR / "role_title_knowledge.json"
GOVERNMENT_CONTEXT_KNOWLEDGE_PATH = DATA_DIR / "government_context_knowledge.json"
HARD_BLOCKER_KNOWLEDGE_PATH = DATA_DIR / "hard_blocker_knowledge.json"
CV_FARMING_RULES_PATH = DATA_DIR / "cv_farming_rules.json"
CV_FARMING_RULES_NAME = "cv_farming_rules"
CV_FARMING_RULES_VERSION = 1
CV_FARMING_RULES_DESCRIPTION = "Learned language patterns that suggest the employer is collecting CVs rather than advertising a live role."
IGNORED_SIGNAL_ARCHIVE_PATH = DATA_DIR / "ignored_signal.json"
LLM_CAPABILITY_NAMING_DEFAULTS_PATH = DATA_DIR / "llm_capability_naming_defaults.json"
LLM_COSTS_PATH = DATA_DIR / "llm_costs.jsonl"
SIGNAL_REGISTRY_PATH = DATA_DIR / "signal_registry.json"
SIGNAL_DEFAULTS_PATH = DATA_DIR / "signal_defaults.json"
UI_LABELS_PATH = DATA_DIR / "ui_labels.json"
WORK_MODE_RULES_PATH = DATA_DIR / "work_mode_rules.json"
LLM_CACHE_PATH = DATA_DIR / "llm_cache.json"
GOVERNMENT_CONTEXT_RULES_PATH = DATA_DIR / "government_context_rules.json"
POSTING_CHANNEL_INDICATORS_PATH = DATA_DIR / "posting_channel_indicators.json"
TITLE_NORMALIZATION_RULES_PATH = DATA_DIR / "title_normalization_rules.json"
DUPLICATE_RULES_PATH = DATA_DIR / "duplicate_rules.json"
COMPANY_RULES_PATH = DATA_DIR / "company_rules.json"
SOURCE_REGISTRY_PATH = DATA_DIR / "source_registry.json"
PARSING_RULES_PATH = DATA_DIR / "parsing_rules.json"
DODGY_JOB_RULES_PATH = DATA_DIR / "dodgy_job_rules.json"
RESULTS_TEMPLATE_PATH = TEMPLATES_DIR / "results.html"
