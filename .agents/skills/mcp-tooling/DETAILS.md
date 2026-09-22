# MCP Tooling Details

Load only the section needed for the current connector task.

## Human MCP external contract

- Published Human MCP action names/schemas are a versioned external interface for connector consumers.
- Preserve existing action names, required arguments, and argument types unless an explicit versioned contract change is approved.
- Prefer additive external changes; internal implementation may evolve behind the stable interface.
- This external compatibility rule does not justify compatibility shims inside Job Hunter business logic, persistence, payloads, caches, UI contracts, or internal APIs.

## Signed-in browser control

- Use the human's existing signed-in Chrome profile; do not create a clean automation profile or copy cookies unless explicitly requested.
- Discover the current browser tool schema before assuming an action is unavailable.
- Prove control with the current status/list/snapshot tools, then target explicit `page_id` values for deterministic actions when supported.
- Use a new tab when the workflow should not disturb existing tabs.
- If navigation works but DOM actions fail, inspect the live extension/permission state before diagnosing bot detection, login failure, or browser unavailability.
- After an extension reload or transient bridge disconnect, rediscover/verify the live browser state once, then retry the requested action; do not launch a second broker/profile as a workaround.
- Opening a URL externally is not proof of browser DOM control.

## Gmail OAuth

- Human MCP Gmail access is currently read-only; discover the live connector schema rather than maintaining a hard-coded action list here.
- Gmail uses the authenticated user's OAuth flow, not the Google service account used for Docs/Sheets.
- Credentials/tokens stay outside the repo under the configured Human MCP Gmail paths.
- First-time OAuth/tool-schema changes may require Human MCP/session refresh; lifecycle changes still require explicit approval under `docs/PROJECT_CONTEXT.md`.
- Do not add Gmail write/send scopes or actions without an explicit requirement and approval model.

## Browser side effects

- Read-only navigation/search/snapshot actions are allowed when required by the user's task.
- Filling, submitting, sending, applying, connecting, accepting, deleting, purchasing, or equivalent external side effects require the human approval appropriate to that action.
- When a click may create an external side effect and approval is unclear, stop before the click.

## Career/application resources

- Start from the authoritative career instructions/persona and their indexed canonical resources.
- Use direct known Docs/Sheets identifiers when the authoritative index provides them; do not rediscover known resources through unrelated search tools.
- Keep application status in the canonical application log when the user reports a status change.
- Browser control is for the application website, not the default discovery mechanism for indexed CV-system documents.
- If a canonical resource lacks a resolvable identifier, ask once and update the authoritative index rather than guessing.
