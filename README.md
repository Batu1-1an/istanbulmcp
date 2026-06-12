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
- `POST /mcp`

## Planning

Project context and roadmap live under `.planning/`.
