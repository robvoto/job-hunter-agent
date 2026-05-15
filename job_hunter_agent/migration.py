"""One-time startup migration: move legacy flat user data files into the admin user folder.

Runs automatically when the server starts (called from fastapi_app.create_app).
Safe to call multiple times — skips silently if USERS_DIR already exists.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


def run_migration() -> None:
    from job_hunter_agent.paths import (
        DATA_DIR,
        WORKSPACE_RESULTS_FILENAME,
        OUTPUT_DIR,
        USERS_DIR,
    )

    if USERS_DIR.exists():
        return  # already migrated

    admin_email = os.getenv("JOB_HUNTER_ADMIN_EMAIL", "").strip().lower()
    if not admin_email:
        return  # can't migrate without knowing which folder to create

    from job_hunter_agent.auth import user_id_from_email
    admin_id = user_id_from_email(admin_email)
    user_dir = USERS_DIR / admin_id
    user_dir.mkdir(parents=True, exist_ok=True)

    # User-owned files to move from their legacy locations
    moves: list[tuple[Path, Path]] = [
        (DATA_DIR / "profile.json",              user_dir / "profile.json"),
        (DATA_DIR / "job_history.json",          user_dir / "job_history.json"),
        (DATA_DIR / "application_materials.json", user_dir / "application_materials.json"),
        (DATA_DIR / "application_inputs" / "source_pack", user_dir / "source_pack"),
        (OUTPUT_DIR / "review_data.json",        user_dir / "review_data.json"),
        (OUTPUT_DIR / "run_stats.json",          user_dir / "run_stats.json"),
        (OUTPUT_DIR / "audit_records.json",      user_dir / "audit_records.json"),
        (OUTPUT_DIR / WORKSPACE_RESULTS_FILENAME, user_dir / WORKSPACE_RESULTS_FILENAME),
    ]

    for src, dst in moves:
        if src.exists() and not dst.exists():
            try:
                shutil.move(str(src), str(dst))
                print(f"[MIGRATION] Moved {src.name} → {dst.relative_to(DATA_DIR.parent)}")
            except Exception as exc:
                print(f"[MIGRATION] Could not move {src}: {exc}")

    # Seed users.json with the admin entry if it doesn't exist yet
    from job_hunter_agent.auth import USERS_PATH, get_or_create_user
    if not USERS_PATH.exists():
        get_or_create_user(admin_email, admin_email)
        print(f"[MIGRATION] Created users.json with admin entry ({admin_id})")

    print(f"[MIGRATION] Complete — admin workspace at data/users/{admin_id}/")
