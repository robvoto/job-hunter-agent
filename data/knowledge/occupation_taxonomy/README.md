# O*NET occupation taxonomy

Versioned local reference data generated from an O*NET source zip.

Generated files:

- `onet_occupations.json` — O*NET-SOC 2019 occupation codes, titles, and descriptions.
- `onet_alternate_titles.json` — alternate titles mapped to O*NET-SOC 2019 occupations.
- `onet_index.json` — lookup index keyed by normalized title.

## Regenerating

Run with either supported O*NET source zip:

```powershell
python -m job_hunter_agent.onet_taxonomy_import "C:\path\to\<source>.zip"
```

The format is auto-detected. Output files are identical regardless of source.

## Source options

### Option A — Full O*NET database (recommended)

~19,000 alternate titles. Much better title classification coverage.

1. Go to https://www.onetcenter.org/database.html
2. Download **Database** → select version → **Text** format → `db_XX_X_text.zip`
3. Run the importer with that zip.

### Option B — OccupationalListings.zip (limited)

~1,680 alternate titles. Many common job titles (e.g. "Tax Accountant", "Property Manager")
will not be recognised as far from target roles, causing unnecessary LLM calls.

Use only if the full database is unavailable.

## Notes

- Do not import the taxonomy into SQLite. SQLite holds only runtime cache decisions in `occupation_title_cache`.
- After regenerating, restart the server — the index is loaded once at startup via `lru_cache`.
- The current files were generated from the OccupationalListings format (limited). Regenerate with the full database to fix coverage gaps.
