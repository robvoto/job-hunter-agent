-Google
add  I accept the terms of service and privacy policy



-also you made me thinkg, how big may job history grow? what are we saving? maybe we can start deleting job history after X time just saving the minimum for our hisory functionality

--mportant finding: this is not just a .env change. The current gateway is coupled to OpenAI’s Responses API and parsed-output behavior, so “support more keys” needs a provider abstraction.

Called tool

To support more AI keys/providers, don’t bolt provider logic into llm_gate.py. Create a small LLM adapter layer and keep the rest of the app provider-neutral.

Current state:

OPENAI_API_KEY=...

Current settings:

"llm": {
  "model": "gpt-4o-mini"
}

Better target:

"llm": {
  "provider": "openai",
  "model": "gpt-4o-mini"
}

And support env vars like:

OPENAI_API_KEY=...
GOOGLE_API_KEY=...
ANTHROPIC_API_KEY=...
OPENROUTER_API_KEY=...
Recommended order

Start with OpenAI + OpenRouter first.

Why: OpenRouter is OpenAI-compatible, so you can support many models with less code change. Gemini/Claude direct APIs are more work because their response formats and structured output handling differ.

Architecture change

Create:

job_hunter_agent/llm_client.py

It should expose one internal interface:

class LLMClient:
    def is_enabled(self) -> bool:
        ...

    def create_text(self, *, model: str, messages: list[dict], max_output_tokens: int) -> str:
        ...

    def parse_json(self, *, model: str, messages: list[dict], max_output_tokens: int, schema_model: type) -> dict:
        ...

Then llm_gate.py stops importing OpenAI directly. It calls your internal client.

Minimal implementation path
1. Add provider to default settings

Update:

"llm": {
  "provider": "openai",
  "model": "gpt-4o-mini"
}
2. Normalize provider in user_settings.py

Add default/allowed provider handling:

DEFAULT_LLM_PROVIDER = str(DEFAULT_USER_SETTINGS[KEY_LLM].get("provider", "openai")).strip()

Then in normalize_user_settings() add:

llm = settings.get(KEY_LLM, {})
settings[KEY_LLM] = {
    "provider": str(llm.get("provider") or defaults[KEY_LLM].get("provider") or "openai").strip().lower(),
    "model": str(llm.get("model") or defaults[KEY_LLM]["model"]).strip(),
}
3. Add adapter factory

Codex-ready instruction:

Create job_hunter_agent/llm_client.py.

Implement provider selection from user settings:
- openai uses OPENAI_API_KEY and base_url default.
- openrouter uses OPENROUTER_API_KEY and base_url https://openrouter.ai/api/v1.
- if key is missing, return disabled client.
- expose get_llm_client(), get_llm_provider(), get_llm_model().
- preserve current behavior for OpenAI.
- for now, use OpenAI-compatible Responses API only for openai.
- for openrouter, use chat.completions and JSON parsing fallback.
4. Refactor llm_gate.py

Replace:

from openai import OpenAI

_api_key = os.environ.get("OPENAI_API_KEY")
client = OpenAI(api_key=_api_key) if (_api_key and not _NO_LLM_MODE) else None

With:

from job_hunter_agent.llm_client import get_llm_client

client = None if _NO_LLM_MODE else get_llm_client()

But don’t expose raw OpenAI clients everywhere. Better rename later:

llm_client = None if _NO_LLM_MODE else get_llm_client()
5. Do not add Gemini direct first

Gemini direct support needs separate handling for:

API SDK
structured JSON output
token/cost logging
model naming
error handling
prompt format differences

Support it after the adapter exists.

Product wording after this change

Once implemented, your tester post can say:

To help me test the app, you will need:

A Google account
An AI API key, currently OpenAI or OpenRouter

Later:

Supported AI providers currently include OpenAI and OpenRouter, with more planned.

  
# Task 2 UI harcoding
These are HTML hardcodes UI options that need un-hardcoding and if logical, be managed from advance settings.
Main issue: HTML, JS, and Python each define their own truth instead of using one shared config/schema.

1 templates/settings.html
Examples: LLM models, themes, yes/no options, onboarding presets, date ranges.

2 HTML hardcodes numeric limits
templates/settings.html
Examples: max pages 1–10, LinkedIn hours 1–168, score 0–100, weights 0–2.

