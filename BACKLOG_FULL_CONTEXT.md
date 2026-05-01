# Job Hunter Agent — BACKLOG (FULL CONTEXT PRESERVED)

NOTE:
- NOTHING removed
- NOTHING summarised
- Each line kept as-is for validation

- [ ] ------------------------ ---------------------------------

  Context:
  ------------------------ ---------------------------------

- [ ] ------------------------ OPENCLAW ------------------------

  Context:
  ------------------------ OPENCLAW ------------------------

- [ ] ------------------------ ---------------------------------

  Context:
  ------------------------ ---------------------------------

- [ ] Feasible with OpenClaw now:

  Context:
  Feasible with OpenClaw now:

- [ ] ✅ Scheduled runs (12pm + 6pm) — OpenClaw has heartbeat/scheduling built in

  Context:
  ✅ Scheduled runs (12pm + 6pm) — OpenClaw has heartbeat/scheduling built in

- [ ] ✅ Learn from applied jobs — reads your decisions, updates profile/rules

  Context:
  ✅ Learn from applied jobs — reads your decisions, updates profile/rules

- [ ] ✅ Learn from interview/call outcomes — same pattern, you tell it, it updates

  Context:
  ✅ Learn from interview/call outcomes — same pattern, you tell it, it updates

- [ ] ✅ Improve prompts — agent reads and edits files in the repo

  Context:
  ✅ Improve prompts — agent reads and edits files in the repo

- [ ] ✅ Improve code — same, it can write diffs and apply them

  Context:
  ✅ Improve code — same, it can write diffs and apply them

- [ ] Feasible but more work:

  Context:
  Feasible but more work:

- [ ] ⚠️ Token usage monitoring — needs an API call to OpenAI, doable but not native

  Context:
  ⚠️ Token usage monitoring — needs an API call to OpenAI, doable but not native

- [ ] ⚠️ Test console — this is a Job Hunter feature to build, not OpenClaw itself

  Context:
  ⚠️ Test console — this is a Job Hunter feature to build, not OpenClaw itself

- [ ] ⚠️ Login to Seek — browser automation is possible but fragile and risky

  Context:
  ⚠️ Login to Seek — browser automation is possible but fragile and risky

- [ ] - can openclaw or sth listen to my interview conversttion to then improve

  Context:
  - can openclaw or sth listen to my interview conversttion to then improve

- [ ] "Stop" = alert only for now. You're right, it can't reach OpenAI without your credentials.

  Context:
  "Stop" = alert only for now. You're right, it can't reach OpenAI without your credentials.

- [ ] ------------------------------------------------------------------------------

  Context:
  ------------------------------------------------------------------------------

- [ ] Turn this Python job-hunter prototype into an OpenClaw tool-first agent.

  Context:
  Turn this Python job-hunter prototype into an OpenClaw tool-first agent.

- [ ] Goal:

  Context:
  Goal:

- [ ] - Keep my existing scraper/filter logic

  Context:
  - Keep my existing scraper/filter logic

- [ ] - Do not rewrite everything

  Context:
  - Do not rewrite everything

- [ ] - Wrap the scraper as a callable tool inside an OpenClaw workspace

  Context:
  - Wrap the scraper as a callable tool inside an OpenClaw workspace

- [ ] - Add memory so the agent remembers jobs already seen, jobs I liked, and jobs I rejected

  Context:
  - Add memory so the agent remembers jobs already seen, jobs I liked, and jobs I rejected

- [ ] - Add a daily loop that finds only new worthwhile jobs

  Context:
  - Add a daily loop that finds only new worthwhile jobs

- [ ] - For each shortlisted job, output:

  Context:
  - For each shortlisted job, output:

- [ ] 1. why it fits me

  Context:
  1. why it fits me

- [ ] 2. next action: apply / review / skip

  Context:
  2. next action: apply / review / skip

- [ ] Constraints:

  Context:
  Constraints:

- [ ] - Local-first where possible

  Context:
  - Local-first where possible

- [ ] - Minimise paid model usage

  Context:
  - Minimise paid model usage

- [ ] - Keep LLM calls optional and only for shortlisted jobs

  Context:
  - Keep LLM calls optional and only for shortlisted jobs

- [ ] - Preserve my current repo structure unless change is necessary

  Context:
  - Preserve my current repo structure unless change is necessary

- [ ] - Add clear logging and JSON output for all jobs processed

  Context:
  - Add clear logging and JSON output for all jobs processed

- [ ] - Prefer simple, debuggable code over clever abstractions

  Context:
  - Prefer simple, debuggable code over clever abstractions

- [ ] The only way to derive the weights from data is outcome calibration: track which jobs you applied for and whether you got an interview, then fit the weights to maximise predictive accuracy. After ~30–50 outcomes you'd have enough signal to calibrate. That's the path to true

  Context:
  The only way to derive the weights from data is outcome calibration: track which jobs you applied for and whether you got an interview, then fit the weights to maximise predictive accuracy. After ~30–50 outcomes you'd have enough signal to calibrate. That's the path to true

- [ ] -remove old models: all this models are occupying a lot of space how to remove some

  Context:
  -remove old models: all this models are occupying a lot of space how to remove some

- [ ] ollama list

  Context:
  ollama list

- [ ] ollama rm llama3.1:8b

  Context:
  ollama rm llama3.1:8b

- [ ] ollama rm qwen3.5

  Context:
  ollama rm qwen3.5

- [ ] OpenClaw is recreating the auth.json file because a bug in versions 2026.3.22 and later triggers a forced OAuth re-authorization flow on every startup, invalidating existing refresh tokens and overwriting credentials. This creates a broken authentication loop where the system cannot persist valid credentials.

  Context:
  OpenClaw is recreating the auth.json file because a bug in versions 2026.3.22 and later triggers a forced OAuth re-authorization flow on every startup, invalidating existing refresh tokens and overwriting credentials. This creates a broken authentication loop where the system cannot persist valid credentials.

- [ ] -------------------------------------------------------------------------------------------

  Context:
  -------------------------------------------------------------------------------------------

- [ ] -------------------------------------------------------------------------

  Context:
  -------------------------------------------------------------------------

- [ ] ---------------------------------DO NEXT --------------------------------

  Context:
  ---------------------------------DO NEXT --------------------------------

- [ ] -------------------------------------------------------------------------

  Context:
  -------------------------------------------------------------------------

- [ ] - location will always match as that is what we are searching in Seek.com or linkedin. We can later make it close to home but lets do that later

  Context:
  - location will always match as that is what we are searching in Seek.com or linkedin. We can later make it close to home but lets do that later

- [ ] So not sure how location is working in scoring

  Context:
  So not sure how location is working in scoring

- [ ] - what else could we suggest by learning from patterns? this is powerful and tell me how you teach the app

  Context:
  - what else could we suggest by learning from patterns? this is powerful and tell me how you teach the app

- [ ] -onboarding,

  Context:
  -onboarding,

- [ ] 3. Optimize the Aliases

  Context:
  3. Optimize the Aliases

- [ ] Don't hide them in a dropdown if the list is long.

  Context:
  Don't hide them in a dropdown if the list is long.

- [ ] Show them as small gray pill tags directly under the title. This lets the user verify the AI's logic instantly without clicking.

  Context:
  Show them as small gray pill tags directly under the title. This lets the user verify the AI's logic instantly without clicking.

- [ ] Color & Accessibility Improvements

  Context:
  Color & Accessibility Improvements

- [ ] Contrast: Use a slightly darker background for the "Page" and a pure white for the "Card."

  Context:
  Contrast: Use a slightly darker background for the "Page" and a pure white for the "Card."

- [ ] Active States: Give the dropdowns a subtle color tint when a value is selected (e.g., a light blue background for "Essential") so the user can "scan" their priorities by color rather than reading every word.

  Context:
  Active States: Give the dropdowns a subtle color tint when a value is selected (e.g., a light blue background for "Essential") so the user can "scan" their priorities by color rather than reading every word.

- [ ] Separator: Use a simple horizontal line --- or a thicker gap between cards.

  Context:
  Separator: Use a simple horizontal line --- or a thicker gap between cards.

- [ ] --

  Context:
  --

- [ ] --------------------------------------------------------------------------------------------------------------------

  Context:
  --------------------------------------------------------------------------------------------------------------------

- [ ] ------------------------------------------------------GENERAL --------------------------------------------------------

  Context:
  ------------------------------------------------------GENERAL --------------------------------------------------------

- [ ] --------------------------------------------------------------------------------------------------------------------

  Context:
  --------------------------------------------------------------------------------------------------------------------

- [ ] - Apply best practice patterns to large files

  Context:
  - Apply best practice patterns to large files

- [ ] - Interactive Tuning: Turn the "Years" and "Months" inputs into Sliders. This feels more like "calibrating" a machine.

  Context:
  - Interactive Tuning: Turn the "Years" and "Months" inputs into Sliders. This feels more like "calibrating" a machine.

- [ ] - Should we save things automatically like google? if not, can we have buttons like Save All Changes and others only light up when a change is detected?

  Context:
  - Should we save things automatically like google? if not, can we have buttons like Save All Changes and others only light up when a change is detected?

