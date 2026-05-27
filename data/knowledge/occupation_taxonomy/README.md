# O*NET occupation taxonomy

This folder stores versioned local reference data generated from `OccupationalListings.zip`.

Generated files:

- `onet_occupations.json` — O*NET-SOC 2019 occupation codes, titles, normalized titles, and descriptions.
- `onet_alternate_titles.json` — alternate titles mapped to O*NET-SOC 2019 occupations.
- `onet_index.json` — lookup index keyed by normalized title.

Generate or refresh the files with:

```powershell
python -m job_hunter_agent.onet_taxonomy_import "C:\path\to\OccupationalListings.zip"
```

Do not import the full O*NET taxonomy into SQLite yet. SQLite should only hold runtime/cache decisions in `occupation_title_cache`.
