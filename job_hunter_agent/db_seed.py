"""Seed the database from the repo's bundled JSON files.

Run once on first deployment (or after a DB reset):

    python -m job_hunter_agent.db_seed

The script is safe to run again — INSERT OR IGNORE means existing data is
never overwritten. Pass --overwrite to force-replace all knowledge entries
(e.g. after updating bundled files in a new app version).
"""

import argparse
import sys
from pathlib import Path

from job_hunter_agent.database import init_db
from job_hunter_agent.knowledge_store import seed_knowledge_from_dir
from job_hunter_agent.paths import REPO_ROOT


def run(overwrite: bool = False) -> None:
    knowledge_dir = REPO_ROOT / "data" / "knowledge"
    config_dir = REPO_ROOT / "data" / "config"
    signals_dir = REPO_ROOT / "data" / "signals"

    print("Initialising database...")
    init_db()

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
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing knowledge entries (use after app upgrade to pick up updated defaults).",
    )
    args = parser.parse_args()
    run(overwrite=args.overwrite)


if __name__ == "__main__":
    main()