3 Python also owns the same defaults/limits
job_hunter_agent/advance_settings.py
job_hunter_agent/agent_settings.py
This can drift from the HTML.

5 JS shared form-field logic
templates/static/settings/shared/settings-page.js
Shared settings logic now lives here instead of a root-level legacy copy.

6 Business judgement still hardcoded in Python
job_hunter_agent/source_connector.py
Scoring weights, salary penalties, location penalties, convergence bonus.

7 Filtering rules still hardcoded in Python
job_hunter_agent/filters.py
Requirement matching, description confidence, capability rejection logic.

8 CV/profile extraction heuristics hardcoded
job_hunter_agent/profile_learning.py
Role-title tokens, sentence filters, promotion logic.
Capability extraction blocklist hardcoded
job_hunter_agent/cv_pipeline.py
_PHRASE_BLOCKLIST.

9 Docs confirm this problem already exists
docs/HARD_CODED_JUDGEMENT_BACKLOG.md
It lists many of the same hardcoded judgement risks.
 
# Task 5 Title Normalisation Rule
Support ambiguous approved acronyms with extensible contextual mappings.

Do not assume an acronym has a permanently fixed set of meanings.

Approved contextual mappings must support:
- multiple expansions
- later expansion with new meanings
- context evidence
- optional confidence
- optional domain hints

Example structure:

"contextual_abbreviation_expansions": {
  "pm": {
    "needs_context": true,
    "expansions": [
      {
        "value": "project manager",
        "context_keywords": ["project", "delivery", "implementation"]
      },
      {
        "value": "product manager",
        "context_keywords": ["product", "roadmap", "go-to-market"]
      },
      {
        "value": "program manager",
        "context_keywords": ["program", "portfolio", "governance"]
      }
    ]
  }
}

New approved meanings may be added later without changing runtime architecture.

If context resolves the acronym, normalize to the matched expansion.
If multiple expansions remain plausible, keep the original token and emit a review signal.
Do not force ambiguous acronyms into one global meaning.



# Task 7 Seniority filtering
  To be defined

# General Backlog

### Shared job cache (global dedup layer)
Pattern: Split `job_history` into two concerns.
- **Current**: `job_history` is per-user and conflates "has the system seen this job" with "what did this user decide."
- **Problem**: Two users searching for the same role each scrape the same SEEK jobs independently. Dedup only works within each user's own history.
- **Better target**:
  - `job_cache` (global, no user_id) — job_key, title, company, description, first/last seen across all users. Written once when any user first encounters the job.
  - `job_history` (per-user) — user decisions only: state (KEEP/DISCARD), applied, hidden, times_seen by this user. References job_cache by job_key.
- **Payoff**: shared scraping efficiency, foundation for community signals ("N users with similar profiles applied here"), dedup across the whole system.
- **Precondition**: wait until there are real concurrent users. Single-user mode does not benefit.
- **Migration**: schema change required — add `job_cache` table, migrate `job_history` to drop columns that move to cache.