- [ ] - centralise labels in place so changing one changes all and supports consitency (follow paterns and guidelines)

  Context:
  - centralise labels in place so changing one changes all and supports consitency (follow paterns and guidelines)

- [ ] --------------------------------------------------------------------------------------------------------------------

  Context:
  --------------------------------------------------------------------------------------------------------------------

- [ ] ----------------------------------------------------DASHBOARD--------------------------------------------------------

  Context:
  ----------------------------------------------------DASHBOARD--------------------------------------------------------

- [ ] --------------------------------------------------------------------------------------------------------------------

  Context:
  --------------------------------------------------------------------------------------------------------------------

- [ ] - Rename "Conditional Fit": Change this to "Potential Matches" or "Stretch Roles." "Conditional" sounds like a warning; "Potential" sounds like an opportunity.

  Context:
  - Rename "Conditional Fit": Change this to "Potential Matches" or "Stretch Roles." "Conditional" sounds like a warning; "Potential" sounds like an opportunity.

- [ ] --------------------------------------------------------------------------------------------------------------------

  Context:
  --------------------------------------------------------------------------------------------------------------------

- [ ] -------------------------------------------------- Dashboard Filters---------------------------------------

  Context:
  -------------------------------------------------- Dashboard Filters---------------------------------------

- [ ] --------------------------------------------------------------------------------------------------------------------

  Context:
  --------------------------------------------------------------------------------------------------------------------

- [ ] - If users want <50, the important thing is: the score dropdown can only filter cards that were actually loaded into the page. It cannot reveal jobs that were cut by the backend floor in job_hunter_agent/source_connector.py (line 82) and job_hunter_agent/source_connector.py (line 1590).

  Context:
  - If users want <50, the important thing is: the score dropdown can only filter cards that were actually loaded into the page. It cannot reveal jobs that were cut by the backend floor in job_hunter_agent/source_connector.py (line 82) and job_hunter_agent/source_connector.py (line 1590).

- [ ] Best UX, in my view:

  Context:
  Best UX, in my view:

- [ ] Normal mode: keep current-run shortlist at 50+.

  Context:
  Normal mode: keep current-run shortlist at 50+.

- [ ] If you want access to borderline roles, make that explicit with a real Show borderline roles (35-49) toggle or mode.

  Context:
  If you want access to borderline roles, make that explicit with a real Show borderline roles (35-49) toggle or mode.

- [ ] Don’t rely on the score filter alone for that, because it suggests “I can reveal hidden jobs” when it usually can’t.

  Context:
  Don’t rely on the score filter alone for that, because it suggests “I can reveal hidden jobs” when it usually can’t.

- [ ] I can see the value for testing, not sure for a final feature for users

  Context:
  I can see the value for testing, not sure for a final feature for users

- [ ] - Custom day filter: so we can used  like seek which is 3 7 14 30 and they can enter a number custom of days but <=30

  Context:
  - Custom day filter: so we can used  like seek which is 3 7 14 30 and they can enter a number custom of days but <=30

- [ ] --------------------------------------------------------------------------------------------------------------------

  Context:
  --------------------------------------------------------------------------------------------------------------------

- [ ] ----------------------------------------------------ONBOARDING------------------------------------------------------

  Context:
  ----------------------------------------------------ONBOARDING------------------------------------------------------

- [ ] --------------------------------------------------------------------------------------------------------------------

  Context:
  --------------------------------------------------------------------------------------------------------------------

- [ ] - Privacy Bullet Points: Break the "Privacy tip" into 3 small bullet points with a 🛡️ icon. People skip paragraphs; they read bullets.

  Context:
  - Privacy Bullet Points: Break the "Privacy tip" into 3 small bullet points with a 🛡️ icon. People skip paragraphs; they read bullets.

- [ ] Real-time AI Feedback: When the user clicks "Build Draft Profile," show "active" status messages (e.g., "Extracting skills...", "Calculating experience...") to show the AI is working.

  Context:
  Real-time AI Feedback: When the user clicks "Build Draft Profile," show "active" status messages (e.g., "Extracting skills...", "Calculating experience...") to show the AI is working.

- [ ] - Would adding industry help apart from capabilities matrix to help us score and be leaner?i think that applies to most candidate?

  Context:
  - Would adding industry help apart from capabilities matrix to help us score and be leaner?i think that applies to most candidate?

- [ ] - after onboarding we need to tell users to check strengths and udpate if necessary, as well as configure search and salary etc

  Context:
  - after onboarding we need to tell users to check strengths and udpate if necessary, as well as configure search and salary etc

- [ ] explain aI is good not perfect :) My openclaw should learn and update this from my applications and other ideas

  Context:
  explain aI is good not perfect :) My openclaw should learn and update this from my applications and other ideas

- [ ] - we need a way to explain to users during onboarding or reset how important the cv structure is to do the best possible extraction. Dates and chronological order is important etc etc

  Context:
  - we need a way to explain to users during onboarding or reset how important the cv structure is to do the best possible extraction. Dates and chronological order is important etc etc

- [ ] Maybe a one off text that can be revisited later on some user guide ?

  Context:
  Maybe a one off text that can be revisited later on some user guide ?

- [ ] - To improve onboarding and overall experience, analyse how can we suggest an ideal CV structure and content for best experience during onboarding (especially if someone never wrote  cv or is new to the market) as a suggestion since they met annoyed if they fill forced to it

  Context:
  - To improve onboarding and overall experience, analyse how can we suggest an ideal CV structure and content for best experience during onboarding (especially if someone never wrote  cv or is new to the market) as a suggestion since they met annoyed if they fill forced to it

- [ ] Maybe a quick guide and visual

  Context:
  Maybe a quick guide and visual

- [ ] --------------------------------------------------------------------------------------------------------------------

  Context:
  --------------------------------------------------------------------------------------------------------------------

- [ ] ---------------------------------------------------- SETTINGS-----------------------------------------------------------

  Context:
  ---------------------------------------------------- SETTINGS-----------------------------------------------------------

- [ ] - Can we have multiple searches with their own run and configuration...may need to add multiple parallel searches in the app..now it is only one PLAN FIRST

  Context:
  - Can we have multiple searches with their own run and configuration...may need to add multiple parallel searches in the app..now it is only one PLAN FIRST

- [ ] - is Suggested Tuning in settings working?

  Context:
  - is Suggested Tuning in settings working?

- [ ] --------------------------------------------------------------------------------------------------------------------

  Context:
  --------------------------------------------------------------------------------------------------------------------

- [ ] --------------------------------------------------------------------------------------------------------------------

  Context:
  --------------------------------------------------------------------------------------------------------------------

- [ ] ------------------------------------------ Capabilities in settings and onboarding-----------------------------------

  Context:
  ------------------------------------------ Capabilities in settings and onboarding-----------------------------------

- [ ] --------------------------------------------------------------------------------------------------------------------

  Context:
  --------------------------------------------------------------------------------------------------------------------

- [ ] capabilities in settings and onboarding:

  Context:
  capabilities in settings and onboarding:

- [ ] - The "Why" Factor: Add a small "Match Score" tooltip next to capabilities that says, "This skill makes you a top 10% match for Business Analyst roles."

  Context:
  - The "Why" Factor: Add a small "Match Score" tooltip next to capabilities that says, "This skill makes you a top 10% match for Business Analyst roles."

- [ ] - Bulk Actions: If the list gets long, add a "Select All" or "Delete All Low Relevance" button at the top to save the user time.

  Context:
  - Bulk Actions: If the list gets long, add a "Select All" or "Delete All Low Relevance" button at the top to save the user time.

- [ ] --------------------------------------------------------------------------------------------------------------------

  Context:
  --------------------------------------------------------------------------------------------------------------------

- [ ] -------------------------------------------------- CV 	Filtering  -------------------------------------------------

  Context:
  -------------------------------------------------- CV 	Filtering  -------------------------------------------------

- [ ] --------------------------------------------------------------------------------------------------------------------

  Context:
  --------------------------------------------------------------------------------------------------------------------

- [ ] - add intelligence to reject roles when they require certain years (eg 2 years of project management) but we can select it.. For example i have 2 years scrum master/pm... but i dont have 4 years

  Context:
  - add intelligence to reject roles when they require certain years (eg 2 years of project management) but we can select it.. For example i have 2 years scrum master/pm... but i dont have 4 years

- [ ] - option for users to hide jobs from certain companies

  Context:
  - option for users to hide jobs from certain companies

- [ ] - blocking like this is now quite right as years make this very unique : 1-3 years project coordination experience ... not sure how easy to just add the experience but not years in it

  Context:
  - blocking like this is now quite right as years make this very unique : 1-3 years project coordination experience ... not sure how easy to just add the experience but not years in it

- [ ] - do we need to parse and keep companies candiate works? could be useful and we dont save persona l info so there is no link.. we will need personal info?

  Context:
  - do we need to parse and keep companies candiate works? could be useful and we dont save persona l info so there is no link.. we will need personal info?

- [ ] - SALARY

  Context:
  - SALARY

