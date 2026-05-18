- if no resutls we should give tips to user 
- we dont show the name of the person logged in- 
  
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
 

# Task 4 Fix title normalization learning and usage.

1. title_normalization_rules.json is approved runtime knowledge only.
   It may contain:
   - seniority_modifiers
   - one-to-one abbreviation_expansions
   - contextual_abbreviation_expansions
   - normalization settings

2. Remove learning_candidates from title_normalization_rules.json.
   Pending/unclear candidates must go to:
   - output/title_normalization_review.json
   or
   - signal_registry as CATEGORY_TITLE_NORMALIZATION_CANDIDATE

3. Do not store confidence/needs_review/pending suggestions in approved rules.

4. Support ambiguous approved acronyms with contextual mappings.

Example:
PM may have multiple approved expansions:
- project manager when context mentions delivery, implementation, project
- product manager when context mentions roadmap, product, go-to-market
- program manager when context mentions program, portfolio, governance

If context resolves it, normalize using the matched expansion.
If context does not resolve it, keep the token as-is and create a review candidate.

5. Replace hardcoded sr/jr/gp/pm detection.
   Detect unknown short uppercase/acronym title tokens from CV/job titles.
   Clear safe mappings may auto-promote.
   Ambiguous mappings require admin review.

6. Usage must be end-to-end:
   - CV/onboarding title extraction uses title normalization
   - title-pattern generation uses title normalization
   - runtime job title filtering uses title normalization
   - quick card filtering uses title normalization
   - scoring title metadata uses normalized/decomposed title info
   - learning writes candidates to review, not approved rules

7. Tests:
   - title_normalization_rules.json has no learning_candidates
   - PM candidate is written to review, not one-to-one rules
   - contextual PM can resolve to different approved meanings
   - unresolved PM remains PM and needs review
   - uploaded CV with new acronym creates review candidate
   - runtime matching uses approved one-to-one and contextual normalization
   
   
   
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