### NEW MANUALLY ADDED - Un-Structured
	- review AI fit brief preview   AI fit review guidance   AI capability naming guidance
	- show the job description on the side?
	- Feedback from users to help make te app great  
  - after onbarding welcome screen fix. 
  - when knowledge reseting we must delete also others , check if i am correct ..or maybe remove this all
  - NOT FOR ME after click the box title can be  misleading. eg:
    Why isn’t "Senior Business Analyst" a fit for you?
	Optional next step. Only add extra blocks when they are safe to reject without more context.
	Always reject exact phrase
	Use this only when any mention should reject the job, even if the term is not framed as a requirement.
	Apply Extra Blocks
		Continue Without Extra Blocks
		View and edit saved rules in the Settings panel.
	
	1 idea is good but what is exactly Apply Extra Blocks ? is that too much or can it be asked diferently?
	2 why is not senior business analyst for me? that is wrong, since it is for me (title wise) . Because it is not the title, it is the content of the job that i found it is bad for me.
		
	- user guide readme and run commands all share things that shouldnt...user guide is for users (we can show later better)
	- seek Classification IDs not used (currently hidden from settings)
	- Dashboard result minimum score in settings may not be Need as a number for normal users and set to whatever worth a look min is
	- in dashbaord when Best Matches has nothing, show a message including something telling the user tp be sure they aare not filtering too much
	- Posting source is hiiden activate when this works great.

	
	- For a dark mode theme, the "Reset All Filters" button should ideally be a secondary or ghost button to avoid distracting from primary actions like "Run Search Now."
	Recommended Styling
	Color: Use a neutral light gray or a desaturated version of your primary brand color (e.g., a soft blue).
	Background: Keep it transparent or a very subtle dark gray that slightly contrasts with the main background.
	Text: Ensure high contrast for readability, using off-white or light gray text.
	State: Only make it "active" (brighter or colored) when filters are actually applied so users know it's usable.

	- consider for candidate job selection/scoring a different layer, government...if the job is a gov job, having gov experience ads value as they are very particular about that
	- consider for candidate job selection/scoring a different layer, clearances...if the job requires a clearance, having them experience is important and if the experience is mandatory, then this i sa rejection pure and simple 
	- consider for candidate job selection/scoring a different layer, education...first we want to save student education in differnent places (and remove if now we do it in capabilities) 
	if the job requires certain education or certification or similar, having them  is important and if the requirement is mandatory, then this is a rejection pure and simple . The app should learn if llm cannot place if something is education, certificate and the like. also we need to capture where the education was done e.g university, pmi etc if possible but not a deal breaker for mvp
	important and if the experience is mandatory, then this i sa rejection pure and simple 
	- consider for candidate job selection/scoring a different layer, industry...first we want to save student education in different places (and remove if now we do it in capabilities) 
	if the job requires certain industry (eg insurance, banking), having them  is important and if the requirement is mandatory, then this is a rejection pure and simple if not found on the candidate. The app should learn if llm cannot place if something is an industry. Candidates may have several industry experience and each can be low (only a few years or too long in the past, decent or strong)
	- OpenAPI: browse /swagger-ui if you want interactive API docs; /docs is still your project markdown JSON.

### Role-level experience duration: use role_experience in scoring

**Status: persist step done** — `cv_pipeline.py` now computes `role_experience` (lowercase title → total months) via `_compute_role_experience()` and writes it to the profile via `run_cv_pipeline()`. Raw lowercase grouping only; seniority variants ("Senior Business Analyst" vs "Business Analyst") stored separately.

**Remaining work**:
- Use `normalize_title_text()` from `title_normalization_rules.py` to collapse seniority variants before grouping (e.g. "senior business analyst" → "business analyst").
- Surface in scoring: when a job requires N years in a role, check `profile["role_experience"].get(role_key, 0) >= min_months` and score accordingly.
- Optionally surface in profile brief so LLM fit review can reference it.
- UI display (years per primary/alternative role) — deferred until scoring is wired up.

**What was done**: `_compute_role_experience(roles)` added to `cv_pipeline.py`; called in `run_cv_pipeline()` and included in output; persists automatically via `source_documents.py patch.update(pipeline_patch)`.

### Required capability not in profile should hurt the score

**Problem**: The scoring system adds points for capabilities it finds in the profile. It does NOT penalise when a job explicitly requires a capability that isn't in the profile. Chinese language proficiency is a clear example: it's required in the job, not mentioned in the CV, and should either push the score down significantly or surface as a named risk. Right now it's invisible — the job scores the same as one with no language requirement.

Capability is the right bucket for this (not a separate language/dimension layer). The gap is the one-directional nature of capability matching — it only rewards matches, it never penalises clearly missing requirements.

**Target behaviour**:
- The LLM or a deterministic detector identifies capabilities in the job description that are marked as required.
- Each required capability is checked against the profile.
- If not found: apply a score penalty and surface it as a named risk on the card ("Required: Chinese — not found in your profile").
- The signal learning system should also suggest the missing required capability as a learning candidate, so the user can confirm "I have this" or "I don't".
- Skills that appear often as "required" across jobs the user rejects could be surfaced in the Optimise/review area as a prompt: "This skill appears as a requirement frequently — do you have it?"

**Precondition**: LLM job requirements extraction (`job_requirements` field) is already in place. This needs a cross-reference step between the extracted requirements and the profile capabilities.

### Company name heuristics for recruiter vs direct employer detection

