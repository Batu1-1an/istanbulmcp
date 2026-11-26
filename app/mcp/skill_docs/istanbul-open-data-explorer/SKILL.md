---
name: istanbul-open-data-explorer
description: Discover and query IBB Open Data (CKAN) datasets, inspect resource schemas, fetch bounded records, and run allowlisted read-only SQL via Istanbul MCP. Use when the user asks to search Istanbul open datasets, explore municipal tables, or query IBB CKAN resources.
license: MIT
---

# Istanbul Open Data Explorer

Use this workflow to explore and query Istanbul Metropolitan Municipality (IBB) Open Data Portal (CKAN) datasets accurately without guessing resource IDs or column names.

## Required Discovery Sequence

1. **Optional schema reference:** Read `istanbul://schema/catalog` to see query bounds (`default_limit`, `max_limit`, whether SQL allowlist is enabled).
2. **Search datasets (`istanbul_search_datasets`):** Find candidate packages by keyword with a small `limit`.
3. **Inspect dataset (`istanbul_get_dataset`):** Retrieve the package's real `resource_id` values, formats, and metadata. Catalog metadata alone is not proof that a resource supports DataStore querying.
4. **Inspect schema (`istanbul_get_resource_schema`):** Always inspect actual published column names and types for the chosen `resource_id` before querying records.
5. **Query records (`istanbul_query_resource`):** Query using real column names, tight filters, and a small initial `limit` to inspect sample rows.

## Bounded Read-Only SQL (`istanbul_datastore_query`)

- Only call `istanbul_datastore_query` when the target `resource_id` is explicitly allowlisted (check `istanbul://coverage` or `istanbul://schema/catalog`).
- Write a **single read-only SQLite `SELECT`** over table `records` only.
- Forbidden constructs: writes (`INSERT`, `UPDATE`, `DELETE`, `DROP`), joins, subqueries, CTEs (`WITH`), window functions, non-allowlisted functions, or access to any table other than `records`.
- Bounded complete capture is required; if a dataset exceeds capture row or byte limits, report the limit honestly and fall back to filtered `istanbul_query_resource`.

## Honesty and Citation Rules

- Never invent `resource_id` values, column names, row counts, or license grants.
- Public read access is not a license grant; refer users to the dataset's published terms when licensing matters.
- Attribute data by publisher name (IBB) and cite only non-null `sources[].url` links — never expose raw API endpoints or data-file URLs as citations.
- Preserve `freshness`, `result_info` truncation counts, `limits`, and `warnings` in every answer.
