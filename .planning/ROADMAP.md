# Roadmap: Istanbul MCP

**Created:** 2026-06-12
**Mode:** Vertical MVP
**Granularity:** Coarse

## Phase Overview

| Phase | Name | Goal | Requirements |
|-------|------|------|--------------|
| 1 | MCP Foundation | Complete — remote server skeleton, storage base, envelope, validation, and health checks | CORE-01..CORE-04 |
| 2 | Catalog Core | Complete — CKAN catalog ingestion, search, metadata, schema, and guarded querying | CAT-01..CAT-04 |
| 3 | Geo & City Services | Complete — normalized geo search plus parking, traffic, metro, and air-quality tools | GEO-01..GEO-03, CITY-01..CITY-04 |
| 4 | Transit & Release | Narrow IETT SOAP integration, tests, docs, and Railway release | TRN-01..TRN-03, REL-01..REL-03 |

## Phase Details

### Phase 1: MCP Foundation

**Goal:** Establish the deployable FastMCP server and shared safety contracts.
**Mode:** mvp
**Status:** Complete

**Requirements:** CORE-01, CORE-02, CORE-03, CORE-04

**Success Criteria**:
1. MCP Inspector or an MCP client can list and call at least one tool through `/mcp`.
2. `/healthz` and `/readyz` return meaningful service/cache status.
3. Response envelope, freshness model, input validation, and limits are implemented and tested.
4. SQLite starts in WAL mode with initial migrations.

### Phase 2: Catalog Core

**Goal:** Make the IBB open-data catalog searchable and inspectable.
**Mode:** mvp
**Status:** Complete

**Requirements:** CAT-01, CAT-02, CAT-03, CAT-04

**Success Criteria**:
1. CKAN package/resource snapshots are stored locally.
2. Dataset search returns relevant results with source and freshness.
3. Dataset and resource metadata tools expose formats, license, URLs, and schema when available.
4. DataStore querying is guarded by filters, limits, and safe errors.

### Phase 3: Geo & City Services

**Goal:** Deliver the main user-facing Istanbul city-data demo path.
**Mode:** mvp
**Status:** Complete

**Requirements:** GEO-01, GEO-02, GEO-03, CITY-01, CITY-02, CITY-03, CITY-04

**Success Criteria**:
1. Radius and bbox search return normalized city features ordered by distance or geometry match.
2. ISPark nearby returns parking data with capacity/availability when provided.
3. Traffic status and Metro station tools work from validated REST/XML/JSON sources.
4. Air-quality tools report station/readings plus clear warnings when readings are stale or null.

### Phase 4: Transit & Release

**Goal:** Add narrow IETT transit capability and ship a documented Railway MVP.
**Mode:** mvp

**Requirements:** TRN-01, TRN-02, TRN-03, REL-01, REL-02, REL-03

**Success Criteria**:
1. IETT line info and stops-for-line tools work for validated sample lines.
2. SOAP failures and nightly downtime produce structured errors or stale fallback.
3. README, tool reference, `.env.example`, and Railway deploy notes are complete.
4. Unit tests cover core connectors, parsers, validation, envelope, freshness, and error states.
5. Railway deploy serves `/mcp`, `/healthz`, and `/readyz`.

## Traceability

All v1 requirements are mapped in `.planning/REQUIREMENTS.md`; coverage is 21/21.

---
*Last updated: 2026-06-12 after Phase 3 completion*
