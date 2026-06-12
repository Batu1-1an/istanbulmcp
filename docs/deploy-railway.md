# Railway Deployment

The project is designed for Railway using the included `Dockerfile` and `railway.json`.

## Commands

```bash
railway status
railway up
```

Set environment variables from `.env.example` as needed. At minimum, Railway should provide `PORT`; the app defaults to `.data/istanbul_mcp.sqlite3` for SQLite.

## Health Checks

- `/healthz` confirms the process is up.
- `/readyz` initializes/checks SQLite and returns readiness details.
- `/mcp` is the Streamable HTTP MCP endpoint.
