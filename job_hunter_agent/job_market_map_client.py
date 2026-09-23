"""HTTP client for Job Market Map's canonical consumer contract."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen

MARKET_MAP_BASE_URL_ENV = "JOB_HUNTER_MARKET_MAP_BASE_URL"
MARKET_MAP_TIMEOUT_ENV = "JOB_HUNTER_MARKET_MAP_TIMEOUT_SECONDS"
MARKET_MAP_API_VERSION = "v3"
JMM_FIELD_STATE_KNOWN = "known"
JMM_FIELD_STATE_NOT_PRESENT = "not_present"
JMM_FIELD_STATE_UNKNOWN = "unknown"
JMM_FIELD_STATE_NOT_APPLICABLE = "not_applicable"
JMM_FIELD_STATES = frozenset(
    {
        JMM_FIELD_STATE_KNOWN,
        JMM_FIELD_STATE_NOT_PRESENT,
        JMM_FIELD_STATE_UNKNOWN,
        JMM_FIELD_STATE_NOT_APPLICABLE,
    }
)
JMM_NEUTRAL_FIELDS = (
    "title",
    "company",
    "location",
    "geography_code",
    "posted_at",
    "classification",
    "subclassification",
    "employment_type",
    "workplace_type",
    "apply_method",
    "salary",
    "description",
)
_PERSONAL_ACTIVITY_FIELDS = frozenset(
    {
        "presented_by_agent",
        "viewed_by_user",
        "liked",
        "hidden",
        "applied",
        "rejected",
        "interview",
        "no_response",
    }
)


class JobMarketMapError(RuntimeError):
    """Base error for failures at the Job Market Map integration boundary."""


class JobMarketMapUnavailable(JobMarketMapError):
    """JMM could not be reached or returned an HTTP failure."""


class JobMarketMapJDUnavailable(JobMarketMapError):
    """JMM confirmed that a job's current JD is no longer available."""


class JobMarketMapJDNotCached(JobMarketMapError):
    """JMM is healthy but this job does not have a cached JD yet."""


class JobMarketMapContractError(JobMarketMapError):
    """JMM returned a response that is not the supported canonical contract."""


def validate_market_job_field_states(item: dict[str, Any]) -> dict[str, str]:
    """Validate JMM's complete neutral field-state map and return a detached copy."""
    raw_states = item.get("field_states")
    if not isinstance(raw_states, dict):
        raise JobMarketMapContractError("Job Market Map job field_states must be an object")

    expected = set(JMM_NEUTRAL_FIELDS)
    actual = set(raw_states)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        detail: list[str] = []
        if missing:
            detail.append(f"missing {missing}")
        if unexpected:
            detail.append(f"unexpected {unexpected}")
        raise JobMarketMapContractError(
            "Job Market Map job field_states does not match the supported neutral contract"
            + (f": {', '.join(detail)}" if detail else "")
        )

    states: dict[str, str] = {}
    for field in JMM_NEUTRAL_FIELDS:
        state = str(raw_states.get(field) or "").strip().casefold()
        if state not in JMM_FIELD_STATES:
            raise JobMarketMapContractError(
                f"Job Market Map field state for {field!r} is invalid: {raw_states.get(field)!r}"
            )
        states[field] = state
    return states


def validate_market_job_salary_normalized(
    item: dict[str, Any], field_states: dict[str, str]
) -> dict[str, Any]:
    """Validate JMM's deterministic salary envelope without reinterpreting it."""
    raw_salary = item.get("salary_normalized")
    if not isinstance(raw_salary, dict):
        raise JobMarketMapContractError(
            "Job Market Map job salary_normalized must be an object"
        )

    state = str(raw_salary.get("state") or "").strip().casefold()
    if state not in JMM_FIELD_STATES:
        raise JobMarketMapContractError(
            f"Job Market Map normalized salary state is invalid: {raw_salary.get('state')!r}"
        )

    field_state = field_states["salary"]
    if field_state != JMM_FIELD_STATE_KNOWN and state != field_state:
        raise JobMarketMapContractError(
            "Job Market Map normalized salary state conflicts with salary field state"
        )

    normalized = {
        "state": state,
        "min_amount": raw_salary.get("min_amount"),
        "max_amount": raw_salary.get("max_amount"),
        "period": raw_salary.get("period"),
        "currency": raw_salary.get("currency"),
        "qualifier": raw_salary.get("qualifier"),
        "bound": raw_salary.get("bound"),
    }
    return normalized


