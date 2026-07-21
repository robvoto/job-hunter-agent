# Playwright E2E

`tests/e2e/` drives the real FastAPI app with a real Chromium browser so click-path bugs show up the way a human would experience them.

If you are looking for the repo's "Selenium-type" tests, this is the suite. The implementation uses Playwright instead of Selenium, but the purpose is the same: real browser automation against the live app, not mocked DOM snapshots.

## Quick start

Install the browser binary once:

```bash
uv run playwright install chromium
```

Run the whole click-test suite:

```bash
./scripts/run-e2e.sh
```

Run one test and watch the browser:

```bash
./scripts/run-e2e.sh --headed tests/e2e/test_workspace_freshness_flow.py -q
```

The onboarding upload path is covered by `tests/e2e/test_onboarding_flow.py`. That test exercises the real upload screen and the extract button flow with a deterministic extraction stub, so upload/click regressions are caught without paying for a real LLM call.

## Real-LLM onboarding test

This one is billed and opt-in only:

```bash
JOB_HUNTER_E2E_ALLOW_LLM=1 OPENAI_API_KEY=sk-... \
./scripts/run-e2e.sh --llm tests/e2e/test_onboarding_llm_flow.py -v
```

## Notes

- Headless is the default. Pass `--headed` if you want to see Chromium.
- The wrapper always adds `--confcutdir=tests/e2e`, which the click-test harness requires.
- Failure screenshots are written to `tests/e2e/artifacts/`.
