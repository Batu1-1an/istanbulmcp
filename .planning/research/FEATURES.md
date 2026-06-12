# Feature Research

## Table Stakes

- Remote MCP endpoint with health/readiness checks.
- Tool list focused on a small, reliable city-data surface.
- CKAN catalog search and dataset/resource metadata.
- Consistent response envelope with summary, data, freshness, sources, limits, warnings, and next queries.
- SQLite-backed cache and source snapshots.
- Input validation, rate limits, timeouts, and safe result limits.

## Differentiators

- Istanbul-specific geo search over normalized city features.
- Source and freshness badges in every answer.
- Practical demo flow: "Kadikoy/Moda traffic, parking, nearest metro/stop".
- IETT SOAP adapter with stale fallback instead of broad brittle realtime scope.

## Anti-Features

- 550 individual tools for every IBB dataset.
- Full route planner in the MVP.
- Health advice based on air quality readings.
- Disaster/earthquake alerting without a dedicated validation phase.
- Public write operations.

## MVP Service Coverage

| Service | MVP Status | Notes |
|---------|------------|-------|
| CKAN catalog | Required | Search, metadata, schema, guarded query |
| ISPark | Required | REST/JSON, parking and capacity fields available |
| Traffic | Required | REST/XML, fast and high demo value |
| Metro | Required | REST/JSON, strong geo value |
| Air quality | Required with warnings | Station endpoint works; readings may be stale/null |
| IETT line/stops | Required, narrow | SOAP adapter for basic line and stop data |
| ISbike | Optional | Useful if source returns data; not MVP-blocking |
