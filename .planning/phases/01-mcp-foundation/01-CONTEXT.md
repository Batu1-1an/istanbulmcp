# Phase 1: MCP Foundation - Context

**Gathered:** 2026-06-12
**Status:** Ready for planning
**Mode:** Auto-generated for autonomous execution

<domain>
## Phase Boundary

Establish the deployable FastMCP server and shared safety contracts. This phase should not integrate live IBB data yet; it creates the app shell, health/readiness endpoints, response envelope, input validation, SQLite WAL initialization, and tests.
</domain>

<decisions>
## Implementation Decisions

- Use Python 3.11+ package structure under `app/`.
- Use FastMCP mounted at `/mcp` through Starlette.
- Use plain environment parsing first; defer richer settings libraries.
- Use SQLite WAL from the start so later phases can add catalog and geo tables.
- Use fixture/unit tests only; no live IBB endpoint dependency in this phase.
</decisions>

<code_context>
## Existing Code Insights

The repository had no implementation code before this phase. Planning documents define the stack and response requirements.
</code_context>

<specifics>
## Specific Ideas

- Add one simple MCP tool, `istanbul_health`, so MCP clients can list/call a tool immediately.
- Provide `/healthz` for process liveness and `/readyz` for database readiness.
- Keep response envelope reusable for all later city-data tools.
</specifics>

<deferred>
## Deferred Ideas

- CKAN integration moves to Phase 2.
- Geo and city-service connectors move to Phase 3.
- IETT SOAP moves to Phase 4.
</deferred>
