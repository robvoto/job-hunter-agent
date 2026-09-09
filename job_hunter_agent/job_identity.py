"""Manage job identity, duplicate detection, and linking across sources.

This module provides functions for normalizing job keys, detecting confirmed
and potential duplicate job postings based on various identifiers (job key, URL,
ATS requisition ID, platform job ID), and annotating records with links to
their duplicates. It relies on managed knowledge for duplicate rules and source
priority to resolve conflicts.
"""

import math
import re
import threading
from copy import deepcopy
from functools import lru_cache
from typing import Any, Callable, Iterable, List, Optional
from urllib.parse import ParseResult, parse_qsl, urlencode, urlsplit, urlunsplit

from job_hunter_agent.company_normalization import company_names_weakly_match
from job_hunter_agent.duplicate_rules import load_duplicate_rules
from job_hunter_agent.locations import load_locations_au
from job_hunter_agent.paths import UNCERTAINTY_LOG_PATH
from job_hunter_agent.record_schema import (
    RECORD_COMPANY_KEY,
    RECORD_DETAILS_STATUS_KEY,
    RECORD_DETAILS_TEXT_KEY,
    RECORD_DUPLICATE_LINKS_KEY,
    RECORD_FIT_SOURCE_TEXT_KEY,
    RECORD_FULL_DESCRIPTION_KEY,
    RECORD_IS_REPOSTED_KEY,
    RECORD_JOB_KEY,
    RECORD_LOCATION_KEY,
    RECORD_POTENTIAL_DUPLICATE_LINKS_KEY,
    RECORD_RUN_STARTED_AT_KEY,
    RECORD_SOURCE_APPLY_URL_KEY,
    RECORD_SOURCE_ATS_REQUISITION_ID_KEY,
    RECORD_SOURCE_ATS_SOURCE_KEY,
    RECORD_SOURCE_CANONICAL_URL_KEY,
    RECORD_SOURCE_KEY,
    RECORD_SOURCE_METADATA_KEY,
    RECORD_SOURCE_NAME_KEY,
    RECORD_SOURCE_PLATFORM_JOB_ID_KEY,
    RECORD_SOURCE_PROVENANCE_KEY,
    RECORD_TITLE_KEY,
    RECORD_URL_KEY,
)
from job_hunter_agent.runtime_helpers import append_uncertainty_log, build_uncertainty_entry
from job_hunter_agent.source_registry import get_domain_to_source_map
from job_hunter_agent.system_warnings import (
    make_system_warning_fingerprint,
    record_system_warning,
)
from job_hunter_agent.title_normalization_rules import normalize_title_text

RUN_IDENTITY_CLAIM_KEY = "_run_identity_claim"


@lru_cache(maxsize=1)
def _get_identity_config() -> dict[str, Any]:
    """Load identity matching rules from managed knowledge."""

    return load_duplicate_rules()


def normalize_job_key(value: str, source: Optional[str] = None) -> str:
    """

    Strict job key normalization (canonical format: 'source:id').

    When a source is provided, raw slugs and numeric ids are namespaced to that source.

    """

    raw = str(value or "").strip().lower()

    if not raw:
        return ""

    # 1. Already follows canonical format? (e.g. 'seek:12345')

    if ":" in raw:
        if re.match(r"^[a-z]+:[a-z0-9_-]+$", raw):
            return raw

    # 1b. Some review flows store already-canonical slug keys without a source.

    if source is None and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", raw):
        return raw

    # 2. Extraction from standard URL patterns

    id_match = re.search(r"/job(?:s)?/(?:view/)?(\d+)", raw)

    # 2b. Salesforce-style listing URLs (e.g. APSJobs): the id lives in a
    # 'job-details/<id>' path segment or an 'id=' / 'jobid=' / 'job_id='
    # query parameter, not a numeric '/job/<id>' path segment.
    if not id_match:
        id_match = re.search(r"/job-?details?/([a-z0-9]+)", raw) or re.search(
            r"[?&](?:job_?id|id)=([a-z0-9]+)", raw
        )

    id_part = ""

    source_part = str(source or "").strip().lower()

    if id_match:
        id_part = id_match.group(1)

        if not source_part:
            domain_map = get_domain_to_source_map()

            for domain, mapped_source in domain_map.items():
                if domain in raw:
                    source_part = mapped_source

                    break

    elif re.fullmatch(r"\d+", raw):
        id_part = raw

    elif source_part and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", raw):
        id_part = raw

    # 3. Strict Canonical Assembly

    if id_part and source_part:
        return f"{source_part}:{id_part}"

    return ""


def _normalize_identity_text(text: str) -> str:

    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def _source_label(record: dict) -> str:

    source = (
        str(record.get(RECORD_SOURCE_KEY) or record.get(RECORD_SOURCE_NAME_KEY) or "")
        .strip()
        .lower()
    )

    return source


def _source_metadata(record: dict) -> dict:

    metadata = record.get(RECORD_SOURCE_METADATA_KEY)

    return metadata if isinstance(metadata, dict) else {}


