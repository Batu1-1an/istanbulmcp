# Repository Guidelines

## Project Structure & Module Organization

- Root `*.md`: scope, research, data validation, roadmap, and user-flow analysis.
- Source code: `app/`, following the Python/FastMCP architecture.
- Tests: `tests/`, mirroring app modules.
- Fixtures and small API samples: `tests/fixtures/`. Do not place raw snapshots in the root.

## Technology Stack

- Python 3.11+
- FastMCP / Python MCP SDK with Streamable HTTP
- `httpx` for REST/JSON/XML sources
- `zeep` for IETT SOAP services only
- SQLite WAL with FTS5 and RTree for the MVP
- `pydantic` for validation/models
- `pytest` for tests
- Railway for deploys. Railway CLI is available and authenticated; use it for project/service/deploy workflows.

## Build, Test, and Development Commands

Validate changes with:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
python -m app.main
railway status
railway up
```

Document new commands in `README.md`. Check Railway state before deploying.

## Coding Style & Naming Conventions

Use Python 3.11+. Prefer small modules by data source/domain, for example `app/connectors/ispark.py` and `app/services/freshness.py`.

Use `snake_case` for files, functions, variables, and tool names. MCP tools keep the `istanbul_` prefix, such as `istanbul_traffic_status`.

Every tool result should include source, freshness, limits, and relevant warnings.

## Testing Guidelines

Use `pytest`. Add fixture-based tests for external APIs, especially SOAP/XML parsing and REST normalization. Test names describe behavior:

```txt
test_parking_nearby_returns_sorted_results
test_iett_parser_handles_empty_response
```

Do not rely on live İBB endpoints for unit tests; reserve them for marked integration tests.

## Commit & Pull Request Guidelines

Use concise, imperative commit messages, matching the current history: `Refactor code structure for improved readability and maintainability`.

PRs need a summary, linked issue/planning doc, test results or a note if not run, and screenshots only for UI/rendered docs.

## Security & Configuration Tips

Treat the MCP server as read-only. Validate inputs, enforce radius/result limits, and avoid unrestricted SQL. Agents may inspect local environment files such as `.env` when needed for development or deploy work, with the user's standing permission. Do not print, commit, or expose keys, `.env`, large datasets, or private captures.

## Agent-Specific Instructions

Use current docs before implementing library, SDK, CLI, API, or cloud-service behavior. Prefer `ctx7`:

```bash
npx ctx7@latest library "FastMCP" "<question>"
npx ctx7@latest docs "/org/project" "<question>"
```

If `ctx7` is unavailable, or the topic is not a library/framework/tool/cloud service, use web search when current information matters. Summarize checked sources in notes or PRs.

## GSD Workflow

Project context lives in `.planning/PROJECT.md`; requirements and phases live in `.planning/REQUIREMENTS.md` and `.planning/ROADMAP.md`. Before feature work, prefer GSD entry points so planning state stays current:

```bash
$gsd-discuss-phase 1
$gsd-plan-phase 1
$gsd-execute-phase 1
```

Do not bypass GSD planning for substantial implementation unless the user explicitly asks.