- [ ] - SEEK: based on SEEK’s employer docs, the indexed pay range and the visible “pay shown on your ad” text are not the same thing, and the visible field is free text, so SEEK can expose plain salary, + super, or package-style text. Source: https://talent.seek.com.au/hiring-advice/article/why-its-important-to-include-salary-in-your-job-ad

  Context:
  - SEEK: based on SEEK’s employer docs, the indexed pay range and the visible “pay shown on your ad” text are not the same thing, and the visible field is free text, so SEEK can expose plain salary, + super, or package-style text. Source: https://talent.seek.com.au/hiring-advice/article/why-its-important-to-include-salary-in-your-job-ad

- [ ] LinkedIn: based on LinkedIn help and job posting docs, LinkedIn compensation is structured around interval types like yearly/monthly/hourly/daily, but I did not find reliable public metadata saying whether Australian job pay shown there is base-only vs includes super. Sources: https://www.linkedin.com/help/linkedin/answer/a1395225 and https://content.linkedin.com/content/dam/help/linkedin/en-us/LinkedIn_Jobs_XML_Development_Guide.pdf

  Context:
  LinkedIn: based on LinkedIn help and job posting docs, LinkedIn compensation is structured around interval types like yearly/monthly/hourly/daily, but I did not find reliable public metadata saying whether Australian job pay shown there is base-only vs includes super. Sources: https://www.linkedin.com/help/linkedin/answer/a1395225 and https://content.linkedin.com/content/dam/help/linkedin/en-us/LinkedIn_Jobs_XML_Development_Guide.pdf

- [ ] Because of that uncertainty, I did not add any guessed conversion for super. The current behaviour is conservative: if the ad explicitly says package/includes super, we do not score it against the user’s excluding-super minimum.

  Context:
  Because of that uncertainty, I did not add any guessed conversion for super. The current behaviour is conservative: if the ad explicitly says package/includes super, we do not score it against the user’s excluding-super minimum.

- [ ] If you want, next step should be a separate pass to surface a salary comparability state in the UI (meets, below, listed but includes super/package, missing) instead of folding all non-comparable salary cases into the generic listed state.

  Context:
  If you want, next step should be a separate pass to surface a salary comparability state in the UI (meets, below, listed but includes super/package, missing) instead of folding all non-comparable salary cases into the generic listed state.

- [ ] --------------------------------------------------------------------------------------------------------------------

  Context:
  --------------------------------------------------------------------------------------------------------------------

- [ ] --------------------------------------------------   job rejections t 	---------------------------------------------

  Context:
  --------------------------------------------------   job rejections t 	---------------------------------------------

- [ ] ---------------------------------------------------------------------------------------------------------------------

  Context:
  ---------------------------------------------------------------------------------------------------------------------

- [ ] - Use this sheet called job rejections that it will be populated by a job with a every job i got rejected from so we can use it in my job hunter app so if a job is from a company i have been rejected already I would ove to know when, how many times, for what roles and this lowers the score a little as i been rehected already and the more rejection the worse https://docs.google.com/spreadsheets/d/1kayUdF2fML62pUSLgJSUbzgvI3orz5SvR-3EPK1cAko/edit?gid=0#gid=0

  Context:
  - Use this sheet called job rejections that it will be populated by a job with a every job i got rejected from so we can use it in my job hunter app so if a job is from a company i have been rejected already I would ove to know when, how many times, for what roles and this lowers the score a little as i been rehected already and the more rejection the worse https://docs.google.com/spreadsheets/d/1kayUdF2fML62pUSLgJSUbzgvI3orz5SvR-3EPK1cAko/edit?gid=0#gid=0

- [ ] I understand this sheet is a special link that requires to show in dashboard with some info or/and maybe a badge (i havent thought of the ui ux) that may only work for me as other users will not have that yet, we need t obuild that for other users to add rejections, etc in admin maybe but for now is a to-do

  Context:
  I understand this sheet is a special link that requires to show in dashboard with some info or/and maybe a badge (i havent thought of the ui ux) that may only work for me as other users will not have that yet, we need t obuild that for other users to add rejections, etc in admin maybe but for now is a to-do

- [ ] --------------------------------------------------------------------------------------------------------------------

  Context:
  --------------------------------------------------------------------------------------------------------------------

- [ ] --------------------------------------------------    	---------------------------------------------

  Context:
  --------------------------------------------------    	---------------------------------------------

- [ ] -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  Context:
  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

- [ ] --------------------------------------------------     	---------------------------------------------

  Context:
  --------------------------------------------------     	---------------------------------------------

- [ ] -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  Context:
  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

- [ ] --------------------------------------------------   ---------------------------------------------

  Context:
  --------------------------------------------------   ---------------------------------------------

- [ ] ---------------------------------------------------------------------------------------------------------------------

  Context:
  ---------------------------------------------------------------------------------------------------------------------

- [ ] - I need people to start using it and access it so i can sell myselft better and get testing feedback...what is the best? render again? do we need a database so far? say i have 3 users this is becoming a cloud saas solution or similar right?

  Context:
  - I need people to start using it and access it so i can sell myselft better and get testing feedback...what is the best? render again? do we need a database so far? say i have 3 users this is becoming a cloud saas solution or similar right?

- [ ] - what label Never run means next to settings

  Context:
  - what label Never run means next to settings

- [ ] - -How “Reject jobs requiring” works position should be like any expanding help, looks weird below

  Context:
  - -How “Reject jobs requiring” works position should be like any expanding help, looks weird below

- [ ] -----------------------------------------------------------------------

  Context:
  -----------------------------------------------------------------------

- [ ] --------------------------------High-----------------------------------

  Context:
  --------------------------------High-----------------------------------

- [ ] -----------------------------------------------------------------------

  Context:
  -----------------------------------------------------------------------

- [ ] - answer short: should we save the cv? do we save the CV? or maybe ask?

  Context:
  - answer short: should we save the cv? do we save the CV? or maybe ask?

- [ ] - description blocker:

  Context:
  - description blocker:

- [ ] so you are sayhing which is fine, that we will block when they are mandatory (or appear to be)

  Context:
  so you are sayhing which is fine, that we will block when they are mandatory (or appear to be)

- [ ] I wonder if people may want to filter in all cases when that is mentioned

  Context:
  I wonder if people may want to filter in all cases when that is mentioned

- [ ] - are we adding similar titles when we search? like if someone is scrum master adding project manager? how can i select that as a user? can we select more than one title in the search if so, we should explain it following the current patterns of how mwe explain fields

  Context:
  - are we adding similar titles when we search? like if someone is scrum master adding project manager? how can i select that as a user? can we select more than one title in the search if so, we should explain it following the current patterns of how mwe explain fields

- [ ] - add the option for people to define what they want by typing it and then we interpret and set up things instead of typical selection (of course somehowe we must guide them)

  Context:
  - add the option for people to define what they want by typing it and then we interpret and set up things instead of typical selection (of course somehowe we must guide them)

- [ ] -Statistical / ML learning

  Context:
  -Statistical / ML learning

- [ ] It predicts keep vs reject from past labels.

  Context:
  It predicts keep vs reject from past labels.

- [ ] This is useful later, but only once you have enough clean feedback data.

  Context:
  This is useful later, but only once you have enough clean feedback data.

- [ ] - what RECENT roles mean? is tht clear text?

  Context:
  - what RECENT roles mean? is tht clear text?

- [ ] - filter kept from earlier runs only show in test mode

  Context:
  - filter kept from earlier runs only show in test mode

- [ ] -when i click a job to see the description whtn i come back and the scrolling where the card was is lost and i see the top of the screen again

  Context:
  -when i click a job to see the description whtn i come back and the scrolling where the card was is lost and i see the top of the screen again

- [ ] - what is and how we implement it Background capabilities?

  Context:
  - what is and how we implement it Background capabilities?

- [ ] - be good to have a search bar in settings for easy access to options in it

  Context:
  - be good to have a search bar in settings for easy access to options in it

- [ ] - |  Your bot is using DM policy: pairing.                                        |

  Context:
  - |  Your bot is using DM policy: pairing.                                        |

- [ ] |  Any Telegram user who discovers the bot can send pairing requests.           |

  Context:
  |  Any Telegram user who discovers the bot can send pairing requests.           |

- [ ] |  For private use, configure an allowlist with your Telegram user id:          |

  Context:
  |  For private use, configure an allowlist with your Telegram user id:          |

- [ ] |    openclaw config set channels.telegram.dmPolicy "allowlist"                 |

  Context:
  |    openclaw config set channels.telegram.dmPolicy "allowlist"                 |

- [ ] |    openclaw config set channels.telegram.allowFrom '["YOUR_USER_ID"]'         |

  Context:
  |    openclaw config set channels.telegram.allowFrom '["YOUR_USER_ID"]'         |

- [ ] |  Docs: channels/pairing  |

  Context:
  |  Docs: channels/pairing  |

- [ ] - Identify roles that seem similar, like for example now there is a mutliple roles federal contract that at least 10 different agencies are looking for and we may inadvertently apply to more htan one wasting time

  Context:
  - Identify roles that seem similar, like for example now there is a mutliple roles federal contract that at least 10 different agencies are looking for and we may inadvertently apply to more htan one wasting time

