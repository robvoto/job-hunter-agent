# O*NET occupation taxonomy

Local, generated reference data used by Job Hunter's deterministic title gate.

Runtime job searches do **not** call O*NET over the network. The application reads the committed local index so title classification stays fast and available offline.

## Current source

The preferred source is the official full **O*NET Database JSON** release advertised at:

https://www.onetcenter.org/database.html

The generated `onet_index.json` records separately:

- `taxonomy_version` — the O*NET-SOC occupation taxonomy version.
- `database_release` — the O*NET database release, for example `30.3`.
- `dataset_fingerprint` — SHA-256 of the deterministic generated title index.
- `source_url` — the exact official database distribution used.

These values are part of cache safety. A newer/different O*NET dataset must not reuse title classifications produced from older data.

## Generated files

- `onet_index.json` — normalized occupation and job-title lookup index used at runtime.
- `onet_occupations.json` — occupation codes, titles and descriptions for inspection/reference.

The old `onet_alternate_titles.json` file was removed because it duplicated title data already represented in the runtime index and became unnecessarily large with the full Job Titles dataset.

## Refreshing

Check whether the local taxonomy is current:

```bash
uv run python -m job_hunter_agent.onet_taxonomy_refresh --check
```

Refresh explicitly from the official advertised O*NET JSON database:

```bash
uv run python -m job_hunter_agent.onet_taxonomy_refresh --update
```

Refresh is fail-safe: the new archive is downloaded to a temporary location, parsed and validated, and generated files are only replaced after a complete valid build.

`.github/workflows/onet-taxonomy-refresh.yml` checks weekly. When O*NET publishes a new database release, it regenerates and validates the reference data and opens/updates a pull request. It does not silently auto-merge taxonomy changes.

The importer accepts the current full O*NET database in JSON or nested text ZIP format. Automated refreshes use the official advertised JSON distribution.

## Target occupation safety

The full O*NET Job Titles dataset intentionally maps many real-world titles to multiple occupations. Job Hunter therefore does not use every alias as permission to widen a candidate's target occupation family.

For user-selected `target_roles` and `also_consider_roles`, resolution is conservative:

1. exact O*NET occupation titles;
2. exact Job Titles that O*NET marks as preferred in **Sample of Reported Titles / My Next Move**;
3. otherwise, an exact job title only when it resolves to one occupation;
4. ambiguous unpreferred aliases contribute no target code.

The broader full Job Titles index is still used to classify scraped job titles. This distinction improves coverage without turning ambiguous aliases such as `Systems Analyst` or `Data Analyst` into false target occupations.

## Attribution

O*NET data is published by the **National Center for O*NET Development** for the U.S. Department of Labor, Employment and Training Administration.

O*NET Database licensing: Creative Commons Attribution 4.0 International (CC BY 4.0):
https://creativecommons.org/licenses/by/4.0/
