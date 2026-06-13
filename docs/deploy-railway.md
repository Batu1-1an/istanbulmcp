# Railway Deployment

The project is designed for Railway using the included `Dockerfile` and `railway.json`.

## Commands

```bash
railway status
railway up
```

Set environment variables from `.env.example` as needed. At minimum, Railway should provide `PORT`; the app defaults to `.data/istanbul_mcp.sqlite3` for SQLite.

Abuse and cache guard variables can be tuned per Railway environment:

- `MCP_MAX_BODY_BYTES`
- `MCP_RATE_LIMIT_CAPACITY`
- `MCP_RATE_LIMIT_REFILL_PER_SECOND`
- `MCP_RATE_LIMIT_MAX_CLIENTS`
- `MCP_MAX_CONCURRENT_REQUESTS`
- `SOURCE_CACHE_MAX_ENTRIES`

## Health Checks

- `/healthz` confirms the process is up.
- `/readyz` initializes/checks SQLite and returns readiness details.
- `/status` returns version, tool inventory, source group, and runtime limits.
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
