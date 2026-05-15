# UI Backlog

### Job decision output

- [ ] For each shortlisted job, output a clear decision summary

  Context:
  - Output why the job fits.
  - Output next action:
    - apply
    - review
    - skip

---

### SEEK login automation

- [ ] Investigate SEEK login automation

  Context:
  - Browser automation is possible.
  - It is fragile and risky.
  - Do not rely on this until investigated properly.

---

## Low Priority / Later Backlog

### Labels and wording

- [ ] Rename recruiter badge

  Context:
  - Current recruiter badge wording may not be clear or polished enough.

---

- [ ] Explain “Block similar titles” better

  Context:
  - Need a clear explanation that blocking similar titles improves efficiency.
  - It also helps avoid consuming unnecessary tokens.

---

- [ ] Explain security and CV data handling

  Context:
  - Add clear user-facing explanation about CV information and security.

---

### Run stats and workspace status

- [ ] Fix Last Run & Review / Latest Run Stats empty state

  Context:
  - Current message always says:
    - “No run stats yet. Run the current job-source connector once and reload this page.”
  - Need to confirm whether stats are not being saved, not being loaded, or not being displayed.

---

- [ ] Clarify “0 cards scanned” under Potential Jobs

  Context:
  - Current text is confusing:
    - “below Potential Jobs what 0 cards scanned means?”

---

### Settings UI

- [ ] Standardise Search settings panel layout

  Context:
  - In settings, the Search panel UI/UX is inconsistent.
  - One section uses separate panels.
  - Another is inside a bigger panel.
  - Standardise panel structure on the same screen using best practices.

---

- [ ] Move / improve Save Search Settings button

  Context:
  - Save Search Settings button is in a bad place.
  - Current placement is poor UX.

---

- [ ] Show whether Daily Search Schedule is already scheduled

  Context:
  - In settings, Daily Search Schedule should clearly show current schedule state.

---

### LLM profile brief / prompt context
---

- [ ] Review duplicate profile loading between prompt builders

  Context:
  - `build_profile_prompt_context()` and `build_system_prompt()` are called independently in different places.
  - `build_system_prompt()` always calls `build_profile_prompt_context()` inline.
  - If both are called separately, the profile may load twice.
  - Minor issue, but worth knowing.

---

### Input / file handling

- [ ] Restrict improve input file types

  Context:
  - Limit improve input to formats such as:
    - docx
    - md
    - pdf
  - This may affect onboarding.

---

- [ ] Delete unused `application_inputs` references

  Context:
  - `application_inputs` and references to it are not to be used.

---

### Token / abuse protection

- [ ] Set GPT-4.1 in knowMe and add abuse protection

  Context:
  - Set `gpt-4.1` in knowMe.
  - Add protections to avoid abuse and burning tokens.
  - Current note:
    - nobody has used it yet.

---

### Expanded role search

- [ ] Design “other roles” / adjacent opportunity search

  Context:
  - User may be a good fit for implementation consultant/configurator roles.
  - Examples:
    - SaaS configurator
    - monday.com
    - Guidewire
  - These may not read as “Senior BA” initially.
  - Need to decide whether this is:
    - keyword
    - special feature
    - separate search profile

---

### Default assumptions for new users

- [ ] Define default rule for missing CV evidence

  Context:
  - For new users, if something is not in the CV, assume they do not have it.
  - Potential enhancement:
    - on first profile load, create a list of common missing items looked for in jobs.
  - If too advanced, defer.

## High Priority / Core Product Decisions

### CV handling

- [ ] Decide whether to store the CV or ask the user

  Context:
  - Question:
    - should we save the CV?
    - or ask the user explicitly?
  - This impacts privacy, UX, and system design.

---

### Terminology clarity

- [ ] Clarify meaning of “Recent roles”

  Context:
  - Current label unclear
  - Users may not understand what it represents

---

### UX bug (important)

- [ ] Fix scroll reset when returning from job detail

  Context:
  - After opening a job and going back:
    - scroll resets to top
  - Breaks usability significantly

---

### Settings usability

- [ ] Add search bar in settings

  Context:
  - Settings becoming large
  - Need quick navigation

---

### Duplicate / similar job detection

- [ ] Detect similar roles across platforms and avoid duplicate applications

  Context:
  - Same role posted by multiple agencies/platforms
  - Example:
    - IQVIA Senior Business Analyst appears in multiple places
  - Risk:
    - applying multiple times
    - wasting effort
  - Idea:
    - link similar roles
    - show previously applied ones

---

### Location handling

- [ ] Fix location configuration across sources

  Context:
  - Location currently under SEEK only
  - Should apply to LinkedIn as well
  - Current field is a simple textbox, not using onboarding structure

---

### Settings UX issues

- [ ] Fix Search / Run / Settings UX structure

  Context:
  - Save button in wrong place
  - Section not user-friendly
  - Needs redesign

---

- [ ] Sync onboarding fields with settings

  Context:
  - Locations and keywords should sync
  - Changes in onboarding/reset must reflect in settings

---

### Search positioning in product

- [ ] Re-evaluate search placement in UI

  Context:
  - Currently hidden in admin
  - But workspace has “run search” without params
  - Needs consistent product logic

