# Istanbul MCP

Remote MCP server for Istanbul open city data. The MVP focuses on a small, reliable city-data core: IBB catalog search, nearby city services, traffic, parking, metro, air quality, and narrow IETT line/stop access.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
python -m app.main
```

The local server exposes:

- `GET /healthz`
- `GET /readyz`
- `GET /status`
- `POST /mcp/` (canonical Streamable HTTP MCP endpoint; `/mcp` redirects to `/mcp/`)

Quick remote smoke test:

```bash
curl -fsS https://istanbulmcp-production.up.railway.app/healthz
curl -fsS https://istanbulmcp-production.up.railway.app/status
curl -i https://istanbulmcp-production.up.railway.app/mcp
```

## Tools

See `docs/tool-reference.md` for the current MCP tool surface.

## Deployment

Railway deployment notes live in `docs/deploy-railway.md`.

## Planning

Project context and roadmap live under `.planning/`.
