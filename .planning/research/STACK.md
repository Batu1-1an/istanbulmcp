# Stack Research

## Recommendation

Use Python 3.11+ with FastMCP/Python MCP SDK, `httpx`, `zeep`, SQLite, `pydantic`, `pytest`, and Railway.

## Checked Documentation

- `ctx7` resolved the official MCP Python SDK as `/modelcontextprotocol/python-sdk`.
- The fetched docs show `FastMCP`, decorators for tools/resources/prompts, `mcp.run(transport="streamable-http")`, and production-oriented `stateless_http=True, json_response=True`.

## Stack Choices

| Area | Choice | Rationale | Confidence |
|------|--------|-----------|------------|
| Runtime | Python 3.11+ | Best fit for SOAP, CSV, GTFS, and geo processing | High |
| MCP | FastMCP / Python MCP SDK | Current docs support Streamable HTTP directly | High |
| REST/XML | `httpx` | One async client for JSON/XML endpoints | High |
| SOAP | `zeep` | Needed only for IETT SOAP JSON-suffixed methods | Medium |
| Storage | SQLite WAL + FTS5 + RTree | Enough for MVP catalog, search, and geo radius/bbox | High |
| Validation | `pydantic` | Clear input/output contracts for tools and connectors | High |
| Testing | `pytest` + fixtures | External APIs must not be required for unit tests | High |
| Deploy | Railway | Remote HTTPS URL, CLI available, simple service deployment | High |

## Avoid For MVP

- PostGIS — useful later, but unnecessary for the first release.
- Full GTFS routing — valuable later, too much for v0.1.
- Browser/map UI — not required to prove MCP value.
