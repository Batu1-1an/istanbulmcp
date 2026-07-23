# ISKI Live Relay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve current ISKI outages and dam data through an authenticated Cloudflare relay, with truthful provenance, bounded snapshots, and safe diagnostics.

**Architecture:** A fixed-route Cloudflare Worker reads official e-Devlet tables with public ISKI JSON fallbacks and shares successful payloads through Workers KV. The Python connector tries relay, direct source, official API where supported, then a timestamped snapshot; the service builds freshness and source metadata from the successful source mode.

**Tech Stack:** Cloudflare Workers, Wrangler, TypeScript, Vitest, Python 3.11+, httpx, pytest, Railway.

## Global Constraints

- Never accept an arbitrary upstream URL in the Worker.
- Never log relay tokens, ISKI bearer tokens, authorization headers, or response bodies.
- Reject expired or undated snapshots instead of presenting them as active data.
- Preserve existing MCP tool names and normalized row schemas.
- Do not commit or expose secrets.
- Do not create git commits unless the user explicitly requests them.

---

### Task 1: Authenticated Cloudflare Relay

**Files:**
- Create: `workers/iski-relay/package.json`
- Create: `workers/iski-relay/wrangler.jsonc`
- Create: `workers/iski-relay/src/index.ts`
- Create: `workers/iski-relay/test/index.test.ts`

**Interfaces:**
- Consumes: Worker secret `RELAY_TOKEN`.
- Produces: authenticated `GET /iski/faults`, `GET /iski/dams`, and unauthenticated `GET /healthz`.

- [ ] Write Worker tests asserting `401` without `Authorization: Bearer <token>`, `404` for unknown routes, `405` for non-GET methods, successful fixed upstream proxying, `502` for upstream errors or oversized payloads, and `504` for timeout aborts.
- [ ] Run `npm test --prefix workers/iski-relay` and confirm tests fail before implementation.
- [ ] Implement a route map containing only:

```ts
const UPSTREAMS = {
  "/iski/faults": "https://harita.iski.gov.tr/data/mahallelerKesinti.geojson",
  "/iski/dams": "https://harita.iski.gov.tr/data/baraj.json",
} as const;
```

- [ ] Implement constant-time bearer comparison, a 10-second `AbortSignal.timeout`, a 2 MiB response limit, JSON parsing validation, and explicit `401/404/405/502/504` responses.
- [ ] Configure Wrangler with `main = "src/index.ts"`, `compatibility_date = "2026-07-23"`, and observability enabled; keep `RELAY_TOKEN` out of the file.
- [ ] Run Worker tests and `npx wrangler deploy --dry-run --config workers/iski-relay/wrangler.jsonc`.

### Task 2: Relay and Snapshot Configuration

**Files:**
- Modify: `app/core/settings.py`
- Modify: `app/core/status.py`
- Modify: `.env.example`
- Test: `tests/test_main.py`

**Interfaces:**
- Produces settings `iski_relay_base_url`, `iski_relay_token`, `iski_faults_snapshot_captured_at`, `iski_dams_snapshot_captured_at`, `iski_faults_snapshot_max_age_seconds`, and `iski_dams_snapshot_max_age_seconds`.

- [ ] Add failing settings tests for relay variables, timestamp variables, and default maximum ages of 21,600 seconds for faults and 86,400 seconds for dams.
- [ ] Run `pytest tests/test_main.py -q` and confirm the new tests fail.
- [ ] Add typed settings fields and environment loading without exposing secret values through `/status`.
- [ ] Update `.env.example` with empty relay/token/timestamp values and documented maximum ages.
- [ ] Update `/status` to expose only relay enabled/disabled state and snapshot age limits.
- [ ] Run `pytest tests/test_main.py -q` and confirm it passes.

### Task 3: Connector Fallback Chain and Safe Diagnostics

**Files:**
- Modify: `app/connectors/iski.py`
- Test: `tests/test_connector_resilience.py`