- [ ] Ideally i should not apply to a role that is similar to one that I applied  maybe provide links to applied one to check? or a list of all that look alike?

  Context:
  Ideally i should not apply to a role that is similar to one that I applied  maybe provide links to applied one to check? or a list of all that look alike?

- [ ] what you propose?

  Context:
  what you propose?

- [ ] also at the moment IQVIA Senior Business Analyst Private sector role for a Senior Business Analyst. is the same role in 2 different platforms

  Context:
  also at the moment IQVIA Senior Business Analyst Private sector role for a Senior Business Analyst. is the same role in 2 different platforms

- [ ] - locations can be change in the settings, but the field for is at the moment under seek and it shouldnt as it appliese to linkedin too

  Context:
  - locations can be change in the settings, but the field for is at the moment under seek and it shouldnt as it appliese to linkedin too

- [ ] also , it is not using the original onboarding proper fields which is not just a text box and it is more user friendly

  Context:
  also , it is not using the original onboarding proper fields which is not just a text box and it is more user friendly

- [ ] - We need to be smart when using use salary from users and know if a job posted salary includes super, NOT sure how seek.com and linked expose that, investigate first

  Context:
  - We need to be smart when using use salary from users and know if a job posted salary includes super, NOT sure how seek.com and linked expose that, investigate first

- [ ] - we need to be smart and know when to use Minimum annual salary or Minimum daily rate adapting to job posting and if no salary is offer be sure to show the job (if it must be show) and not filter away due to salary issues

  Context:
  - we need to be smart and know when to use Minimum annual salary or Minimum daily rate adapting to job posting and if no salary is offer be sure to show the job (if it must be show) and not filter away due to salary issues

- [ ] -  Add filter to see contract duration so i can see 12 months contract or larger for example to remove those contracts <12 mths ...carefull if contract length not clear...show anyway

  Context:
  -  Add filter to see contract duration so i can see 12 months contract or larger for example to remove those contracts <12 mths ...carefull if contract length not clear...show anyway

- [ ] - save search settings button is in the wrong place in the settings/search/run search screen. the whole section is not very UX friendly

  Context:
  - save search settings button is in the wrong place in the settings/search/run search screen. the whole section is not very UX friendly

- [ ] - check this is done: locations and search keywords are part of onboarding and you must synchornise them with settings  if they change on onboarding or reset

  Context:
  - check this is done: locations and search keywords are part of onboarding and you must synchornise them with settings  if they change on onboarding or reset

- [ ] - restructure

  Context:
  - restructure

- [ ] -- Incremental learning

  Context:
  -- Incremental learning

- [ ] -- Learning Inbox

  Context:
  -- Learning Inbox

- [ ] - Decision Weights is very important to tailor user exp but it is sort of hidden in settings... we could add advance or further onboarding where they fill optionally this in and maybe we can add other options later and/or they can know at least it can be tailor later in settings but i am not that convince settings being a big one page is the best. what is the best practice?

  Context:
  - Decision Weights is very important to tailor user exp but it is sort of hidden in settings... we could add advance or further onboarding where they fill optionally this in and maybe we can add other options later and/or they can know at least it can be tailor later in settings but i am not that convince settings being a big one page is the best. what is the best practice?

- [ ] - how to handle certifications. is it in scoring arelady as part of llm description search? wil lit make it better if separated for MVP? or for efficiency ?

  Context:
  - how to handle certifications. is it in scoring arelady as part of llm description search? wil lit make it better if separated for MVP? or for efficiency ?

- [ ] for example CBAP is common for BA sometimes required or bachelors degree, and definitely more for doctors, architects, etc

  Context:
  for example CBAP is common for BA sometimes required or bachelors degree, and definitely more for doctors, architects, etc

- [ ] - What words like ERP or Salesforce, there are lots of those roles like the for BAs in IT that I dont qualify bc they are mandatory requirements.

  Context:
  - What words like ERP or Salesforce, there are lots of those roles like the for BAs in IT that I dont qualify bc they are mandatory requirements.

- [ ] - I think search is something close to the dashboard, since we are hiding it in admin, shouldnt there be a reason? we have a run now search without params in the dashboard

  Context:
  - I think search is something close to the dashboard, since we are hiding it in admin, shouldnt there be a reason? we have a run now search without params in the dashboard

- [ ] - add https://iworkfor.nsw.gov.au/jobs to the search, you must analyse the site? need help?

  Context:
  - add https://iworkfor.nsw.gov.au/jobs to the search, you must analyse the site? need help?

- [ ] - add  https://www.apsjobs.gov.au/ to the search, you must analyse the site? need help?

  Context:
  - add  https://www.apsjobs.gov.au/ to the search, you must analyse the site? need help?

- [ ] - find a smart way to find and flag greaveyard jobs, dodgy ads clearly hunting for CVs or even money or those being there for >1 months and always get reposted...

  Context:
  - find a smart way to find and flag greaveyard jobs, dodgy ads clearly hunting for CVs or even money or those being there for >1 months and always get reposted...

- [ ] In linkedin specially is KEY to detect reposting, which is not easy.

  Context:
  In linkedin specially is KEY to detect reposting, which is not easy.

- [ ] - in linkedin you cannot trust job age of thos that are NOT easy apply. The only way is checking the description, and if the description doesnt tell the real post date then the job can't be trusted. This is key to make my  application powerful

  Context:
  - in linkedin you cannot trust job age of thos that are NOT easy apply. The only way is checking the description, and if the description doesnt tell the real post date then the job can't be trusted. This is key to make my  application powerful

- [ ] - start caputing the great things we are building in a boostmyapp text or similar name so i can then use it to sell it (just local file)

  Context:
  - start caputing the great things we are building in a boostmyapp text or similar name so i can then use it to sell it (just local file)

- [ ] - Add Minimum annual salary and minimnum daily rate to onboarding search and be sure it is linked with the values that are then managed in admin

  Context:
  - Add Minimum annual salary and minimnum daily rate to onboarding search and be sure it is linked with the values that are then managed in admin

- [ ] - when search have the filter permanent or contract but if for some reason we can't tell the type of a job when parsing from source, then bring those "unclear" roles anyway ...if not they will stay hidden forever

  Context:
  - when search have the filter permanent or contract but if for some reason we can't tell the type of a job when parsing from source, then bring those "unclear" roles anyway ...if not they will stay hidden forever

- [ ] - dont allow users to enter small 1 word in their own term, be bure we prevent DOS in general. We need a proper search and analysis

  Context:
  - dont allow users to enter small 1 word in their own term, be bure we prevent DOS in general. We need a proper search and analysis

- [ ] - Do we need junior senior mid filter and or search?  do people care to say dont bring me junior roles?

  Context:
  - Do we need junior senior mid filter and or search?  do people care to say dont bring me junior roles?

- [ ] - learn patterns from hide

  Context:
  - learn patterns from hide

- [ ] - we need something to only show COMPANIES directly hiring as oposed to recruiters, as it is much better and much quicker on direct company contact

  Context:
  - we need something to only show COMPANIES directly hiring as oposed to recruiters, as it is much better and much quicker on direct company contact

- [ ] I particulaly prefere to see this roles first

  Context:
  I particulaly prefere to see this roles first

- [ ] - Rate companies...like they never answered etc...make it public? this is gold since nobody rates the shit recruiters  and hiring managers are!! share in a website, people can be annonymous.,.,this is just rating recruitment process and recruiters can answer. Does thid exist?

  Context:
  - Rate companies...like they never answered etc...make it public? this is gold since nobody rates the shit recruiters  and hiring managers are!! share in a website, people can be annonymous.,.,this is just rating recruitment process and recruiters can answer. Does thid exist?

- [ ] -In templates/workspace.html, remove the unconditional background polling line:

  Context:
  -In templates/workspace.html, remove the unconditional background polling line:

- [ ] setInterval(checkRunStatus, 30000);

  Context:
  setInterval(checkRunStatus, 30000);

- [ ] Then simplify startRunPolling() so it only polls while the scraper run is active.

  Context:
  Then simplify startRunPolling() so it only polls while the scraper run is active.

- [ ] Rules:

  Context:
  Rules:

- [ ] - On page load, call checkRunStatus() once.

  Context:
  - On page load, call checkRunStatus() once.

- [ ] - If status is running, disable the Run Search button and call startRunPolling().

  Context:
  - If status is running, disable the Run Search button and call startRunPolling().

- [ ] - When polling sees status === "running", keep polling.

  Context:
  - When polling sees status === "running", keep polling.

- [ ] - When polling sees any non-running status, clear the interval, reset the Run Search button, and reload the page.

  Context:
  - When polling sees any non-running status, clear the interval, reset the Run Search button, and reload the page.

- [ ] - Do not poll while idle.

  Context:
  - Do not poll while idle.

- [ ] - Do not change backend endpoints.

  Context:
  - Do not change backend endpoints.

- [ ] - Do not change /api/run-status.

  Context:
  - Do not change /api/run-status.

- [ ] - Do not change /api/run.

  Context:
  - Do not change /api/run.

- [ ] -------------------------------------------------------------------------------------------------------------------------------------------

  Context:
  -------------------------------------------------------------------------------------------------------------------------------------------

