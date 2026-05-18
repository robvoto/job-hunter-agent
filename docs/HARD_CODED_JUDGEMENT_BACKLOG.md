# Hardcoded Judgment Backlog

This document lists instances of hardcoded business judgment logic identified in the project. For each item, it outlines its current decision-making, associated risks, and recommended future replacements to enhance flexibility, user control, and adaptability.

---

## 1. CV Onboarding & Structural Learning

### Item: `_GENERIC_ROLE_TOKENS`
- **File:** `e:\Programming\job-hunter-agent\job_hunter_agent\profile_learning.py`
- **Symbol/Function Name:** `_GENERIC_ROLE_TOKENS`
- **What it currently decides:** Defines a set of common professional role words (e.g., "analyst", "manager", "engineer") used as a "sealed" guard to identify valid professional titles and prevent company names or description fragments from being promoted as role titles.
- **Why it is risky:**
    - **Limited Scope:** The list is finite and may not cover all valid generic role tokens, especially for niche or emerging roles, leading to false negatives in title extraction.
    - **Language/Cultural Bias:** The tokens are likely English-centric and may not be universally applicable across different languages or cultural contexts.
    - **Maintenance Overhead:** Requires manual updates to stay current with evolving job titles.
    - **Rigidity:** The "sealed" nature prevents dynamic adaptation without code changes.
- **Recommended future replacement:** Managed knowledge (a configurable, extensible list of generic role tokens that can be updated by a user or administrator without code changes).

### Item: `_TITLE_SENTENCE_LEAD_TOKENS` & `_TITLE_SENTENCE_CONTEXT_TOKENS`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\profile_learning.py`
- **Symbol/Function Name:** `_TITLE_SENTENCE_LEAD_TOKENS` & `_TITLE_SENTENCE_CONTEXT_TOKENS`
- **What it currently decides:** These sets of tokens are used in `_looks_like_role_title_line` as grammatical heuristics to reject lines that look like descriptive sentences (e.g., starting with "working", "responsible for") from being classified as role titles.
- **Why it is risky:**
    - **False Negatives:** A legitimate role title might coincidentally contain or start with these tokens, leading to its incorrect rejection.
    - **Limited Linguistic Coverage:** The heuristics are based on specific English sentence structures and might fail for variations or other languages.
    - **Maintenance:** Requires manual updates if common descriptive patterns change.
- **Recommended future replacement:** LLM classifier (an LLM could be fine-tuned to classify whether a given text string is a role title or a descriptive sentence, offering more flexibility and robustness).

### Item: `_looks_like_role_title_line()` thresholds
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\profile_learning.py`
- **Symbol/Function Name:** `_looks_like_role_title_line()`
- **What it currently decides:** Imposes arbitrary length and punctuation constraints (e.g., line length > 80 characters, presence of commas or periods) to filter out noise from CV role headers, assuming long or punctuated lines are not titles.
- **Why it is risky:**
    - **Oversimplification:** Legitimate, but unusually long or punctuated, role titles could be incorrectly rejected.
    - **Fragility:** CV formatting varies widely; these fixed thresholds might be too strict for some well-formatted CVs or too lenient for others.
    - **Lack of Context:** Ignores semantic context, relying solely on superficial textual features.
- **Recommended future replacement:** LLM classifier (an LLM could evaluate the likelihood of a line being a role title based on broader contextual and semantic cues, rather than rigid rules).

### Item: `_classify_titles_from_evidence()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\profile_learning.py`
- **Symbol/Function Name:** `_classify_titles_from_evidence()`
- **What it currently decides:** Contains high-level logic for promoting a role title to a target or secondary pattern based on recency, repetition, and "purity" (standalone vs. compound usage).
- **Why it is risky:**
    - **Subjectivity of Weights:** The implicit weighting of recency, repetition, and purity is a business judgment that might not align with all users' preferences.
    - **Complexity:** The logic is intricate and can be difficult to debug or modify without unintended side effects.
    - **Limited Adaptability:** Does not easily adapt to nuanced career paths where, for example, a less recent but highly specialized role might be more relevant than a recent but generic one.
- **Recommended future replacement:** User usefulness review (allow users to explicitly rank or confirm the importance of extracted titles, or provide a UI to adjust the weights of recency, repetition, and purity).

### Item: `_PHRASE_BLOCKLIST`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\cv_pipeline.py`
- **Symbol/Function Name:** `_PHRASE_BLOCKLIST`
- **What it currently decides:** A hardcoded list of words (e.g., "experience", "project", "tools") that are explicitly excluded from being considered standalone capabilities during phrase extraction.
- **Why it is risky:**
    - **Over-blocking:** A word in the blocklist might be a legitimate capability in a specific context (e.g., "Project Management" is a capability, but "project" is blocked).
    - **Inflexibility:** Cannot be easily updated or customized by users.
    - **Maintenance:** Requires manual review and updates to ensure it remains relevant and doesn't inadvertently block valid terms.