@dataclass(frozen=True)
class JobMarketMapClient:
    """Small transport-only client; JMM remains the owner of market/JD truth."""

    base_url: str
    timeout_seconds: float = 30.0
    opener: Callable[..., Any] = urlopen

    def __post_init__(self) -> None:
        from urllib.parse import urlsplit

        parsed = urlsplit(str(self.base_url or "").strip().rstrip("/"))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                f"{MARKET_MAP_BASE_URL_ENV} must be an absolute http(s) URL ending at the JMM API base"
            )
        if not parsed.path.rstrip("/").endswith(f"/{MARKET_MAP_API_VERSION}"):
            raise ValueError(f"{MARKET_MAP_BASE_URL_ENV} must include /{MARKET_MAP_API_VERSION}")
        if self.timeout_seconds <= 0:
            raise ValueError("Job Market Map timeout must be positive")

    @classmethod
    def from_environment(cls) -> "JobMarketMapClient":
        base_url = str(os.environ.get(MARKET_MAP_BASE_URL_ENV) or "").strip()
        if not base_url:
            raise JobMarketMapUnavailable(
                f"Job Market Map is not configured; set {MARKET_MAP_BASE_URL_ENV}"
            )
        raw_timeout = str(os.environ.get(MARKET_MAP_TIMEOUT_ENV) or "30").strip()
        try:
            timeout = float(raw_timeout)
        except ValueError as exc:
            raise JobMarketMapUnavailable(
                f"{MARKET_MAP_TIMEOUT_ENV} must be a positive number"
            ) from exc
        return cls(base_url=base_url, timeout_seconds=timeout)

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        terminal_jd_unavailable: bool = False,
    ) -> dict[str, Any]:
        url = urljoin(f"{self.base_url.rstrip('/')}/", path.lstrip("/"))
        if query:
            query_items: list[tuple[str, Any]] = []
            for key, value in query.items():
                if value is None:
                    continue
                if isinstance(value, (list, tuple)):
                    query_items.extend((key, item) for item in value)
                else:
                    query_items.append((key, value))
            if query_items:
                url = f"{url}?{urlencode(query_items)}"
        encoded_body = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            url,
            data=encoded_body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method=method,
        )
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = ""
            try:
                error_payload = json.loads(exc.read().decode("utf-8"))
                if isinstance(error_payload, dict):
                    detail = str(
                        error_payload.get("detail") or error_payload.get("error") or ""
                    ).strip()
            except (UnicodeDecodeError, json.JSONDecodeError, OSError):
                pass
            message = f"Job Market Map request failed: {exc}"
            if detail:
                message = f"{message}: {detail}"
            if terminal_jd_unavailable and exc.code == 409:
                raise JobMarketMapJDNotCached(message) from exc
            if terminal_jd_unavailable and exc.code == 410:
                raise JobMarketMapJDUnavailable(message) from exc
            raise JobMarketMapUnavailable(message) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise JobMarketMapUnavailable(f"Job Market Map request failed: {exc}") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JobMarketMapContractError("Job Market Map returned a non-JSON response") from exc
        if not isinstance(payload, dict):
            raise JobMarketMapContractError("Job Market Map response must be an object")
        return payload

    @staticmethod
    def _validate_metadata(payload: dict[str, Any]) -> None:
        if payload.get("api_version") != MARKET_MAP_API_VERSION:
            raise JobMarketMapContractError("Job Market Map API version is not supported")
        if not isinstance(payload.get("schema_version"), int):
            raise JobMarketMapContractError("Job Market Map schema_version is required")

    def feed_page(
        self,
        *,
        after_id: int = 0,
        limit: int | None = None,
        source: str | None = None,
        geography_code: str | None = None,
    ) -> dict[str, Any]:
        payload = self._request(
            "GET",
            "/feed/jobs",
            query={
                "after_id": after_id,
                "limit": limit,
                "source": source,
                "geography_code": geography_code,
                "include_archived": False,
                "include_raw": False,
            },
        )
        return self._validate_feed_payload(payload, after_id=after_id)

    @classmethod
    def _validate_feed_payload(
        cls,
        payload: dict[str, Any],
        *,
        after_id: int,
        require_total: bool = False,
    ) -> dict[str, Any]:
        cls._validate_metadata(payload)
        items = payload.get("items")
        if not isinstance(items, list):
            raise JobMarketMapContractError("Job Market Map feed items must be a list")
        for item in items:
            if not isinstance(item, dict):
                raise JobMarketMapContractError("Job Market Map feed item must be an object")
            if _PERSONAL_ACTIVITY_FIELDS.intersection(item):
                raise JobMarketMapContractError(
                    "Job Market Map returned personal activity fields in its neutral feed"
                )
        next_cursor = payload.get("next_cursor")
        if not isinstance(next_cursor, int) or next_cursor < after_id:
            raise JobMarketMapContractError("Job Market Map feed cursor is invalid")
        if not isinstance(payload.get("has_more"), bool):
            raise JobMarketMapContractError("Job Market Map feed has_more is required")
        if require_total and (
            not isinstance(payload.get("total"), int) or payload["total"] < 0
        ):
            raise JobMarketMapContractError("Job Market Map search total is required")
        return payload

    def consumer_state(self, *, consumer_key: str) -> dict[str, Any]:
        """Read the named consumer checkpoint plus JMM's fixed pending-work snapshot."""
        payload = self._request(
            "GET",
            f"/consumers/{quote(consumer_key, safe='')}/state",
        )
        last_job_id = payload.get("last_job_id")
        snapshot_max_id = payload.get("snapshot_max_id")
        pending_count = payload.get("pending_active_primary_count")
        if not isinstance(last_job_id, int) or last_job_id < 0:
            raise JobMarketMapContractError("Job Market Map consumer state last_job_id is invalid")
        if not isinstance(snapshot_max_id, int) or snapshot_max_id < last_job_id:
            raise JobMarketMapContractError(
                "Job Market Map consumer state snapshot_max_id is invalid"
            )
        if not isinstance(pending_count, int) or pending_count < 0:
            raise JobMarketMapContractError(
                "Job Market Map consumer state pending_active_primary_count is invalid"
            )
        return payload

    def consumer_feed_page(
        self,
        *,
        consumer_key: str,
        through_id: int | None = None,
        source: str | None = None,
        geography_code: str | None = None,
    ) -> dict[str, Any]:
        """Read one named-consumer page within an optional run-scoped market snapshot."""
        payload = self._request(
            "GET",
            f"/consumers/{quote(consumer_key, safe='')}/feed",
            query={
                "through_id": through_id,
                "source": source,
                "geography_code": geography_code,
                "include_raw": False,
            },
        )
        validated = self._validate_feed_payload(payload, after_id=0)
        snapshot_max_id = validated.get("snapshot_max_id")
        if not isinstance(snapshot_max_id, int) or snapshot_max_id < 0:
            raise JobMarketMapContractError(
                "Job Market Map consumer feed snapshot_max_id is required"
            )
        return validated

    def search_page(
        self,
        *,
        role_terms: list[str],
        sources: list[str],
        geography_codes: list[str],
        locations: list[str] | None = None,
        classifications: list[str] | None = None,
        subclassifications: list[str] | None = None,
        employment_types: list[str] | None = None,
        workplace_types: list[str] | None = None,
        apply_methods: list[str] | None = None,
        companies: list[str] | None = None,
        posted_after: str | None = None,
        salary_min: float | int | None = None,
        salary_max: float | int | None = None,
        salary_period: str | None = None,
        salary_currency: str | None = None,
        after_id: int = 0,
        through_id: int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Read one bounded `/v3/jobs/search` page without consumer state.

        This client deliberately forwards only neutral JMM search fields. Source
        semantics, salary comparability and uncertain-field eligibility remain
        JMM responsibilities; JH applies personal filtering/scoring afterwards.
        """
        payload = self._request(
            "GET",
            "/jobs/search",
            query={
                "q": role_terms,
                "source": sources,
                "geography_code": geography_codes,
                "location": locations or [],
                "classification": classifications or [],
                "subclassification": subclassifications or [],
                "employment_type": employment_types or [],
                "workplace_type": workplace_types or [],
                "apply_method": apply_methods or [],
                "company": companies or [],
                "posted_after": posted_after,
                "salary_min": salary_min,
                "salary_max": salary_max,
                "salary_period": salary_period,
                "salary_currency": salary_currency,
                "after_id": after_id,
                "through_id": through_id,
                "include_archived": False,
                "include_raw": False,
                "limit": limit,
            },
        )
        return self._validate_feed_payload(payload, after_id=after_id, require_total=True)

    def iter_feed(self) -> Iterator[dict[str, Any]]:
        """Read the supported neutral feed without creating a JH market cache."""
        cursor = 0
        seen_ids: set[int] = set()
        while True:
            page = self.feed_page(after_id=cursor)
            for item in page["items"]:
                if not isinstance(item, dict):
                    raise JobMarketMapContractError("Job Market Map feed item must be an object")
                item_id = item.get("id")
                if not isinstance(item_id, int) or item_id in seen_ids:
                    raise JobMarketMapContractError(
                        "Job Market Map feed item id is invalid or repeated"
                    )
                seen_ids.add(item_id)
                yield item
            next_cursor = int(page["next_cursor"])
            if not page["has_more"]:
                return
            if next_cursor == cursor:
                raise JobMarketMapContractError("Job Market Map feed cursor did not advance")
            cursor = next_cursor

    def checkpoint(
        self, *, consumer_key: str, last_job_id: int, note: str | None = None
    ) -> dict[str, Any]:
        payload = self._request(
            "POST",
            f"/consumers/{quote(consumer_key, safe='')}/checkpoint",
            body={"last_job_id": last_job_id, "note": note},
        )
        if not isinstance(payload.get("last_job_id"), int):
            raise JobMarketMapContractError("Job Market Map checkpoint response is invalid")
        return payload

    def lookup_job(self, *, identity_key: str) -> dict[str, Any]:
        payload = self._request("GET", "/jobs/lookup", query={"identity_key": identity_key})
        self._validate_metadata(payload)
        job = payload.get("job")
        if not isinstance(job, dict):
            raise JobMarketMapContractError("Job Market Map lookup did not return a job")
        return payload

    def lookup_source_job(self, *, source: str, source_job_id: str) -> dict[str, Any]:
        """Resolve a source-native identity through JMM's exact lookup contract."""
        source_value = str(source or "").strip()
        source_id_value = str(source_job_id or "").strip()
        if not source_value or not source_id_value:
            raise ValueError("source and source_job_id are required for exact lookup")
        payload = self._request(
            "GET",
            "/jobs/lookup",
            query={"source": source_value, "source_job_id": source_id_value},
        )
        self._validate_metadata(payload)
        job = payload.get("job")
        if not isinstance(job, dict):
            raise JobMarketMapContractError("Job Market Map lookup did not return a job")
        if (
            str(job.get("source") or "").strip().casefold() != source_value.casefold()
            or str(job.get("source_job_id") or "").strip() != source_id_value
        ):
            raise JobMarketMapContractError(
                "Job Market Map exact lookup returned a different source identity"
            )
        return payload

    def get_readiness(self) -> dict[str, Any]:
        payload = self._request("GET", "/readiness")
        self._validate_metadata(payload)
        source_runs = payload.get("source_runs")
        coverage = payload.get("jd_coverage")
        if not isinstance(source_runs, dict) or not isinstance(coverage, dict):
            raise JobMarketMapContractError("Job Market Map readiness payload is incomplete")
        for source in ("seek", "linkedin"):
            run = source_runs.get(source)
            if not isinstance(run, dict) or not str(run.get("status") or "").strip():
                raise JobMarketMapContractError(
                    f"Job Market Map readiness source status is invalid: {source}"
                )
        for key in ("available", "missing_not_cached", "failed"):
            value = coverage.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise JobMarketMapContractError(
                    f"Job Market Map readiness JD count is invalid: {key}"
                )
        return payload

    def get_cached_jd(self, *, jmm_job_id: int, identity_key: str) -> dict[str, Any]:
        payload = self._request(
            "GET",
            f"/jobs/{jmm_job_id}/jd",
            query={"identity_key": str(identity_key or "").strip()},
            terminal_jd_unavailable=True,
        )
        self._validate_metadata(payload)
        if not str(payload.get("full_description") or "").strip():
            raise JobMarketMapContractError("Job Market Map returned an empty canonical JD")
        if not str(payload.get("jd_source") or "").strip():
            raise JobMarketMapContractError("Job Market Map returned no JD provenance")
        return payload