- [ ] ----------------------------------------------------------------------Low--------------------------------------------------------------------------------

  Context:
  ----------------------------------------------------------------------Low--------------------------------------------------------------------------------

- [ ] -------------------------------------------------------------------------------------------------------------------------------------------

  Context:
  -------------------------------------------------------------------------------------------------------------------------------------------

- [ ] - rename recuiter badge

  Context:
  - rename recuiter badge

- [ ] - can we add job boards dynamically?

  Context:
  - can we add job boards dynamically?

- [ ] - find a way to explain that Block similar titles make it all more efficient and avoid conusming tokens

  Context:
  - find a way to explain that Block similar titles make it all more efficient and avoid conusming tokens

- [ ] - improve _GOVERNMENT_CONTEXT_PATTERNS

  Context:
  - improve _GOVERNMENT_CONTEXT_PATTERNS

- [ ] - improve _GOVERNMENT_CONTEXT_FALSE_POSITIVE_PATTERNS

  Context:
  - improve _GOVERNMENT_CONTEXT_FALSE_POSITIVE_PATTERNS

- [ ] - Last Run & Review /Latest Run Stats

  Context:
  - Last Run & Review /Latest Run Stats

- [ ] is always saying:  No run stats yet. Run the current job-source connector once and reload this page.

  Context:
  is always saying:  No run stats yet. Run the current job-source connector once and reload this page.

- [ ] - is this information below highlighting properly what we want to see ?

  Context:
  - is this information below highlighting properly what we want to see ?

- [ ] Posted 20 Apr 2026 (listed as 1d ago when retrieved)

  Context:
  Posted 20 Apr 2026 (listed as 1d ago when retrieved)

- [ ] Location Sydney NSW

  Context:
  Location Sydney NSW

- [ ] Work mode Hybrid

  Context:
  Work mode Hybrid

- [ ] Type Full time

  Context:
  Type Full time

- [ ] Salary 180k per annum

  Context:
  Salary 180k per annum

- [ ] for one thing it don twant to make a colour pallete panel but for the other side it seems it all blends with teh bakround... should we show differently only when the salary

  Context:
  for one thing it don twant to make a colour pallete panel but for the other side it seems it all blends with teh bakround... should we show differently only when the salary

- [ ] - job short title/desc needs a little bit more space from text below starting with Posted

  Context:
  - job short title/desc needs a little bit more space from text below starting with Posted

- [ ] - Explain security (cv infor etc.)

  Context:
  - Explain security (cv infor etc.)

- [ ] - add proper location and radius from neighborhood level , like I want jobs 50km from Kellyville NSW

  Context:
  - add proper location and radius from neighborhood level , like I want jobs 50km from Kellyville NSW

- [ ] - in settings panel Search as overall panel UI and UX it is different from that in Advanced one has separate panels the other all inside a bigger pannel. try to standarise all panels in the same screen following best practices

  Context:
  - in settings panel Search as overall panel UI and UX it is different from that in Advanced one has separate panels the other all inside a bigger pannel. try to standarise all panels in the same screen following best practices

- [ ] - can  we show the role description also as a right side panel when users click them in the dashboard? specially since the right side panel with Run Snapshot

  Context:
  - can  we show the role description also as a right side panel when users click them in the dashboard? specially since the right side panel with Run Snapshot

- [ ] no sure if they users can also apply from there but that probably should take them to a new tab

  Context:
  no sure if they users can also apply from there but that probably should take them to a new tab

- [ ] - below Potential Jobs  what 0 cards scanned means?

  Context:
  - below Potential Jobs  what 0 cards scanned means?

- [ ] - Save Search Settings button in settings panel is in a bad place UI and UX wise

  Context:
  - Save Search Settings button in settings panel is in a bad place UI and UX wise

- [ ] - for Daily Search Schedule in settings show if it is already scheduled

  Context:
  - for Daily Search Schedule in settings show if it is already scheduled

- [ ] - improve seek Classification IDs

  Context:
  - improve seek Classification IDs

- [ ] B — Sector & seniority context in the brief (no new storage needed). Change build_llm_profile_brief to also include:

  Context:
  B — Sector & seniority context in the brief (no new storage needed). Change build_llm_profile_brief to also include:

- [ ] "Background: Senior BA 20+ years, predominantly Federal/State Government contracts"

  Context:
  "Background: Senior BA 20+ years, predominantly Federal/State Government contracts"

- [ ] This is the single highest-impact change — the LLM reads this for every job

  Context:
  This is the single highest-impact change — the LLM reads this for every job

- [ ] - limit improve input to docx or md or pdf etc this mnay affect onboarding

  Context:
  - limit improve input to docx or md or pdf etc this mnay affect onboarding

- [ ] - delete application_inputs and references to it which are not to be used

  Context:
  - delete application_inputs and references to it which are not to be used

- [ ] - set gpt-4.1 in knowMe put things in place to avoid abuse and burning my tokens (at the moment nobody has use it)

  Context:
  - set gpt-4.1 in knowMe put things in place to avoid abuse and burning my tokens (at the moment nobody has use it)

- [ ] -build_profile_prompt_context() and build_system_prompt() are called independently in different places but build_system_prompt always calls build_profile_prompt_context inline — meaning if you ever call both separately you load the profile twice. Minor but worth knowing.

  Context:
  -build_profile_prompt_context() and build_system_prompt() are called independently in different places but build_system_prompt always calls build_profile_prompt_context inline — meaning if you ever call both separately you load the profile twice. Minor but worth knowing.

- [ ] - in dashboard, allow users save filters for them to reuse easily so they dont have to select them every time. Also add reset to default option

  Context:
  - in dashboard, allow users save filters for them to reuse easily so they dont have to select them every time. Also add reset to default option

- [ ] - I have a problem, i need to have techincal cv, not techincal cv and for each one for Governemnt one for private... the current app is not contemplateing that now

  Context:
  - I have a problem, i need to have techincal cv, not techincal cv and for each one for Governemnt one for private... the current app is not contemplateing that now

- [ ] - Other roles search: i can be a good implementation consultant like a configurator of SAAS like monday.com and guidewire, etc when they dont require experience which i have seen happning... how can we add this? should this be a keyword? a special feature ?

  Context:
  - Other roles search: i can be a good implementation consultant like a configurator of SAAS like monday.com and guidewire, etc when they dont require experience which i have seen happning... how can we add this? should this be a keyword? a special feature ?

- [ ] - So let me know if you get this?  For the default for new users, if it is not in the CV, they dont have it, plus the first time they load it you can create a proper list of common things looked that they dont have (but if this is too advcance forget it now)

  Context:
  - So let me know if you get this?  For the default for new users, if it is not in the CV, they dont have it, plus the first time they load it you can create a proper list of common things looked that they dont have (but if this is too advcance forget it now)

- [ ] -------------------------------------------------------------------------------------------------------------------------------------------

  Context:
  -------------------------------------------------------------------------------------------------------------------------------------------

- [ ] -------------------------------------------------------------------- Unfilter --------------------------------------------------------------------

  Context:
  -------------------------------------------------------------------- Unfilter --------------------------------------------------------------------

- [ ] -------------------------------------------------------------------------------------------------------------------------------------------

  Context:
  -------------------------------------------------------------------------------------------------------------------------------------------

- [ ] -STAR / evidence notes

  Context:
  -STAR / evidence notes

- [ ] Optional examples, impact stories, or selection-criteria style evidence.

  Context:
  Optional examples, impact stories, or selection-criteria style evidence.

- [ ] i think this is weak, but i also recognise we need to learn from our candidates. openclaw or manual the more the merrier. what can be added in place of star notes, which is something that I have but not many will have >?  is like a free text box with a proper explanation to populated a good idea?

  Context:
  i think this is weak, but i also recognise we need to learn from our candidates. openclaw or manual the more the merrier. what can be added in place of star notes, which is something that I have but not many will have >?  is like a free text box with a proper explanation to populated a good idea?

- [ ] -One honest note: the new hard-block behavior is configurable in profile.json right now, but I have not yet exposed those hard-block cluster controls in the admin UI. If you want, next I can make those editable from admin instead of JSON.

  Context:
  -One honest note: the new hard-block behavior is configurable in profile.json right now, but I have not yet exposed those hard-block cluster controls in the admin UI. If you want, next I can make those editable from admin instead of JSON.

- [ ] - Our Agentic AI should learn from this and improve my llm, that is the hole point and my biggest selling point if i am positioning myself as AI BA so dont forget this

  Context:
  - Our Agentic AI should learn from this and improve my llm, that is the hole point and my biggest selling point if i am positioning myself as AI BA so dont forget this

- [ ] -2. Learn from your actions automatically

  Context:
  -2. Learn from your actions automatically

- [ ] This is the biggest opportunity.

  Context:
  This is the biggest opportunity.

- [ ] If you:

  Context:
  If you:

- [ ] hide a job

  Context:
  hide a job

- [ ] apply to a job

  Context:
  apply to a job

- [ ] keep revisiting a job

  Context:
  keep revisiting a job

- [ ] reject a recurring skill cluster

  Context:
  reject a recurring skill cluster