- **Recommended future replacement:** Managed knowledge (a configurable blocklist that can be updated by users or administrators, potentially with contextual exceptions).

### Item: `score_and_promote()` thresholds
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\cv_pipeline.py`
- **Symbol/Function Name:** `score_and_promote()`
- **What it currently decides:** Assigns a default strength ("strong", "working", "basic") to extracted capability clusters based on hardcoded thresholds for recency (years since last use), duration (min months), and breadth (min roles).
- **Why it is risky:**
    - **Arbitrary Thresholds:** The specific numeric thresholds (e.g., 4 years for "strong", 36 months, 2 roles) are arbitrary business judgments that may not universally reflect a capability's true strength or a user's perception of it.
    - **Lack of Nuance:** Does not account for the qualitative nature of experience (e.g., a short but intense project might be more impactful than a long but routine one).
    - **User Disagreement:** Users might disagree with the system's default strength assignments, leading to frustration.
- **Recommended future replacement:** User usefulness review (allow users to manually adjust the strength of capabilities, with the system learning from these adjustments, or provide a UI to fine-tune the aging parameters).

### Item: `classify_evidence_section_label()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\profile_store.py`
- **Symbol/Function Name:** `classify_evidence_section_label()`
- **What it currently decides:** Maps CV section headers (e.g., "detailed", "legacy", "note") to predefined evidence tiers (Primary/Secondary/Background) based on hardcoded keywords.
- **Why it is risky:**
    - **Limited Keyword Set:** The predefined keywords might not cover all possible ways users label their CV sections, leading to misclassification.
    - **Inflexibility:** Cannot easily adapt to new or custom section labels.
    - **Ambiguity:** Some keywords might be ambiguous or used differently by various users.
- **Recommended future replacement:** LLM classifier (an LLM could classify section labels into evidence tiers based on semantic understanding, offering more robust and flexible classification).

## 2. Job Filtering & Rejection

### Item: `_matches_hard_requirement()` / `_matches_soft_requirement()` regex
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\filters.py`
- **Symbol/Function Name:** `_matches_hard_requirement()` / `_matches_soft_requirement()`
- **What it currently decides:** Uses hardcoded regex patterns to identify linguistic cues that indicate "Essential" vs "Desirable" skills in job descriptions.
- **Why it is risky:**
    - **Fragility of Regex:** Regex patterns are brittle and can easily break with slight variations in phrasing or grammar.
    - **Limited Linguistic Coverage:** Cannot capture the full spectrum of ways "essential" or "desirable" requirements are expressed in natural language.
    - **Maintenance Overhead:** Requires constant updates and testing to maintain accuracy as language evolves.
    - **False Positives/Negatives:** May incorrectly classify requirements due to the limitations of pattern matching.
- **Recommended future replacement:** LLM classifier (an LLM could be trained to identify the strength of requirements based on semantic understanding, offering more robust and adaptable classification).

### Item: `_evaluate_description_confidence()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\filters.py`
- **Symbol/Function Name:** `_evaluate_description_confidence()`
- **What it currently decides:** Scores the structural quality of a job ad (e.g., length, presence of sections like "responsibilities", bullet points) to determine if it's too vague to be trusted for automated review.
- **Why it is risky:**
    - **Arbitrary Thresholds:** The specific numeric thresholds for length, section count, and bullet points are arbitrary and may not universally correlate with description quality.
    - **Format Bias:** Favors certain formatting styles (e.g., bullet points, explicit section headers) and might penalize well-written but unconventionally formatted ads.
    - **Ignores Content:** Focuses on structure rather than the actual informational content, potentially rejecting concise but informative ads.
- **Recommended future replacement:** LLM classifier (an LLM could evaluate the informational density and clarity of a job description, providing a more nuanced confidence score).

### Item: `_evaluate_capability_profile()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\filters.py`
- **Symbol/Function Name:** `_evaluate_capability_profile()`
- **What it currently decides:** Determines when a skill gap (based on the candidate's capability level and the job's requirements) becomes a hard rejection (e.g., `DESC_CAPABILITY_LOW`).
- **Why it is risky:**
    - **Rigid Rejection Rules:** Hardcoded rules for rejection based on capability levels might be too strict and lead to false negatives, especially for roles where some skills can be learned on the job.
    - **Lack of Contextual Understanding:** Does not fully understand the criticality of a skill in the context of the entire job description.
    - **User Preference Override:** May override a user's willingness to consider roles with certain skill gaps.
- **Recommended future replacement:** Neutral scoring (assign penalties for skill gaps rather than hard rejections, allowing the overall fit score to reflect the gap, and let the user decide the acceptable threshold).

