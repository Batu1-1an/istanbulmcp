# Phase 2: Catalog Core - Context

**Gathered:** 2026-06-12
**Status:** Ready for planning
**Mode:** Auto-generated for autonomous execution

<domain>
## Phase Boundary

Make the IBB CKAN catalog searchable and inspectable. This phase owns CKAN connector methods, dataset/resource persistence, FTS-backed local snapshots, and catalog MCP tools.
</domain>

<decisions>
## Implementation Decisions

- Use CKAN Action API directly over `httpx`.
- Use POST JSON payloads for `package_search`, `package_show`, and `datastore_search`.
- Snapshot datasets and resources into SQLite for later phases.
- Guard resource querying through filters and limit only; no arbitrary SQL in MVP.
- Use `ctx7` checked CKAN documentation for `datastore_search` fields, records, filters, and limit behavior.
</decisions>

<code_context>
## Existing Code Insights

Phase 1 added FastMCP, settings, validation, envelope, and SQLite base tables. Catalog services can reuse those contracts.
</code_context>

<specifics>
## Specific Ideas

- Tools: `istanbul_search_datasets`, `istanbul_get_dataset`, `istanbul_get_resource_schema`, `istanbul_query_resource`.
- Every result returns CKAN source and freshness.
- Unit tests use `httpx.MockTransport`.
</specifics>

<deferred>
## Deferred Ideas

- Dataset quality scoring is v2.
- Schema drift detection is v2.
- Full SQL is out of scope for MVP.
</deferred>
