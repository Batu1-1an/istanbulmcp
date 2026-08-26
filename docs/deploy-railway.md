# Railway Deployment

The project is designed for Railway using the included `Dockerfile` and `.railway/railway.ts` Infrastructure as Code file. The service remains a single read-only web service; this feature adds no Railway volume, backup, replica increase, or new service.

## Plan-only verification

The IaC file uses the pinned Railway TypeScript SDK declared in the root `package.json`. Install it once before running the Railway plan commands:

```bash
npm install
```

```bash
railway status
railway config pull
railway config plan --detailed-exit-code
```

`railway config plan` is the normal verification command. It does not change Railway. Exit code `0` means no diff; a non-zero detailed-plan result means a diff is available for review. For the 2026-08-25 local verification, `railway status` plus the plan completed in 3.67 seconds and reported two expected configuration changes copied from the retired `railway.json`: Dockerfile builder and healthcheck/restart settings. It reported no service, replica, volume, or backup addition/drift. `railway config apply` was not run.

The imported `.railway/railway.ts` preserves the linked `istanbulmcp` service, the healthcheck at `/healthz` with a 30-second timeout, the existing single-region replica intent, and secret values through `preserve()`. The old `railway.json` was removed after those settings were represented in IaC.

Rollback boundary: until an explicitly approved `railway config apply` or deploy is run, Railway production has not changed and there is no production rollback to perform. To roll back this local migration, restore the previous tracked files or revert the local IaC commit; do not apply a rollback command by default.

## Production deploy — 2026-08-25

After commit `46ebfdf` was fast-forward merged to `main`, the application was deployed with:

```bash
railway up --detach --yes
```

Deployment `028bdb05-7249-40f5-a0c1-cba0a949cbe5` completed with `SUCCESS`. Post-deploy smoke checks passed:

- `/healthz`: `ok=true`
- `/readyz`: `ready=true`, SQLite WAL active, schema version `1`
- `/status`: `ok=true`, `tool_count=23`
- MCP `tools/list`: `23` tools, including `istanbul_transit_disruptions` and `istanbul_planned_departures`

The IaC changes remain plan-only; `railway config apply` was not run.

The historical production smoke above predates the local US5 multi-mode increment and therefore records the then-current `23`-tool deployment. The approved follow-up deployment below contains the current `24`-tool build.

## Production deploy — unified transport disruptions — 2026-08-25

The current working tree was deployed with `railway up --detach --yes --message "Deploy unified transport disruptions"`.

- Deployment: `7556e1bf-88a5-4c54-840e-d333e9c3efef`
- Status: `SUCCESS`, one running SFO instance
- `/healthz`: `ok=true`
- `/readyz`: `ready=true`, SQLite WAL active, schema version `1`
- `/status`: `ok=true`, `tool_count=24`, `istanbul_transport_disruptions` registered, disruption cache TTL `120`
- MCP smoke: unified all-source call `ok=true` with 5 records; IETT and Metro sources `checked`; Şehir Hatları and Marmaray `unavailable` because their current HTML responses do not contain the recognized static page markers.
- Existing `istanbul_transit_disruptions`: `ok=true`, 5 records.
- Metro mode: `ok=true`, fresh empty result from a checked source.
- Ferry and suburban-rail mode calls: structured `ok=false`, `freshness=broken`, source-specific warnings; no data was fabricated.

The live HTML limitation is intentionally surfaced as source unavailability rather than treated as an empty “no disruption” result. No Railway volume, backup, replica increase, or new service was added.

## Production source compatibility follow-up — 2026-08-25

The live source check found that Şehir Hatları now serves a WebForms `notice-detail-text-content` block with a date-only value and the explicit message `İptal seferimiz bulunmamaktadır.`. The connector now recognizes that official shape, returns a checked empty result for that message, and preserves a global active notice without inventing a line code or time.

