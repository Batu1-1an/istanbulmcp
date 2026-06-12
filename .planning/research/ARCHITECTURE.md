# Architecture Research

## Component Boundaries

```txt
MCP Client
  -> FastMCP server (/mcp)
  -> Tool layer
  -> Domain services
  -> Connectors
  -> SQLite cache
  -> IBB/Metro/ISPark/IETT sources
```

## Planned Modules

- `app/mcp/server.py`: FastMCP app, tools, resources, prompts.
- `app/core/settings.py`: environment and deployment configuration.
- `app/core/envelope.py`: standard source/freshness response format.
- `app/connectors/ckan.py`: CKAN package/resource/DataStore access.
- `app/connectors/ispark.py`, `traffic.py`, `metro.py`, `air_quality.py`: REST/XML/JSON sources.
- `app/connectors/iett.py`: SOAP adapter using `zeep`.
- `app/storage/`: SQLite migrations, repositories, FTS and RTree helpers.
- `app/services/`: catalog, geo, city services, transit, freshness.
- `tests/fixtures/`: deterministic API and SOAP samples.

## Data Flow

Tools validate input, call a domain service, fetch live data or cache, normalize to canonical models, calculate freshness, and return the standard envelope. Source failures should return stale cache when available or structured failure with a clear warning.

## Build Order

1. Server skeleton, settings, envelope, storage base.
2. CKAN catalog scanner and metadata tools.
3. Geo feature model and city-service connectors.
4. IETT SOAP adapter and release hardening.