def _normalized_identity_url(value: object) -> str:
    """Normalize a URL while retaining unknown query parameters as identity facts.

    Only the managed duplicate-rules allowlist is removed. An unknown parameter
    remains part of the identity because external apply systems commonly encode
    the vacancy ID in the query string.
    """

    raw_url = str(value or "").strip()

    if not raw_url:
        return ""

    try:
        parsed: ParseResult = urlsplit(raw_url)
        ignored_parameters = set(
            _get_identity_config().get("non_identity_query_parameters", [])
        )
        retained_query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.strip().lower() not in ignored_parameters
        ]
    except ValueError:
        return raw_url.split("#", 1)[0].strip().lower()

    normalized_path = parsed.path.rstrip("/")
    normalized_query = urlencode(retained_query, doseq=True)
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), normalized_path, normalized_query, "")
    )


def _normalized_url(record: dict) -> str:

    raw_url = str(record.get(RECORD_URL_KEY) or "").strip()

    if not raw_url:
        return ""

    try:  # Catches ValueError for malformed URLs
        return _normalized_identity_url(raw_url)

    except ValueError:
        return raw_url.split("#", 1)[0].split("?", 1)[0].strip().lower()


def _normalized_job_key(record: dict) -> str:

    val = record.get(RECORD_JOB_KEY) or ""

    source = record.get(RECORD_SOURCE_KEY) or record.get(RECORD_SOURCE_NAME_KEY)

    return normalize_job_key(str(val), source=source)


def _record_identity_signatures(record: dict) -> dict[str, str]:

    signatures: dict[str, str] = {}

    job_key = _normalized_job_key(record)

    if job_key:
        signatures["job_key"] = job_key

    url = _normalized_url(record)

    if url:
        signatures["url"] = url

    metadata = _source_metadata(record)

    for metadata_key in (RECORD_SOURCE_CANONICAL_URL_KEY, RECORD_SOURCE_APPLY_URL_KEY):
        metadata_url = _normalized_identity_url(metadata.get(metadata_key))
        if metadata_url:
            signatures[f"metadata_{metadata_key}"] = metadata_url

    ats_requisition_id = _normalize_identity_text(
        str(metadata.get(RECORD_SOURCE_ATS_REQUISITION_ID_KEY) or "")
    )

    if ats_requisition_id:
        ats_source = _normalize_identity_text(
            str(metadata.get(RECORD_SOURCE_ATS_SOURCE_KEY) or _source_label(record))
        )

        if ats_source:
            signatures["ats_requisition_id"] = f"{ats_source}:{ats_requisition_id}"

    platform_job_id = _normalize_identity_text(
        str(metadata.get(RECORD_SOURCE_PLATFORM_JOB_ID_KEY) or "")
    )

    if platform_job_id:
        source = _source_label(record)

        if source:
            signatures["platform_job_id"] = f"{source}:{platform_job_id}"

    return signatures


def _confirmed_duplicate_signatures(record: dict) -> dict[str, str]:
    """Return deterministic identity facts from the record itself."""

    return _record_identity_signatures(record)


def _confirmed_duplicate_signature_values(record: dict) -> set[tuple[str, str]]:
    """Return deterministic identities for the record and linked source records."""

    values = set(_record_identity_signatures(record).items())
    provenance = record.get(RECORD_SOURCE_PROVENANCE_KEY)
    if isinstance(provenance, list):
        for entry in provenance:
            if isinstance(entry, dict):
                values.update(_record_identity_signatures(entry).items())
    return values