At the time of this historical compatibility check, the Marmaray page served an Angular shell (`<app-root>`) without rendered notices and the first API probe returned HTTP `401 Unauthorized`; the connector then kept Marmaray as `coverage_status=unavailable` rather than treating the shell as an empty result.

That historical compatibility build was deployed as `ca148d57-2ac8-40e3-9fac-211779745148`, followed by warning-format deployment `659e36f9-90c0-49c7-bb85-3ccc4631e6be`; current source-access results are recorded below.

## Production source access resolution — 2026-08-25

The remaining source-access implementation is deployed:

- `MARMARAY_API_BASIC_TOKEN` is stored as a Railway secret. When the official Marmaray page is an Angular shell, the connector calls the official frontend API, validates the list shape, and returns source title/date fields only. The production `suburban_rail` MCP call is `ok=true`, `coverage_status=checked`, and currently has `data_count=0`.
- The existing Cloudflare Worker now has authenticated fixed-target `GET /transport/sehir-hatlari`, bounded HTML handling, a separate `TRANSPORT_RELAY_TOKEN`, and an official announcement-index fallback. It accepts no user-supplied target URL.
- The Railway service was moved to the single allowed Hobby-plan region `EU West` and deployed as `4ff48882-ecfa-4f66-bcd4-c977fcd880cd`. `/healthz`, `/readyz`, and `/status` passed; `/status` reports both source fallback flags enabled and `tool_count=24`.
- Verification: Python `182 passed, 16 skipped`; Worker `25 passed`; Worker typecheck and dry-run passed. Real MCP calls confirmed Marmaray `checked` and all-source partial success.

Şehir Hatları is still an external access blocker: the official canonical page returns HTTP `403` through the relay and through the EU Railway direct fallback. The service therefore correctly returns `coverage_status=unavailable` and never invents an empty ferry result. Completing this last production item requires an approved upstream allowlist or authorized Turkish egress path (tracked as T063); no third-party proxy or fabricated data was added.

## Local transit-source implementation follow-up — 2026-08-26

The local implementation now includes Metro İstanbul's separate planned-notice source and the
additive `istanbul_ferry_schedules(route, limit?)` tool. The ferry schedule connector reads only
the official Şehir Hatları `/tr/seferler` index and the selected canonical route-detail HTML;
its `published_timetable` coverage is static and does not represent live departures, delays, or
ETA. The local inventory is now 29 tools after this registration.

This follow-up was initially validated offline and with read-only source smoke only; Docker and
Railway deploy/apply were intentionally skipped at that stage. The production deployment is
recorded below.

## Production deploy — 2026-08-26

The ferry timetable and Metro planned-notice implementation was deployed with:

```bash
railway up --detach --yes --message "Deploy ferry schedules and Metro planned notices"
```

- Deployment: `3dac1bf0-26db-40f7-a0f1-0e51582d0ac1`
- Status: `SUCCESS`, one running production instance
- `/healthz`: `ok=true`
- `/readyz`: `ready=true`
- `/status`: `tool_count=29`, `istanbul_ferry_schedules` registered
- MCP smoke: Metro `operator=metro_istanbul,line=M7` returned live status plus official planned notice (`2` records); ferry schedule and ferry disruption calls reached the official source but received HTTP `403`, so both remain explicitly `unavailable` with source-scoped warnings.

Set environment variables from `.env.example` as needed. At minimum, Railway should provide `PORT`; the app defaults to `.data/istanbul_mcp.sqlite3` for SQLite. Do not add a volume or backup solely to support this feature.

## ISKI Relay

Railway egress can time out against ISKI hosts. Deploy the fixed-route Cloudflare Worker before configuring the Railway service:

```bash
npm install --prefix workers/iski-relay
npm test --prefix workers/iski-relay
npm run typecheck --prefix workers/iski-relay
npx wrangler secret put RELAY_TOKEN --config workers/iski-relay/wrangler.jsonc
npx wrangler deploy --config workers/iski-relay/wrangler.jsonc
```