### Item: `infer_posting_channel()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\source_connector.py`
- **Symbol/Function Name:** `infer_posting_channel()`
- **What it currently decides:** Uses heuristics (keywords in company name, description patterns like "our client" vs "about us") to identify whether a job was posted by a recruiter or a direct employer.
- **Why it is risky:**
    - **Pattern Fragility:** Regex patterns and keyword lists are prone to false positives/negatives as job posting language evolves.
    - **Ambiguity:** Some phrases can be used by both recruiters and direct employers, leading to misclassification.
    - **Maintenance:** Requires ongoing updates to the keyword lists and patterns.
- **Recommended future replacement:** LLM classifier (an LLM could be trained to classify posting channels with higher accuracy and adaptability based on a broader understanding of the text).

### Item: `_GOVERNMENT_CONTEXT_PATTERNS`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\source_connector.py`
- **Symbol/Function Name:** `_GOVERNMENT_CONTEXT_PATTERNS`
- **What it currently decides:** Defines a set of keywords (e.g., "government", "APS", "department") to identify jobs with a government/public sector context.
- **Why it is risky:**
    - **Limited Keyword Set:** May miss government roles that use different terminology or are in specific sub-sectors not covered by the list.
    - **False Positives:** Some keywords might appear in non-government contexts (e.g., "department" in a large private company).
    - **Maintenance:** Requires manual updates to keep the list comprehensive and accurate.
- **Recommended future replacement:** Managed knowledge (a configurable list of government-related terms and entities that can be updated by users or administrators).

### Item: `_VALID_CATEGORIES` for rejection rules
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\local_server.py`
- **Symbol/Function Name:** `_VALID_CATEGORIES`
- **What it currently decides:** Defines a fixed set of categories (e.g., "domain", "seniority", "work_arrangement") that users can assign to rejection rules.
- **Why it is risky:**
    - **Limited Categorization:** The predefined categories might not cover all possible reasons for job rejection, limiting the granularity of user feedback.
    - **Rigidity:** Users cannot define custom categories, which might be useful for specific niche rejections.
    - **Maintenance:** Requires code changes to add or modify categories.
- **Recommended future replacement:** Managed knowledge (a configurable list of rejection categories that can be extended by users or administrators, possibly with a "custom" option).

## 3. Fit Scoring & Match Labeling

### Item: `MATCH_LEVELS`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\match_labels.py`
- **Symbol/Function Name:** `MATCH_LEVELS`
- **What it currently decides:** Defines the numeric score thresholds that map to human-readable "Match Bands" (e.g., "Strong match", "Good match").
- **Why it is risky:**
    - **Arbitrary Thresholds:** The specific score thresholds are arbitrary business judgments that might not align with a user's perception of what constitutes a "strong" or "good" match.
    - **Lack of Personalization:** Does not allow users to customize their own match band thresholds.
    - **Misinterpretation:** Users might misinterpret the bands if the underlying scoring logic doesn't align with their expectations.
- **Recommended future replacement:** User usefulness review (allow users to define or adjust their own match band thresholds, or provide feedback on the appropriateness of the current bands).

