"""Seed the database from the repo's bundled JSON files.

Run once on first deployment (or after a DB reset):

    python -m job_hunter_agent.db_seed

The script is safe to run again — INSERT OR IGNORE means existing data is
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
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from job_hunter_agent.database import init_db
from job_hunter_agent.knowledge_store import seed_knowledge_from_dir, upgrade_knowledge_from_dir
from job_hunter_agent.paths import REPO_ROOT


def run(overwrite: bool = False, upgrade: bool = False) -> None:
    knowledge_dir = REPO_ROOT / "data" / "knowledge"
    config_dir = REPO_ROOT / "data" / "config"
    signals_dir = REPO_ROOT / "data" / "signals"

    print("Initialising database...")
    init_db()

    if upgrade:
        print(f"Upgrading knowledge from {knowledge_dir} ...")
        updated = upgrade_knowledge_from_dir(knowledge_dir)
        print(f"  {len(updated)} knowledge entries updated: {updated or '(none — all current)'}")

        print(f"Upgrading config from {config_dir} ...")
        updated = upgrade_knowledge_from_dir(config_dir)
        print(f"  {len(updated)} config entries updated: {updated or '(none — all current)'}")

        print(f"Upgrading signals config from {signals_dir} ...")
        updated = upgrade_knowledge_from_dir(signals_dir)
        print(f"  {len(updated)} signal config entries updated: {updated or '(none — all current)'}")
    else:
        print(f"Seeding knowledge from {knowledge_dir} ...")
        seeded = seed_knowledge_from_dir(knowledge_dir, overwrite=overwrite)
        print(f"  {len(seeded)} knowledge entries written: {seeded or '(none — all already present)'}")

        print(f"Seeding config from {config_dir} ...")
        seeded = seed_knowledge_from_dir(config_dir, overwrite=overwrite)
        print(f"  {len(seeded)} config entries written: {seeded or '(none — all already present)'}")

        print(f"Seeding signals config from {signals_dir} ...")
        seeded = seed_knowledge_from_dir(signals_dir, overwrite=overwrite)
        print(f"  {len(seeded)} signal config entries written: {seeded or '(none — all already present)'}")

    print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the Job Hunter database from bundled JSON files.")
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
