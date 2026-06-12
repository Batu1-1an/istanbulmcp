# Istanbul MCP

## What This Is

Istanbul MCP is a remote Model Context Protocol server that exposes Istanbul Metropolitan Municipality open data to AI assistants through a single URL. It focuses on reliable, source-aware city data rather than wrapping every dataset: catalog search, nearby city services, traffic, metro, parking, air quality, and narrow IETT line/stop access.

## Core Value

AI assistants should answer Istanbul city-data questions with real sources, freshness, and limitations instead of guessing.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Remote MCP endpoint works from MCP clients using Streamable HTTP.
- [ ] IBB CKAN catalog can be searched and inspected.
- [ ] Responses use a consistent source/freshness/limits envelope.
- [ ] Geo search supports radius and bbox queries over normalized city features.
- [ ] MVP city services cover ISPark parking, traffic status, Metro stations, air quality stations/readings where available, and basic IETT line/stop data.
- [ ] MVP deploys to Railway with documented setup and safe defaults.

### Out of Scope

- Full route planning — GTFS routing and realtime arrival logic are deferred to later phases.
- Normalizing all IBB datasets — too broad for a reliable MVP.
- Water outages, disaster/earthquake alerts, and high-stakes warnings — require extra validation and responsibility boundaries.
- User accounts, OAuth, push notifications, and map UI — not needed for the first MCP release.
- PostGIS/vector tiles — SQLite WAL/FTS5/RTree is enough for the MVP.

## Context

The repository currently contains research and planning documents only. Live validation found that CKAN, ISPark, traffic, Metro, and air-quality station endpoints are reachable without auth, while SOAP is limited mainly to IETT. ISbike was documented as useful but returned empty data during validation, so it should be optional rather than MVP-blocking.

The agreed stack is Python 3.11+, FastMCP/Python MCP SDK, `httpx`, `zeep` for IETT SOAP only, SQLite WAL with FTS5 and RTree, `pydantic`, `pytest`, and Railway. `ctx7` documentation lookup confirmed the official Python MCP SDK exposes FastMCP tools/resources/prompts and Streamable HTTP with stateless JSON-friendly deployment patterns.

## Constraints

- **Tech stack**: Python/FastMCP first — strongest fit for SOAP, CSV, GTFS, and geo processing.
- **Deployment**: Railway — CLI is authenticated locally and should be used for deploy workflows.
- **Reliability**: Every tool must return source, freshness, limits, and warnings when relevant.
- **Safety**: Read-only MCP tools; no unrestricted SQL; validate radius, bbox, limits, and user inputs.
- **Testing**: Unit tests should use fixtures rather than live IBB endpoints.
- **Secrets**: Agents may inspect local `.env` when needed, but secrets must never be printed or committed.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Build MVP as "City Data Core" | Keeps first release useful without drowning in 550 datasets | — Pending |
| Use Python + FastMCP | Official SDK supports tools/resources/prompts and Streamable HTTP; Python fits data processing | — Pending |
| Use Railway for deploy | Matches project goal of one remote URL and local CLI is authenticated | — Pending |
| Use SQLite for MVP | WAL, FTS5, and RTree cover the first data volume without PostGIS overhead | — Pending |
| Treat ISbike as optional | Live service returned empty data during validation | — Pending |
| Keep IETT SOAP narrow | SOAP risk is real but limited to IETT; avoid broad realtime transit scope | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition**:
1. Requirements invalidated? Move to Out of Scope with reason.
2. Requirements validated? Move to Validated with phase reference.
3. New requirements emerged? Add to Active.
4. Decisions to log? Add to Key Decisions.
5. "What This Is" still accurate? Update if drifted.

**After each milestone**:
1. Full review of all sections.
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state.

---
*Last updated: 2026-06-12 after initialization*
