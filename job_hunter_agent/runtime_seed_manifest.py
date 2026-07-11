"""Approved repo-managed runtime seed files.

This module defines the explicit allowlists used when seeding managed JSON
into the runtime DB and copying required runtime files into JOB_HUNTER_DATA_DIR.
"""

from __future__ import annotations

from pathlib import Path

APPROVED_DB_KNOWLEDGE_JSON_REL_PATHS: tuple[str, ...] = (
    "apply_method_indicators.json",
    "capability_knowledge.json",
    "company_name_normalization.json",
    "cv_farming_rules.json",
    "description_compaction_rules.json",
    "dodgy_job_rules.json",
    "duplicate_rules.json",
    "hard_blocker_rules.json",
    "job_type.json",
    "llm_capability_naming_defaults.json",
    "llm_fit_review_defaults.json",
    "llm_fit_review_grade_defaults.json",
    "llm_job_requirements_defaults.json",
    "llm_learning_defaults.json",
    "llm_rejection_suggestions_defaults.json",
    "llm_requirement_coverage_defaults.json",
    "locations_au.json",
    "match_level_defaults.json",
    "parsing_rules.json",
    "posting_channel_indicators.json",
    "salary.json",
    "scoring_rules.json",
    "source_registry.json",
    "ui_labels.json",
    "work_mode_rules.json",
)

APPROVED_RUNTIME_KNOWLEDGE_JSON_REL_PATHS: tuple[str, ...] = (
    *APPROVED_DB_KNOWLEDGE_JSON_REL_PATHS,
    "occupation_taxonomy/onet_alternate_titles.json",
    "occupation_taxonomy/onet_index.json",
    "occupation_taxonomy/onet_occupations.json",
)

APPROVED_SIGNAL_JSON_REL_PATHS: tuple[str, ...] = ("signal_defaults.json",)


def resolve_seed_json_paths(source_dir: Path, relative_paths: tuple[str, ...]) -> list[Path]:
    """Resolve an approved JSON allowlist against source_dir and fail on gaps."""

    resolved: list[Path] = []
    for relative_path in relative_paths:
        path = (source_dir / relative_path).resolve()
        if not path.exists():
            raise FileNotFoundError(
                f"Required bundled seed file is missing from repo: {source_dir / relative_path}"
            )
        if path.suffix.lower() != ".json":
            raise ValueError(f"Approved seed path must be a JSON file: {source_dir / relative_path}")
        resolved.append(path)
    return resolved
