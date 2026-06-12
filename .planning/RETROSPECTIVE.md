# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — MVP

**Shipped:** 2026-06-12
**Phases:** 4 | **Plans:** 4 | **Sessions:** 1

### What Was Built

- Remote FastMCP service with health/readiness endpoints and Railway/Docker release config.
- CKAN catalog tools for search, dataset metadata, schema inspection, and guarded DataStore access.
- Geo-backed city-service tools for nearby/bbox search, ISPark, traffic, Metro, and air quality.
- Narrow IETT line/stops support with structured SOAP error handling.

### What Worked

- Keeping the MVP to a small set of high-value Istanbul sources avoided the 550-dataset trap.
- A shared response envelope made source, freshness, limits, warnings, and errors consistent across tools.
- Live smoke checks caught source-specific behavior that unit fixtures alone would not catch.

### What Was Inefficient

- IETT SOAP WSDL loading was brittle; raw SOAP was faster and more reliable for the narrow MVP.
- Railway verification initially failed because local auth had expired; after login, live deploy exposed the MCP lifespan issue and drove a useful production regression test.

### Patterns Established

- Connectors stay thin; services normalize, envelope, cache, and expose MCP-facing behavior.
- Unit tests use fixtures/mocks; only explicit smoke checks touch live IBB services.
- Any live source uncertainty becomes a response warning or structured error, not silent failure.

### Key Lessons

1. Validate Istanbul source endpoints early, because documented availability and usable payloads differ.
2. Keep transit narrow until GTFS and realtime semantics are researched separately.
3. Treat deployment authentication as an operator dependency and verify container behavior independently.

### Cost Observations

- Model mix: balanced profile.
- Sessions: 1.
- Notable: coarse GSD phases worked well for a compact MVP with several external data sources.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Sessions | Phases | Key Change |
|-----------|----------|--------|------------|
| v1.0 | 1 | 4 | Established autonomous GSD flow from research to verified release artifact |

### Cumulative Quality

| Milestone | Tests | Coverage | Runtime Checks |
|-----------|-------|----------|----------------|
| v1.0 | 29 passed | Core connectors, services, validation, storage, health | Live source smokes plus Docker health/readiness |

### Top Lessons (Verified Across Milestones)

1. Source validation must be part of planning and verification for city-data MCP tools.
2. A narrow, reliable tool surface is more valuable than broad dataset wrapping for the first release.