### Item: `fit_score_breakdown()` (Scoring Budget)
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\source_connector.py`
- **Symbol/Function Name:** `fit_score_breakdown()`
- **What it currently decides:** Implements the core "Scoring Budget" by assigning fixed point values to various components (e.g., Title match, LLM grade, Freshness).
- **Why it is risky:**
    - **Fixed Budget Allocation:** The specific point values (e.g., 15 for title, 25 for LLM) are arbitrary business judgments about the relative importance of each component.
    - **Lack of Personalization:** Does not allow users to customize the weighting of different scoring components based on their personal priorities.
    - **Opacity:** While documented, the underlying rationale for these specific numbers might not be immediately clear or agreeable to all users.
- **Recommended future replacement:** User usefulness review (allow users to adjust the weights of different scoring components, or provide a UI to fine-tune the "Scoring Budget" allocation).

### Item: `salary_fit_adjustment()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\source_connector.py`
- **Symbol/Function Name:** `salary_fit_adjustment()`
- **What it currently decides:** Defines how aggressively to penalize job offers that fall below the user's minimum salary target, using fixed ratios and point deductions.
- **Why it is risky:**
    - **Arbitrary Ratios/Penalties:** The specific ratios (0.80, 0.60) and point deductions (-1, -3, -5) are arbitrary business judgments that might not align with a user's financial priorities or risk tolerance.
    - **Lack of Personalization:** Does not allow users to customize how sensitive the system is to salary discrepancies.
    - **Oversimplification:** A simple ratio might not capture the full nuance of salary expectations (e.g., a slightly lower salary might be acceptable for a dream role).
- **Recommended future replacement:** User usefulness review (allow users to define their own salary sensitivity thresholds and associated penalties, or provide a UI to fine-tune these parameters).

### Item: `assess_location_preference()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\source_connector.py`
- **Symbol/Function Name:** `assess_location_preference()`
- **What it currently decides:** Quantifies the "pain" or benefit of a job's location relative to the user's home and secondary locations, including penalties for required onsite attendance.
- **Why it is risky:**
    - **Arbitrary Point Values:** The specific point values (e.g., 8 for home, -5 for mandatory local onsite) are arbitrary business judgments about the desirability/undesirability of different location scenarios.
    - **Lack of Personalization:** Does not allow users to customize their own location preferences or the severity of penalties for undesirable locations.
    - **Oversimplification:** A fixed point system might not capture the full complexity of commuting preferences, travel tolerance, or relocation willingness.
- **Recommended future replacement:** User usefulness review (allow users to define their own location preferences and associated point values/penalties, or provide a UI to fine-tune these parameters).

### Item: `convergence_bonus_entry()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\source_connector.py`
- **Symbol/Function Name:** `convergence_bonus_entry()`
- **What it currently decides:** Awards a fixed bonus (+5 points) when multiple strong, independent signals (title OK, content OK, high description confidence, LLM grade EXCELLENT/STRONG, 2+ positive capability matches, no missing evidence) simultaneously confirm job fit.
- **Why it is risky:**
    - **Arbitrary Bonus Value:** The +5 point bonus is an arbitrary business judgment about the value of signal convergence.
    - **Fixed Conditions:** The specific conditions for triggering the bonus are rigid and might not capture all forms of strong signal alignment.
    - **Lack of Transparency:** While documented, the exact interplay of conditions leading to the bonus might not be immediately clear to users.
- **Recommended future replacement:** Neutral scoring (integrate the benefits of convergence more organically into the existing scoring components rather than as a separate bonus, or allow users to configure the bonus value and conditions).

### Item: `evaluate_competitive_signal_alignment()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\source_connector.py`
- **Symbol/Function Name:** `evaluate_competitive_signal_alignment()`
- **What it currently decides:** Penalizes jobs that are "saturated" with a specialist domain that the user's profile does not strongly align with, using fixed negative adjustments.
- **Why it is risky:**
    - **Arbitrary Penalties:** The specific negative adjustments (-5 to -8) are arbitrary business judgments about the severity of misalignment with competitive signals.
    - **Lack of Personalization:** Does not allow users to customize how sensitive the system is to competitive signal misalignment.
    - **Potential for False Negatives:** Might overly penalize roles that are slightly outside the user's core domain but still within their interest or growth areas.
- **

Rob V
can you just create a txt as this jobg was truncated


Gemini
Defining the Objective
Gemini 2.5 generated this response due to high traffic on Gemini 3

New file: HARD_CODED_JUDGEMENT_BACKLOG.txt
+278
The code change produced by Gemini cannot be automatically applied. You can manually apply the change or ask Gemini to try again.
# Hardcoded Judgment Backlog

This document lists instances of hardcoded business judgment logic identified in the project. For each item, it outlines its current decision-making, associated risks, and recommended future replacements to enhance flexibility, user control, and adaptability.

---

## 1. CV Onboarding & Structural Learning

### Item: `_GENERIC_ROLE_TOKENS`
- **File:** `e:\Programming\job-hunter-agent\job_hunter_agent\profile_learning.py`
- **Symbol/Function Name:** `_GENERIC_ROLE_TOKENS`
- **What it currently decides:** Defines a set of common professional role words (e.g., "analyst", "manager", "engineer") used as a "sealed" guard to identify valid professional titles and prevent company names or description fragments from being promoted as role titles.
- **Why it is risky:**
    - **Limited Scope:** The list is finite and may not cover all valid generic role tokens, especially for niche or emerging roles, leading to false negatives in title extraction.
    - **Language/Cultural Bias:** The tokens are likely English-centric and may not be universally applicable across different languages or cultural contexts.
    - **Maintenance Overhead:** Requires manual updates to stay current with evolving job titles.
    - **Rigidity:** The "sealed" nature prevents dynamic adaptation without code changes.
- **Recommended future replacement:** Managed knowledge (a configurable, extensible list of generic role tokens that can be updated by a user or administrator without code changes).

### Item: `_TITLE_SENTENCE_LEAD_TOKENS` & `_TITLE_SENTENCE_CONTEXT_TOKENS`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\profile_learning.py`
- **Symbol/Function Name:** `_TITLE_SENTENCE_LEAD_TOKENS` & `_TITLE_SENTENCE_CONTEXT_TOKENS`
- **What it currently decides:** These sets of tokens are used in `_looks_like_role_title_line` as grammatical heuristics to reject lines that look like descriptive sentences (e.g., starting with "working", "responsible for") from being classified as role titles.
- **Why it is risky:**
    - **False Negatives:** A legitimate role title might coincidentally contain or start with these tokens, leading to its incorrect rejection.
    - **Limited Linguistic Coverage:** The heuristics are based on specific English sentence structures and might fail for variations or other languages.
    - **Maintenance:** Requires manual updates if common descriptive patterns change.
- **Recommended future replacement:** LLM classifier (an LLM could be fine-tuned to classify whether a given text string is a role title or a descriptive sentence, offering more flexibility and robustness).

