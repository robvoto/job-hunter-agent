"""Shared path helpers for package modules."""

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
DATA_DIR = Path(os.environ.get("JOB_HUNTER_DATA_DIR", REPO_ROOT / "data")).expanduser().resolve()
DEFAULTS_DIR = DATA_DIR / "defaults"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
RUNTIME_DIR = DATA_DIR / "runtime"
OUTPUT_DIR = (
    Path(os.environ.get("JOB_HUNTER_OUTPUT_DIR", REPO_ROOT / "output")).expanduser().resolve()
)
TEMPLATES_DIR = REPO_ROOT / "templates"
DOCS_DIR = REPO_ROOT / "docs"
WORKSPACE_RESULTS_FILENAME = "workspace_results.html"

# Per-user data lives under this directory.
USERS_DIR = DATA_DIR / "users"

# Server-level output (not per-user)
SERVER_LOG_PATH = OUTPUT_DIR / "server.log"
UNCERTAINTY_LOG_PATH = OUTPUT_DIR / "uncertainty.jsonl"
DEBUG_SOURCE_PAYLOADS_DIR = REPO_ROOT / "debug" / "source_payloads"
# Persistent Playwright profile so local testing can reuse login state.
PLAYWRIGHT_USER_DATA_DIR = DATA_DIR / "playwright_user_data"

# Web Assets (global, not per-user)
STATIC_DIR = TEMPLATES_DIR / "static"
WORKSPACE_HTML_PATH = TEMPLATES_DIR / "workspace.html"
SETTINGS_HTML_PATH = TEMPLATES_DIR / "settings.html"
GLOBAL_SETTINGS_HTML_PATH = TEMPLATES_DIR / "global-settings.html"
AWS_BROWSER_SESSION_HTML_PATH = TEMPLATES_DIR / "aws-browser-session.html"
SETTINGS_PARTIALS_DIR = TEMPLATES_DIR / "partials"
SETTINGS_STANDARD_PARTIALS_DIR = SETTINGS_PARTIALS_DIR / "settings" / "standard"
SETTINGS_GLOBAL_PARTIALS_DIR = SETTINGS_PARTIALS_DIR / "settings" / "global"
ONBOARDING_HTML_PATH = TEMPLATES_DIR / "onboarding.html"


def get_active_user_id() -> str:
    from job_hunter_agent.user_context import get_user_id

    uid = get_user_id()
    if uid:
        return uid
    raise RuntimeError(
        "No signed-in user is available. Log in to the app and try again."
    )


def _active_user_dir() -> Path:
    return USERS_DIR / get_active_user_id()


def get_workspace_results_path() -> Path:
    return _active_user_dir() / WORKSPACE_RESULTS_FILENAME


def get_candidate_application_history_path() -> Path:
    return RUNTIME_DIR / "candidate_application_history.json"


def get_db_path() -> Path:
    val = os.environ.get("JOB_HUNTER_DB_PATH")
    if not val:
        raise RuntimeError(
            "JOB_HUNTER_DB_PATH is not set. "
            "Set it in the systemd service file: Environment=JOB_HUNTER_DB_PATH=/var/lib/job-hunter/data/app.db"
        )
    return Path(val).expanduser().resolve()


GLOBAL_SETTINGS_PATH = DATA_DIR / "config" / "global_settings.json"
DEFAULT_USER_SETTINGS_PATH = DEFAULTS_DIR / "user_settings.json"
SCORING_RULES_PATH = KNOWLEDGE_DIR / "scoring_rules.json"
MATCH_LEVEL_DEFAULTS_PATH = KNOWLEDGE_DIR / "match_level_defaults.json"
FIT_REVIEW_DEFAULTS_PATH = KNOWLEDGE_DIR / "llm_fit_review_defaults.json"
HARD_BLOCKER_RULES_PATH = KNOWLEDGE_DIR / "hard_blocker_rules.json"
ONET_TAXONOMY_DIR = KNOWLEDGE_DIR / "occupation_taxonomy"
CAPABILITY_KNOWLEDGE_PATH = KNOWLEDGE_DIR / "capability_knowledge.json"
CV_FARMING_RULES_PATH = KNOWLEDGE_DIR / "cv_farming_rules.json"
CV_FARMING_RULES_NAME = "cv_farming_rules"
CV_FARMING_RULES_VERSION = 1
CV_FARMING_RULES_DESCRIPTION = "Learned language patterns that suggest the employer is collecting CVs rather than advertising a live role."
LLM_CAPABILITY_NAMING_DEFAULTS_PATH = KNOWLEDGE_DIR / "llm_capability_naming_defaults.json"
LLM_COSTS_PATH = RUNTIME_DIR / "llm_costs.jsonl"
UI_LABELS_PATH = KNOWLEDGE_DIR / "ui_labels.json"
WORK_MODE_RULES_PATH = KNOWLEDGE_DIR / "work_mode_rules.json"
LLM_CACHE_PATH = RUNTIME_DIR / "llm_cache.json"
CV_EXTRACTION_CACHE_PATH = RUNTIME_DIR / "cv_extraction_cache.json"
CANDIDATE_APPLICATION_HISTORY_CACHE_PATH = RUNTIME_DIR / "candidate_application_history_cache.json"
TITLE_NORMALIZATION_RULES_PATH = KNOWLEDGE_DIR / "title_normalization_rules.json"
DUPLICATE_RULES_PATH = KNOWLEDGE_DIR / "duplicate_rules.json"
COMPANY_NAME_NORMALIZATION_PATH = KNOWLEDGE_DIR / "company_name_normalization.json"
SOURCE_REGISTRY_PATH = KNOWLEDGE_DIR / "source_registry.json"
PARSING_RULES_PATH = KNOWLEDGE_DIR / "parsing_rules.json"
DODGY_JOB_RULES_PATH = KNOWLEDGE_DIR / "dodgy_job_rules.json"
RESULTS_TEMPLATE_PATH = TEMPLATES_DIR / "results.html"