class RunIdentityRegistry:
    """Coordinate exact identity claims across concurrent source workers.

    This registry owns only deterministic identity facts already accepted by the
    job-identity contract. It prevents a second source from entering detail or
    fit review while the first source is processing the same vacancy, and
    releases an unreviewable claim so another source can continue safely.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._claims: dict[tuple[str, str], dict[str, Any]] = {}
        self._claims_by_token: dict[object, dict[str, Any]] = {}

    def claim_or_wait(
        self,
        record: dict,
        *,
        should_abort: Callable[[], bool] | None = None,
    ) -> tuple[str, dict | None, object | None]:
        """Return ``owner``, ``duplicate``, ``unresolved``, or ``aborted``.

        Waiting is bounded by the owning source's normal completion/stop path,
        not by a second identity timeout. A failed or incomplete owner releases
        its claim and lets the waiting source try the work.
        """

        signatures = _confirmed_duplicate_signature_values(record)
        if not signatures:
            return "unresolved", None, None

        with self._condition:
            while True:
                claim = next(
                    (
                        candidate
                        for signature, candidate in self._claims.items()
                        if signature in signatures
                    ),
                    None,
                )
                if claim is None:
                    token = object()
                    claim = {
                        "token": token,
                        "record": record,
                        "signatures": signatures,
                        "state": "pending",
                    }
                    self._claims_by_token[token] = claim
                    for signature in signatures:
                        self._claims[signature] = claim
                    return "owner", None, token

                if claim["record"] is record:
                    return "owner", None, claim["token"]

                if claim["state"] == "complete":
                    return "duplicate", claim["record"], None

                if should_abort is not None and should_abort():
                    return "aborted", None, None

                self._condition.wait(timeout=0.05)

    def finish(self, token: object, record: dict) -> None:
        """Complete an exact claim only when usable detail evidence exists."""

        with self._condition:
            claim = self._claims_by_token.pop(token, None)
            if claim is None:
                return

            if str(record.get(RECORD_DETAILS_STATUS_KEY) or "") == "ok" and str(
                record.get(RECORD_DETAILS_TEXT_KEY) or ""
            ).strip():
                claim["state"] = "complete"
                claim["record"] = record
                final_signatures = _confirmed_duplicate_signature_values(record)
                claim["signatures"].update(final_signatures)
                for signature in claim["signatures"]:
                    self._claims[signature] = claim
            else:
                for signature, current in list(self._claims.items()):
                    if current is claim:
                        del self._claims[signature]
            self._condition.notify_all()

    def release(self, token: object) -> None:
        """Release a claim when finalisation itself cannot complete."""

        with self._condition:
            claim = self._claims_by_token.pop(token, None)
            if claim is None:
                return
            for signature, current in list(self._claims.items()):
                if current is claim:
                    del self._claims[signature]
            self._condition.notify_all()


def _confirmed_duplicate_match(a: dict, b: dict) -> Optional[tuple[str, str]]:

    signatures_a = _confirmed_duplicate_signature_values(a)
    signatures_b = _confirmed_duplicate_signature_values(b)

    for key in (
        "job_key",
        "url",
        f"metadata_{RECORD_SOURCE_CANONICAL_URL_KEY}",
        f"metadata_{RECORD_SOURCE_APPLY_URL_KEY}",
        "ats_requisition_id",
        "platform_job_id",
    ):
        for signature_key, signature_value in signatures_a:
            if signature_key == key and (signature_key, signature_value) in signatures_b:
                return key, signature_value

    if _cross_source_content_duplicate_match(a, b):
        return "cross_source_content", "title_company_location_date_description"

    return None


def _content_repost_description(record: dict) -> str:
    """Return the strongest available description text for repost comparison."""

    return str(
        record.get(RECORD_DETAILS_TEXT_KEY)
        or record.get(RECORD_FULL_DESCRIPTION_KEY)
        or record.get(RECORD_FIT_SOURCE_TEXT_KEY)
        or ""
    ).strip()


def _cross_source_description(record: dict) -> str:
    """Use the longest available description so generic teasers cannot dominate."""

    candidates = (
        record.get(RECORD_FULL_DESCRIPTION_KEY),
        record.get(RECORD_DETAILS_TEXT_KEY),
        record.get(RECORD_FIT_SOURCE_TEXT_KEY),
    )
    return max((str(value or "").strip() for value in candidates), key=len, default="")


def _description_shingles(text: str, size: int) -> set[tuple[str, ...]]:
    tokens = re.findall(r"[a-z0-9]+", str(text or "").lower())
    if len(tokens) < size:
        return set()
    return {tuple(tokens[index : index + size]) for index in range(len(tokens) - size + 1)}


def _description_similarity_matches(text_a: str, text_b: str, config: dict[str, Any]) -> bool:
    """Apply the configured full-description evidence test shared by repost rules."""

    min_chars = int(config["min_description_chars"])
    shingle_size = int(config["shingle_size"])
    min_jaccard = float(config["min_jaccard"])
    min_shorter_coverage = float(config["min_shorter_coverage"])

    if len(text_a) < min_chars or len(text_b) < min_chars:
        return False

    shingles_a = _description_shingles(text_a, shingle_size)
    shingles_b = _description_shingles(text_b, shingle_size)
    if not shingles_a or not shingles_b:
        return False

    overlap = len(shingles_a & shingles_b)
    union = len(shingles_a | shingles_b)
    jaccard = overlap / union if union else 0.0
    shorter_coverage = overlap / min(len(shingles_a), len(shingles_b))
    return jaccard >= min_jaccard and shorter_coverage >= min_shorter_coverage


def are_jobs_content_reposts(a: dict, b: dict) -> bool:
    """Return True for a high-confidence same-board repost with a changed platform id.

    Platform ids are authoritative when they match, but job boards can issue a new id
    for a repost.  We only bridge that gap when source, company and normalized title
    agree and the full descriptions are overwhelmingly the same.  This intentionally
    does *not* collapse same-title vacancies whose role-specific text differs.
    """

    source_a = _source_label(a)
    source_b = _source_label(b)
    if not source_a or source_a != source_b:
        return False

    title_a = normalize_title_text(str(a.get(RECORD_TITLE_KEY) or ""))
    title_b = normalize_title_text(str(b.get(RECORD_TITLE_KEY) or ""))
    if not title_a or title_a != title_b:
        return False

    company_a = str(a.get(RECORD_COMPANY_KEY) or "").strip()
    company_b = str(b.get(RECORD_COMPANY_KEY) or "").strip()
    if not company_a or not company_b or not company_names_weakly_match(company_a, company_b):
        return False

    location_a = _normalize_identity_text(str(a.get(RECORD_LOCATION_KEY) or ""))
    location_b = _normalize_identity_text(str(b.get(RECORD_LOCATION_KEY) or ""))
    if location_a and location_b and location_a != location_b:
        return False

    text_a = _content_repost_description(a)
    text_b = _content_repost_description(b)
    return _description_similarity_matches(text_a, text_b, _get_identity_config()["content_repost"])


@lru_cache(maxsize=256)
def _location_match_keys(value: str) -> frozenset[str]:
    """Resolve listing location text to managed location identities for comparison."""

    normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
    if not normalized or normalized in {"n a", "na", "unknown", "not specified"}:
        return frozenset()

    keys = {normalized}
    locations = load_locations_au()
    state_by_capital = {
        re.sub(r"[^a-z0-9]+", " ", str(entry.get("capital") or "").lower()).strip(): str(
            entry.get("code") or entry.get("name") or ""
        ).strip().lower()
        for entry in locations.values()
        if str(entry.get("kind") or "").strip().lower() in {"state", "territory"}
        and str(entry.get("capital") or "").strip()
    }

    for entry in locations.values():
        labels = [entry.get("code"), entry.get("name"), *(entry.get("aliases") or [])]
        identity = re.sub(
            r"[^a-z0-9]+",
            " ",
            str(entry.get("code") or entry.get("name") or "").lower(),
        ).strip()
        if not identity:
            continue
        for label in labels:
            label_text = re.sub(r"[^a-z0-9]+", " ", str(label or "").lower()).strip()
            if not label_text:
                continue
            if normalized == label_text or re.search(
                rf"(?<![a-z0-9]){re.escape(label_text)}(?![a-z0-9])", normalized
            ):
                keys.add(identity)
                if str(entry.get("kind") or "").strip().lower() == "city":
                    capital_key = re.sub(
                        r"[^a-z0-9]+", " ", str(entry.get("name") or "").lower()
                    ).strip()
                    if capital_key in state_by_capital:
                        keys.add(state_by_capital[capital_key])
                break
    return frozenset(keys)


def _locations_compatible(a: dict, b: dict) -> bool:
    """Reject only an evidenced location conflict during cross-source matching.

    A blank or placeholder location is missing evidence, not evidence that two
    vacancies differ. Company, title, posting age, and trusted description
    similarity remain required independent signals for the cross-source match.
    """

    location_keys = [
        _location_match_keys(str(record.get(RECORD_LOCATION_KEY) or "").strip())
        for record in (a, b)
    ]
    if not location_keys[0] or not location_keys[1]:
        return True
    return bool(location_keys[0] & location_keys[1])


def _posting_ages_compatible(a: dict, b: dict, max_difference_days: float) -> bool:
    # Import lazily because posting_utils imports normalize_job_key from this
    # module; at comparison time job_identity is fully initialized.
    from job_hunter_agent.posting_utils import (
        posted_datetime_from_age,
        posted_reference_time,
    )

    ages: list[float | None] = []
    for record in (a, b):
        try:
            age = float(record.get("posted_age_days"))
        except (TypeError, ValueError):
            age = None
        ages.append(age if age is not None and math.isfinite(age) and age >= 0 else None)
    if ages[0] is None or ages[1] is None:
        return True

    posted_at = [
        posted_datetime_from_age(age, posted_reference_time(record))
        for age, record in zip(ages, (a, b))
    ]
    if posted_at[0] is not None and posted_at[1] is not None:
        try:
            return (
                abs((posted_at[0] - posted_at[1]).total_seconds())
                <= max_difference_days * 86400
            )
        except TypeError:
            pass
    return abs(ages[0] - ages[1]) <= max_difference_days


def _cross_source_content_duplicate_match(a: dict, b: dict) -> bool:
    """Confirm a cross-board vacancy only from independent metadata and full content."""

    source_a = _source_label(a)
    source_b = _source_label(b)
    if not source_a or not source_b or source_a == source_b:
        return False

    title_a = normalize_title_text(str(a.get(RECORD_TITLE_KEY) or ""))
    title_b = normalize_title_text(str(b.get(RECORD_TITLE_KEY) or ""))
    if not title_a or title_a != title_b:
        return False

    company_a = str(a.get(RECORD_COMPANY_KEY) or "").strip()
    company_b = str(b.get(RECORD_COMPANY_KEY) or "").strip()
    if not company_a or not company_b or not company_names_weakly_match(company_a, company_b):
        return False

    if not _locations_compatible(a, b):
        return False

    config = _get_identity_config()["cross_source_content"]
    if not _posting_ages_compatible(
        a, b, float(config["max_posting_age_difference_days"])
    ):
        return False

    return _description_similarity_matches(
        _cross_source_description(a),
        _cross_source_description(b),
        config,
    )


def find_content_repost(record: dict, pool: Iterable[dict]) -> Optional[dict]:
    """Return the first high-confidence content repost from the supplied pool."""

    for candidate in pool:
        if candidate is record:
            continue
        if are_jobs_content_reposts(record, candidate):
            return candidate
    return None


def find_content_repost_history_entry(
    record: dict, history: dict[str, dict], job_keys: Iterable[str]
) -> Optional[dict]:
    """Return current-schema manual-state history for a changed-id content repost."""

    for job_key in job_keys:
        entry = history.get(str(job_key or "").strip())
        if not isinstance(entry, dict):
            continue
        snapshot = entry.get("last_kept_snapshot")
        if isinstance(snapshot, dict) and are_jobs_content_reposts(record, snapshot):
            return entry
    return None


def _content_repost_preference_key(record: dict) -> tuple[float, str, str]:
    try:
        posted_age = float(record.get("posted_age_days"))
    except (TypeError, ValueError):
        posted_age = 9999.0
    first_seen = str(record.get("first_seen_at") or "")
    job_key = _normalized_job_key(record) or str(record.get(RECORD_JOB_KEY) or "")
    return (-posted_age, first_seen, job_key)


def deduplicate_content_reposts(records: Iterable[dict]) -> list[dict]:
    """Collapse high-confidence same-board reposts, preferring the fresher record."""

    deduped: list[dict] = []
    for record in records:
        match_index = next(
            (index for index, kept in enumerate(deduped) if are_jobs_content_reposts(record, kept)),
            None,
        )
        if match_index is None:
            deduped.append(record)
            continue
        record[RECORD_IS_REPOSTED_KEY] = True
        deduped[match_index][RECORD_IS_REPOSTED_KEY] = True
        if _content_repost_preference_key(record) > _content_repost_preference_key(
            deduped[match_index]
        ):
            deduped[match_index] = record
    return deduped


def _duplicate_link(record: dict, matched_on: str, matched_value: str) -> dict[str, Any]:

    metadata = _source_metadata(record)

    return {
        "kind": "confirmed_duplicate",
        "matched_on": matched_on,
        "matched_value": matched_value,
        "source": _source_label(record),
        "title": str(record.get(RECORD_TITLE_KEY) or "").strip(),
        "company": str(record.get(RECORD_COMPANY_KEY) or "").strip(),
        "job_key": _normalized_job_key(record),
        "url": _normalized_url(record),
        "identity_signatures": _confirmed_duplicate_signatures(record),
        "source_metadata": deepcopy(metadata),
        "source_provenance": _source_provenance_entry(record),
    }


def _source_provenance_entry(record: dict) -> dict[str, Any]:
    """Capture source facts without making them part of the user preference model."""

    entry: dict[str, Any] = {}
    for key in (
        RECORD_SOURCE_KEY,
        RECORD_SOURCE_NAME_KEY,
        RECORD_JOB_KEY,
        RECORD_URL_KEY,
        RECORD_TITLE_KEY,
        RECORD_COMPANY_KEY,
        RECORD_LOCATION_KEY,
        RECORD_SOURCE_METADATA_KEY,
    ):
        value = record.get(key)
        if value not in (None, "", [], {}):
            entry[key] = deepcopy(value)
    return entry


def _source_provenance(record: dict) -> list[dict]:
    entries = record.get(RECORD_SOURCE_PROVENANCE_KEY)
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _provenance_key(entry: dict) -> tuple[str, ...]:
    metadata = entry.get(RECORD_SOURCE_METADATA_KEY)
    metadata = metadata if isinstance(metadata, dict) else {}
    return (
        str(
            entry.get(RECORD_SOURCE_KEY) or entry.get(RECORD_SOURCE_NAME_KEY) or ""
        )
        .strip()
        .lower(),
        str(entry.get(RECORD_JOB_KEY) or "").strip().lower(),
        _normalized_identity_url(entry.get(RECORD_URL_KEY)),
        _normalized_identity_url(metadata.get(RECORD_SOURCE_CANONICAL_URL_KEY)),
        _normalized_identity_url(metadata.get(RECORD_SOURCE_APPLY_URL_KEY)),
        _normalize_identity_text(metadata.get(RECORD_SOURCE_ATS_SOURCE_KEY)),
        _normalize_identity_text(metadata.get(RECORD_SOURCE_ATS_REQUISITION_ID_KEY)),
    )


def _merge_source_provenance(*records: dict) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple[str, ...]] = set()
    for record in records:
        for entry in [*_source_provenance(record), _source_provenance_entry(record)]:
            if not entry:
                continue
            key = _provenance_key(entry)
            if key in seen:
                continue
            seen.add(key)
            merged.append(deepcopy(entry))
    return merged


def _set_source_provenance(record: dict, entries: list[dict]) -> None:
    if entries:
        record[RECORD_SOURCE_PROVENANCE_KEY] = entries
    else:
        record.pop(RECORD_SOURCE_PROVENANCE_KEY, None)


_PRESERVED_STATE_KEYS = (
    "application_history",
    "candidate_application_history",
    "seen_before",
    "times_seen",
    "times_kept",
    "times_viewed",
    "first_seen_at",
    "last_seen_at",
    "first_viewed_at",
    "last_viewed_at",
    "first_kept_at",
    "last_kept_at",
    "first_applied_at",
    "last_applied_at",
    "last_unapplied_at",
    "last_not_for_me_at",
    "times_not_for_me",
    "last_block_title_at",
    "times_block_title",
    "is_hidden",
    "first_hidden_at",
    "last_hidden_at",
    "last_unhidden_at",
)


def _merge_preserved_state(kept: dict, merged_away: dict) -> None:
    """Retain non-empty application/history state while merging proven duplicates."""

    for key in _PRESERVED_STATE_KEYS:
        incoming = merged_away.get(key)
        current = kept.get(key)
        if incoming in (None, "", [], {}):
            continue
        if current in (None, "", [], {}):
            kept[key] = deepcopy(incoming)
        elif key in {"seen_before", "is_hidden"} and bool(incoming):
            kept[key] = True
        elif key.startswith("times_"):
            try:
                kept[key] = max(int(current or 0), int(incoming or 0))
            except (TypeError, ValueError):
                pass
        elif key.startswith("first_") and isinstance(current, str) and isinstance(incoming, str):
            kept[key] = min(current, incoming)
        elif key.startswith("last_") and isinstance(current, str) and isinstance(incoming, str):
            kept[key] = max(current, incoming)


def _duplicate_links(record: dict) -> list[dict]:

    links = record.get(RECORD_DUPLICATE_LINKS_KEY)

    return links if isinstance(links, list) else []


def _set_duplicate_links(record: dict, links: list[dict]) -> None:

    if links:
        record[RECORD_DUPLICATE_LINKS_KEY] = links

    elif RECORD_DUPLICATE_LINKS_KEY in record:
        record.pop(RECORD_DUPLICATE_LINKS_KEY, None)


def _merge_duplicate_links(*link_groups: list[dict]) -> list[dict]:

    merged: list[dict] = []

    seen: set[tuple[str, str, str, str]] = set()

    for group in link_groups:
        for link in group:
            if not isinstance(link, dict):
                continue

            dedupe_key = (
                str(link.get("kind") or ""),
                str(link.get("matched_on") or ""),
                str(link.get("matched_value") or ""),
                str(link.get("job_key") or link.get("url") or ""),
            )

            if dedupe_key in seen:
                continue

            seen.add(dedupe_key)

            merged.append(link)

    return merged


def _append_duplicate_link(
    record: dict, linked_record: dict, matched_on: str, matched_value: str
) -> None:

    links = _duplicate_links(record)

    links.append(_duplicate_link(linked_record, matched_on, matched_value))

    _set_duplicate_links(record, _merge_duplicate_links(links))


def merge_confirmed_duplicate_evidence(canonical: dict, duplicate: dict) -> bool:
    """Attach a same-run duplicate's source facts to the canonical record."""

    match = _confirmed_duplicate_match(canonical, duplicate)
    if match is None:
        return False

    matched_on, matched_value = match
    _append_duplicate_link(canonical, duplicate, matched_on, matched_value)
    _merge_preserved_state(canonical, duplicate)
    _set_source_provenance(canonical, _merge_source_provenance(canonical, duplicate))
    return True


