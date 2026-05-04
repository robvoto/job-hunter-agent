"""Shared path helpers for package modules."""

from pathlib import Path
from job_hunter_agent.config import OUTPUT_HTML


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "output"
TEMPLATES_DIR = REPO_ROOT / "templates"
DOCS_DIR = REPO_ROOT / "docs"

# Specific file paths
AUDIT_RECORDS_PATH = OUTPUT_DIR / "audit_records.json"
RUN_STATS_PATH = OUTPUT_DIR / "run_stats.json"
REVIEW_DATA_PATH = OUTPUT_DIR / "review_data.json"
JOB_HISTORY_PATH = DATA_DIR / "job_history.json"
REJECTION_RULES_PATH = OUTPUT_DIR / "rejection_rules.json"
REJECTION_RULE_CATEGORY_KNOWLEDGE_PATH = DATA_DIR / "rejection_rule_categories.json"

# Web Assets
STATIC_DIR = TEMPLATES_DIR / "static"
WORKSPACE_HTML_PATH = TEMPLATES_DIR / "workspace.html"
SETTINGS_HTML_PATH = TEMPLATES_DIR / "settings.html"
ONBOARDING_HTML_PATH = TEMPLATES_DIR / "onboarding.html"
SHOWCASE_PATH = DOCS_DIR / "SHOWCASE.html"
DASHBOARD_PATH = REPO_ROOT / OUTPUT_HTML

PROFILE_PATH = DATA_DIR / "profile.json"
SCORING_RULES_PATH = DATA_DIR / "scoring_rules.json" 
MATCH_LEVEL_DEFAULTS_PATH = DATA_DIR / "match_level_defaults.json"
FIT_REVIEW_DEFAULTS_PATH = DATA_DIR / "llm_fit_review_defaults.json" 
HARD_BLOCKER_RULES_PATH = DATA_DIR / "hard_blocker_rules.json"
CAPABILITY_KNOWLEDGE_PATH = DATA_DIR / "capability_knowledge.json"
ROLE_TITLE_KNOWLEDGE_PATH = DATA_DIR / "role_title_knowledge.json"
GOVERNMENT_CONTEXT_KNOWLEDGE_PATH = DATA_DIR / "government_context_knowledge.json"
HARD_BLOCKER_KNOWLEDGE_PATH = DATA_DIR / "hard_blocker_knowledge.json"
IGNORED_SIGNAL_ARCHIVE_PATH = DATA_DIR / "ignored_signal.json"
LLM_CAPABILITY_NAMING_DEFAULTS_PATH = DATA_DIR / "llm_capability_naming_defaults.json"
LLM_COSTS_PATH = DATA_DIR / "llm_costs.jsonl"
SIGNAL_REGISTRY_PATH = DATA_DIR / "signal_registry.json"
LLM_CACHE_PATH = DATA_DIR / "llm_cache.json"
GOVERNMENT_CONTEXT_RULES_PATH = DATA_DIR / "government_context_rules.json"
RESULTS_TEMPLATE_PATH = TEMPLATES_DIR / "results.html"