### Item: `_looks_like_role_title_line()` thresholds
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\profile_learning.py`
- **Symbol/Function Name:** `_looks_like_role_title_line()`
- **What it currently decides:** Imposes arbitrary length and punctuation constraints (e.g., line length > 80 characters, presence of commas or periods) to filter out noise from CV role headers, assuming long or punctuated lines are not titles.
- **Why it is risky:**
    - **Oversimplification:** Legitimate, but unusually long or punctuated, role titles could be incorrectly rejected.
    - **Fragility:** CV formatting varies widely; these fixed thresholds might be too strict for some well-formatted CVs or too lenient for others.
    - **Lack of Context:** Ignores semantic context, relying solely on superficial textual features.
- **Recommended future replacement:** LLM classifier (an LLM could evaluate the likelihood of a line being a role title based on broader contextual and semantic cues, rather than rigid rules).

### Item: `_classify_titles_from_evidence()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\profile_learning.py`
- **Symbol/Function Name:** `_classify_titles_from_evidence()`
- **What it currently decides:** Contains high-level logic for promoting a role title to a target or secondary pattern based on recency, repetition, and "purity" (standalone vs. compound usage).
- **Why it is risky:**
    - **Subjectivity of Weights:** The implicit weighting of recency, repetition, and purity is a business judgment that might not align with all users' preferences.
    - **Complexity:** The logic is intricate and can be difficult to debug or modify without unintended side effects.
    - **Limited Adaptability:** Does not easily adapt to nuanced career paths where, for example, a less recent but highly specialized role might be more relevant than a recent but generic one.
- **Recommended future replacement:** User usefulness review (allow users to explicitly rank or confirm the importance of extracted titles, or provide a UI to adjust the weights of recency, repetition, and purity).

### Item: `_PHRASE_BLOCKLIST`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\cv_pipeline.py`
- **Symbol/Function Name:** `_PHRASE_BLOCKLIST`
- **What it currently decides:** A hardcoded list of words (e.g., "experience", "project", "tools") that are explicitly excluded from being considered standalone capabilities during phrase extraction.
- **Why it is risky:**
    - **Over-blocking:** A word in the blocklist might be a legitimate capability in a specific context (e.g., "Project Management" is a capability, but "project" is blocked).
    - **Inflexibility:** Cannot be easily updated or customized by users.
    - **Maintenance:** Requires manual review and updates to ensure it remains relevant and doesn't inadvertently block valid terms.
- **Recommended future replacement:** Managed knowledge (a configurable blocklist that can be updated by users or administrators, potentially with contextual exceptions).

### Item: `score_and_promote()` thresholds
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\cv_pipeline.py`
- **Symbol/Function Name:** `score_and_promote()`
- **What it currently decides:** Assigns a default strength ("strong", "working", "basic") to extracted capability clusters based on hardcoded thresholds for recency (years since last use), duration (min months), and breadth (min roles).
- **Why it is risky:**
    - **Arbitrary Thresholds:** The specific numeric thresholds (e.g., 4 years for "strong", 36 months, 2 roles) are arbitrary business judgments that may not universally reflect a capability's true strength or a user's perception of it.
    - **Lack of Nuance:** Does not account for the qualitative nature of experience (e.g., a short but intense project might be more impactful than a long but routine one).
    - **User Disagreement:** Users might disagree with the system's default strength assignments, leading to frustration.
- **Recommended future replacement:** User usefulness review (allow users to manually adjust the strength of capabilities, with the system learning from these adjustments, or provide a UI to fine-tune the aging parameters).

### Item: `classify_evidence_section_label()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\profile_store.py`
- **Symbol/Function Name:** `classify_evidence_section_label()`
- **What it currently decides:** Maps CV section headers (e.g., "detailed", "legacy", "note") to predefined evidence tiers (Primary/Secondary/Background) based on hardcoded keywords.
- **Why it is risky:**
    - **Limited Keyword Set:** The predefined keywords might not cover all possible ways users label their CV sections, leading to misclassification.
    - **Inflexibility:** Cannot easily adapt to new or custom section labels.
    - **Ambiguity:** Some keywords might be ambiguous or used differently by various users.
- **Recommended future replacement:** LLM classifier (an LLM could classify section labels into evidence tiers based on semantic understanding, offering more robust and flexible classification).

## 2. Job Filtering & Rejection

### Item: `_matches_hard_requirement()` / `_matches_soft_requirement()` regex
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\filters.py`
- **Symbol/Function Name:** `_matches_hard_requirement()` / `_matches_soft_requirement()`
- **What it currently decides:** Uses hardcoded regex patterns to identify linguistic cues that indicate "Essential" vs "Desirable" skills in job descriptions.
- **Why it is risky:**
    - **Fragility of Regex:** Regex patterns are brittle and can easily break with slight variations in phrasing or grammar.
    - **Limited Linguistic Coverage:** Cannot capture the full spectrum of ways "essential" or "desirable" requirements are expressed in natural language.
    - **Maintenance Overhead:** Requires constant updates and testing to maintain accuracy as language evolves.
    - **False Positives/Negatives:** May incorrectly classify requirements due to the limitations of pattern matching.
