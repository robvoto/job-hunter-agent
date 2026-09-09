"""Explicit retention housekeeping for workspace history and manual review state."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from job_hunter_agent.global_settings import (
    get_hidden_retention_days,
    get_potential_retention_days,
)
from job_hunter_agent.io_utils import (
    active_hidden_job_keys_with_expiry,
    prune_workspace_pool_for_retention,
)
from job_hunter_agent.posting_utils import get_manual_skip_sets
from job_hunter_agent.profile_store import save_profile

logger = logging.getLogger(__name__)


def run_retention_housekeeping(
    profile: dict[str, Any],
    job_history: dict[str, dict[str, Any]],
    reference_time: datetime,
) -> tuple[set[str], set[str]]:
    """Apply board retention before deriving scraper/workspace manual-state sets.

    Hidden is temporary: once its retention window expires the key is removed
    from the persisted profile so the job can be reviewed again. Applied is a
    durable user record and remains protected. Stale non-applied workspace-pool
    rows are deleted so their full payloads/links do not linger in SQLite.
    """
    applied_job_keys, hidden_job_keys = get_manual_skip_sets(profile)
    hidden_retention_days = get_hidden_retention_days()
    active_hidden_job_keys, expired_hidden_job_keys = active_hidden_job_keys_with_expiry(
        hidden_job_keys,
        job_history,
        hidden_retention_days=hidden_retention_days,
        now=reference_time,
    )

    if expired_hidden_job_keys:
        review_controls = profile.setdefault("review_controls", {})
        review_controls["hidden_job_keys"] = sorted(active_hidden_job_keys)
        save_profile(profile)
        logger.info(
            "[RETENTION] expired %d Hidden job(s); they are eligible for review again",
            len(expired_hidden_job_keys),
        )

    removed_pool_records = prune_workspace_pool_for_retention(
        job_history,
        applied_job_keys,
        active_hidden_job_keys,
        potential_retention_days=get_potential_retention_days(),
        hidden_retention_days=hidden_retention_days,
        now=reference_time,
    )
    if removed_pool_records:
        logger.info(
            "[RETENTION] removed %d stale non-applied workspace-pool job(s)",
            removed_pool_records,
        )

    return applied_job_keys, active_hidden_job_keys