Set these Railway variables after deployment:

- `ISKI_RELAY_BASE_URL`: deployed Worker base URL, without a trailing slash.
- `ISKI_RELAY_TOKEN`: the same secret stored as the Worker's `RELAY_TOKEN`.
- `ISKI_RELAY_TIMEOUT_SECONDS`: defaults to `15`; allows a cold relay cache to complete without increasing direct ISKI timeouts.
- `ISKI_FAULTS_SNAPSHOT_CAPTURED_AT` and `ISKI_DAMS_SNAPSHOT_CAPTURED_AT`: timezone-aware ISO 8601 capture times when legacy bare snapshots are configured.
- `ISKI_FAULTS_SNAPSHOT_MAX_AGE_SECONDS`: defaults to `21600` (6 hours).
- `ISKI_DAMS_SNAPSHOT_MAX_AGE_SECONDS`: defaults to `86400` (24 hours).

The Worker exposes unauthenticated `GET /healthz` and authenticated `GET /iski/faults` and `GET /iski/dams`. It does not accept arbitrary target URLs. The tracked Wrangler configuration binds the `CACHE` Workers KV namespace. Successful payloads are retained for 24 hours, considered fresh for 5 minutes, returned immediately when stale, and refreshed in the background. Stale cache age is propagated to MCP freshness metadata. Error responses are never cached, and KV read/write failures bypass the cache. Do not place relay or ISKI bearer tokens in tracked files or command arguments.

After a new cache namespace or cache-key version is deployed, warm both routes from a network that can reach the official sources. The resulting KV values are shared across Cloudflare colos, including the colo reached by Railway.

Abuse and cache guard variables can be tuned per Railway environment:

- `MCP_MAX_BODY_BYTES`
- `MCP_RATE_LIMIT_CAPACITY`
- `MCP_RATE_LIMIT_REFILL_PER_SECOND`
- `MCP_RATE_LIMIT_MAX_CLIENTS`
- `MCP_MAX_CONCURRENT_REQUESTS`
- `SOURCE_CACHE_MAX_ENTRIES`
- `AIR_QUALITY_RATE_CAPACITY`
- `AIR_QUALITY_RATE_REFILL_PER_SECOND`
- `AIR_QUALITY_RATE_MAX_WAIT_SECONDS`

## Health Checks

- `/healthz` confirms the process is up.
- `/readyz` initializes/checks SQLite and returns readiness details without exposing the local database path.
- `/status` returns version, tool inventory, source group, runtime limits, and redacted cache metadata.
- `/mcp/` is the canonical Streamable HTTP MCP endpoint.
- `/mcp` returns a relative `308` redirect to `/mcp/`.

## Production Smoke Checks

Replace `BASE_URL` if Railway assigns a new domain.

```bash
BASE_URL=https://istanbulmcp-production.up.railway.app

curl -fsS "$BASE_URL/healthz"
curl -fsS "$BASE_URL/readyz"
curl -fsS "$BASE_URL/status"
curl -i "$BASE_URL/mcp"

curl -fsS "$BASE_URL/mcp/" \
  -H 'accept: application/json, text/event-stream' \
  -H 'content-type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"smoke","version":"1.0"}}}'

curl -i "$BASE_URL/mcp/" \
  -H 'accept: application/json, text/event-stream' \
  -H 'content-type: application/json' \
  --data '{"jsonrpc":"2.0","id":null,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"smoke","version":"1.0"}}}'
```

The final command should return HTTP `400` with JSON-RPC error code `-32600`.

## Live Regression

Run the opt-in live regression suite after production deploys:

```bash
RUN_LIVE_MCP_TESTS=1 pytest tests/live
python scripts/live_mcp_uat.py --base-url "$BASE_URL/mcp/"
```

The script writes timestamped JSON and Markdown reports under `.planning/reports/`.
