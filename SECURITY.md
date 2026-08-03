# Security Policy

## Supported code

Security fixes apply to the current `main` branch. Older local builds should be upgraded before a security issue is investigated.

## Sensitive data

Job Hunter processes candidate profile material, job history, scraped listings, authentication state, and optional notification credentials. Treat the following as sensitive and local-only:

- uploaded CV or onboarding files;
- candidate profiles and evidence text;
- per-user SQLite data;
- scraped source payloads and browser profiles;
- application logs, debug output, and generated workspaces;
- cookies, passwords, API keys, email credentials, and Telegram tokens.

These files must not be committed, bundled into shared installers, attached to public issues, or copied into example fixtures without sanitisation.

## Secret management

- Load secrets from environment or protected runtime configuration.
- Never place real credentials in committed defaults, tests, screenshots, or documentation.
- Rotate a secret immediately if it is exposed in source control, logs, or chat.
- Use user-owned provider and notification credentials where those integrations are enabled.

## Web deployment

Network deployments must use the controls described in `docs/OPERATIONS.md`, including:

- HTTPS termination;
- secure session-cookie settings;
- CSRF protection for state-changing actions;
- restricted access to administration routes;
- non-public application and database paths;
- appropriate reverse-proxy and firewall configuration.

## Reporting

Report suspected vulnerabilities privately to the repository owner. Do not include credentials, CV content, recruiter details, live cookies, or production database extracts in an issue. Provide a minimal sanitised reproduction instead.