- **Recommended future replacement:** LLM classifier (an LLM could be trained to identify the strength of requirements based on semantic understanding, offering more robust and adaptable classification).

### Item: `_evaluate_description_confidence()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\filters.py`
- **Symbol/Function Name:** `_evaluate_description_confidence()`
- **What it currently decides:** Scores the structural quality of a job ad (e.g., length, presence of sections like "responsibilities", bullet points) to determine if it's too vague to be trusted for automated review.
- **Why it is risky:**
    - **Arbitrary Thresholds:** The specific numeric thresholds for length, section count, and bullet points are arbitrary and may not universally correlate with description quality.
    - **Format Bias:** Favors certain formatting styles (e.g., bullet points, explicit section headers) and might penalize well-written but unconventionally formatted ads.
    - **Ignores Content:** Focuses on structure rather than the actual informational content, potentially rejecting concise but informative ads.
- **Recommended future replacement:** LLM classifier (an LLM could evaluate the informational density and clarity of a job description, providing a more nuanced confidence score).

### Item: `_evaluate_capability_profile()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\filters.py`
- **Symbol/Function Name:** `_evaluate_capability_profile()`
- **What it currently decides:** Determines when a skill gap (based on the candidate's capability level and the job's requirements) becomes a hard rejection (e.g., `DESC_CAPABILITY_LOW`).
- **Why it is risky:**
    - **Rigid Rejection Rules:** Hardcoded rules for rejection based on capability levels might be too strict and lead to false negatives, especially for roles where some skills can be learned on the job.
    - **Lack of Contextual Understanding:** Does not fully understand the criticality of a skill in the context of the entire job description.
    - **User Preference Override:** May override a user's willingness to consider roles with certain skill gaps.
- **Recommended future replacement:** Neutral scoring (assign penalties for skill gaps rather than hard rejections, allowing the overall fit score to reflect the gap, and let the user decide the acceptable threshold).

### Item: `infer_posting_channel()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\source_connector.py`
- **Symbol/Function Name:** `infer_posting_channel()`
- **What it currently decides:** Uses heuristics (keywords in company name, description patterns like "our client" vs "about us") to identify whether a job was posted by a recruiter or a direct employer.
- **Why it is risky:**
    - **Pattern Fragility:** Regex patterns and keyword lists are prone to false positives/negatives as job posting language evolves.
    - **Ambiguity:** Some phrases can be used by both recruiters and direct employers, leading to misclassification.
    - **Maintenance:** Requires ongoing updates to the keyword lists and patterns.
- **Recommended future replacement:** LLM classifier (an LLM could be trained to classify posting channels with higher accuracy and adaptability based on a broader understanding of the text).

### Item: `_GOVERNMENT_CONTEXT_PATTERNS`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\source_connector.py`
- **Symbol/Function Name:** `_GOVERNMENT_CONTEXT_PATTERNS`
- **What it currently decides:** Defines a set of keywords (e.g., "government", "APS", "department") to identify jobs with a government/public sector context.
- **Why it is risky:**
    - **Limited Keyword Set:** May miss government roles that use different terminology or are in specific sub-sectors not covered by the list.
    - **False Positives:** Some keywords might appear in non-government contexts (e.g., "department" in a large private company).
    - **Maintenance:** Requires manual updates to keep the list comprehensive and accurate.
- **Recommended future replacement:** Managed knowledge (a configurable list of government-related terms and entities that can be updated by users or administrators).

### Item: `_VALID_CATEGORIES` for rejection rules
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\local_server.py`
- **Symbol/Function Name:** `_VALID_CATEGORIES`
- **What it currently decides:** Defines a fixed set of categories (e.g., "domain", "seniority", "work_arrangement") that users can assign to rejection rules.
- **Why it is risky:**
    - **Limited Categorization:** The predefined categories might not cover all possible reasons for job rejection, limiting the granularity of user feedback.
    - **Rigidity:** Users cannot define custom categories, which might be useful for specific niche rejections.
    - **Maintenance:** Requires code changes to add or modify categories.
- **Recommended future replacement:** Managed knowledge (a configurable list of rejection categories that can be extended by users or administrators, possibly with a "custom" option).

## 3. Fit Scoring & Match Labeling

### Item: `MATCH_LEVELS`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\match_labels.py`
- **Symbol/Function Name:** `MATCH_LEVELS`
- **What it currently decides:** Defines the numeric score thresholds that map to human-readable "Match Bands" (e.g., "Strong match", "Good match").
- **Why it is risky:**
    - **Arbitrary Thresholds:** The specific score thresholds are arbitrary business judgments that might not align with a user's perception of what constitutes a "strong" or "good" match.
    - **Lack of Personalization:** Does not allow users to customize their own match band thresholds.
    - **Misinterpretation:** Users might misinterpret the bands if the underlying scoring logic doesn't align with their expectations.