def _potential_duplicate_signature(record: dict) -> dict[str, str]:

    title = str(record.get(RECORD_TITLE_KEY) or "").strip()

    return {"normalized_title": normalize_title_text(title)}


def _potential_duplicate_link(record: dict, matched_on: list[str]) -> dict[str, Any]:

    url = _normalized_url(record)

    link: dict[str, Any] = {
        "kind": "potential_duplicate",
        "matched_on": matched_on,
        "related_job_key": str(record.get(RECORD_JOB_KEY) or "").strip(),
        "related_title": str(record.get(RECORD_TITLE_KEY) or "").strip(),
        "related_company": str(record.get(RECORD_COMPANY_KEY) or "").strip(),
        "related_source": _source_label(record),
    }

    if url and url != "#":
        link["related_url"] = url

    return link


def _record_label(record: dict) -> str:
    """One-line description of a record for log messages: title / company / location (key)."""

    title = str(record.get(RECORD_TITLE_KEY) or "").strip()

    company = str(record.get(RECORD_COMPANY_KEY) or "").strip()

    location = str(record.get(RECORD_LOCATION_KEY) or "").strip()

    key = _normalized_job_key(record) or str(record.get(RECORD_JOB_KEY) or "")

    parts = " / ".join(p for p in [title, company, location] if p)

    return f"{parts} ({key})" if key else parts


