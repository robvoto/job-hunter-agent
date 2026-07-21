"""Click-test: the onboarding wizard's real CV-extraction step, driven with a
real (billed) OpenAI call -- opt-in only.

Safety, by design:
  - Skipped at COLLECTION time (not just at runtime) unless both
    JOB_HUNTER_E2E_ALLOW_LLM=1 and a real OPENAI_API_KEY are present, so a
    normal `pytest` run can never accidentally trigger it.
  - Forces the cheapest selectable model (see conftest._cheapest_llm_model,
    resolved from the app's own live pricing config, not hardcoded) before
    the wizard's create-profile click fires.
  - The app itself has max_retries=0 and a 30s request timeout for LLM calls
    (data/config/global_settings.json), and the wizard's click handler fires
    exactly one fetch per click with no client-side retry -- this test
    additionally asserts only one request actually hit the endpoint.
  - A hard pytest-timeout wall-clock cap so a hang can't run indefinitely.
  - A hard USD ceiling asserted against the endpoint's own reported
    llm_cost_usd, using a tiny synthetic CV so the real cost stays a small
    fraction of the ceiling.

Run explicitly with real credentials:
    JOB_HUNTER_E2E_ALLOW_LLM=1 OPENAI_API_KEY=sk-... \
        ./scripts/run-e2e.sh --llm tests/e2e/test_onboarding_llm_flow.py -v

The wrapper adds --confcutdir=tests/e2e automatically. That flag is required:
the parent tests/conftest.py
unconditionally blanks OPENAI_API_KEY, and job_hunter_agent.llm_gate builds
its OpenAI client once at import time, so once that env var has been blanked
anywhere earlier in the process it stays blanked for the rest of it.
"""

from __future__ import annotations

import os

import pytest

COST_CEILING_USD = 0.02

_ALLOW_LLM = os.environ.get("JOB_HUNTER_E2E_ALLOW_LLM") == "1"
_HAS_REAL_KEY = bool(os.environ.get("OPENAI_API_KEY"))

TINY_CV_TEXT = """Jane Doe
Senior Backend Engineer

EXPERIENCE
Acme Corp -- Backend Engineer (2020-2024)
Built and maintained Python/FastAPI services. Worked with PostgreSQL and Docker.

SKILLS
Python, FastAPI, PostgreSQL, Docker, AWS
"""


@pytest.mark.llm_e2e
@pytest.mark.timeout(90)
@pytest.mark.skipif(
    not (_ALLOW_LLM and _HAS_REAL_KEY),
    reason=(
        "Real-LLM e2e test: costs money, opt-in only. "
        "Set JOB_HUNTER_E2E_ALLOW_LLM=1 and a real OPENAI_API_KEY to run it."
    ),
)
def test_onboarding_cv_extraction_uses_cheapest_model_within_cost_ceiling(
    fresh_candidate_page_cheap_llm,
):
    page = fresh_candidate_page_cheap_llm
    import_requests: list[str] = []
    page.on(
        "request",
        lambda req: import_requests.append(req.url)
        if req.url.endswith("/api/onboarding/import")
        else None,
    )

    page.goto("/start")
    page.locator("#primary_cv").set_input_files(
        files=[{"name": "tiny_cv.txt", "mimeType": "text/plain", "buffer": TINY_CV_TEXT.encode("utf-8")}]
    )

    with page.expect_response("**/api/onboarding/import") as response_info:
        page.locator("#create_profile").click()
    response = response_info.value
    assert response.ok, f"onboarding import failed: {response.status} {response.text()}"

    payload = response.json()
    assert "error" not in payload, f"onboarding import returned an error: {payload.get('error')}"

    cost = float(payload.get("llm_cost_usd") or 0.0)
    assert cost <= COST_CEILING_USD, (
        f"onboarding LLM extraction cost ${cost:.6f}, exceeding the "
        f"${COST_CEILING_USD:.2f} safety ceiling -- investigate before re-running."
    )

    assert len(import_requests) == 1, (
        f"expected exactly one /api/onboarding/import request, got {len(import_requests)}: "
        f"{import_requests} -- a retry/loop would silently multiply LLM spend."
    )

    page.locator('[data-step="2"]').wait_for(state="visible")