- **Recommended future replacement:** User usefulness review (allow users to define or adjust their own match band thresholds, or provide feedback on the appropriateness of the current bands).

### Item: `fit_score_breakdown()` (Scoring Budget)
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\source_connector.py`
- **Symbol/Function Name:** `fit_score_breakdown()`
- **What it currently decides:** Implements the core "Scoring Budget" by assigning fixed point values to various components (e.g., Title match, LLM grade, Freshness).
- **Why it is risky:**
    - **Fixed Budget Allocation:** The specific point values (e.g., 15 for title, 25 for LLM) are arbitrary business judgments about the relative importance of each component.
    - **Lack of Personalization:** Does not allow users to customize the weighting of different scoring components based on their personal priorities.
    - **Opacity:** While documented, the underlying rationale for these specific numbers might not be immediately clear or agreeable to all users.
- **Recommended future replacement:** User usefulness review (allow users to adjust the weights of different scoring components, or provide a UI to fine-tune the "Scoring Budget" allocation).

### Item: `salary_fit_adjustment()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\source_connector.py`
- **Symbol/Function Name:** `salary_fit_adjustment()`
- **What it currently decides:** Defines how aggressively to penalize job offers that fall below the user's minimum salary target, using fixed ratios and point deductions.
- **Why it is risky:**
    - **Arbitrary Ratios/Penalties:** The specific ratios (0.80, 0.60) and point deductions (-1, -3, -5) are arbitrary business judgments that might not align with a user's financial priorities or risk tolerance.
    - **Lack of Personalization:** Does not allow users to customize how sensitive the system is to salary discrepancies.
    - **Oversimplification:** A simple ratio might not capture the full nuance of salary expectations (e.g., a slightly lower salary might be acceptable for a dream role).
- **Recommended future replacement:** User usefulness review (allow users to define their own salary sensitivity thresholds and associated penalties, or provide a UI to fine-tune these parameters).

### Item: `assess_location_preference()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\source_connector.py`
- **Symbol/Function Name:** `assess_location_preference()`
- **What it currently decides:** Quantifies the "pain" or benefit of a job's location relative to the user's home and secondary locations, including penalties for required onsite attendance.
- **Why it is risky:**
    - **Arbitrary Point Values:** The specific point values (e.g., 8 for home, -5 for mandatory local onsite) are arbitrary business judgments about the desirability/undesirability of different location scenarios.
    - **Lack of Personalization:** Does not allow users to customize their own location preferences or the severity of penalties for undesirable locations.
    - **Oversimplification:** A fixed point system might not capture the full complexity of commuting preferences, travel tolerance, or relocation willingness.
- **Recommended future replacement:** User usefulness review (allow users to define their own location preferences and associated point values/penalties, or provide a UI to fine-tune these parameters).

### Item: `convergence_bonus_entry()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\source_connector.py`
- **Symbol/Function Name:** `convergence_bonus_entry()`
- **What it currently decides:** Awards a fixed bonus (+5 points) when multiple strong, independent signals (title OK, content OK, high description confidence, LLM grade EXCELLENT/STRONG, 2+ positive capability matches, no missing evidence) simultaneously confirm job fit.
- **Why it is risky:**
    - **Arbitrary Bonus Value:** The +5 point bonus is an arbitrary business judgment about the value of signal convergence.
    - **Fixed Conditions:** The specific conditions for triggering the bonus are rigid and might not capture all forms of strong signal alignment.
    - **Lack of Transparency:** While documented, the exact interplay of conditions leading to the bonus might not be immediately clear to users.
- **Recommended future replacement:** Neutral scoring (integrate the benefits of convergence more organically into the existing scoring components rather than as a separate bonus, or allow users to configure the bonus value and conditions).

### Item: `evaluate_competitive_signal_alignment()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\source_connector.py`
- **Symbol/Function Name:** `evaluate_competitive_signal_alignment()`
- **What it currently decides:** Penalizes jobs that are "saturated" with a specialist domain that the user's profile does not strongly align with, using fixed negative adjustments.
- **Why it is risky:**
    - **Arbitrary Penalties:** The specific negative adjustments (-5 to -8) are arbitrary business judgments about the severity of misalignment with competitive signals.
    - **Lack of Personalization:** Does not allow users to customize how sensitive the system is to competitive signal misalignment.
    - **Potential for False Negatives:** Might overly penalize roles that are slightly outside the user's core domain but still within their interest or growth areas.
- **Recommended future replacement:** Neutral scoring (assign penalties for competitive signal misalignment rather than fixed adjustments, allowing the user to define their tolerance for such roles).

### Item: `dashboard_data.py` `_rank_by_fit()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\dashboard_data.py`
- **Symbol/Function Name:** `_rank_by_fit()`
- **What it currently decides:** Defines the sort order of the "Best Matches" section on the dashboard using a tuple of `(fit, newness, age, recency)`.
- **Why it is risky:**
    - **Fixed Sort Order:** The predefined sort order might not align with all users' priorities (e.g., some users might prioritize newness over raw fit).
    - **Lack of Customization:** Users cannot easily customize the ranking criteria or their weights.
- **Recommended future replacement:** User usefulness review (allow users to define their preferred sort order and weighting of different factors for ranking jobs).

## 4. LLM Prompting & Guidance

### Item: `build_system_prompt()` (Instructions on how to judge gaps)
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\llm_gate.py`
- **Symbol/Function Name:** `build_system_prompt()`
- **What it currently decides:** Instructs the LLM on how to evaluate job fit, emphasizing recent experience, honesty about gaps, and the weighting of evidence tiers.
- **Why it is risky:**
    - **Implicit Bias:** The instructions embed a specific "recruiter-like" bias (e.g., "Recent directly relevant experience matters more") that might not align with all users' career strategies (e.g., career changers).
    - **Lack of Transparency/Control:** Users cannot easily inspect or modify these core instructions that guide the AI's judgment.
