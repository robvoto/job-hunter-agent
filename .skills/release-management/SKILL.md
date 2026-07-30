---
name: release-management
description: Use for application versions, release preparation, Git tags, release checks, or publishing a Job Hunter version to GitHub before AWS deployment.
---

# Skill: Release Management

Use for every Job Hunter release or version change.

## Source of truth

- `pyproject.toml` `[project].version` is the single application version owner.
- `uv.lock`, the rendered header, and the Git tag must match that version.
- Do not hardcode a separate version in Python, templates, JSON, deployment scripts, or docs.

## Required command

Never edit the version or create/push a release tag manually. Use:

```bash
./scripts/release-jobhunter.sh current
./scripts/release-jobhunter.sh patch
./scripts/release-jobhunter.sh minor
./scripts/release-jobhunter.sh major
```

Use `--dry-run` to execute all release gates without changing files or Git history.

## Release meanings

- `current`: publish the already-declared version when its matching tag does not exist.
- `patch`: bug fix or correction; `1.5.0 -> 1.5.1`.
- `minor`: backward-compatible functionality; `1.5.0 -> 1.6.0`.
- `major`: breaking change; `1.5.0 -> 2.0.0`.

## Mandatory gates

A release is blocked unless:

1. The branch is `main`.
2. The working tree is completely clean.
3. Local `main` exactly matches `origin/main`.
4. The current project version matches the latest release tag.
5. `pyproject.toml`, `uv.lock`, and the UI release metadata agree.
6. The full unit suite passes.
7. The non-LLM Playwright E2E suite passes.
8. The new version commit and annotated tag can be pushed atomically.
9. Local `HEAD`, `origin/main`, and unrelated working files remain unchanged while release tests run; concurrent-agent changes block the release.

Do not skip a failed gate, move an existing release tag, or force-push a release. Fix the cause and rerun the release command.

## AWS boundary

AWS deploys code after a release is published. Do not edit the displayed version on AWS. Deploy the tagged `main` version through the existing `deploy-jobhunter` command.

## Validation

For release-tool changes, run:

```bash
uv run python scripts/check-release-integrity.py
uv run pytest tests/test_release_management.py tests/test_settings_rendering.py -q
bash -n scripts/release-jobhunter.sh
```

Release/merge preparation also requires the full unit and non-LLM E2E suites.
