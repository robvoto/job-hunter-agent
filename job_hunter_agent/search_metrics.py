"""Diagnostic query-yield metrics for source search-plan execution.

Purely observational logging for one source search target (one search_term x
location combination). Consumed only by humans/learning review via structured
logs — must never gate scraping decisions, retire a search term, or otherwise
feed back into runtime behaviour from a single run. See the search-plan
ownership rules in `.agents/skills/scraping/SKILL.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging

from job_hunter_agent.logging_utils import format_log_block

logger = logging.getLogger(__name__)


@dataclass
class QueryYieldMetric:
    source: str
    search_term: str
    location: str
    elapsed_seconds: float
    discovered_count: int
    new_unique_job_count: int
    duplicate_job_count: int
    pages_searched: int
    success: bool
    direct_title_match_count: int | None = None
    new_direct_title_match_count: int | None = None
    failure_reason: str = ""


def record_query_yield_metric(metric: QueryYieldMetric) -> None:
    """Log one source search target's discovery yield. Diagnostic only."""
    fields: dict[str, object] = {
        "search_term": metric.search_term or "(unset)",
        "location": metric.location or "(all)",
        "elapsed_seconds": round(metric.elapsed_seconds, 2),
        "discovered_count": metric.discovered_count,
        "new_unique_job_count": metric.new_unique_job_count,
        "duplicate_job_count": metric.duplicate_job_count,
        "pages_searched": metric.pages_searched,
        "success": metric.success,
    }
    if metric.direct_title_match_count is not None:
        fields["direct_title_match_count"] = metric.direct_title_match_count
    if metric.new_direct_title_match_count is not None:
        fields["new_direct_title_match_count"] = metric.new_direct_title_match_count
    if metric.failure_reason:
        fields["failure_reason"] = metric.failure_reason
    logger.info(format_log_block(f"{metric.source.upper()}][QUERY_YIELD", fields))