def _log_potential_duplicate(a: dict, b: dict, matched_on: list[str]) -> None:
    """Log when two jobs match on title+company but cannot be confirmed as the same posting."""

    detail = (
        f"Two jobs matched on {', '.join(matched_on)} but could not be confirmed as the same posting. "
        f"A: {_record_label(a)}. B: {_record_label(b)}. "
        "Review whether these are the same role or distinct postings."
    )

    append_uncertainty_log(
        UNCERTAINTY_LOG_PATH,
        build_uncertainty_entry(
            reason_code="POTENTIAL_DUPLICATE_DETECTED",
            stage="deduplication",
            field="job_identity",
            raw_value=f"{_normalized_job_key(a)} | {_normalized_job_key(b)}",
            normalized_value=", ".join(matched_on),
            detail=detail,
            source="annotate_potential_duplicate_links",
            job_key=_normalized_job_key(a),
            severity="info",
        ),
    )
    record_system_warning(
        severity="info",
        category="job_identity_uncertainty",
        source="annotate_potential_duplicate_links",
        message=detail,
        fingerprint=make_system_warning_fingerprint(
            "job_identity",
            "potential_duplicate_detected",
            _normalized_job_key(a),
            _normalized_job_key(b),
            ",".join(matched_on),
            detail,
        ),
        job_key=_normalized_job_key(a),
        run_id=str(a.get(RECORD_RUN_STARTED_AT_KEY) or b.get(RECORD_RUN_STARTED_AT_KEY) or ""),
        context={
            "reason_code": "POTENTIAL_DUPLICATE_DETECTED",
            "matched_on": matched_on,
            "related_job_key": _normalized_job_key(b),
            "related_title": str(b.get(RECORD_TITLE_KEY) or "").strip(),
            "related_company": str(b.get(RECORD_COMPANY_KEY) or "").strip(),
        },
    )