- [ ] the app should start producing suggested profile updates from that behavior.

  Context:
  the app should start producing suggested profile updates from that behavior.

- [ ] Examples:

  Context:
  Examples:

- [ ] “You keep applying to delivery transformation roles, boost those title patterns”

  Context:
  “You keep applying to delivery transformation roles, boost those title patterns”

- [ ] “You keep hiding platform-admin roles, strengthen those reject rules”

  Context:
  “You keep hiding platform-admin roles, strengthen those reject rules”

- [ ] “This skill shows up in jobs you keep, classify it as supporting instead of unknown”

  Context:
  “This skill shows up in jobs you keep, classify it as supporting instead of unknown”

- [ ] 3. Unknown skills review should become profile evolution

  Context:
  3. Unknown skills review should become profile evolution

- [ ] You already have an unknown skills review path. Great.

  Context:
  You already have an unknown skills review path. Great.

- [ ] Next step:

  Context:
  Next step:

- [ ] track frequency

  Context:
  track frequency

- [ ] track whether unknown skills appear more in kept/applied jobs or rejected jobs

  Context:
  track whether unknown skills appear more in kept/applied jobs or rejected jobs

- [ ] suggest a default classification

  Context:
  suggest a default classification

- [ ] one-click apply into capability_profile_rules

  Context:
  one-click apply into capability_profile_rules

- [ ] That is exactly the kind of “learn and improve it” loop you’re describing.

  Context:
  That is exactly the kind of “learn and improve it” loop you’re describing.

- [ ] 4. Add “why this rule should change” evidence in admin

  Context:
  4. Add “why this rule should change” evidence in admin

- [ ] Not just “add keyword X”.

  Context:
  Not just “add keyword X”.

- [ ] Instead:

  Context:
  Instead:

- [ ] show sample jobs

  Context:
  show sample jobs

- [ ] show counts

  Context:
  show counts

- [ ] show impact estimate

  Context:
  show impact estimate

- [ ] show whether change affects false rejects or false positives

  Context:
  show whether change affects false rejects or false positives

- [ ] That makes tuning much safer.

  Context:
  That makes tuning much safer.

- [ ] - 1. Admin should suggest keyword/rule changes, not just let you type them

  Context:
  - 1. Admin should suggest keyword/rule changes, not just let you type them

- [ ] Right now admin can store keywords and rules.

  Context:
  Right now admin can store keywords and rules.

- [ ] The next level is:

  Context:
  The next level is:

- [ ] “These terms appeared often in strong matches”

  Context:
  “These terms appeared often in strong matches”

- [ ] “These terms appeared often in junk roles”

  Context:
  “These terms appeared often in junk roles”

- [ ] “Add this keyword?”

  Context:
  “Add this keyword?”

- [ ] “Add this to reject rules?”

  Context:
  “Add this to reject rules?”

- [ ] “Move this from contextual to supporting?”

  Context:
  “Move this from contextual to supporting?”

- [ ] That would make admin feel like a real tuning cockpit.

  Context:
  That would make admin feel like a real tuning cockpit.

- [ ] - '130 Cards Seen' what is this? i haven't click 130 card i know this.

  Context:
  - '130 Cards Seen' what is this? i haven't click 130 card i know this.

- [ ] - "instructions_file":  still is needed? i want an efficient cohesive structure to filter jobs

  Context:
  - "instructions_file":  still is needed? i want an efficient cohesive structure to filter jobs

- [ ] - put in web/render

  Context:
  - put in web/render

- [ ] - make an agent that learns from jobs I applied

  Context:
  - make an agent that learns from jobs I applied

- [ ] - make an agent that learns from jobs I get an interview or a call

  Context:
  - make an agent that learns from jobs I get an interview or a call

- [ ] - make an agent that checks daily maybe 2 times a day 12pm and 6pm and updates the seek html page for me

  Context:
  - make an agent that checks daily maybe 2 times a day 12pm and 6pm and updates the seek html page for me

- [ ] - agent use efficiency stats to learn how to be more efficient next time

  Context:
  - agent use efficiency stats to learn how to be more efficient next time

- [ ] - Create test cases that cover all you can think of, have them proiperly stuctured and a test console (we can add a new tab or reuse existing one) so we see all is green when we change something or red flag as typical board..also would be great tokens left if you can access my https://platform.openai.com/settings/organization/usage or limit

  Context:
  - Create test cases that cover all you can think of, have them proiperly stuctured and a test console (we can add a new tab or reuse existing one) so we see all is green when we change something or red flag as typical board..also would be great tokens left if you can access my https://platform.openai.com/settings/organization/usage or limit

- [ ] - use my login and access seek, if that is possible or even relevant

  Context:
  - use my login and access seek, if that is possible or even relevant

- [ ] - make generic and check there is seek specifics in the code, ui or file names.

  Context:
  - make generic and check there is seek specifics in the code, ui or file names.

- [ ] - i do love the idea of having an augmented search like i also can qualify for scrummaster junior and product owner junior  or  other implementation roles (i usually got calls) like work perfect that implements monday.com and I got to the last interview and it doesnt initially read Senior BA

  Context:
  - i do love the idea of having an augmented search like i also can qualify for scrummaster junior and product owner junior  or  other implementation roles (i usually got calls) like work perfect that implements monday.com and I got to the last interview and it doesnt initially read Senior BA

- [ ] - Classification ID are useful in seek.com, but do they apply in linkedin? They are good to avoid shit jobs but its value may be marginal

  Context:
  - Classification ID are useful in seek.com, but do they apply in linkedin? They are good to avoid shit jobs but its value may be marginal

- [ ] -- Classification ID must show me names and the IDs which i dont know should be hidden and used by you not me

  Context:
  -- Classification ID must show me names and the IDs which i dont know should be hidden and used by you not me

- [ ] -- Give me the exact clasification id dropdown from seek (it doesnt change often so for now you dont need to check it to update it)

  Context:
  -- Give me the exact clasification id dropdown from seek (it doesnt change often so for now you dont need to check it to update it)

- [ ] - Give me the exact location selection box you get from seek (it doesnt change often so for now you dont need to check it to update it) and add it to the admin  html (now we have 1 text area)

  Context:
  - Give me the exact location selection box you get from seek (it doesnt change often so for now you dont need to check it to update it) and add it to the admin  html (now we have 1 text area)

- [ ] - we should feed my rejections to get the agent to learn..i get emails usually generic but we can match the role and cv sent

  Context:
  - we should feed my rejections to get the agent to learn..i get emails usually generic but we can match the role and cv sent

- [ ] - we need a way to check when i ask you to, to check seek and be sure all the keywords and things you took from their site to scrap are still up to date so our app is still working fine. I know you took ids, field names , urls and more from seek.

  Context:
  - we need a way to check when i ask you to, to check seek and be sure all the keywords and things you took from their site to scrap are still up to date so our app is still working fine. I know you took ids, field names , urls and more from seek.

- [ ] - maybe also main location /canberra for starters and then more specific like sydney cbd etc

  Context:
  - maybe also main location /canberra for starters and then more specific like sydney cbd etc

- [ ] - Regarding if the  is new but nto sure you can check that easily in linkedin.com and indeed.com they lie a lot about it and are very very dodgy, so once you open the ad (it if is an external linked) you suddenly see it is an old ass job really

  Context:
  - Regarding if the  is new but nto sure you can check that easily in linkedin.com and indeed.com they lie a lot about it and are very very dodgy, so once you open the ad (it if is an external linked) you suddenly see it is an old ass job really

- [ ] -The next best step is to make onboarding feel even more product-ready by adding a post-upload preview page: “here is the summary we generated, here are the strengths we extracted, here is what you can edit next.” before the user lands in admin.

  Context:
  -The next best step is to make onboarding feel even more product-ready by adding a post-upload preview page: “here is the summary we generated, here are the strengths we extracted, here is what you can edit next.” before the user lands in admin.

- [ ] - do we need a DB?

  Context:
  - do we need a DB?

- [ ] - gave you 2 formats which for now are sort of hardcoded (will take notes for later)

  Context:
  - gave you 2 formats which for now are sort of hardcoded (will take notes for later)

- [ ] - be sure all files have a proper header explaining whtat they do and if good practice a file explaining all files one by one and how they connect ...is there  visual for this for my benefit and also to show off later? you only did some files

  Context:
  - be sure all files have a proper header explaining whtat they do and if good practice a file explaining all files one by one and how they connect ...is there  visual for this for my benefit and also to show off later? you only did some files

- [ ] - The page auto-refreshes every 60 seconds so it picks up later runs without a manual browser reload. Can it be only when the job run runs?

  Context:
  - The page auto-refreshes every 60 seconds so it picks up later runs without a manual browser reload. Can it be only when the job run runs?

- [ ] - we must not show roles that are canberra only, did we consider that? where? is it configurable at the moment?

  Context:
  - we must not show roles that are canberra only, did we consider that? where? is it configurable at the moment?

- [ ] create tailored CV for each job (maybe a button)

  Context:
  create tailored CV for each job (maybe a button)

