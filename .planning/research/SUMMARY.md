# Research Summary

## Stack

Build the MVP with Python 3.11+, FastMCP/Python MCP SDK, `httpx`, `zeep`, SQLite WAL/FTS5/RTree, `pydantic`, `pytest`, and Railway. `ctx7` confirmed current FastMCP examples for tools/resources/prompts and Streamable HTTP, including stateless JSON-friendly server configuration.

## Table Stakes

- Remote `/mcp` endpoint.
- CKAN catalog search and metadata.
- Consistent source/freshness envelope.
- SQLite-backed cache with FTS and geo search.
- Input validation, limits, timeouts, and fixture-based tests.

## Differentiators

- Istanbul-specific high-value city service tools.
- Practical geo queries over parking, metro, traffic, air quality, and IETT stops.
- Explicit freshness and limitations in every answer.

## Watch Out For

- Do not build a tool per dataset.
- Do not make ISbike or air-quality readings MVP blockers if live data is empty/stale.
- Do not treat IETT SOAP as a broad realtime routing system in v0.1.
- Do not expose unrestricted DataStore SQL.
