# Requirements: Istanbul MCP

**Defined:** 2026-06-12
**Core Value:** AI assistants should answer Istanbul city-data questions with real sources, freshness, and limitations instead of guessing.

## v1 Requirements

### Core MCP

- [x] **CORE-01**: User can connect an MCP client to a remote Streamable HTTP `/mcp` endpoint.
- [x] **CORE-02**: Operator can check `/healthz` and `/readyz` for service and cache readiness.
- [x] **CORE-03**: Every tool response includes summary, source, freshness, limits, and warnings when relevant.
- [x] **CORE-04**: Tools validate inputs and enforce max radius, bbox, timeout, and result limits.

### Catalog

- [x] **CAT-01**: User can search the IBB CKAN catalog by query and format filters.
- [x] **CAT-02**: User can inspect a dataset's metadata, resources, license, and source URL.
- [x] **CAT-03**: User can inspect a resource's schema or format when available.
- [x] **CAT-04**: User can query supported DataStore resources through guarded filters and limits.

### Geo

- [x] **GEO-01**: User can find nearby city features by coordinate, type, radius, and limit.
- [x] **GEO-02**: User can search city features inside a bbox.
- [x] **GEO-03**: System stores normalized city features in SQLite with queryable coordinates.

### City Services

- [x] **CITY-01**: User can find nearby ISPark parking lots with capacity/availability fields when provided.
- [x] **CITY-02**: User can get Istanbul traffic status from the validated traffic source.
- [x] **CITY-03**: User can find nearby Metro Istanbul stations and line metadata.
- [x] **CITY-04**: User can find nearby air-quality stations and latest readings when the source provides them.

### Transit

- [x] **TRN-01**: User can retrieve basic IETT line information by line code.
- [x] **TRN-02**: User can retrieve stops for an IETT line when source data supports the mapping.
- [x] **TRN-03**: IETT SOAP failures produce structured errors or stale cache fallback.

### Release

- [x] **REL-01**: Project includes README, tool reference, `.env.example`, and Railway deployment notes.
- [x] **REL-02**: Unit tests cover connectors, parsers, response envelope, validation, and freshness states.
- [x] **REL-03**: Railway deployment runs with documented environment configuration.

## v2 Requirements

### Deferred

- **V2-01**: User can resolve common Istanbul place names to coordinates.
- **V2-02**: User can import and query deeper GTFS route/trip relationships.
- **V2-03**: User can query ISbike if the source returns usable station data.
- **V2-04**: User can query water outages after source and usage rules are revalidated.
- **V2-05**: User can view source-health and freshness dashboards.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Full route planning | Requires GTFS routing and validation beyond MVP |
| Realtime arrivals | Endpoint semantics need separate verification |
| Disaster/earthquake alerts | High-stakes accuracy and liability |
| User accounts/OAuth | Not necessary for first MCP release |
| PostGIS/vector tiles | SQLite is enough for v0.1 |
| Web map UI | Nice demo, not core MCP value |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CORE-01 | Phase 1 | Complete |
| CORE-02 | Phase 1 | Complete |
| CORE-03 | Phase 1 | Complete |
| CORE-04 | Phase 1 | Complete |
| CAT-01 | Phase 2 | Complete |
| CAT-02 | Phase 2 | Complete |
| CAT-03 | Phase 2 | Complete |
| CAT-04 | Phase 2 | Complete |
| GEO-01 | Phase 3 | Complete |
| GEO-02 | Phase 3 | Complete |
| GEO-03 | Phase 3 | Complete |
| CITY-01 | Phase 3 | Complete |
| CITY-02 | Phase 3 | Complete |
| CITY-03 | Phase 3 | Complete |
| CITY-04 | Phase 3 | Complete |
| TRN-01 | Phase 4 | Complete |
| TRN-02 | Phase 4 | Complete |
| TRN-03 | Phase 4 | Complete |
| REL-01 | Phase 4 | Complete |
| REL-02 | Phase 4 | Complete |
| REL-03 | Phase 4 | Complete |

**Coverage:**
- v1 requirements: 21 total
- Mapped to phases: 21
- Unmapped: 0

---
*Requirements defined: 2026-06-12*
*Last updated: 2026-06-12 after Phase 4 verification*
