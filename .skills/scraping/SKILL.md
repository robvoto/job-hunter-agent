# Skill: Scraping

Use before editing SEEK/LinkedIn scrapers or scraped job data shape.

## Rules
- SEEK uses direct job pages only; do not restore pane scraping.
- Scrapers collect evidence; they do not decide fit.
- Preserve raw/important job signals where possible.
- Capture source metadata separately from classification, including apply URL/domain, company links, poster identity, and ATS hints.
- Keep posting-channel fallback heuristics data-driven in managed JSON, not hardcoded in scraper code, and keep the extracted evidence unique/canonical.
- Use strong metadata first; only use fallback heuristics when trusted metadata is unavailable.
- When debug capture is enabled, persist raw HTML, raw JSON, and normalized records for source payload review.
- Do not add filtering, scoring, or rejection judgement inside scraper code.
- Normalise job identity consistently for dedup/history.
- Surface partial or low-confidence descriptions; do not hide them.
- Prefer board-declared metadata over text inference when extracting work mode.
- Only use fallback text heuristics for work mode when no structured or visible board metadata is available.
- Preserve work mode provenance so later review can distinguish trusted board metadata from inferred text.

## Work type normalization
Both Seek and LinkedIn normalize the raw work_type string through `map_job_type(raw, load_job_type())` from `scrapers/base.py` and `job_types.py`. The normalization mapping lives in `data/job_type.json` under the `"mapping"` key — no source-specific logic or hardcoded labels in scraper code. Unknown values are passed through and registered via the signal registry. The `"filter_groups"` key in the same file defines how canonical values map to dashboard filter options; scrapers do not use filter_groups.

## Owners
- `scrapers/seek.py`: SEEK scraping.
- `scrapers/linkedin.py`: LinkedIn via python-jobspy.
- `source_connector.py`: orchestration.
- `job_identity.py`: cross-source identity/dedup.
- `description_trust.py`: full-description confidence.
- `job_types.py`: work type normalization mapping and filter group definitions.

## Work mode extraction

Work mode extraction is evidence collection only. It must not score, reject, rank, or apply candidate preference.

Expected output fields when available:

```json
{
  "work_mode": "remote | hybrid | onsite | unknown",
  "work_mode_source": "seek_filter | seek_card | seek_detail_visible | seek_detail_payload | linkedin_structured | fallback_text | unknown",
  "work_mode_evidence": "exact text, selector, or structured field used",
  "work_mode_needs_review": true
}
```

### SEEK order
1. Search/listing metadata and selected work arrangement filter:
   - `[data-automation="refineWorkArrangement"]`
   - option links containing `/jobs/on-site`, `/jobs/hybrid`, `/jobs/remote`
   - visible option text or `aria-label`: `On-site`, `Hybrid`, `Remote`
   - selected state via checkbox / `aria-checked="true"`
2. Job card visible work arrangement/location metadata.
3. Direct job page visible metadata.
4. Embedded SEEK state/payload fields if already captured, especially fields containing:
   - `workArrangement`
   - `workArrangements`
   - `remote`
   - `hybrid`
   - `onsite`
   - `workplace`
   - `location`
5. Description text fallback only when metadata is unavailable.

Search filters are search context, not always job-level proof. If a filter value is used, preserve `work_mode_source="seek_filter"` and the exact filter evidence.

### LinkedIn order
1. Use python-jobspy structured output first when present:
   - `workplace_type`
   - `workplaceType`
   - `job_workplace`
   - `work_type`
   - `remote_allowed`
   - `is_remote`
   - `location`
2. If LinkedIn HTML is inspected directly, only use structured job-level state as metadata.
3. Do not treat search keywords such as `hybrid or remote` as job-level work mode evidence.
4. Description text fallback only when metadata is unavailable.

### Logging
Add structured debug logs when work mode is extracted:

- `job_id`
- `source_board`
- `work_mode`
- `work_mode_source`
- `work_mode_evidence`
- `fallback_used`
- `work_mode_needs_review`

These logs exist to support later review and learning. They must not promote new rules automatically.

## Checklist
- Is this collection logic, not judgement?
- Is full-description confidence preserved?
- Are missing/partial descriptions surfaced, not hidden?
- Is job identity stable across sources?
- Is work mode extracted from board metadata before fallback text inference?
- Is work mode provenance preserved for review/debugging?
- Are search keywords avoided as job-level work mode proof?
- Did you run the smallest relevant scraper/data-shape check?
