# Istanbul MCP

Istanbul MCP is a remote Model Context Protocol server for Istanbul open city data. It lets AI assistants, IDE agents, and CLI tools answer practical Istanbul questions with live or cached source data, freshness metadata, limits, warnings, and map links where available.

Public endpoint:

```text
https://istanbulmcp-production.up.railway.app/mcp/
```

## What It Can Do

- Search Istanbul Metropolitan Municipality open datasets and inspect dataset/resource schemas.
- Query selected CKAN DataStore resources with guarded filters and limits.
- Return citywide traffic index data.
- Find nearby parking lots, show capacity/empty capacity, open status, and Google Maps links.
- List district-wide ISPark parking records without inventing fake center distances.
- Find nearby Metro Istanbul stations, public transport stops, WiFi points, and air quality stations.
- Summarize mobility near known places such as `Kadıköy Rıhtım`, `Taksim`, and `Levent`.
- Return IETT line information and ordered stops for a line code.
- Return district-level library address, phone, hours, and Google Maps search links.
- Build neighborhood profiles from social assistance, building stock, and earthquake scenario open data.

Coordinate results include `maps_url`. Address-only records, such as libraries, can include `maps_search_url` and `location_precision=address_search` so users get a useful map search link without fake coordinates.

## Example Questions

Try these from any MCP-compatible client:

```text
Beşiktaş'ta hangi kütüphaneler var?
Başakşehir'de hangi otoparklar var, doluluk oranı nedir?
Kadıköy Rıhtım çevresinde ulaşım seçenekleri neler?
34A hattının durakları neler?
Levent yakınında metro istasyonu var mı?
Kadıköy'de hava kalitesi istasyonları neler?
Trafik verisiyle ilgili hangi datasetler var?
Kadıköy Caferağa mahalle profili nedir?
```

## MCP Tools

The server exposes read-only tools:

```text
istanbul_health
istanbul_search_datasets
istanbul_get_dataset
istanbul_get_resource_schema
istanbul_query_resource
istanbul_nearby
istanbul_bbox_search
istanbul_parking_nearby
istanbul_parking_by_district
istanbul_metro_stations_nearby
istanbul_air_quality_nearby
istanbul_traffic_status
istanbul_mobility_nearby
istanbul_city_services_nearby
istanbul_neighborhood_profile
istanbul_transit_line_info
istanbul_stops_for_line
```

See [docs/tool-reference.md](docs/tool-reference.md) for parameters, behavior, and limitations.

## Add To Codex CLI

Codex supports Streamable HTTP MCP servers. Add Istanbul MCP with:

```bash
codex mcp add istanbul --url https://istanbulmcp-production.up.railway.app/mcp/
codex mcp list
```

Equivalent manual config in `~/.codex/config.toml`:

```toml
[mcp_servers.istanbul]
url = "https://istanbulmcp-production.up.railway.app/mcp/"
```

Then open a new Codex session and ask an Istanbul question, for example:

```text
Başakşehir'de hangi otoparklar var, doluluk oranı nedir?
```

## Add To Claude Code

Claude Code supports remote HTTP MCP servers. Add Istanbul MCP with:

```bash
claude mcp add --transport http istanbul https://istanbulmcp-production.up.railway.app/mcp/
claude mcp list
```

Equivalent JSON server definition for Claude tools that accept MCP config:

```json
{
  "mcpServers": {
    "istanbul": {
      "type": "http",
      "url": "https://istanbulmcp-production.up.railway.app/mcp/"
    }
  }
}
```

Then start a new Claude Code session and ask:

```text
Beşiktaş'ta hangi kütüphaneler var?
```

## Add To Claude Desktop

Claude Desktop supports remote MCP through custom connectors. In Claude Desktop:

1. Open **Customize > Connectors**.
2. Click **+** and choose **Add custom connector**.
3. Use `Istanbul MCP` as the name.
4. Use this URL:

```text
https://istanbulmcp-production.up.railway.app/mcp/
```

If your Claude Desktop setup uses the local MCP config file instead, bridge the remote endpoint through `mcp-remote` in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "istanbul": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://istanbulmcp-production.up.railway.app/mcp/"
      ]
    }
  }
}
```

Restart Claude Desktop after editing the config.

## Add To Cursor

Cursor supports remote MCP servers in `~/.cursor/mcp.json` or through **Cursor Settings > MCP**.

```json
{
  "mcpServers": {
    "istanbul": {
      "url": "https://istanbulmcp-production.up.railway.app/mcp/"
    }
  }
}
```

After saving, refresh MCP servers in Cursor settings or restart Cursor.

## Add To OpenCode

OpenCode supports remote MCP servers in `opencode.json`.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "istanbul": {
      "type": "remote",
      "url": "https://istanbulmcp-production.up.railway.app/mcp/",
      "enabled": true
    }
  }
}
```

After saving the config, restart OpenCode or start a new session, then run:

```bash
opencode mcp list
```

## Add To Windsurf

Windsurf Cascade supports remote HTTP MCP servers in `~/.codeium/windsurf/mcp_config.json`.

```json
{
  "mcpServers": {
    "istanbul": {
      "serverUrl": "https://istanbulmcp-production.up.railway.app/mcp/"
    }
  }
}
```

You can also open Windsurf's MCP tools/settings screen, choose raw config, paste the same entry, then refresh MCP servers.

## Generic MCP Client Config

For other MCP-compatible tools, add Istanbul MCP as a remote or Streamable HTTP server:

```json
{
  "mcpServers": {
    "istanbul": {
      "url": "https://istanbulmcp-production.up.railway.app/mcp/"
    }
  }
}
```

Some clients use a different top-level key or require `"type": "remote"` / `"transport": "http"`. Keep the endpoint exactly as shown, including the trailing `/mcp/`.

## HTTP Health Checks

Quick service checks:

```bash
curl -fsS https://istanbulmcp-production.up.railway.app/healthz
curl -fsS https://istanbulmcp-production.up.railway.app/status
curl -i https://istanbulmcp-production.up.railway.app/mcp
```

`/mcp` redirects to `/mcp/`; MCP clients should use `/mcp/` directly.

## Response Model

Tools return a standard envelope with:

- `ok`
- `summary`
- `data`
- `freshness`
- `sources`
- `limits`
- `warnings`
- `next_queries` where useful

The server is read-only. It does not book parking, alter public data, provide emergency advice, or invent unavailable source fields.

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
- `POST /mcp/`

Opt-in live MCP regression:

```bash
RUN_LIVE_MCP_TESTS=1 pytest tests/live
python scripts/live_mcp_uat.py
```

## Configuration

Key upstream cache TTLs:

- `CKAN_CATALOG_CACHE_TTL_SECONDS`
- `CKAN_RESOURCE_CACHE_TTL_SECONDS`
- `IETT_LINE_CACHE_TTL_SECONDS`
- `IETT_STOPS_CACHE_TTL_SECONDS`
- `SOURCE_CACHE_MAX_ENTRIES`

Public MCP guard limits:

- `MCP_MAX_BODY_BYTES`
- `MCP_RATE_LIMIT_CAPACITY`
- `MCP_RATE_LIMIT_REFILL_PER_SECOND`
- `MCP_RATE_LIMIT_MAX_CLIENTS`
- `MCP_MAX_CONCURRENT_REQUESTS`

## Deployment

The production service runs on Railway. Deployment notes live in [docs/deploy-railway.md](docs/deploy-railway.md).

## Planning

Project context and roadmap live under `.planning/`.