def _log_confirmed_duplicate_merge(
    kept: dict, merged_away: dict, matched_on: str, matched_value: str
) -> None:
    """Log which posting was kept and which was merged away as a confirmed duplicate."""

    detail = (
        f"Confirmed duplicate on {matched_on} ({matched_value}). "
        f"Kept: {_record_label(kept)}. Merged away: {_record_label(merged_away)}."
    )

    append_uncertainty_log(
        UNCERTAINTY_LOG_PATH,
        build_uncertainty_entry(
            reason_code="CONFIRMED_DUPLICATE_MERGED",
            stage="deduplication",
            field="job_identity",
            raw_value=f"{_normalized_job_key(kept)} | {_normalized_job_key(merged_away)}",
            normalized_value=f"{matched_on}={matched_value}",
            detail=detail,
            source="deduplicate_across_sources",
            job_key=_normalized_job_key(kept),
            severity="info",
        ),
    )
    record_system_warning(
        severity="info",
        category="job_identity_uncertainty",
        source="deduplicate_across_sources",
        message=detail,
        fingerprint=make_system_warning_fingerprint(
            "job_identity",
            "confirmed_duplicate_merged",
            _normalized_job_key(kept),
            _normalized_job_key(merged_away),
            matched_on,
            matched_value,
        ),
        job_key=_normalized_job_key(kept),
        run_id=str(
            kept.get(RECORD_RUN_STARTED_AT_KEY) or merged_away.get(RECORD_RUN_STARTED_AT_KEY) or ""
        ),
        context={
            "reason_code": "CONFIRMED_DUPLICATE_MERGED",
            "matched_on": matched_on,
            "matched_value": matched_value,
            "kept_job_key": _normalized_job_key(kept),
            "kept_title": str(kept.get(RECORD_TITLE_KEY) or "").strip(),
            "kept_source": _source_label(kept),
            "merged_job_key": _normalized_job_key(merged_away),
            "merged_title": str(merged_away.get(RECORD_TITLE_KEY) or "").strip(),
            "merged_source": _source_label(merged_away),
        },
    )