- **Recommended future replacement:** User usefulness review (expose these high-level instructions as configurable "AI persona" settings, allowing users to fine-tune the LLM's judgment style).

### Item: `name_capability_clusters()` (Instructions to skip client/project names)
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\llm_gate.py`
- **Symbol/Function Name:** `name_capability_clusters()`
- **What it currently decides:** Guides the LLM to normalize capability names by skipping client/project names, app names, company names, etc.
- **Why it is risky:**
    - **Over-generalization:** While generally useful, in some niche contexts, a specific client or project name might actually be a valuable capability (e.g., "worked on Project X for Client Y" is a specific skill).
    - **Rigidity:** The instructions are hardcoded and cannot be easily adapted for specific user needs.
- **Recommended future replacement:** LLM classifier with user feedback (allow the LLM to suggest labels, but provide a mechanism for users to override or confirm, teaching the system what constitutes a valid capability in their context).

### Item: `HARD_BLOCKER_KINDS`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\llm_gate.py`
- **Symbol/Function Name:** `HARD_BLOCKER_KINDS`
- **What it currently decides:** Defines the "universe" of categories for hard requirements that the LLM can suggest as blockers (e.g., "credential", "clearance", "language").
- **Why it is risky:**
    - **Limited Taxonomy:** The predefined list of blocker kinds might not be exhaustive or flexible enough to cover all possible hard requirements.
    - **Rigidity:** Users cannot define new blocker kinds or modify existing ones.
- **Recommended future replacement:** Managed knowledge (a configurable and extensible list of hard blocker kinds that users or administrators can manage).

## 5. Technical Constants & Safety

### Item: `parse_seek_posted_age_days()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\utils.py`
- **Symbol/Function Name:** `parse_seek_posted_age_days()`
- **What it currently decides:** Parses time units (m, h, d, y) from SEEK's "posted age" strings.
- **Why it is risky:** (None - this is a technical parsing function)
- **Recommended future replacement:** (N/A - safe technical validation)

### Item: `_allowed_models`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\local_server.py`
- **Symbol/Function Name:** `_allowed_models`
- **What it currently decides:** Whitelists specific LLM models (e.g., gpt-4o, gpt-4o-mini) that the application is allowed to use.
- **Why it is risky:** (None - this is a security/cost control)
- **Recommended future replacement:** (N/A - safe technical validation)

### Item: `_normalize_identity_text()`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\job_identity.py`
- **Symbol/Function Name:** `_normalize_identity_text()`
- **What it currently decides:** Strips common legal suffixes (e.g., "pty ltd", "inc") from company names for deduplication purposes.
- **Why it is risky:** (None - this is a technical normalization function)
- **Recommended future replacement:** (N/A - safe technical validation)

### Item: `_coerce_int()` / `MAX_PAGES_CAP_HARD_LIMIT`
- **File:** `e:\Programming\job_hunter-agent\job_hunter_agent\profile_store.py`
- **Symbol/Function Name:** `_coerce_int()` / `MAX_PAGES_CAP_HARD_LIMIT`
- **What it currently decides:** Provides input sanitization and safety caps for numeric inputs (e.g., maximum pages to scrape).
- **Why it is risky:** (None - this is a safety/robustness control)
- **Recommended future replacement:** (N/A - safe technical validation)

### Summary of Observation
The **Scoring Budget** in `source_connector.py` and the **Role Parsing Heuristics** in `profile_learning.py` are the two most critical areas of "Business Judgment". They represent the core "Soul" of how the agent thinks. 

Most of the "Unclear" items usually reside in the `cv_pipeline` where heuristic thresholds (like `score >= 0.25`) are used to decide what data to discard versus what to promote—these are technically "Business Judgments" but often feel like "Fine Tuning."

```
