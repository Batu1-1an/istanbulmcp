# Istanbul MCP

## What This Is

Istanbul MCP is a remote Model Context Protocol server that exposes Istanbul Metropolitan Municipality open data to AI assistants through a single URL. It focuses on reliable, source-aware city data rather than wrapping every dataset: catalog search, nearby city services, traffic, metro, parking, air quality, and narrow IETT line/stop access.

## Core Value

AI assistants should answer Istanbul city-data questions with real sources, freshness, and limitations instead of guessing.

## Requirements

### Validated

- ✓ Remote MCP endpoint works from MCP clients using Streamable HTTP — v1.0
- ✓ IBB CKAN catalog can be searched and inspected — v1.0
- ✓ Responses use a consistent source/freshness/limits envelope — v1.0
- ✓ Geo search supports radius and bbox queries over normalized city features — v1.0
- ✓ MVP city services cover ISPark parking, traffic status, Metro stations, air quality stations/readings where available, and basic IETT line/stop data — v1.0
- ✓ MVP includes Railway deployment configuration and documented safe defaults — v1.0

### Active

- [ ] Re-authenticate and link Railway, then run live Railway deployment verification.
- [ ] Resolve common Istanbul place names to coordinates.
- [ ] Add source-health and freshness diagnostics for operators.
- [ ] Evaluate deeper GTFS route/trip support for transit v2.

### Out of Scope

- Full route planning — GTFS routing and realtime arrival logic are deferred to later phases.
- Normalizing all IBB datasets — too broad for a reliable MVP.
- Water outages, disaster/earthquake alerts, and high-stakes warnings — require extra validation and responsibility boundaries.
- User accounts, OAuth, push notifications, and map UI — not needed for the first MCP release.
- PostGIS/vector tiles — SQLite WAL/FTS5/RTree is enough for the MVP.

## Context

v1.0 shipped a Python/FastMCP remote MCP server with 2,067 lines of Python across app and test code. The implementation includes CKAN catalog tools, normalized geo storage, ISPark parking, Istanbul traffic, Metro station, air-quality, and narrow IETT line/stop tools. Unit tests and live source smoke checks passed; Docker runtime was verified. Live Railway deployment remains an operator task because local Railway auth returned `invalid_grant` and no project is currently linked.

The agreed stack is Python 3.11+, FastMCP/Python MCP SDK, `httpx`, `zeep` for IETT SOAP only, SQLite WAL with FTS5 and RTree, `pydantic`, `pytest`, and Railway. `ctx7` documentation lookup confirmed the official Python MCP SDK exposes FastMCP tools/resources/prompts and Streamable HTTP with stateless JSON-friendly deployment patterns.

## Constraints

- **Tech stack**: Python/FastMCP first — strongest fit for SOAP, CSV, GTFS, and geo processing.
- **Deployment**: Railway — target platform; run `railway login` and `railway link` before live deploy workflows.
- **Reliability**: Every tool must return source, freshness, limits, and warnings when relevant.
- **Safety**: Read-only MCP tools; no unrestricted SQL; validate radius, bbox, limits, and user inputs.
- **Testing**: Unit tests should use fixtures rather than live IBB endpoints.
- **Secrets**: Agents may inspect local `.env` when needed, but secrets must never be printed or committed.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Build MVP as "City Data Core" | Keeps first release useful without drowning in 550 datasets | ✓ Good |
| Use Python + FastMCP | Official SDK supports tools/resources/prompts and Streamable HTTP; Python fits data processing | ✓ Good |
| Use Railway for deploy | Matches project goal of one remote URL, but local auth must be refreshed | ⚠ Revisit auth |
| Use SQLite for MVP | WAL, FTS5, and RTree cover the first data volume without PostGIS overhead | ✓ Good |
| Treat ISbike as optional | Live service returned empty data during validation | ✓ Good |
| Keep IETT SOAP narrow | SOAP risk is real but limited to IETT; avoid broad realtime transit scope | ✓ Good |

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
*Last updated: 2026-06-12 after v1.0 milestone*
