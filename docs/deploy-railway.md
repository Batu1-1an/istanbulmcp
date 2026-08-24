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

`railway config plan` is the normal verification command. It does not change Railway. Exit code `0` means no diff; exit code `2` means a diff is available for review. For the 2026-08-25 local verification, `railway status` plus the plan completed in 3.67 seconds and reported two expected configuration changes copied from the retired `railway.json`: Dockerfile builder and healthcheck/restart settings. It reported no service, replica, volume, or backup addition/drift. No `railway config apply` or `railway up` was run.

The imported `.railway/railway.ts` preserves the linked `istanbulmcp` service, the healthcheck at `/healthz` with a 30-second timeout, the existing single-region replica intent, and secret values through `preserve()`. The old `railway.json` was removed after those settings were represented in IaC.

Rollback boundary: until an explicitly approved `railway config apply` or deploy is run, Railway production has not changed and there is no production rollback to perform. To roll back this local migration, restore the previous tracked files or revert the local IaC commit; do not apply a rollback command by default.

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
