"""Click-testing harness: boots a real FastAPI server and drives it with a real
Chromium browser via Playwright, so bugs in the actual rendered page/JS/API wiring
surface the way they would for a human clicking through the app — not just what
unit tests exercise in isolation.

Auth: Google OAuth is bypassed by minting a signed session cookie with the same
HMAC helper the server uses (`auth._build_session_cookie_value`), the same way a
successful OAuth callback would. This avoids a real browser having to complete a
real Google login, while still exercising the app's real cookie/CSRF verification
on every request.

Isolation from the unit suite: this conftest can run either (a) as part of the
normal `pytest` collection, where the parent `tests/conftest.py` has already set
up an isolated seeded DB, or (b) standalone via
`pytest tests/e2e/... --confcutdir=tests/e2e`, which skips the parent conftest
entirely. Mode (b) is required for `test_onboarding_llm_flow.py`: the parent
conftest unconditionally blanks `OPENAI_API_KEY`, and job_hunter_agent.llm_gate
builds its OpenAI client once at import time, so once that env var has been
blanked anywhere in the process it stays blanked for the rest of it. The DB
bootstrap below is therefore duplicated (not inherited) and guarded to be a
no-op when the parent conftest already did it.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import requests

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("JOB_HUNTER_AUTH_SESSION_SECRET", "e2e-click-test-session-secret")
os.environ.setdefault("JOB_HUNTER_ADMIN_EMAIL", "admin@e2e.test")
os.environ.setdefault("JOB_HUNTER_SESSION_COOKIE_SECURE", "false")

if not os.environ.get("JOB_HUNTER_DB_PATH"):
    import tempfile

    from job_hunter_agent.database import init_db
    from job_hunter_agent.global_settings import seed_global_settings_from_file
    from job_hunter_agent.knowledge_store import seed_knowledge_from_dir
    from job_hunter_agent.runtime_seed_manifest import (
        APPROVED_DB_KNOWLEDGE_JSON_REL_PATHS,
        APPROVED_SIGNAL_JSON_REL_PATHS,
        resolve_seed_json_paths,
    )

    _e2e_db_path = Path(tempfile.mkdtemp(prefix="jh_e2e_")) / "e2e.db"
    os.environ["JOB_HUNTER_DB_PATH"] = str(_e2e_db_path)
    init_db(_e2e_db_path)
    seed_knowledge_from_dir(
        ROOT_DIR / "data" / "knowledge",
        _e2e_db_path,
        json_files=resolve_seed_json_paths(
            ROOT_DIR / "data" / "knowledge", APPROVED_DB_KNOWLEDGE_JSON_REL_PATHS
        ),
    )
    seed_knowledge_from_dir(
        ROOT_DIR / "data" / "signals",
        _e2e_db_path,
        json_files=resolve_seed_json_paths(
            ROOT_DIR / "data" / "signals", APPROVED_SIGNAL_JSON_REL_PATHS
        ),
    )
    seed_global_settings_from_file(_e2e_db_path, overwrite=True)

CANDIDATE_EMAIL = "candidate@e2e.test"
FRESH_CANDIDATE_EMAIL = "fresh-candidate@e2e.test"
WORKSPACE_CANDIDATE_EMAIL = "workspace-candidate@e2e.test"
WORKSPACE_LINKEDIN_FRESHNESS_EMAIL = "workspace-linkedin-freshness@e2e.test"
# normalize_job_key requires a pure-alphabetic "source:id" prefix (job_identity.py),
# so this can't be namespaced "e2e:..." -- the digit in "e2e" fails that regex and
# every review action on the seeded card would 400 with "Missing job key".
SEEDED_JOB_KEY = "seek:e2e-sample-job-1"
SEEDED_LINKEDIN_FRESHNESS_JOB_KEY = "linkedin:sample-freshness-job"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def live_server():
    """Boot the real FastAPI app with uvicorn in a background thread."""
    import uvicorn

    import job_hunter_agent.fastapi_app as fastapi_app

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    os.environ["JOB_HUNTER_BASE_URL"] = base_url
    # The module can be imported while the E2E DB is bootstrapped, before this
    # dynamic port exists. Keep the module-level CORS owner aligned with the
    # real click-test server rather than leaking a developer/runtime base URL.
    fastapi_app.JOB_HUNTER_BASE_URL = base_url

    app = fastapi_app.create_app()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        ws="websockets-sansio",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="e2e-uvicorn", daemon=True)
    thread.start()

    deadline = time.monotonic() + 15
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            resp = requests.get(f"{base_url}/api/health", timeout=1)
            if resp.status_code == 200:
                break
        except requests.RequestException as exc:
            last_error = exc
        time.sleep(0.1)
    else:
        raise RuntimeError(f"live_server did not become healthy in time: {last_error}")

    yield base_url

    server.should_exit = True
    thread.join(timeout=10)


def _mark_onboarding_complete(user_id: str) -> None:
    """Most protected pages gate on onboarding completeness before anything else
    (see routes/pages.py). Real onboarding goes through the CV/LLM wizard, which
    click-tests outside test_onboarding_llm_flow.py deliberately avoid, so we set
    the same flag the wizard would set once it finishes, directly via profile_store.
    """
    from job_hunter_agent.profile_store import KEY_ONBOARDING_COMPLETE, patch_profile
    from job_hunter_agent.user_context import set_user_id

    set_user_id(user_id)
    try:
        patch_profile({KEY_ONBOARDING_COMPLETE: True})
    finally:
        set_user_id(None)


def _reset_fresh_onboarding_user(user_id: str) -> None:
    """Force the onboarding test user back to a truly fresh pre-onboarding state.

    The same e2e email can be reused across test runs, so simply *not* marking
    onboarding complete is not enough if a previous run already persisted
    onboarding-owned profile fields or uploaded source documents.
    """
    from job_hunter_agent.profile_store import (
        KEY_PRIMARY_PATTERNS,
        KEY_SECONDARY_PATTERNS,
        patch_profile,
    )
    from job_hunter_agent.source_documents import (
        DEFAULT_SOURCE_MATERIALS,
        build_onboarding_reset_patch,
        save_source_materials,
    )
    from job_hunter_agent.user_context import set_user_id

    set_user_id(user_id)
    try:
        fresh_patch = build_onboarding_reset_patch()
        fresh_patch.update({KEY_PRIMARY_PATTERNS: [], KEY_SECONDARY_PATTERNS: []})
        patch_profile(fresh_patch)
        save_source_materials(DEFAULT_SOURCE_MATERIALS)
    finally:
        set_user_id(None)


def _session_cookie(email: str, complete_onboarding: bool = True) -> dict:
    from job_hunter_agent.auth import _build_session_cookie_value, get_or_create_user
    from job_hunter_agent.database import ensure_user_row

    admin_email = os.environ["JOB_HUNTER_ADMIN_EMAIL"]
    user = get_or_create_user(email, admin_email)
    # E2E candidate fixtures exercise protected application pages, not the
    # approval workflow itself. Keep them approved explicitly now that new
    # candidate accounts default to pending access.
    ensure_user_row(
        user["user_id"],
        email=user["email"],
        access_status="approved",
    )
    user["access_status"] = "approved"
    if complete_onboarding:
        _mark_onboarding_complete(user["user_id"])
    else:
        _reset_fresh_onboarding_user(user["user_id"])
    secret = os.environ["JOB_HUNTER_AUTH_SESSION_SECRET"]
    value = _build_session_cookie_value(user, secret)

    from job_hunter_agent.config import SESSION_COOKIE_DEFAULT_NAME

    return {
        "name": SESSION_COOKIE_DEFAULT_NAME,
        "value": value,
        "domain": "127.0.0.1",
        "path": "/",
        "httpOnly": True,
        "secure": False,
    }


def _cheapest_llm_model() -> str:
    """Resolve the cheapest selectable model from the app's own live pricing
    config, rather than hardcoding a model name that could drift out of date
    and silently stop being the cheapest option.
    """
    from job_hunter_agent.global_settings import load_global_settings
    from job_hunter_agent.settings.global_settings_defaults import (
        KEY_LLM_PRICING_PER_1M,
        KEY_LLM_SETTINGS,
        KEY_MODEL_OPTIONS,
    )

    llm_settings = load_global_settings()[KEY_LLM_SETTINGS]
    options = llm_settings[KEY_MODEL_OPTIONS]
    pricing = llm_settings[KEY_LLM_PRICING_PER_1M]

    def _cost(model: str) -> float:
        prices = pricing[model]
        return float(prices["input"]) + float(prices["output"])

    return min(options, key=_cost)


def _seed_workspace_records(email: str, records: list[dict], *, reason: str) -> None:
    """Seed a known workspace snapshot for a dedicated e2e user."""
    from job_hunter_agent.auth import get_or_create_user
    from job_hunter_agent.scrape_finalize import _save_workspace_pool
    from job_hunter_agent.server_helpers import clear_current_user_search_state
    from job_hunter_agent.user_context import set_user_id
    from job_hunter_agent.workspace_rebuild_service import rebuild_workspace_results

    admin_email = os.environ["JOB_HUNTER_ADMIN_EMAIL"]
    user = get_or_create_user(email, admin_email)
    set_user_id(user["user_id"])
    try:
        clear_current_user_search_state()
        # JH-306 retired the legacy audit snapshot as a workspace rebuild
        # source. Seed the canonical JH-owned workspace pool used at runtime.
        _save_workspace_pool(records)
        rebuild_workspace_results(reason=reason)
    finally:
        set_user_id(None)


def _seed_kept_job(email: str) -> None:
    """Seed exactly one KEEP-scored, high-fit job into the workspace so a real job
    card renders on /workspace -- used to click-test per-card actions (score
    display, save/"applied", dismiss/"hidden") that filter-only workspace
    coverage never exercises.
    """
    run_started_at = "2026-07-20T08:00:00+00:00"
    _seed_workspace_records(
        email,
        [
            {
                "job_key": SEEDED_JOB_KEY,
                "url": "https://example.test/jobs/sample-job-1",
                "title": "Senior Backend Engineer",
                "company": "Acme Corp",
                "teaser": "Build and ship backend services.",
                "location": "Remote",
                "posted": run_started_at,
                "source": "seek",
                "decision": "KEEP",
                "run_started_at": run_started_at,
                "fit_score": 95,
                "fit_score_breakdown": [],
                "llm_decision": "KEEP",
                "llm_fit_grade": "STRONG",
                "requirement_coverage": [
                    {
                        "capability_name": "Backend engineering",
                        "status": "supported",
                        "importance": "mandatory",
                    }
                ],
            }
        ],
        reason="e2e workspace job seed",
    )


def _seed_linkedin_freshness_job(email: str) -> None:
    """Seed one LinkedIn external-apply job whose original post date is unverified."""
    run_started_at = "2026-07-20T08:00:00+00:00"
    _seed_workspace_records(
        email,
        [
            {
                "job_key": SEEDED_LINKEDIN_FRESHNESS_JOB_KEY,
                "url": "https://www.linkedin.com/jobs/view/123456789",
                "title": "Senior Business Analyst",
                "company": "Acme Corp",
                "teaser": "Lead discovery and delivery alignment across product teams.",
                "location": "Sydney NSW",
                "posted": "15 hours ago",
                "posted_age_days": 15 / 24,
                "source": "linkedin",
                "decision": "KEEP",
                "run_started_at": run_started_at,
                "fit_score": 91,
                "fit_score_breakdown": [],
                "llm_decision": "KEEP",
                "llm_fit_grade": "STRONG",
                "apply_method": "external_apply",
                "original_posted_date_status": "unverified",
                "full_description": (
                    "Lead requirements discovery, stakeholder workshops, and delivery planning "
                    "across digital transformation programs."
                ),
                "requirement_coverage": [
                    {
                        "capability_name": "Stakeholder engagement",
                        "status": "supported",
                        "importance": "mandatory",
                    }
                ],
            }
        ],
        reason="e2e linkedin freshness workspace seed",
    )


def _force_cheapest_llm_model(email: str) -> None:
    from job_hunter_agent.auth import get_or_create_user
    from job_hunter_agent.user_settings import save_user_settings

    admin_email = os.environ["JOB_HUNTER_ADMIN_EMAIL"]
    user = get_or_create_user(email, admin_email)
    save_user_settings(user["user_id"], {"llm": {"model": _cheapest_llm_model()}})


@dataclass
class Diagnostics:
    console_errors: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    failed_requests: list[str] = field(default_factory=list)
    failed_responses: list[str] = field(default_factory=list)
    teardown_started: bool = False

    ALLOWLIST = ("/favicon.ico",)

    def is_clean(self) -> bool:
        return not (
            self.console_errors
            or self.page_errors
            or self.failed_requests
            or self.failed_responses
        )

    def describe(self) -> str:
        lines = ["Browser diagnostics captured unexpected errors:"]
        for label, items in (
            ("console errors", self.console_errors),
            ("uncaught page errors", self.page_errors),
            ("failed network requests", self.failed_requests),
            ("HTTP error responses", self.failed_responses),
        ):
            for item in items:
                lines.append(f"  [{label}] {item}")
        return "\n".join(lines)


def _wire_diagnostics(page) -> Diagnostics:
    diag = Diagnostics()

    def _on_console(msg):
        if msg.type == "error":
            diag.console_errors.append(f"{msg.text} ({page.url})")

    def _on_pageerror(exc):
        diag.page_errors.append(f"{exc} ({page.url})")

    def _on_requestfailed(request):
        # Closing the browser context intentionally aborts any request still in
        # flight. Those teardown cancellations are not application failures; real
        # request failures that happen before teardown remain diagnostic errors.
        if diag.teardown_started:
            return
        if request.failure:
            diag.failed_requests.append(f"{request.method} {request.url} -> {request.failure}")

    def _on_response(response):
        if response.status >= 400 and not any(
            allowed in response.url for allowed in Diagnostics.ALLOWLIST
        ):
            diag.failed_responses.append(f"{response.status} {response.url}")

    page.on("console", _on_console)
    page.on("pageerror", _on_pageerror)
    page.on("requestfailed", _on_requestfailed)
    page.on("response", _on_response)
    return diag


def _authenticated_page(browser, base_url: str, request, cookie: dict | None):
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    context = browser.new_context(base_url=base_url, ignore_https_errors=True)
    if cookie:
        context.add_cookies([cookie])
    page = context.new_page()
    diag = _wire_diagnostics(page)
    request.node._e2e_page = page

    yield page

    request.node._e2e_diagnostics = diag
    diag.teardown_started = True
    context.close()
    if not diag.is_clean():
        pytest.fail(diag.describe())


@pytest.fixture()
def candidate_page(browser, live_server, request):
    yield from _authenticated_page(browser, live_server, request, _session_cookie(CANDIDATE_EMAIL))


@pytest.fixture()
def fresh_candidate_page(browser, live_server, request):
    """A candidate whose onboarding is NOT marked complete, for testing the wizard
    itself -- an onboarding-complete user hitting /start gets redirected to /.
    """
    cookie = _session_cookie(FRESH_CANDIDATE_EMAIL, complete_onboarding=False)
    yield from _authenticated_page(browser, live_server, request, cookie)


@pytest.fixture()
def fresh_candidate_page_cheap_llm(browser, live_server, request):
    """A fresh (onboarding-incomplete) candidate whose LLM model has been forced
    to the cheapest available option. Used exclusively by
    test_onboarding_llm_flow.py, which makes real, billed OpenAI calls -- the
    forced-cheap-model step must run before the wizard's create-profile click
    triggers the real extraction call.
    """
    _force_cheapest_llm_model(FRESH_CANDIDATE_EMAIL)
    cookie = _session_cookie(FRESH_CANDIDATE_EMAIL, complete_onboarding=False)
    yield from _authenticated_page(browser, live_server, request, cookie)


@pytest.fixture()
def workspace_job_page(browser, live_server, request):
    """An onboarding-complete candidate with exactly one seeded KEEP job, for
    click-testing per-job-card actions (score, save/"applied", dismiss/"hidden")
    on /workspace. Uses a dedicated user so the seeded job doesn't leak into
    other tests' candidate_page (which is intentionally job-free).
    """
    _seed_kept_job(WORKSPACE_CANDIDATE_EMAIL)
    cookie = _session_cookie(WORKSPACE_CANDIDATE_EMAIL)
    yield from _authenticated_page(browser, live_server, request, cookie)


@pytest.fixture()
def workspace_linkedin_freshness_page(browser, live_server, request):
    """An onboarding-complete candidate with one seeded LinkedIn freshness-risk job."""
    _seed_linkedin_freshness_job(WORKSPACE_LINKEDIN_FRESHNESS_EMAIL)
    cookie = _session_cookie(WORKSPACE_LINKEDIN_FRESHNESS_EMAIL)
    yield from _authenticated_page(browser, live_server, request, cookie)


@pytest.fixture()
def admin_page(browser, live_server, request):
    admin_email = os.environ["JOB_HUNTER_ADMIN_EMAIL"]
    yield from _authenticated_page(browser, live_server, request, _session_cookie(admin_email))


@pytest.fixture()
def anon_page(browser, live_server, request):
    yield from _authenticated_page(browser, live_server, request, None)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return
    page = getattr(item, "_e2e_page", None)
    if page is None:
        return
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = item.nodeid.replace("/", "_").replace("::", "__")
    screenshot_path = ARTIFACTS_DIR / f"{safe_name}-{int(time.time())}.png"
    try:
        page.screenshot(path=str(screenshot_path))
        report.longrepr = f"{report.longreprtext}\n\nScreenshot: {screenshot_path}"
    except Exception:
        pass