- [ ] -build the first application-pack generator means: after a good job is selected, the app can create the next-step application materials instead of stopping at “this looks like a fit.”

  Context:
  -build the first application-pack generator means: after a good job is selected, the app can create the next-step application materials instead of stopping at “this looks like a fit.”

- [ ] That would usually mean generating a local pack such as:

  Context:
  That would usually mean generating a local pack such as:

- [ ] tailored CV draft

  Context:
  tailored CV draft

- [ ] tailored cover letter draft

  Context:
  tailored cover letter draft

- [ ] key selection-criteria / pitch notes

  Context:
  key selection-criteria / pitch notes

- [ ] “why you fit / where the gaps are” notes

  Context:
  “why you fit / where the gaps are” notes

- [ ] maybe a job-specific evidence summary from your CV and STAR material

  Context:
  maybe a job-specific evidence summary from your CV and STAR material

- [ ] So instead of only:

  Context:
  So instead of only:

- [ ] find jobs

  Context:
  find jobs

- [ ] score jobs

  Context:
  score jobs

- [ ] show dashboard

  Context:
  show dashboard

- [ ] it becomes:

  Context:
  it becomes:

- [ ] find jobs

  Context:
  find jobs

- [ ] score jobs

  Context:
  score jobs

- [ ] pick one

  Context:
  pick one

- [ ] prepare application-ready material

  Context:
  prepare application-ready material

- [ ] That is a big selling point because it closes the loop.

  Context:
  That is a big selling point because it closes the loop.

- [ ] - what is the diff btw 'Saved Earlier' and 'Older Saved'

  Context:
  - what is the diff btw 'Saved Earlier' and 'Older Saved'

- [ ] ---------------------------------------------------------------------------------------------------------------------------------------------------

  Context:
  ---------------------------------------------------------------------------------------------------------------------------------------------------

- [ ] -------------------------------------------------------------------- OTHER TOOLS --------------------------------------------------------------------

  Context:
  -------------------------------------------------------------------- OTHER TOOLS --------------------------------------------------------------------

- [ ] ---------------------------------------------------------------------------------------------------------------------------------------------------

  Context:
  ---------------------------------------------------------------------------------------------------------------------------------------------------

- [ ] https://github.com/talaniz/fitcheck

  Context:
  https://github.com/talaniz/fitcheck

- [ ] https://cvjet.co/ats-checker

  Context:
  https://cvjet.co/ats-checker

- [ ] 1. IDEAS TO BORROW (future list)

  Context:
  1. IDEAS TO BORROW (future list)

- [ ] From fitcheck:

  Context:
  From fitcheck:

- [ ] Ghost job risk score (posting age + JD vagueness + repost signal + process signals)

  Context:
  Ghost job risk score (posting age + JD vagueness + repost signal + process signals)

- [ ] Two separate LLM calls: one for JD quality, one for fit — cleaner than one mega-prompt

  Context:
  Two separate LLM calls: one for JD quality, one for fit — cleaner than one mega-prompt

- [ ] Risk labels (Low / Moderate / High / Ghost job likely) for dashboard display

  Context:
  Risk labels (Low / Moderate / High / Ghost job likely) for dashboard display

- [ ] Post-interview risk flags (market research feel, role disappeared/reappeared)

  Context:
  Post-interview risk flags (market research feel, role disappeared/reappeared)

- [ ] From CVJet:

  Context:
  From CVJet:

- [ ] ATS keyword gap analysis — compare JD keywords against your CV automatically

  Context:
  ATS keyword gap analysis — compare JD keywords against your CV automatically

- [ ] 6-category CV scoring: summary, experience impact, keywords, skills, formatting, length

  Context:
  6-category CV scoring: summary, experience impact, keywords, skills, formatting, length

- [ ] "Missing keywords" list surfaced per job card

  Context:
  "Missing keywords" list surfaced per job card

- [ ] Bullet impact scoring ("responsible for" = weak signal)

  Context:
  Bullet impact scoring ("responsible for" = weak signal)

- [ ] ---------------------------------------------------------------------------------------------------------------------------------------------------------------

  Context:
  ---------------------------------------------------------------------------------------------------------------------------------------------------------------

- [ ] ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- 	DONE ------------------------------------------------------------------------------------------------------------ ---------------------------------------------------------------------------------------------------------------------------------------------------------------

  Context:
  ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- 	DONE ------------------------------------------------------------------------------------------------------------ ---------------------------------------------------------------------------------------------------------------------------------------------------------------

- [ ] ---------------------------------------------------------------------------------------------------------------------------------------------------------------

  Context:
  ---------------------------------------------------------------------------------------------------------------------------------------------------------------

- [ ] - seek html page dynamic, not autogenerated each time. This way we dont have to recreate and check all pages every time, also jobs taht are good i can check them later eeven if they become 4 day older or more...what do you think? maybe what we are doing is that you are becoming my personalised seek.com so when i see our html i see exactly  what i need or close to perfect...do we ned soemthing to rebuild the html or hide jobs older than 15 days maybe?

  Context:
  - seek html page dynamic, not autogenerated each time. This way we dont have to recreate and check all pages every time, also jobs taht are good i can check them later eeven if they become 4 day older or more...what do you think? maybe what we are doing is that you are becoming my personalised seek.com so when i see our html i see exactly  what i need or close to perfect...do we ned soemthing to rebuild the html or hide jobs older than 15 days maybe?

- [ ] - add match starts or numbers so i see what are really great matches and what are not so great and hten we can filter by that in the html page, and we need pagination and we need it to always be sorted by newest first by default

  Context:
  - add match starts or numbers so i see what are really great matches and what are not so great and hten we can filter by that in the html page, and we need pagination and we need it to always be sorted by newest first by default

- [ ] - we shoould have a great CV ready for me to apply when i am ready...now i am using a chat project inside chatgpt...can we reuse that or we need to code the logic into python as well?

  Context:
  - we shoould have a great CV ready for me to apply when i am ready...now i am using a chat project inside chatgpt...can we reuse that or we need to code the logic into python as well?

- [ ] - question, what is my audience, which professions mostly use SEEK.COM and Linkedin? lets concentrate on those first

  Context:
  - question, what is my audience, which professions mostly use SEEK.COM and Linkedin? lets concentrate on those first

- [ ] - capability matrix:

  Context:
  - capability matrix:

- [ ] capability matrix is huge if we how one card for each

  Context:
  capability matrix is huge if we how one card for each

- [ ] the idea of serach keywords is great but why tht title? arent those aliases? and the explanation is not clear

  Context:
  the idea of serach keywords is great but why tht title? arent those aliases? and the explanation is not clear

- [ ] do we need low and basic both?

  Context:
  do we need low and basic both?

- [ ] Do we need role fit? how is that helpful ?

  Context:
  Do we need role fit? how is that helpful ?

- [ ] - are you using Blocked description phrases Blocked description patterns? if not automatically then should be learned somehow and used by the system and/or at leasst via user interaction (using from adming is lioke the last resort)...

  Context:
  - are you using Blocked description phrases Blocked description patterns? if not automatically then should be learned somehow and used by the system and/or at leasst via user interaction (using from adming is lioke the last resort)...

- [ ] -

  Context:
  -

- [ ] - apply best practice patterns to large files

  Context:
  - apply best practice patterns to large files

- [ ] - Set Up Your Profile is the right name for onboarding? and can we make that page ui and ux better? and shouldnt we merge at least visually somehow What this does and  What happens next

  Context:
  - Set Up Your Profile is the right name for onboarding? and can we make that page ui and ux better? and shouldnt we merge at least visually somehow What this does and  What happens next

- [ ] - Back to results makes not much sense unless the page was visited FROM the dashboard and ui wise doesnt seem proper and isnt back to dashboard doing the same?

  Context:
  - Back to results makes not much sense unless the page was visited FROM the dashboard and ui wise doesnt seem proper and isnt back to dashboard doing the same?

- [ ] - settings : Profile loaded message would be good if floating initially so I see them nomatter where i am on the screen

  Context:
  - settings : Profile loaded message would be good if floating initially so I see them nomatter where i am on the screen

- [ ] - telegram:  if users click https://t.me/JobVotBot?start=connect, then we all be conected to the same job bot? every user should have their own telegram channels, also the messager is nto clear one why to click this

  Context:
  - telegram:  if users click https://t.me/JobVotBot?start=connect, then we all be conected to the same job bot? every user should have their own telegram channels, also the messager is nto clear one why to click this

- [ ] - settings: if this

  Context:
  - settings: if this

- [ ] "How mandatory blockers work

  Context:
  "How mandatory blockers work

- [ ] Add skills or tools you do not have. The engine only rejects when those terms look mandatory in context." is the explanation of Reject jobs requiring"

  Context:
  Add skills or tools you do not have. The engine only rejects when those terms look mandatory in context." is the explanation of Reject jobs requiring"

- [ ] then the wordings are not in synch

  Context:
  then the wordings are not in synch

- [ ] - settings: Daily Schedule and Run Search are disconnected visually but i think they are attached

  Context:
  - settings: Daily Schedule and Run Search are disconnected visually but i think they are attached