def _log_dedup_company_missing(a: dict, b: dict, normalized_title: str) -> None:
    """Log when titles match but company is absent — duplicate status is unverifiable."""

    company_a = str(a.get(RECORD_COMPANY_KEY) or "").strip()

    company_b = str(b.get(RECORD_COMPANY_KEY) or "").strip()

    missing_side = "B" if not company_b else "A"

    detail = (
        f"Title normalized to '{normalized_title}' matched between two jobs but company is missing on side {missing_side} — "
        f"cannot confirm or deny duplicate. A: {_record_label(a)}. B: {_record_label(b)}."
    )

    append_uncertainty_log(
        UNCERTAINTY_LOG_PATH,
        build_uncertainty_entry(
            reason_code="DEDUP_COMPANY_MISSING",
            stage="deduplication",
            field="company",
            raw_value=f"A: '{company_a}' | B: '{company_b}'",
            normalized_value=normalized_title,
            detail=detail,
            source="_potential_duplicate_match",
            job_key=_normalized_job_key(a),
            severity="warning",
        ),
    )
    record_system_warning(
        severity="warning",
        category="job_identity_uncertainty",
        source="_potential_duplicate_match",
        message=detail,
        fingerprint=make_system_warning_fingerprint(
            "job_identity",
            "dedup_company_missing",
            _normalized_job_key(a),
            _normalized_job_key(b),
            normalized_title,
            company_a,
            company_b,
            detail,
        ),
        job_key=_normalized_job_key(a),
        run_id=str(a.get(RECORD_RUN_STARTED_AT_KEY) or b.get(RECORD_RUN_STARTED_AT_KEY) or ""),
        context={
            "reason_code": "DEDUP_COMPANY_MISSING",
            "normalized_title": normalized_title,
            "company_a": company_a,
            "company_b": company_b,
            "missing_side": missing_side,
        },
    )


