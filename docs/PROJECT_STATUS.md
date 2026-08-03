# Project Status

This document prevents the README and technical documentation from presenting planned, disabled, or configuration-dependent behaviour as universally available.

## Implemented

- Candidate onboarding from `.docx` and plain-text source material.
- Per-user runtime profile stored in SQLite.
- SEEK and LinkedIn job collection through configurable source connectors.
- Job normalisation and canonical source identifiers.
- Deterministic hard blockers and title checks.
- Capability, requirement, and eligibility evidence evaluation.
- Explainable bounded fit scores.
- Potential, applied, hidden, and review-oriented workspace states.
- Settings, workspace, onboarding, and owner administration interfaces.
- Explicit approval boundaries for learned signals.
- Daily-agent execution, local digest output, and configurable notification delivery.
- CSRF protection and transport-aware session handling for state-changing web actions.

## Configuration-dependent

These capabilities exist but require runtime configuration or an appropriate deployment environment:

- LinkedIn collection depends on its connector dependencies and source availability.
- Email and Telegram notifications require user-owned delivery settings.
- HTTPS cookie hardening requires HTTPS termination through the deployment proxy.
- LLM-assisted review depends on the active deployment's provider configuration and privacy policy.
- Browser-assisted SEEK verification requires the relevant assisted browser setting.

## Privacy boundary

The runtime profile is the matching source of truth after onboarding. Raw uploaded CV files are evidence inputs and are not treated as permanent canonical matching state.

Packaged or shared builds must not include:

- a developer or user's CV;
- candidate profiles or job history;
- scraped job payloads;
- runtime databases;
- browser profiles;
- logs, output, debug files, or private examples;
- API keys, cookies, passwords, or notification credentials.

## Not claimed as complete

- Fully autonomous application submission.
- Unreviewed self-modifying rejection rules.
- Guaranteed completeness or availability of third-party job sources.
- Universal LLM availability across every build.
- Multi-tenant production SaaS readiness.

## Status language

Documentation should use these terms consistently:

- **Implemented** — code path exists and is part of the supported product flow.
- **Configuration-dependent** — code path exists but needs external credentials, services, flags, or deployment support.
- **Experimental** — available for controlled testing but not relied on as a normal product guarantee.
- **Planned** — design or backlog intent only; not represented as current behaviour.