**Problem**: `infer_posting_channel()` correctly detects company vs recruiter when SEEK/LinkedIn metadata fields are present, but falls back to `kind=unknown` when they aren't. For a job posted by "Green Life Windows Adelaide Pty Ltd", the result is no badge — even though the name alone strongly suggests a direct employer.

Current gaps:
- Company name is not used as a signal at all (Pty Ltd, Inc, Corp → direct employer; "Recruitment", "Staffing", "Resources", "Talent" in name → recruiter).
- `weak_text_matches` returns `kind=unknown` even when recruiter language is found in the description — it should return `kind=agency_or_recruiter` (with lower confidence) rather than staying unknown.
- The badge rendering only shows Company/Recruiter when `source == "metadata_first"`. Name-based and text-based inferences should also show a badge (possibly with a confidence qualifier like "likely").

**Target behaviour**:
- Add a name-pattern check in `infer_posting_channel()`: Pty Ltd / Inc / Corp etc. → `kind=direct_employer, source=name_pattern`. Known recruiter name tokens → `kind=agency_or_recruiter, source=name_pattern`.
- When weak text matches find recruiter language → `kind=agency_or_recruiter, source=text_inference` rather than staying `unknown`.
- Update badge rendering to show the badge for all resolved kinds, not just `metadata_first`. Name-pattern and text-inference can show a slightly different tooltip to indicate confidence level.
- The recruiter name tokens and Pty Ltd patterns belong in `posting_channel_indicators` managed knowledge, not hardcoded.



## We must un hardcode never! These are hardcoded issues
- "stopwords"
- generic_summary_phrases
- identity rules
-  source connector: deterministic_review_outcome
- is this part of the search in settings?
    "enabled_sources": ["seek", "linkedin"],
    "enabled_sources": ["seek"], # Default to 'seek' if not explicitly configured
    "search_settings": {
        **DEFAULT_SEARCH_SETTINGS,
    },
	
	
 - Security
 One caveat: the app still has broad CORS headers in fastapi_app.py (line 134), which is a separate issue.

## Production hardening — EC2 deployment (added 2026-05-22)

The app is now deploying to AWS EC2 (Ubuntu 24.04 + EBS). The following gaps must be closed before the deployment is treated as stable. These are not optional.

### Security
- **CORS headers too broad** — `fastapi_app.py` allows all origins. Must be locked to the actual production domain once Nginx + HTTPS is in place.
- **Session cookie `secure` flag** — confirm `JOB_HUNTER_SESSION_COOKIE_SECURE=true` is set in production env so cookies are HTTPS-only.
- **Admin gate audit** — verify every admin-only route and API endpoint calls `is_admin()`. Any gap is a privilege escalation risk with real users on the system.

### Config / data paths
- **EBS data volume** — `JOB_HUNTER_DATA_DIR` and `JOB_HUNTER_OUTPUT_DIR` must point to the EBS mount path in the systemd unit file, not the repo root. Document this in `docs/aws-ec2-setup.md`.
- **`.env` on EC2** — production env vars (session secret, OAuth keys, admin email) must live in a restricted file on the instance, not checked into git.

### Ops
- **systemd unit** — app must restart on failure (`Restart=always`). Log to a persistent path on EBS, not the repo.
- **Nginx reverse proxy** — required before exposing any port publicly. Document config in `docs/aws-ec2-setup.md`.
- **HTTPS** — Let's Encrypt / ACM required. No production traffic over plain HTTP.
- **Backup** — EBS snapshot schedule for the data volume.

### Observability
- **Silent failures** — scraper and LLM errors must surface as visible admin alerts, not swallowed to logs only. This becomes critical when not sitting at the machine.
- **CORS/security error logging** — rejected requests should be logged at WARN level with enough context to diagnose misconfiguration.


4. Broken Path in job_types.py (Risk: Logic Failure)
In job_types.py, the pathing is inconsistent with the rest of the app.

The Bug: It defines _JOB_TYPE_STORE_PATH using Path(__file__).resolve().parent / "data" / "job_type.json". This points inside the job_hunter_agent/ package folder. However, all other data (like profile.json) is stored in a root-level data/ directory.
The Impact: The app likely fails to find or load your job type mappings, which degrades the accuracy of role classification.