**Interfaces:**
- `IskiClient.active_faults() -> dict`
- `IskiClient.dams() -> list[dict]`
- Source metadata properties: `last_faults_source`, `last_dams_source`, `last_faults_source_updated_at`, `last_dams_source_updated_at`.

- [ ] Add failing tests proving relay precedence, direct fallback after relay failure, official dam API fallback, timestamped snapshot acceptance, expired snapshot rejection, undated snapshot rejection, and diagnostic logs containing only source name, elapsed milliseconds, and exception class.
- [ ] Run the targeted connector tests and confirm failures.
- [ ] Add relay requests using `Authorization: Bearer <relay token>` and fixed relay paths.
- [ ] Refactor source attempts into a small internal function that records safe structured events on `istanbul_mcp.connectors.iski` and preserves the last exception.
- [ ] Parse snapshots in either `{ "captured_at": "...", "payload": ... }` form or legacy payload plus configured capture timestamp; compare aware UTC datetimes against the configured maximum age.
- [ ] Set accurate source modes: `relay_geojson`, `relay_json`, `live_geojson`, `live_json`, `official_api`, and `snapshot`.
- [ ] Run `pytest tests/test_connector_resilience.py -q` and confirm it passes.

### Task 4: Truthful MCP Provenance

**Files:**
- Modify: `app/services/iski.py`
- Test: `tests/test_iski_service.py`

**Interfaces:**
- Consumes connector source modes and source timestamps.
- Produces dynamic `Source`, `Freshness`, `limits`, and `warnings` fields.

- [ ] Add failing service tests for relay source URL/name, direct source metadata, snapshot `source_updated_at`, expired fallback failure, and removal of the false `source=live ISKI GeoJSON` limit during snapshot mode.
- [ ] Run `pytest tests/test_iski_service.py -q` and confirm failures.
- [ ] Pass all relay and snapshot settings into `IskiClient`.
- [ ] Store source mode and source timestamp in `SourceLoadResult.metadata` so cache hits preserve provenance.
- [ ] Build source objects, source limits, freshness, and warnings from cached metadata rather than mutable client state.
- [ ] Ensure snapshots report `status=stale`, timestamped `source_updated_at`, and `source=configured ISKI snapshot`; live relay responses report `status=fresh` and the relay source.
- [ ] Run `pytest tests/test_iski_service.py -q` and confirm it passes.

### Task 5: Documentation and Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/deploy-railway.md`

**Interfaces:**
- Documents Worker deployment, secret setup, Railway variables, and fallback behavior.

- [ ] Document `npx wrangler secret put RELAY_TOKEN --config workers/iski-relay/wrangler.jsonc`, Worker deployment, and the matching Railway variables.
- [ ] Replace claims that stale snapshots are an acceptable indefinite fallback with the bounded-age behavior.
- [ ] Run `pytest -q` and require all tests to pass.
- [ ] Run `npm test --prefix workers/iski-relay` and require all Worker tests to pass.
- [ ] Run the Worker dry-run deployment and inspect generated bundle size/errors.

### Task 6: Deploy and Production UAT

**Files:**
- No tracked file changes expected.

**Interfaces:**
- Configures Cloudflare secret `RELAY_TOKEN` and Railway variables `ISKI_RELAY_BASE_URL`, `ISKI_RELAY_TOKEN`, snapshot timestamps, and maximum ages.

- [ ] Generate a cryptographically random relay token without printing it.
- [ ] Store it with Wrangler and deploy `workers/iski-relay`.
- [ ] Verify `/healthz`, authenticated faults, authenticated dams, and unauthorized rejection.
- [ ] Set matching Railway relay variables without printing secret values.
- [ ] Refresh both Railway snapshots from current official payloads using timestamped envelopes.
- [ ] Deploy the Railway service and wait for `/readyz`.
- [ ] Invoke `istanbul_iski_active_faults` and `istanbul_iski_dam_occupancy`; require current source data, `freshness.status=fresh`, relay provenance, and response latency below the old 5/10-second timeout paths.
- [ ] Inspect Railway logs and confirm no credentials or response bodies appear.
