---
name: release-management
description: Use for application versions, release preparation, Git tags, release checks, or publishing a Job Hunter version to GitHub before AWS deployment.
---

# Skill: Release Management

Use for every Job Hunter release or version change.

## Source of truth

- `pyproject.toml` `[project].version` is the single application version owner.
- `uv.lock`, the rendered header, and the Git tag must match that version.
- Internal managed JSON `version` fields (for example in knowledge/config payloads) are separate schema/content versioning and are **not** the application SemVer.
- Do not hardcode a separate version in Python, templates, JSON, deployment scripts, or docs.

## Commit vs release

- Do **not** bump the application version on every ordinary commit.
- Professional default: many commits can happen between releases; the version moves only when preparing a real release from clean `main`.
- `main` may legitimately contain unreleased commits after the latest release tag. That is normal as long as the current application version still matches the latest published tag.
- Ordinary feature, fix, refactor, and test commits should leave version files and release tags unchanged.
- Create the version bump only in the dedicated release commit produced by the release command below.
- If the team ever wants "every merge to `main` is a release", keep using the release command at merge/release time rather than hand-editing version files in unrelated commits.

## Required command

Never edit the version or create/push a release tag manually. Use:

```bash
./scripts/release-jobhunter.sh patch
./scripts/release-jobhunter.sh minor
./scripts/release-jobhunter.sh major
```

Use `--dry-run` to execute all release gates without changing files or Git history.

## Release meanings

- `patch`: bug fix or correction; `X.Y.Z -> X.Y.(Z+1)`.
- `minor`: backward-compatible functionality; `X.Y.Z -> X.(Y+1).0`.
- `major`: breaking change; `(X+1).0.0`.

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

AWS deploys code only after a release tag is published. Production must deploy an explicit release tag, for example `deploy-jobhunter vX.Y.Z`; it must not deploy "whatever main currently is". Do not edit the displayed version on AWS.

For AWS smoke tests or debug sessions that should not create a release, use the separate non-production helper:

```bash
deploy-jobhunter-ref <branch-or-sha>
```

Rules:
- `deploy-jobhunter-ref` is for staging/test/debug only.
- Never use `deploy-jobhunter-ref` as the normal production deploy path.
- Never replace or move an existing production tag just to get newer code onto AWS.

## Validation

For release-tool changes, run:

```bash
uv run python scripts/check-release-integrity.py
uv run pytest tests/test_release_management.py tests/test_settings_rendering.py -q
bash -n scripts/release-jobhunter.sh
```

Release/merge preparation also requires the full unit and non-LLM E2E suites.
