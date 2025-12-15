# llm-ai-lc
LLM / AI /Langchain portfolio

SEEK Job Scraper with Rule-Based Filtering and LLM Judgement
This project is a local Python + Playwright tool that scrapes Business Analyst job listings from SEEK (Australia) and produces a clean shortlist based on deterministic rules first, with an optional LLM-based judgement step for borderline cases.
The goal is to replicate how a human scans job ads:
Apply hard, explainable rules to reject obvious mismatches.
For jobs that pass those rules, optionally ask an LLM a single question:
“Should this job be considered?”
The LLM is not an agent, does not replace rules, and is intentionally constrained to return only:
KEEP
REJECT
MAYBE
