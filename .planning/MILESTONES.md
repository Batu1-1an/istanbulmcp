# Milestones

## v1.0 MVP (Shipped: 2026-06-12)

**Phases completed:** 4 phases, 4 plans
**Audit:** Passed — 21/21 requirements satisfied
**Tag:** v1.0

**Key accomplishments:**

- Shipped a FastMCP remote server mounted at `/mcp` with `/healthz` and `/readyz`.
- Added consistent source/freshness/limits/warnings envelopes and guarded input validation.
- Added CKAN catalog search, dataset metadata, resource schema, and guarded DataStore query tools.
- Added normalized geo search plus ISPark, traffic, Metro, and air-quality city-service tools.
- Added narrow IETT line and stops tools with structured SOAP error handling.
- Added README, tool reference, Railway deploy notes, Dockerfile, and `railway.json`.

**Verification:**

- `.venv/bin/pytest` — 30 passed, 1 warning.
- Live CKAN, ISPark, traffic, Metro, air-quality, and IETT smoke checks passed.
- Docker build and container `/healthz` + `/readyz` smoke checks passed.
- Railway production deployment passed `/healthz`, `/readyz`, and MCP initialize checks.

**Production URL:**

- `https://istanbulmcp-production.up.railway.app`

---
