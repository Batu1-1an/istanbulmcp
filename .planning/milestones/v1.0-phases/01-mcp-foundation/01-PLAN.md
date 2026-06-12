# Phase 1 Plan: MCP Foundation

## Goal

Establish the deployable FastMCP server and shared safety contracts.

## Tasks

- [x] Add Python package metadata and development commands.
- [x] Create settings, response envelope, validation, and SQLite storage modules.
- [x] Create FastMCP server with an initial `istanbul_health` tool.
- [x] Mount FastMCP under `/mcp` and expose `/healthz` and `/readyz`.
- [x] Add unit tests for envelope, validation, storage, and health/readiness endpoints.
- [x] Run tests and fix failures.

## Verification

- `python3 -m json.tool .planning/config.json`
- `.venv/bin/pytest`
- Manual smoke check of `/healthz` and `/readyz` through Starlette TestClient.

## Risks

- FastMCP mount path can accidentally become `/mcp/mcp`; set `streamable_http_path="/"` to keep endpoint at `/mcp`.
- SQLite WAL can fail if database directory is missing; create parent directory in storage helper.
