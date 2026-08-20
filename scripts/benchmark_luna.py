#!/usr/bin/env python3
"""Benchmark gpt-5.6-luna against the currently configured LLM model.

Standalone, read-only harness. Never switches the live/configured model — every
LLM call passes an explicit `benchmark_model=` override (default None = today's
configured model), so normal app behavior is unaffected by running this script.

For each purpose whose call site takes job-description/job-record text as input,
this pulls N recently scored real job records for the active user, re-runs the
purpose against gpt-5.6-luna at reasoning effort "none" and "low", and (where a
historical result was actually recorded) diffs the outcome against it. Purposes
are discovered by reading the real `_log_llm_call(...)` call sites in
job_hunter_agent/{llm_gate,candidate_application_history,profile_learning}.py —
not hardcoded here — so a renamed or newly added purpose is picked up
automatically. Purposes with no job-record based input (capability_naming,
profile_storage_resolution, section_label_classification,
rejection_email_extraction, cv_extraction) are reported as skipped rather than
benchmarked, since there is no comparable per-job ground truth to diff against.

Every call here is a real, billed API call and is logged through the normal
`_log_llm_call` cost-logging path, same as production traffic.

Usage:
    JOB_HUNTER_DB_PATH=/var/lib/job-hunter/data/app.db python3 scripts/benchmark_luna.py
    python3 scripts/benchmark_luna.py --db /path/to/app.db --count 20 --admin-email you@example.com
"""

from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

BENCHMARK_MODEL = "gpt-5.6-luna"
REASONING_EFFORTS = ("none", "low")

_PURPOSE_SOURCE_FILES = [
    _REPO_ROOT / "job_hunter_agent" / "llm_gate.py",
    _REPO_ROOT / "job_hunter_agent" / "candidate_application_history.py",
    _REPO_ROOT / "job_hunter_agent" / "profile_learning.py",
]

# Purposes below are diffed against a stored historical result. Every other
# purpose discovered via discover_logged_purposes() is reported as skipped —
# this set only decides which purposes get a *diffable* ground truth, it is
# not the purpose list itself (that is always read from the source files).
_DIFFABLE_PURPOSES = {"job_review_with_learning", "title_judgment"}


