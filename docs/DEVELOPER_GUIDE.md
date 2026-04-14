# Developer Guide

## Purpose

This file is for technical contributors.

Use it alongside:

- `SOUL.md` for project memory and product intent
- `docs/OPERATIONS.md` for runtime behavior
- `docs/USER_GUIDE.md` for the end-user flow

## Current Architecture

Core runtime pieces:

- `admin_api.py`
  Local web UI, onboarding route, admin route, and profile/review APIs.

- `source_documents.py`
  Local source-pack persistence and source-document import into `profile.json`.

- `profile_store.py`
  Default profile model, load/save, and patch behavior.

- `profile_learning.py`
  Text-to-profile extraction helpers.

- `scraper_direct.py`
  Current SEEK source connector and dashboard renderer. The filename is historical.

- `filters.py`
  Deterministic title and content filtering.

- `llm_gate.py`
  Optional constrained LLM decision step.

## Naming Note

The code still uses terms like `scraper` and `seek_results.html` because that is how the project evolved.

For product-level docs and future architecture, prefer:

- source connector
- job-source connector
- dashboard
- runtime profile

Do not rename major files casually unless there is time to clean the whole project consistently.

## Current Onboarding Flow

1. User visits `/start`
2. Uploads a detailed CV and optional supporting background
3. Uploaded documents are saved into a local source pack under ignored paths
4. The source pack is imported into `data/profile.json`
5. Admin is then used to refine the runtime profile

## Current Runner Split

- `run_jobs.py`
  Preferred explicit entry point for refreshing source data and rebuilding outputs.

- `main.py`
  Compatibility wrapper that forwards to `run_jobs.py`.

- `agent_runner.py`
  Orchestration layer for refresh plus digest plus notifications.

## Current Product Boundary

Current implemented source:

- SEEK

Planned additional sources:

- LinkedIn
- others later

Design assumption:

- new sources should normalize into the same record shape used by the dashboard, review flow, history, and fit logic

## Safe Local State

Do not accidentally commit:

- `data/profile.json`
- `data/job_history.json`
- `data/llm_cache.json`
- `data/capability_profile.txt`
- `data/application_inputs/`
- `data/application_materials.json`
- `TODO.txt`
- `.venv/`
