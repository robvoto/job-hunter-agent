"""Seed the database and runtime-managed files from the repo's bundled JSON files.

Run once on first deployment (or after a DB reset):

    python -m job_hunter_agent.db_seed

The script is safe to run again - INSERT OR IGNORE means existing data is
never overwritten.

Upgrade flags:

  --upgrade  Version-aware merge: adds new entries from updated JSON files
             without touching existing DB entries (including user-approved ones).
             Use after shipping new baseline knowledge entries.

  --overwrite  Hard reset: replace all DB knowledge entries from the bundled
               files. Wipes any user-approved additions. Use only for a full
               DB reset or to recover from corruption.
"""

import argparse
import shutil
from pathlib import Path

from job_hunter_agent.runtime_helpers import load_repo_dotenv

load_repo_dotenv()

from job_hunter_agent.database import init_db
from job_hunter_agent.global_settings import seed_global_settings_from_file
from job_hunter_agent.knowledge_store import seed_knowledge_from_dir, upgrade_knowledge_from_dir
from job_hunter_agent.paths import (
    DATA_DIR,
    DEFAULT_USER_SETTINGS_PATH,
    GLOBAL_SETTINGS_PATH,
    REPO_ROOT,
)
from job_hunter_agent.runtime_seed_manifest import (
    APPROVED_DB_KNOWLEDGE_JSON_REL_PATHS,
    APPROVED_RUNTIME_KNOWLEDGE_JSON_REL_PATHS,
    APPROVED_SIGNAL_JSON_REL_PATHS,
    resolve_seed_json_paths,
)


def _copy_required_runtime_file(source: Path, target: Path) -> bool:
    """Copy a required repo-managed JSON file into JOB_HUNTER_DATA_DIR.

    Runtime on AWS reads from JOB_HUNTER_DATA_DIR, while the repo keeps the
    versioned source files under data/. The deploy/seed step must keep those
    runtime copies present so application startup is deterministic.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() == source.read_bytes():
        return False
    shutil.copy2(source, target)
    return True


def _copy_required_runtime_tree(source_dir: Path, target_dir: Path, *, relative_paths: tuple[str, ...]) -> list[str]:
    """Copy the approved repo-managed JSON seed files into DATA_DIR."""
    updated: list[str] = []
    for source in resolve_seed_json_paths(source_dir, relative_paths):
        relative_path = source.relative_to(source_dir)
        target = target_dir / relative_path
        if _copy_required_runtime_file(source, target):
            updated.append(str(target.relative_to(DATA_DIR)))
    return updated


def sync_required_runtime_files() -> list[str]:
    """Ensure required repo-managed runtime files exist under DATA_DIR."""
    required_files = [
        (REPO_ROOT / "data" / "config" / "global_settings.json", GLOBAL_SETTINGS_PATH),
        (REPO_ROOT / "data" / "defaults" / "user_settings.json", DEFAULT_USER_SETTINGS_PATH),
    ]

    updated: list[str] = []
    for source, target in required_files:
        if not source.exists():
            raise FileNotFoundError(f"Required bundled seed file is missing from repo: {source}")
        if _copy_required_runtime_file(source, target):
            updated.append(str(target.relative_to(DATA_DIR)))

    updated.extend(
        _copy_required_runtime_tree(
            REPO_ROOT / "data" / "knowledge",
            DATA_DIR / "knowledge",
            relative_paths=APPROVED_RUNTIME_KNOWLEDGE_JSON_REL_PATHS,
        )
    )
    return updated


def run(overwrite: bool = False, upgrade: bool = False) -> None:
    knowledge_dir = REPO_ROOT / "data" / "knowledge"
    signals_dir = REPO_ROOT / "data" / "signals"
    global_settings_path = REPO_ROOT / "data" / "config" / "global_settings.json"
    approved_knowledge_json = resolve_seed_json_paths(
        knowledge_dir,
        APPROVED_DB_KNOWLEDGE_JSON_REL_PATHS,
    )
    approved_signal_json = resolve_seed_json_paths(
        signals_dir,
        APPROVED_SIGNAL_JSON_REL_PATHS,
    )

    print("Initialising database...")
    init_db()

    print(f"Syncing required runtime files into {DATA_DIR} ...")
    synced_files = sync_required_runtime_files()
    print(f"  {len(synced_files)} runtime files updated: {synced_files or '(none - all current)'}")

    if upgrade:
        print(f"Upgrading knowledge from {knowledge_dir} ...")
        updated = upgrade_knowledge_from_dir(knowledge_dir, json_files=approved_knowledge_json)
        print(f"  {len(updated)} knowledge entries updated: {updated or '(none - all current)'}")

        print(f"Upgrading signals config from {signals_dir} ...")
        updated = upgrade_knowledge_from_dir(signals_dir, json_files=approved_signal_json)
        print(
            f"  {len(updated)} signal config entries updated: {updated or '(none - all current)'}"
        )

        print(f"Seeding global settings from {global_settings_path} ...")
        # Global settings has no per-entry user approvals, so upgrade always overwrites.
        written = seed_global_settings_from_file(overwrite=True)
        print(f"  {'updated' if written else 'already present'}")
    else:
        print(f"Seeding knowledge from {knowledge_dir} ...")
        seeded = seed_knowledge_from_dir(
            knowledge_dir,
            overwrite=overwrite,
            json_files=approved_knowledge_json,
        )
        print(
            f"  {len(seeded)} knowledge entries written: {seeded or '(none - all already present)'}"
        )

        print(f"Seeding signals config from {signals_dir} ...")
        seeded = seed_knowledge_from_dir(
            signals_dir,
            overwrite=overwrite,
            json_files=approved_signal_json,
        )
        print(
            f"  {len(seeded)} signal config entries written: {seeded or '(none - all already present)'}"
        )

        print(f"Seeding global settings from {global_settings_path} ...")
        written = seed_global_settings_from_file(overwrite=overwrite)
        print(f"  {'updated' if written else 'already present'}")

    print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed the Job Hunter database from bundled JSON files."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--upgrade",
        action="store_true",
        help="Version-aware merge: add new baseline entries without touching existing DB entries.",
    )
    group.add_argument(
        "--overwrite",
        action="store_true",
        help="Hard reset: replace all knowledge entries from bundled files (wipes user-approved additions).",
    )
    args = parser.parse_args()
    run(overwrite=args.overwrite, upgrade=args.upgrade)


if __name__ == "__main__":
    main()
