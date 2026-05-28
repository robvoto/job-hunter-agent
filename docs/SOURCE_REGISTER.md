# Source Register

Purpose:
Track external sources used to justify Job Hunter design decisions.

Rules:
- Add sources when a design decision depends on external evidence.
- Keep entries short.
- Each entry must explain:
  - what the source is
  - what we use it for
  - what limit/caution applies
- Do not use sources to justify uncontrolled automation.
- If a source supports a capability but warns about limits, record both.

This document tracks external sources used to justify Job Hunter design decisions.

## O*NET occupation taxonomy

Sources:
- O*NET Resource Center / Database: https://www.onetcenter.org/database.html
- O*NET OnLine: https://www.onetonline.org/

Used for:
- Local occupation taxonomy reference data.
- Occupation/title sanity checking.
- Avoiding hand-written title synonym lists.

Design decision:
- Store O*NET taxonomy as local JSON reference data.
- Do not load the full taxonomy into the app DB initially.
- Use DB only for runtime/cache classification results.
- O*NET is reference data, not runtime learning.

Limit:
- O*NET should not hard-reject jobs by itself unless combined with explicit user blockers.
- Unknown or ambiguous title matches should return uncertain.

## LLM for CV title extraction

Sources:
- LLM4Jobs: Unsupervised occupation extraction and standardization leveraging Large Language Models: https://arxiv.org/abs/2309.09708
- Named entity recognition overview: https://en.wikipedia.org/wiki/Named-entity_recognition
- OpenAI Structured Outputs documentation: https://platform.openai.com/docs/guides/structured-outputs
- ResumeFlow: LLM-facilitated resume/job-description information extraction: https://arxiv.org/abs/2402.06221

Used for:
- Structured extraction of role-title candidates from messy CV text when deterministic parsing is unreliable.

Design decision:
- LLM may be used to extract structured title evidence from CV text.
- LLM must return title candidates with evidence/snippet/confidence.
- LLM must not invent target occupations or desired future roles.
- If confidence is low, ask the user to manually confirm or enter target roles.
- O*NET handles occupation matching after title evidence exists.

Limit:
- LLM extraction is allowed only as controlled structured extraction.
- LLM must not generate free-form target occupation queries from the CV.
- LLM output must be inspectable by the user.

## Mandatory requirement gaps

Sources:
- Named entity recognition overview: https://en.wikipedia.org/wiki/Named-entity_recognition
- OpenAI Structured Outputs documentation: https://platform.openai.com/docs/guides/structured-outputs

Used for:
- Extracting required credentials, licences, certifications, clearances, registrations, checks, or requirements from job descriptions.
- Showing candidate-visible gaps when a job requires something not found in the profile.

Design decision:
- Show missing required items in the job card.
- User choices:
  - Yes, I have this
  - No, I don’t have this
  - Decide later
- Yes adds to candidate profile data.
- No adds to must_not_require_skills.
- Unknown gaps are visible, not silently hidden.

Limit:
- Do not silently reject first-time unknown gaps.
- Do not maintain partial government/clearance dictionaries.
- Do not use vague government-context learning.

## Hybrid retrieval and staged review pipelines

Sources:
- Pinecone — Hybrid Search Explained: https://www.pinecone.io/learn/hybrid-search/
- Haystack — Pipelines Overview: https://haystack.deepset.ai/overview/pipelines
- Google — Rules of ML: https://developers.google.com/machine-learning/guides/rules-of-ml

Used for:
- Multi-stage filtering and review pipelines.
- Cheap deterministic retrieval before expensive semantic evaluation.
- Avoiding uncontrolled heuristic growth.

Design decision:
- Use staged evaluation:
  - cheap deterministic filtering
  - occupation-family sanity checks
  - semantic LLM review only when needed
- Deterministic stages should reject only obvious non-fit cases.
- Semantic interpretation belongs to the LLM review layer.

Limit:
- Do not let deterministic title heuristics become semantic classifiers.
- Avoid duplicate scoring paths with different semantics.
- Avoid uncontrolled growth of alias/synonym lists.

## Prompt constraints and structured outputs

Sources:
- OpenAI Prompt Engineering Guide: https://platform.openai.com/docs/guides/prompt-engineering
- OpenAI Structured Outputs documentation: https://platform.openai.com/docs/guides/structured-outputs

Used for:
- Constraining LLM outputs.
- Structured capability extraction and validation.
- Preventing free-form capability invention.

Design decision:
- LLM capability scoring must operate only against candidate capability groups already present in the profile.
- Related skills are context/evidence for matching, not standalone capabilities.
- Validation layers must reject invalid capability names.

Limit:
- Do not trust unconstrained free-form LLM labels.
- Capability aliases must not create duplicate scoring semantics.

## Incremental architecture replacement

Sources:
- Martin Fowler — Strangler Fig Pattern: https://martinfowler.com/bliki/StranglerFigApplication.html

Used for:
- Safely replacing legacy scoring and filtering paths.

Design decision:
- Replace duplicate/legacy scoring paths incrementally.
- Remove dead code once replacement behaviour is verified.

Limit:
- Do not preserve duplicate logic paths indefinitely.
- Avoid parallel systems with conflicting semantics.

## Browser/API integration

Sources:
- MDN — Cross-Origin Resource Sharing (CORS): https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS

Used for:
- Browser/frontend communication with backend APIs.
- Understanding browser-enforced cross-origin restrictions.

Design decision:
- Explicitly configure allowed origins and API access behaviour.
- Fail loudly when browser/API integration assumptions are broken.

Limit:
- Do not rely on permissive wildcard CORS in production.