---

### Job sources expansion

- [ ] Add new sources

  Context:
  - https://iworkfor.nsw.gov.au/jobs
  - https://www.apsjobs.gov.au/
  - Need scraping analysis

---

### Product positioning / marketing

- [ ] Track features for marketing (“boostmyapp” file)

  Context:
  - Capture strong features locally
  - Use later to present/sell product

---

### Search input protection

- [ ] Prevent bad user inputs / DOS risk

  Context:
  - Do not allow meaningless inputs (e.g. 1-word)
  - Need controlled search parsing

---

### Direct vs recruiter roles

- [ ] Prioritise direct company roles

  Context:
  - Direct hiring is faster and better
  - Recruiters often slow/unresponsive
  - User prefers direct roles first

---

### Company reputation system (experimental)

- [ ] Investigate company/recruiter rating system

  Context:
  - Idea:
    - track rejections / responses
    - rate recruiters and hiring process
  - Potential:
    - public anonymous ratings
  - Concern:
    - legal implications
	## Feature-Specific Backlog (Structured from Source)

### Onboarding UI / UX (Aliases + Visual clarity)

- [ ] Improve alias display in onboarding

  Context:
  - Do NOT hide aliases in dropdowns if list is long.
  - Show as small grey pill tags under the title.
  - Goal:
    - user verifies AI logic instantly without clicking.

---

- [ ] Improve onboarding visual clarity (contrast + scanning)

  Context:
  - Use slightly darker background for page.
  - Use pure white for cards.
  - Add subtle color tint for selected dropdown values (e.g. light blue).
  - Helps users scan priorities quickly.

---

- [ ] Improve separation between cards

  Context:
  - Use horizontal line or larger spacing.
  - Avoid visual clutter.

---

### Workspace Terminology

- [ ] Rename “Conditional Fit”

  Context:
  - Proposed:
    - “Potential Matches”
    - “Stretch Roles”
  - Reason:
    - “Conditional” sounds negative
    - “Potential” sounds positive

---

### Settings (multi-search + tuning)

- [ ] Support multiple parallel searches

  Context:
  - Each search has:
    - its own config
    - its own run
  - Currently only one search exists
  - Must PLAN FIRST

---

- [ ] Verify Suggested Tuning feature

  Context:
  - Not clear if working

---

### Product / Growth

- [ ] Plan for user onboarding and testing

  Context:
  - Need users to test app
  - Options:
    - Render deployment
    - early SaaS setup
  - Question:
    - do we need DB yet?

---

### Settings clarity

- [ ] Clarify “Never run” label

- [ ] Improve “Reject jobs requiring” help placement

  Context:
  - Should behave like expandable help
  - Current placement looks wrong

## Additional Feature Backlog (From Source)

### Workspace clarity issues

- [ ] Clarify “130 Cards Seen”

  Context:
  - Current number confusing
  - User did not interact with that many cards
  - Needs proper definition

---

### Deployment / Platform

- [ ] Decide deployment approach

  Context:
  - Options:
    - Render
    - AWS
  - Question:
    - do we need DB yet?
    - is this becoming SaaS already?

---

### External integration

- [ ] Investigate using personal SEEK login

  Context:
  - Use real account to access jobs
  - Question:
    - feasible?
    - relevant?

---

### Location selection (SEEK-style UI)

- [ ] Replace free-text location with structured selector

  Context:
  - Current:
    - single textarea
  - Target:
    - SEEK-style location selector
  - Add to admin UI
  - Could include:
    - main location (e.g. Canberra)
    - sub-location (e.g. Sydney CBD)

---

### Scraping reliability

- [ ] Add validation for scraping configuration

  Context:
  - Ensure:
    - selectors
    - IDs
    - field names
    - URLs
  - Stay up to date with SEEK changes
  - Provide manual “check” trigger

---

### Job freshness / reliability

- [ ] Improve detection of job freshness (especially LinkedIn)

  Context:
  - LinkedIn job age unreliable
  - External links often show real age
  - If real post date cannot be determined:
    - job should be considered untrustworthy

---

### Onboarding UX improvement

- [ ] Add post-upload preview page

  Context:
  - Show:
    - extracted summary
    - strengths
    - editable fields
  - Before entering admin
  - Makes onboarding more product-ready

---

### Architecture decision

- [ ] Decide if database is required

  Context:
  - Currently local
  - Question:
    - needed for multi-user / SaaS?

---

### Workspace refresh behaviour

- [ ] Improve auto-refresh logic

  Context:
  - Currently refreshes every 60s
  - Better:
    - refresh only when job run completes

---

### Application generation (major feature)

- [ ] Build application pack generator

  Context:
  - After selecting a job:
    - generate tailored CV
    - generate cover letter
    - generate pitch notes
    - highlight fit vs gaps
    - include job-specific evidence
  - Moves system from:
    - job finder → full application assistant
  - Major selling point

---

### Workspace terminology

- [ ] Clarify “Saved Earlier” vs “Older Saved”

  Context:
  - Difference unclear
  - Needs clearer naming or explanation