def _string_literals(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return _string_literals(node.body) + _string_literals(node.orelse)
    return []


def discover_logged_purposes() -> set[str]:
    """Read the real _log_llm_call(...) call sites instead of hardcoding a purpose list."""
    purposes: set[str] = set()
    for path in _PURPOSE_SOURCE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id != "_log_llm_call" or len(node.args) < 2:
                continue
            purposes.update(_string_literals(node.args[1]))
    return purposes


@dataclass
class CallOutcome:
    ok: bool
    latency_ms: float
    cost_usd: float
    error: str | None = None
    result: object = None


@dataclass
class PurposeStats:
    purpose: str
    n_records: int = 0
    n_errors: int = 0
    n_diffable: int = 0
    n_agree: int = 0
    cost_delta_total: float = 0.0
    latency_delta_ms_total: float = 0.0

    @property
    def agreement_pct(self) -> str:
        if self.n_diffable == 0:
            return "n/a"
        return f"{100.0 * self.n_agree / self.n_diffable:.0f}%"

    @property
    def json_valid_pct(self) -> str:
        if self.n_records == 0:
            return "n/a"
        return f"{100.0 * (self.n_records - self.n_errors) / self.n_records:.0f}%"

    @property
    def avg_cost_delta(self) -> str:
        if self.n_records == 0:
            return "n/a"
        return f"${self.cost_delta_total / self.n_records:+.6f}"

    @property
    def avg_latency_delta_ms(self) -> str:
        if self.n_records == 0:
            return "n/a"
        return f"{self.latency_delta_ms_total / self.n_records:+.0f}ms"


@contextmanager
def forced_luna_reasoning(llm_gate_module, effort: str):
    """Force BENCHMARK_MODEL to a specific reasoning effort for this block.

    Patches the get_llm_reasoning_effort name inside llm_gate's module namespace
    (what _llm_reasoning_kwargs actually looks up), so the exact production
    call sites are exercised unchanged — only the effort for BENCHMARK_MODEL
    is overridden; every other model keeps using its configured effort.
    """
    original = llm_gate_module.get_llm_reasoning_effort

    def _override(model: str) -> str | None:
        if model == BENCHMARK_MODEL:
            return effort
        return original(model)

    with patch.object(llm_gate_module, "get_llm_reasoning_effort", _override):
        yield


def timed_call(llm_gate_module, fn, *args, **kwargs) -> CallOutcome:
    cost_before = llm_gate_module.get_session_cost_usd()
    t0 = time.monotonic()
    try:
        result = fn(*args, **kwargs)
        ok = True
        error = None
    except Exception as exc:  # noqa: BLE001 - one bad record must not abort the run
        result = None
        ok = False
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = (time.monotonic() - t0) * 1000
    cost_usd = llm_gate_module.get_session_cost_usd() - cost_before
    return CallOutcome(ok=ok, latency_ms=latency_ms, cost_usd=cost_usd, error=error, result=result)


def record_sort_key(record: dict, last_seen_key: str, run_started_key: str) -> str:
    return str(record.get(last_seen_key) or record.get(run_started_key) or "")


def select_records(
    records: list[dict], *, count: int, require_keys: list[str], last_seen_key: str, run_started_key: str
) -> list[dict]:
    eligible = [record for record in records if all(record.get(key) for key in require_keys)]
    eligible.sort(key=lambda r: record_sort_key(r, last_seen_key, run_started_key), reverse=True)
    return eligible[:count]


def build_review_text(record: dict, *, fit_source_key: str, full_description_key: str, title_key: str) -> str:
    from job_hunter_agent.global_settings import get_llm_max_chars
    from job_hunter_agent.source_learning import _fit_review_source_context

    title_text = str(record.get(title_key) or "").strip()
    body_text = str(record.get(fit_source_key) or record.get(full_description_key) or "").strip()
    source_context = _fit_review_source_context(record)
    text = "\n".join(part for part in [title_text, *source_context, body_text] if part)
    return text[: get_llm_max_chars()]


def build_description_text(record: dict, *, fit_source_key: str, full_description_key: str) -> str:
    return str(record.get(fit_source_key) or record.get(full_description_key) or "").strip()


def print_table(effort: str, current_model: str, stats_by_purpose: dict[str, PurposeStats], skipped_purposes: list[str]) -> None:
    headers = ["purpose", "n", "agreement", "json_valid", "avg_cost_delta", "avg_latency_delta"]
    rows: list[list[str]] = []
    for purpose in sorted(stats_by_purpose):
        stats = stats_by_purpose[purpose]
        rows.append(
            [
                purpose,
                str(stats.n_records),
                stats.agreement_pct,
                stats.json_valid_pct,
                stats.avg_cost_delta,
                stats.avg_latency_delta_ms,
            ]
        )
    for purpose in skipped_purposes:
        rows.append([purpose, "-", "skipped (no job-record input)", "-", "-", "-"])

    widths = [max([len(headers[i])] + [len(row[i]) for row in rows]) for i in range(len(headers))]

    print(f"=== {BENCHMARK_MODEL} vs {current_model} — reasoning effort: {effort} ===")
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--db", help="Path to the job-hunter sqlite DB (else JOB_HUNTER_DB_PATH env var)")
    parser.add_argument(
        "--count", type=int, default=20, help="Max job records to benchmark per purpose (default: 20)"
    )
    parser.add_argument(
        "--admin-email", help="Admin email to run as (else JOB_HUNTER_ADMIN_EMAIL env var)"
    )
    args = parser.parse_args()

    if args.db:
        os.environ["JOB_HUNTER_DB_PATH"] = args.db
    if not os.environ.get("JOB_HUNTER_DB_PATH"):
        parser.error("JOB_HUNTER_DB_PATH must be set (via --db or the environment)")
    if args.admin_email:
        os.environ["JOB_HUNTER_ADMIN_EMAIL"] = args.admin_email

    purposes = discover_logged_purposes()

    import job_hunter_agent.llm_gate as llm_gate
    from job_hunter_agent.global_settings import load_global_settings
    from job_hunter_agent.profile_store import (
        KEY_CANDIDATE_CAPABILITIES,
        KEY_EXPLORE_ADJACENT_ROLES,
        load_profile,
    )
    from job_hunter_agent.record_schema import (
        RECORD_FIT_SOURCE_TEXT_KEY,
        RECORD_FULL_DESCRIPTION_KEY,
        RECORD_LAST_SEEN_AT_KEY,
        RECORD_LLM_DECISION_KEY,
        RECORD_LLM_FIT_GRADE_KEY,
        RECORD_LLM_TITLE_JUDGMENT_KEY,
        RECORD_RUN_STARTED_AT_KEY,
        RECORD_TITLE_KEY,
    )
    from job_hunter_agent.settings.global_settings_defaults import (
        KEY_LLM_PRICING_PER_1M,
        KEY_LLM_SETTINGS,
    )
    from job_hunter_agent.user_context import set_user_context_from_admin_env
    from job_hunter_agent.workspace_service import load_saved_workspace_pool

    pricing = load_global_settings().get(KEY_LLM_SETTINGS, {}).get(KEY_LLM_PRICING_PER_1M, {})
    if BENCHMARK_MODEL not in pricing:
        print(f"ERROR: {BENCHMARK_MODEL} has no pricing_per_1m entry in global settings.", file=sys.stderr)
        return 1
    if llm_gate.client is None:
        print("ERROR: no LLM client configured (missing API key).", file=sys.stderr)
        return 1

    set_user_context_from_admin_env()
    current_model = llm_gate.get_llm_model()

    records = load_saved_workspace_pool()
    if not records:
        print("No job records found for the active user; nothing to benchmark.")
        return 0

    profile = load_profile()

    review_records = select_records(
        records,
        count=args.count,
        require_keys=[RECORD_LLM_DECISION_KEY, RECORD_LLM_FIT_GRADE_KEY],
        last_seen_key=RECORD_LAST_SEEN_AT_KEY,
        run_started_key=RECORD_RUN_STARTED_AT_KEY,
    )
    review_records = [
        record
        for record in review_records
        if str(record.get(RECORD_FIT_SOURCE_TEXT_KEY) or record.get(RECORD_FULL_DESCRIPTION_KEY) or "").strip()
    ]
    title_records = select_records(
        records,
        count=args.count,
        require_keys=[RECORD_LLM_TITLE_JUDGMENT_KEY, RECORD_TITLE_KEY],
        last_seen_key=RECORD_LAST_SEEN_AT_KEY,
        run_started_key=RECORD_RUN_STARTED_AT_KEY,
    )

    target_roles = profile.get("target_roles")
    secondary_roles = profile.get("also_consider_roles")
    explore_adjacent_roles = bool(profile.get(KEY_EXPLORE_ADJACENT_ROLES, False))
    capability_names = [
        str(rule.get("name") or "").strip()
        for rule in (profile.get(KEY_CANDIDATE_CAPABILITIES) or [])
        if isinstance(rule, dict) and str(rule.get("name") or "").strip()
    ]
    has_capabilities = bool(capability_names)

    print(f"Current configured model: {current_model}")
    print(f"Loaded {len(records)} job records for the active user.")
    print(f"Purposes discovered from _log_llm_call(...) call sites: {', '.join(sorted(purposes))}")
    print(
        "job_review_with_learning / job_learning_candidates / job_requirements / "
        f"rejection_suggestions sample: {len(review_records)} records"
    )
    print(f"title_judgment sample: {len(title_records)} records")
    if not has_capabilities:
        print("WARNING: profile has no candidate_capabilities — job_review_with_learning will be skipped.")
    print()

    all_stats: dict[str, dict[str, PurposeStats]] = {effort: {} for effort in REASONING_EFFORTS}

    for effort in REASONING_EFFORTS:
        stats_by_purpose = all_stats[effort]

        if has_capabilities and review_records:
            stats = stats_by_purpose.setdefault(
                "job_review_with_learning", PurposeStats("job_review_with_learning")
            )
            for record in review_records:
                text = build_review_text(
                    record,
                    fit_source_key=RECORD_FIT_SOURCE_TEXT_KEY,
                    full_description_key=RECORD_FULL_DESCRIPTION_KEY,
                    title_key=RECORD_TITLE_KEY,
                )
                if not text:
                    continue
                current = timed_call(
                    llm_gate, llm_gate.llm_should_consider_with_learning, text, benchmark_model=None
                )
                with forced_luna_reasoning(llm_gate, effort):
                    luna = timed_call(
                        llm_gate,
                        llm_gate.llm_should_consider_with_learning,
                        text,
                        benchmark_model=BENCHMARK_MODEL,
                    )
                stats.n_records += 1
                if not luna.ok:
                    stats.n_errors += 1
                else:
                    fit = (luna.result or {}).get("fit_review") or {}
                    got_decision = str(fit.get("decision") or "").strip().upper()
                    got_grade = str(fit.get("grade") or "").strip().upper()
                    want_decision = str(record.get(RECORD_LLM_DECISION_KEY) or "").strip().upper()
                    want_grade = str(record.get(RECORD_LLM_FIT_GRADE_KEY) or "").strip().upper()
                    stats.n_diffable += 1
                    if got_decision == want_decision and got_grade == want_grade:
                        stats.n_agree += 1
                stats.cost_delta_total += luna.cost_usd - current.cost_usd
                stats.latency_delta_ms_total += luna.latency_ms - current.latency_ms

        if review_records:
            stats = stats_by_purpose.setdefault(
                "job_learning_candidates", PurposeStats("job_learning_candidates")
            )
            for record in review_records:
                text = build_review_text(
                    record,
                    fit_source_key=RECORD_FIT_SOURCE_TEXT_KEY,
                    full_description_key=RECORD_FULL_DESCRIPTION_KEY,
                    title_key=RECORD_TITLE_KEY,
                )
                if not text:
                    continue
                current = timed_call(
                    llm_gate, llm_gate.llm_should_consider_learning_candidates, text, benchmark_model=None
                )
                with forced_luna_reasoning(llm_gate, effort):
                    luna = timed_call(
                        llm_gate,
                        llm_gate.llm_should_consider_learning_candidates,
                        text,
                        benchmark_model=BENCHMARK_MODEL,
                    )
                stats.n_records += 1
                if not luna.ok:
                    stats.n_errors += 1
                stats.cost_delta_total += luna.cost_usd - current.cost_usd
                stats.latency_delta_ms_total += luna.latency_ms - current.latency_ms

        if review_records:
            stats = stats_by_purpose.setdefault("job_requirements", PurposeStats("job_requirements"))
            for record in review_records:
                text = build_description_text(
                    record,
                    fit_source_key=RECORD_FIT_SOURCE_TEXT_KEY,
                    full_description_key=RECORD_FULL_DESCRIPTION_KEY,
                )
                if not text:
                    continue
                current = timed_call(
                    llm_gate, llm_gate.llm_extract_job_requirements, text, benchmark_model=None
                )
                with forced_luna_reasoning(llm_gate, effort):
                    luna = timed_call(
                        llm_gate, llm_gate.llm_extract_job_requirements, text, benchmark_model=BENCHMARK_MODEL
                    )
                stats.n_records += 1
                if not luna.ok:
                    stats.n_errors += 1
                stats.cost_delta_total += luna.cost_usd - current.cost_usd
                stats.latency_delta_ms_total += luna.latency_ms - current.latency_ms

        if review_records:
            stats = stats_by_purpose.setdefault("rejection_suggestions", PurposeStats("rejection_suggestions"))
            for record in review_records:
                text = build_description_text(
                    record,
                    fit_source_key=RECORD_FIT_SOURCE_TEXT_KEY,
                    full_description_key=RECORD_FULL_DESCRIPTION_KEY,
                )
                if not text:
                    continue
                current = timed_call(
                    llm_gate, llm_gate.llm_suggest_rejection_blockers, text, benchmark_model=None
                )
                with forced_luna_reasoning(llm_gate, effort):
                    luna = timed_call(
                        llm_gate, llm_gate.llm_suggest_rejection_blockers, text, benchmark_model=BENCHMARK_MODEL
                    )
                stats.n_records += 1
                if not luna.ok:
                    stats.n_errors += 1
                stats.cost_delta_total += luna.cost_usd - current.cost_usd
                stats.latency_delta_ms_total += luna.latency_ms - current.latency_ms

        if title_records:
            stats = stats_by_purpose.setdefault("title_judgment", PurposeStats("title_judgment"))
            for record in title_records:
                title = str(record.get(RECORD_TITLE_KEY) or "").strip()
                if not title:
                    continue
                current = timed_call(
                    llm_gate,
                    llm_gate.llm_judge_title,
                    title,
                    target_roles,
                    secondary_roles,
                    capability_names,
                    explore_adjacent_roles=explore_adjacent_roles,
                    benchmark_model=None,
                )
                with forced_luna_reasoning(llm_gate, effort):
                    luna = timed_call(
                        llm_gate,
                        llm_gate.llm_judge_title,
                        title,
                        target_roles,
                        secondary_roles,
                        capability_names,
                        explore_adjacent_roles=explore_adjacent_roles,
                        benchmark_model=BENCHMARK_MODEL,
                    )
                stats.n_records += 1
                if not luna.ok:
                    stats.n_errors += 1
                else:
                    got_verdict = str((luna.result or {}).get("verdict") or "").strip().lower()
                    want_verdict = str(
                        (record.get(RECORD_LLM_TITLE_JUDGMENT_KEY) or {}).get("verdict") or ""
                    ).strip().lower()
                    stats.n_diffable += 1
                    if got_verdict == want_verdict:
                        stats.n_agree += 1
                stats.cost_delta_total += luna.cost_usd - current.cost_usd
                stats.latency_delta_ms_total += luna.latency_ms - current.latency_ms

    exercised_purposes = {
        "job_review_with_learning",
        "job_learning_candidates",
        "job_requirements",
        "rejection_suggestions",
        "title_judgment",
    }
    skipped_purposes = sorted(purposes - exercised_purposes)

    for effort in REASONING_EFFORTS:
        print_table(effort, current_model, all_stats[effort], skipped_purposes)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
