"""Error types for preserving partial source scrape results."""

from __future__ import annotations


class PartialSourceResultsError(Exception):
    """Raised when a source fails after collecting partial results."""

    def __init__(
        self,
        source: str,
        *,
        kept_records: list[dict],
        audit_rows: list[dict],
        skill_observations: list[dict],
        original_error: Exception,
    ) -> None:
        self.source = source
        self.kept_records = list(kept_records)
        self.audit_rows = list(audit_rows)
        self.skill_observations = list(skill_observations)
        self.original_error = original_error
        super().__init__(f"{source} failed after collecting partial results: {original_error}")
