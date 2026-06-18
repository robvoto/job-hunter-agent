# Showcase Notes

Local notes for future demos, portfolio write-ups, and product positioning. This is not roadmap truth; the active backlog remains the shared Google Sheet.

## Differentiating Features

| Feature | User value | Proof / demo note |
|---|---|---|
| Explainable fit scoring | Users can see why a job is worth applying for or skipping instead of trusting a black-box rank. | Show a workspace card with score breakdown, positive evidence, risks, and next action. |
| Strict-but-safe filtering | Poor matches are reduced without silently hiding uncertain jobs that may still be worth review. | Demo an unclear work-type or salary case staying visible with a warning instead of disappearing. |
| Guided CV onboarding | Users can turn a detailed CV into searchable role direction, capabilities, and preferences without editing JSON. | Walk through upload, Review Draft, Search Basics, and Check Setup. |
| Local-first job workspace | The app can run locally with user-controlled runtime state and explainable persistence paths. | Show local FastAPI workspace plus SQLite-backed profile/history state. |
| Multi-source search foundation | SEEK and LinkedIn results can feed the same review workspace while keeping source-specific scraping isolated. | Run a search with both sources enabled and point to source tags in results. |
| Learning-ready review loop | User actions and review signals can become evidence-backed suggestions before changing matching behaviour. | Show capability review/settings surfaces and the pending learning workflow direction. |

## Demo Guardrails

- Use sample or scrubbed personal data only.
- Prefer showing explanations and review controls over raw scraper logs.
- Do not imply production SaaS readiness until deployment, multi-user isolation, and cost controls are complete.
- Keep claims tied to visible behaviour or tests in the repo.