5. Render-Time Calculation Drag (Risk: Performance Bottleneck)
In dashboard_renderer.py, fit scores and highlights are calculated inside the HTML rendering loop.

The Bug: Every time you refresh the dashboard, the app re-runs heavy regex matching and capability scoring for every job in your shortlist and history.
The Impact: As your job_history.json grows to hundreds or thousands of records, the dashboard will become increasingly sluggish, eventually taking several seconds to load a single page.
    
---
 

- on reonboarding maybe make optional wiping out
It must not wipe user_profile_overrides, must_not_require_skills, review decisions, or learning history.

That is the correct boundary.

Only future improvement I still recommend:

"contextual_abbreviation_expansions": {}

for ambiguous acronyms like:

PM
GP
SM
EM

But that can come later.

Right now the structure is good and safe to grow.



- for 

"title_similarity_threshold": 0.8,
  "company_suffixes": [
    "pty",
    "ltd",
    "inc",
    "corp",
    "corporation",
    "limited",
    "llc",
    "holdings",
    "group",
    "australia"
  ]
  I did the basics but this is missing:
Layer 2 — next
Improve scrapers to capture stronger IDs:
platform job ID
canonical URL
advertiser/company profile ID
ATS/requisition ID if visible

Layer 3 — later
Build identity graph:
jobs are linked by evidence
not deleted

Layer 4 — optional
Use LLM only to help label/group uncertain links
never to hide jobs


- I need to know for each thing done the cost in USD or AUD whatever it is the source

Basically after every llm intervention , we categorise that intervention and we can learn about it...
for example after scrapping, after categorising, after searching...
Can you show me this in the advanced settings? 
Fx and UI idea:
- latest costs (so the last time each llm in each category was called) for example latest run cost $0.2 is the currency
- and then the accumulated costs but this one should be per candidate so for me i would learn since we implement this how much i have spent and it shouldnt be reset (this we keep as a car keeps their kilometre count)
- Then i want a admin only advance setting to stop all LLM work when reached a MAX i will set and a warning on top that LLM is OFF on all screens
We want this cost  log too 
 
	
- be sure seek or linkedin scrapping dont fail silently. I need a way to know taht if linkedin or seek or any new board i add change their variables or other things affecting our scrapping info quality, we must know so we can adapt. Maybe i need a section in adavance admin with major warnings as list there. This board can be also used to tell me if we are overusing regex so llm is not wokring as expected or something needs learning or worse it usually fails.

-normalize_job_key is hardcoding many central values


- There is no dedicated “advance settings alert” mechanism in place today.

What exists now:

needs_review flags on individual signals and extracted items
warning badges in the dashboard
signal_registry for pending learning review
review_data / history warnings for surfaced issues
What does not exist:

a global alert bucket in advance_settings.py that says “review this area of code with me”
a central admin warning list for code-quality or pattern-quality concerns
So if you want a real mechanism for “we are missing the mark, review this with me”, the right shape is:

a global review-warning section, not another tuning setting
backed by managed data, not hardcoded text
surfaced in Admin or the dashboard, not hidden in feature code
My recommendation:

keep advance_settings for tunables only
add a separate global review/warning store if you want proactive flags
use it for things like:
“regex family needs review”
“scraper quality changed”
“LLM suggestions look noisy”
“new rule family should be inspected”
If you want, I can next propose the minimal design 


- we need a selection to select MAX power Med or Min so we choose pgt 4.1 mini for min 5.1 for mid and latest 5.5 for MAX with a message that they MUST accept that costs will be increased and we should show if possibler the cost per token and an exmple (if you find this just create the message and make it static so you dont rewrite this every time and waste llm calls

- setup openkey when onboarding (if not NO LLM explanation means shit experience) give option for grok claude openai  

- in global settings, Model pricing per 1M tokens should have a refresh so the llm or whatever should refresh with the latest values for the llms listed in the box and it sohuld be read only  and it should show only llms listed in Allowed models


- Capability strength preset should be defaulted to balance for new onboarding actitity but it is no use in global settings s oremove from there unless it affects seomthing else we dont know

-in global settings, it says Default country suffix but the value is the full country...which is which?

-remove from settings js all the fallback values that are already served from global settings
