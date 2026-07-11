# User Guide

## What This App Does

This app helps a candidate build a profile once, review jobs against that profile, and keep a local shortlist that gets better over time.

Current live job source:

- SEEK
- LinkedIn

That is the current source connector, not the final limit of the product.

## First-Time Use

1. Follow the **Environment Setup** and local web UI startup instructions in [OPERATIONS.md](OPERATIONS.md).
2. Open:

- `http://127.0.0.1:8765/start`

3. Upload:

- one strong detailed CV (supports .docx and plain text)
- optionally extra notes in plain English

If you open the app from another device on your local network, the login session still works over plain HTTP. The cookie only flips to `Secure` when the request is HTTPS unless you force it with `JOB_HUNTER_SESSION_COOKIE_SECURE`.

4. Click `Create Profile`

5. Then open settings:

- `http://127.0.0.1:8765/settings`

The app will create or enrich your runtime profile (stored in the SQLite DB), which becomes your working profile for job matching.

## CV Structure For Better Extraction

This guidance is optional. Job Hunter should not force you to rewrite a CV before onboarding, but extraction is more reliable when the source document is structured clearly.

Best input:

- roles listed in reverse chronological order
- dates for each role, ideally month and year
- clear job titles and employer names
- bullet points that describe what you actually did
- skills, tools, domains, and platforms near the roles where you used them
- recent detailed roles first, with older or less relevant roles kept shorter

Avoid when possible:

- one-page marketing CVs with almost no role detail
- image-heavy layouts where text extraction may fail
- missing dates or vague time ranges
- mixing several unrelated target directions into one short summary

Plain, detailed content usually beats polished formatting. If the extracted draft looks wrong, improve the source structure and rebuild onboarding rather than hand-tuning every downstream setting.

## Privacy And CV Data

Job Hunter does not keep the raw uploaded CV as a long-term user-facing file.

It uses the uploaded document to extract matching signals and profile structure, then keeps the runtime profile, review state, and other working data needed for job matching.

Decision:

- the runtime profile is what matching uses after onboarding
- the raw uploaded CV is not treated as the ongoing source of truth
- if a future application-pack feature needs a CV file, the app should ask for or manage that source document explicitly
- packaged/shared builds must not include developer CVs, profiles, job history, scraped jobs, logs, runtime DBs, or private examples

If you want the broader retention context, start from the documentation index and the operational docs.

## What Onboarding Creates

The onboarding flow creates a runtime profile from your source documents.

That profile includes:

- candidate summary
- fit brief
- CV/background text
- up to 3 search locations, chosen from the canonical AU states and capital cities list
- profile support tiers
- capability rules
- title targeting hints

You can then refine those fields from the settings UI.

## What Settings Is For

Use the settings UI to maintain the runtime profile and review controls.

Tabs:

- `Search`: controls the current job-source query
- `Candidate Profile`: profile summary, fit brief, evidence text, search preferences, and rules
- `Review`: hidden jobs, applied jobs, and skill-review decisions
- `Test`: latest run stats and rejected samples

Think of settings as the maintenance surface for your profile, not the place where you upload raw source files every time.

Search placement rule:

- configure search terms, location, enabled sources, and preference settings in `Settings`
- start or stop an actual search from the `Workspace`
- review results, run status, and job decisions in the `Workspace`
- return to `Settings` only when you want to change what the next run should search for

Search location uses one canonical AU choice only. The UI defaults to a recommended state or capital city, then SEEK and LinkedIn adapt that same value to their own search format.

SEEK also has its own on/off switch in the Search section. Turn it off when you want to skip SEEK runs entirely while leaving the rest of your settings alone.

Sector preference now uses the same checkbox-strip pattern as work mode and work type. Pick Public sector, Private sector, or both if you do not care which sector a role is in.

## What Admin Is For

Use the Admin screen for owner-only global controls.

It covers:

- global display and search defaults
- onboarding defaults and capability presets
- shared learning and signal review

Changes here affect the app globally, but users do not edit them from their own Settings screen.

## What The Main Profile Fields Mean

`Candidate summary`

- the short top-level positioning statement
- created from onboarding, then edited over time

`Fit brief`

- the short machine-facing positioning brief used by the LLM prompt
- can be generated automatically from profile rules or edited manually

`CV / background text`

- the larger background context used for matching and LLM review
- this should reflect what you uploaded during onboarding
- you can edit it, but it should stay consistent with your real experience

`Profile support tiers`

- primary, secondary, and background evidence blocks used for matching and LLM review
- lets the profile weight recent direct evidence above older or optional context

`Capability rules`

- structured capability names with strength and aliases
- used by deterministic filtering and the LLM prompt

`Title targeting`

- target roles, also-consider roles, and a single search keyword
- used to keep role targeting configurable per candidate instead of hardcoded in code

`Minimum annual base (excludes super)` / `Minimum daily rate (excludes super)`

- optional salary targets used as light fit signals
- if a role lists pay, the workspace can show whether it meets your target
- these targets also power the salary filter in the workspace

