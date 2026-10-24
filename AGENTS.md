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

Never remove or rename a published MCP tool. Clients cache `tools/list`, so keep the old name callable as a hidden alias, add every newly published name to `PUBLISHED_TOOL_NAMES` in `tests/test_tool_compatibility.py`, and bump the version in `pyproject.toml` and `server.json`.

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

<!-- OPENWIKI:START -->

## OpenWiki

A generated `openwiki/` evidence index may be available locally. The wiki and its publishing workflow are gitignored; they are optional just-in-time context, not required startup reading.

- Do not enumerate, preload, or search wikis at task start. Use retrieval when the user asks for it, when unfamiliar architecture or dependency behavior materially affects the task, or when source inspection leaves an important uncertainty. Stop once the question is grounded.
- When those conditions apply and OpenWiki retrieval tools are available, use `openwiki_search` for just-in-time context and `openwiki_read` for the relevant complete sections. If search returns `workspace_required`, ask which listed workspace to use and retry with its ID.
- Use `openwiki_list_workspaces` or `openwiki_list_wikis` when workspace membership itself needs to be discovered.
- If the retrieval tools are unavailable and a local wiki exists, read `openwiki/quickstart.md` and follow its links to the relevant pages. If no local wiki is present, inspect source code and versioned docs directly.
- Treat source code and tests as authoritative. A brief's unknowns and review items are verification gaps, not automatic requirements.
- Prefer the narrowest quiet validation that proves the changed behavior. Preserve complete failure output.

OpenWiki output and its publishing workflow stay local rather than running as repository CI. Do not hand-edit generated OpenWiki pages unless explicitly asked; update source code/docs and regenerate the local wiki when needed.

<!-- OPENWIKI:END -->