- [ ] settings: Common Search Settings should be at the same level of seek and linkedin, and be the first one... or better search all together somehow and not really linked with run search and daily schedule visually as it is now

  Context:
  settings: Common Search Settings should be at the same level of seek and linkedin, and be the first one... or better search all together somehow and not really linked with run search and daily schedule visually as it is now

- [ ] - onboarding: isn't Search keywords in search  stale and useless? if yes /no how to manage this? didnt we have roles extracted via llm from cv?

  Context:
  - onboarding: isn't Search keywords in search  stale and useless? if yes /no how to manage this? didnt we have roles extracted via llm from cv?

- [ ] and in dashboard, Common Search Settings, again keyword there?

  Context:
  and in dashboard, Common Search Settings, again keyword there?

- [ ] dashboard:  Idle means what and what are the other statuses and should say what the hell is Idle?

  Context:
  dashboard:  Idle means what and what are the other statuses and should say what the hell is Idle?

- [ ] - Set Up Your Profile is the right name for onboarding? and can we make that page ui and ux better? and shouldnt we merge at least visually somehow What this does and  What happens next

  Context:
  - Set Up Your Profile is the right name for onboarding? and can we make that page ui and ux better? and shouldnt we merge at least visually somehow What this does and  What happens next

- [ ] - what open in telegram means?

  Context:
  - what open in telegram means?

- [ ] - telegram:  sync subsscribers mean what? who does that? and jobs will have only 1 maybe in rare cases 2 subscribers?

  Context:
  - telegram:  sync subsscribers mean what? who does that? and jobs will have only 1 maybe in rare cases 2 subscribers?

- [ ] - telegram and scanning loop closes when i close vscode if run from there or stays in memory?

  Context:
  - telegram and scanning loop closes when i close vscode if run from there or stays in memory?

- [ ] - settings: Back to results makes not much sense unless the page was visited FROM the dashboard and ui wise doesnt seem proper and isnt back to dashboard doing the same?

  Context:
  - settings: Back to results makes not much sense unless the page was visited FROM the dashboard and ui wise doesnt seem proper and isnt back to dashboard doing the same?

- [ ] - what is this mean in admin Disable dashboard link preview?

  Context:
  - what is this mean in admin Disable dashboard link preview?

- [ ] - save daily schedule is wrong...what i wannted was a button to setup a daily run that we have to maintain and keep and shouldnt close unless the job is killed (we also need a kill switch if users dont want a schedule run anymore) ONLY MAKES SENSE IN CLOUD but now used via OPENCLAW

  Context:
  - save daily schedule is wrong...what i wannted was a button to setup a daily run that we have to maintain and keep and shouldnt close unless the job is killed (we also need a kill switch if users dont want a schedule run anymore) ONLY MAKES SENSE IN CLOUD but now used via OPENCLAW

- [ ] - Suggested Tuning is always empty, is it ok? is it learning differentyl?

  Context:
  - Suggested Tuning is always empty, is it ok? is it learning differentyl?

- [ ] - I've updated the terminology from "adjacent titles" to "secondary titles" across all the provided files. This includes updating UI labels, internal variable names, dictionary keys (affecting profile.json schema), and documentation.

  Context:
  - I've updated the terminology from "adjacent titles" to "secondary titles" across all the provided files. This includes updating UI labels, internal variable names, dictionary keys (affecting profile.json schema), and documentation.

- [ ] - settings: Reload Profile has no context and no explanation of what it does

  Context:
  - settings: Reload Profile has no context and no explanation of what it does

- [ ] - any point in having Previously Kept except for internal login for debugin?

  Context:
  - any point in having Previously Kept except for internal login for debugin?

- [ ] - we need to improve strength in capabilities matrix to

  Context:
  - we need to improve strength in capabilities matrix to

- [ ] Expert: Can lead, innovate, and mentor others.

  Context:
  Expert: Can lead, innovate, and mentor others.

- [ ] Advanced: Can handle complex tasks independently.

  Context:
  Advanced: Can handle complex tasks independently.

- [ ] Intermediate: Can handle routine tasks with minimal help.

  Context:
  Intermediate: Can handle routine tasks with minimal help.

- [ ] Beginner: Learning the basics; needs heavy supervision.

  Context:
  Beginner: Learning the basics; needs heavy supervision.

- [ ] check if you like it, and see how helpful and consistent it is now including help?

  Context:
  check if you like it, and see how helpful and consistent it is now including help?

- [ ] use Color-Code for  Strengths

  Context:
  use Color-Code for  Strengths

- [ ] - Page 1: The Upload (The "Onboarding")

  Context:
  - Page 1: The Upload (The "Onboarding")

- [ ] Modernize the Upload: Swap the "Choose file" button for a large Drag & Drop zone. It makes the app feel like a modern tool rather than a 2005 web form.

  Context:
  Modernize the Upload: Swap the "Choose file" button for a large Drag & Drop zone. It makes the app feel like a modern tool rather than a 2005 web form.

- [ ] - Waiting/working/transition icon  in case things get slow later

  Context:
  - Waiting/working/transition icon  in case things get slow later

- [ ] Real-time AI Feedback: When the user clicks "Build Draft Profile," show "active" status messages (e.g., "Extracting skills...", "Calculating experience...") to show the AI is working.

  Context:
  Real-time AI Feedback: When the user clicks "Build Draft Profile," show "active" status messages (e.g., "Extracting skills...", "Calculating experience...") to show the AI is working.

- [ ] capability matrix: The "Remove" Button: Placing a high-consequence action (Remove) right next to the primary dropdowns without a distinct visual style (like a trash icon) makes accidental deletions likely.

  Context:
  capability matrix: The "Remove" Button: Placing a high-consequence action (Remove) right next to the primary dropdowns without a distinct visual style (like a trash icon) makes accidental deletions likely.

- [ ] Repetitive Headers: The question "How relevant is this to your target roles?" is repeated for every single row. This creates massive visual clutter.

  Context:
  Repetitive Headers: The question "How relevant is this to your target roles?" is repeated for every single row. This creates massive visual clutter.

- [ ] Consolidate Table Headers: Move "How relevant is this..." into the table header row. Don't repeat the full question next to every dropdown.

  Context:
  Consolidate Table Headers: Move "How relevant is this..." into the table header row. Don't repeat the full question next to every dropdown.

- [ ] Use "Pill" Tags for Aliases: Instead of a dropdown, show the aliases as small tags under the capability name so the user can see them instantly but with a + sign if there are so many that would make this weird, to expand it

  Context:
  Use "Pill" Tags for Aliases: Instead of a dropdown, show the aliases as small tags under the capability name so the user can see them instantly but with a + sign if there are so many that would make this weird, to expand it

- [ ] Stop treating each capability as a floating box. Use a rigid table structure with 3 distinct columns.

  Context:
  Stop treating each capability as a floating box. Use a rigid table structure with 3 distinct columns.

- [ ] Column 1: The Identity (Left Aligned)

  Context:
  Column 1: The Identity (Left Aligned)

- [ ] Top line: The capability title in Bold Black font.

  Context:
  Top line: The capability title in Bold Black font.

- [ ] Bottom line: Small, plain gray text for aliases.

  Context:
  Bottom line: Small, plain gray text for aliases.

- [ ] ❌ Do not put aliases in colored bubbles.

  Context:
  ❌ Do not put aliases in colored bubbles.

- [ ] Example:

  Context:
  Example:

- [ ] bpmn modelling

  Context:
  bpmn modelling

- [ ] Also known as: bpmn model, bpmn model define

  Context:
  Also known as: bpmn model, bpmn model define

- [ ] --

  Context:
  --

- [ ] - improve this hardcoded things. How pros do it?

  Context:
  - improve this hardcoded things. How pros do it?

- [ ] _ROLE_SECTION_HINTS = ("experience", "employment", "career", "work history", "professional")

  Context:
  _ROLE_SECTION_HINTS = ("experience", "employment", "career", "work history", "professional")

- [ ] _SKILL_SECTION_HINTS = ("skill", "capabilit", "tool", "technology", "competenc", "summary", "profile")

  Context:
  _SKILL_SECTION_HINTS = ("skill", "capabilit", "tool", "technology", "competenc", "summary", "profile")

- [ ] _IGNORE_SECTION_HINTS = ("education", "certification", "certificate", "training", "award")

  Context:
  _IGNORE_SECTION_HINTS = ("education", "certification", "certificate", "training", "award")

- [ ] - Minimum annual salary : if we dont have a min put 0 as default and this cannot be negative. Also this is not mandatory for user input. This should clarify it is without super

  Context:
  - Minimum annual salary : if we dont have a min put 0 as default and this cannot be negative. Also this is not mandatory for user input. This should clarify it is without super

- [ ] We need to be smart to use salary from users and know if a job posted salary includes  super, NOT sure how seek.com and linked expose that, investigate first

  Context:
  We need to be smart to use salary from users and know if a job posted salary includes  super, NOT sure how seek.com and linked expose that, investigate first

- [ ] - Minimum daily rate:  if we dont have a min put 0 as default and this cannot be negative. Also this is not mandatory for user input. This should clarify it is without super

  Context:
  - Minimum daily rate:  if we dont have a min put 0 as default and this cannot be negative. Also this is not mandatory for user input. This should clarify it is without super