`Search keyword`

- a single role term used by onboarding and search
- keep it broad enough to capture relevant roles without combining multiple titles into one field
- the helper text under the field should stay short and explanatory

`Sector preference`

- optional public/private preference for search
- leave it at no preference unless you want sector filtering to be active

`Work type`

- lets you include Permanent, Contract, and FTC (Full Time Contract) roles in search and review
- FTC is shown as a short chip label, but means Full Time Contract
- contract-length preference applies to Contract and FTC roles where a duration is visible

`Work mode`

- lets you include remote, hybrid, and on-site in search
- this is the search preference shown on the onboarding Search Basics step

## Running A Job Review

Follow the standard refresh workflow in [OPERATIONS.md](OPERATIONS.md).

Before running, confirm search setup in `Settings > Search`. The runtime profile controls which sources are active. If `LinkedIn` is not in `enabled_sources` for the current user profile, the run will skip it.

Then open the workspace at:

- `http://127.0.0.1:8765/workspace`

If the workspace sidebar shows all zeroes after a run that otherwise completed, check that you are in the same authenticated user session that triggered the scrape. The `This Run`, `Crawler Stats`, and `Applications` cards are user-scoped, so a mismatched session or fallback local path can make a good run look empty.

## Match Score Bands

The workspace groups jobs by their calculated fit score:

- **Strong match** (85-100): High alignment with core capabilities and experience.
- **Good match** (70-84): Solid alignment, perhaps missing secondary criteria.
- **Possible fit** (55-69): Plausible fit worth reviewing.
- **Stretch** (0-54): Low alignment or significant requirement gaps.

The workspace groups jobs into:

- `Potential Jobs`
- `Applied`
- `Hidden`

The sidebar counts on the workspace are not global totals. They come from the active user bucket and the most recent saved run for that same user.

The workspace can filter by:

- match score
- posted age
- work mode
- salary state

## Job Card Layout

Each job card in the workspace can expand into up to four separate panels, so fit reasoning, requirement coverage, risk flags, and internal debug detail don't get mixed together:

- **Fit breakdown** — why the score landed where it did: requirement coverage only, shown as a short set of direct bullets. Location, freshness, Easy Apply / Quick Apply, viewed status, salary, and action recommendations are context only, not fit evidence.
- **Checks before applying** — one merged review panel for incomplete description capture, red flags from review history, salary issues, missing or partial requirements, and other pre-apply checks. The old separate warning banner is gone.
- **Requirements** — the extracted requirement list with per-item status (in profile, partial match, not in profile). Normal mode hides the matched capability and source-text subtitle, and debug mode shows it.
- **Debug: LLM fit review** (debug mode only) — LLM decision/grade/cost, filter status, raw score breakdown, matched text, capability mapping, and reviewed-signal evidence for troubleshooting why a card was scored or filtered as it was. Hidden entirely outside debug mode.

The workspace summary counts at the top of a run are operational totals for the scrape, not proof that every listed role is a strong fit.

When Job Hunter explains why a role fits, the primary user-facing evidence is requirement coverage. Convenience or context signals such as location, freshness, Easy Apply / Quick Apply, viewed status, salary, and action recommendations can still appear in the UI, but they are not core fit evidence.

## Improving Accuracy (Rejection Learning)

If the agent keeps suggesting roles with a specific requirement you don't have (e.g., a specific security clearance or software tool), use the **Not For Me** button on the job card.

- It will prompt you to select the "mandatory blockers" found in that job description.
- Once saved, the agent learns to automatically reject future roles that list those terms as mandatory requirements.
- You can review and delete these rules in the **Admin > Learning** screen.

## Dodgy Jobs

The app also flags job ads that look suspicious or stale.

- `job_closed` means the posting page says the role is no longer available.
- `date_mismatch` means the external job page looks much older than the source listing.
- `cv_farming` means the wording looks like the employer is collecting CVs rather than advertising a live role.

These checks are shown for review and do not replace your own judgment.

## LLM Use

Desktop v1 does not use `OPENAI_API_KEY` or any other global/provider key source.
The desktop rule is:

> No global keys. No shared learning. No upload without consent.

Current behavior:

- deterministic filters run first
- only surviving job descriptions reach the LLM
- the LLM reads from your runtime profile (DB)
- it returns only `KEEP`, `REJECT`, or `MAYBE`
- you can tune AI fit review guidance and AI capability naming guidance in **Settings**

If user-owned provider-key support is not configured, the app runs without live LLM review.

## Security and Network Access

If you are running this app on a home server or accessing it over a network, please see the **Network Deployment & Security** section in Operations.md.

## Operations and Commands
For detailed CLI flags, automation setup, and troubleshooting, refer to OPERATIONS.md.

## Local Files To Keep

- The SQLite DB (path set by `JOB_HUNTER_DB_PATH` — contains profile, history, settings, run data)
- `data/runtime/llm_cache.json`

These are also local-only if used:
 
- `.venv/`