def _set_potential_duplicate_links(record: dict, links: list[dict]) -> None:

    if links:
        record[RECORD_POTENTIAL_DUPLICATE_LINKS_KEY] = links

    elif RECORD_POTENTIAL_DUPLICATE_LINKS_KEY in record:
        record.pop(RECORD_POTENTIAL_DUPLICATE_LINKS_KEY, None)


def _potential_duplicate_match(a: dict, b: dict) -> Optional[list[str]]:

    signatures_a = _potential_duplicate_signature(a)

    signatures_b = _potential_duplicate_signature(b)

    matched_on: list[str] = []

    if (
        signatures_a["normalized_title"]
        and signatures_a["normalized_title"] == signatures_b["normalized_title"]
    ):
        matched_on.append("normalized_title")

    if not matched_on:
        return None

    company_a = str(a.get(RECORD_COMPANY_KEY) or "")

    company_b = str(b.get(RECORD_COMPANY_KEY) or "")

    if not company_a.strip() or not company_b.strip():
        # Title matched but company is absent — can't confirm or deny; surface it.

        _log_dedup_company_missing(a, b, signatures_a["normalized_title"])

        return None

    if not company_names_weakly_match(company_a, company_b):
        return None

    matched_on.append("company_name")

    return matched_on


def annotate_potential_duplicate_links(records: List[dict]) -> List[dict]:
    """Attach potential duplicate links without collapsing records."""

    potential_link_map: dict[int, list[dict]] = {index: [] for index in range(len(records))}

    for index, record in enumerate(records):
        for other_index in range(index + 1, len(records)):
            other = records[other_index]

            matched_on = _potential_duplicate_match(record, other)

            if not matched_on:
                continue

            potential_link_map[index].append(_potential_duplicate_link(other, matched_on))

            potential_link_map[other_index].append(_potential_duplicate_link(record, matched_on))

            _log_potential_duplicate(record, other, matched_on)

    for index, record in enumerate(records):
        _set_potential_duplicate_links(record, potential_link_map.get(index, []))

    return records


def _source_priority(record: dict) -> int:

    source_map = _get_identity_config().get("source_priority", {})

    source = _source_label(record)

    fallback_priority = (max(source_map.values()) + 1) if source_map else 1

    return source_map.get(source, fallback_priority)


def are_jobs_confirmed_duplicates(a: dict, b: dict) -> bool:
    """Return True only when two records share a deterministic identity."""

    return _confirmed_duplicate_match(a, b) is not None


def find_confirmed_duplicate(record: dict, pool: Iterable[dict]) -> Optional[dict]:
    """Return only a confirmed duplicate from the supplied pool."""

    for candidate in pool:
        if are_jobs_confirmed_duplicates(record, candidate):
            return candidate

    return None


def find_confirmed_identity_history_entry(
    record: dict, history: dict[str, dict]
) -> Optional[dict]:
    """Return history for an exact identity, including a previously linked source."""

    job_key = _normalized_job_key(record)
    if job_key and isinstance(history.get(job_key), dict):
        return history[job_key]

    # SEEK reviews title gates across a thread pool while other threads finalize
    # records into the same shared job_history dict, so iterate a snapshot rather
    # than the live view to avoid "dictionary changed size during iteration".
    for entry in list(history.values()):
        if not isinstance(entry, dict):
            continue
        for candidate_key in ("last_kept_snapshot", "detail_evidence"):
            candidate = entry.get(candidate_key)
            if isinstance(candidate, dict) and are_jobs_confirmed_duplicates(record, candidate):
                return entry
    return None


def deduplicate_across_sources(records: List[dict]) -> List[dict]:
    """Collapse only confirmed duplicates and keep explicit duplicate links."""

    deduped: List[dict] = []

    for record in records:
        duplicate_index = None

        duplicate_match: Optional[tuple[str, str]] = None

        for index, kept in enumerate(deduped):
            match = _confirmed_duplicate_match(record, kept)

            if match:
                duplicate_index = index

                duplicate_match = match

                break

        if duplicate_index is not None and duplicate_match is not None:
            matched_on, matched_value = duplicate_match

            kept_record = deduped[duplicate_index]

            if _source_priority(record) < _source_priority(kept_record):
                _append_duplicate_link(record, kept_record, matched_on, matched_value)

                _set_duplicate_links(
                    record,
                    _merge_duplicate_links(_duplicate_links(record), _duplicate_links(kept_record)),
                )
                _merge_preserved_state(record, kept_record)
                _set_source_provenance(
                    record,
                    _merge_source_provenance(record, kept_record),
                )

                _log_confirmed_duplicate_merge(record, kept_record, matched_on, matched_value)

                deduped[duplicate_index] = record

            else:
                _append_duplicate_link(kept_record, record, matched_on, matched_value)
                _merge_preserved_state(kept_record, record)
                _set_source_provenance(
                    kept_record,
                    _merge_source_provenance(kept_record, record),
                )

                _log_confirmed_duplicate_merge(kept_record, record, matched_on, matched_value)

            continue

        deduped.append(record)

    return annotate_potential_duplicate_links(deduped)
