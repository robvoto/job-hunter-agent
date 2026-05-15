"""Shared path helpers for package modules."""

from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
DATA_DIR = REPO_ROOT / "data"
CONFIG_DIR = DATA_DIR / "config"
DEFAULTS_DIR = DATA_DIR / "defaults"
AUTH_DIR = DATA_DIR / "auth"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
SIGNALS_DIR = DATA_DIR / "signals"
RUNTIME_DIR = DATA_DIR / "runtime"
OUTPUT_DIR = REPO_ROOT / "output"
TEMPLATES_DIR = REPO_ROOT / "templates"
DOCS_DIR = REPO_ROOT / "docs"
WORKSPACE_RESULTS_FILENAME = "workspace_results.html"
USER_SETTINGS_FILENAME = "settings.json"
LOCAL_USER_ID = "_local"

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
SETTINGS_PARTIALS_DIR = TEMPLATES_DIR / "partials"
ONBOARDING_HTML_PATH = TEMPLATES_DIR / "onboarding.html"
SHOWCASE_PATH = DOCS_DIR / "SHOWCASE.html"


def _active_user_dir() -> Path | None:
    from job_hunter_agent.user_context import get_user_id
    uid = get_user_id()
    return (USERS_DIR / uid) if uid else None


def _active_or_local_user_dir() -> Path:
    d = _active_user_dir()
    return d if d is not None else USERS_DIR / LOCAL_USER_ID


def get_profile_path() -> Path:
    return _active_or_local_user_dir() / "profile.json"


def get_job_history_path() -> Path:
    return _active_or_local_user_dir() / "job_history.json"


def get_review_data_path() -> Path:
    return _active_or_local_user_dir() / "review_data.json"


def get_run_stats_path() -> Path:
    return _active_or_local_user_dir() / "run_stats.json"


def get_workspace_results_path() -> Path:
    d = _active_user_dir()
    return (d / WORKSPACE_RESULTS_FILENAME) if d else OUTPUT_DIR / WORKSPACE_RESULTS_FILENAME


def get_audit_records_path() -> Path:
    return _active_or_local_user_dir() / "audit_records.json"


def get_user_settings_path(user_id: str | None = None) -> Path:
    if user_id is None:
        d = _active_user_dir()
    else:
        d = USERS_DIR / user_id if user_id else None
    if d is None:
        d = USERS_DIR / LOCAL_USER_ID
    return d / USER_SETTINGS_FILENAME


def get_source_materials_path() -> Path:
    return _active_or_local_user_dir() / "application_materials.json"


def get_source_pack_dir() -> Path:
    return _active_or_local_user_dir() / "source_pack"
GLOBAL_SETTINGS_PATH = CONFIG_DIR / "global_settings.json"
DEFAULT_USER_SETTINGS_PATH = DEFAULTS_DIR / "user_settings.json"
SCORING_RULES_PATH = KNOWLEDGE_DIR / "scoring_rules.json"
MATCH_LEVEL_DEFAULTS_PATH = KNOWLEDGE_DIR / "match_level_defaults.json"
FIT_REVIEW_DEFAULTS_PATH = KNOWLEDGE_DIR / "llm_fit_review_defaults.json"
HARD_BLOCKER_RULES_PATH = KNOWLEDGE_DIR / "hard_blocker_rules.json"
CAPABILITY_KNOWLEDGE_PATH = KNOWLEDGE_DIR / "capability_knowledge.json"
ROLE_TITLE_KNOWLEDGE_PATH = KNOWLEDGE_DIR / "role_title_knowledge.json"
GOVERNMENT_CONTEXT_KNOWLEDGE_PATH = KNOWLEDGE_DIR / "government_context_knowledge.json"
CV_FARMING_RULES_PATH = KNOWLEDGE_DIR / "cv_farming_rules.json"
CV_FARMING_RULES_NAME = "cv_farming_rules"
CV_FARMING_RULES_VERSION = 1
CV_FARMING_RULES_DESCRIPTION = "Learned language patterns that suggest the employer is collecting CVs rather than advertising a live role."
IGNORED_SIGNAL_ARCHIVE_PATH = SIGNALS_DIR / "ignored_signal.json"
LLM_CAPABILITY_NAMING_DEFAULTS_PATH = KNOWLEDGE_DIR / "llm_capability_naming_defaults.json"
LLM_COSTS_PATH = RUNTIME_DIR / "llm_costs.jsonl"
SIGNAL_REGISTRY_PATH = SIGNALS_DIR / "signal_registry.json"
SIGNAL_DEFAULTS_PATH = SIGNALS_DIR / "signal_defaults.json"
UI_LABELS_PATH = KNOWLEDGE_DIR / "ui_labels.json"
WORK_MODE_RULES_PATH = KNOWLEDGE_DIR / "work_mode_rules.json"
LLM_CACHE_PATH = RUNTIME_DIR / "llm_cache.json"
GOVERNMENT_CONTEXT_RULES_PATH = KNOWLEDGE_DIR / "government_context_rules.json"
POSTING_CHANNEL_INDICATORS_PATH = KNOWLEDGE_DIR / "posting_channel_indicators.json"
TITLE_NORMALIZATION_RULES_PATH = KNOWLEDGE_DIR / "title_normalization_rules.json"
DUPLICATE_RULES_PATH = KNOWLEDGE_DIR / "duplicate_rules.json"
COMPANY_RULES_PATH = KNOWLEDGE_DIR / "company_rules.json"
SOURCE_REGISTRY_PATH = KNOWLEDGE_DIR / "source_registry.json"
PARSING_RULES_PATH = KNOWLEDGE_DIR / "parsing_rules.json"
DODGY_JOB_RULES_PATH = KNOWLEDGE_DIR / "dodgy_job_rules.json"
RESULTS_TEMPLATE_PATH = TEMPLATES_DIR / "results.html"
