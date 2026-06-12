# Phase 4 Summary: Transit & Release

## Completed

- Added raw SOAP IETT adapter with JSON and XML result parsing.
- Added transit service for `istanbul_transit_line_info` and `istanbul_stops_for_line`.
- Registered transit MCP tools.
- Upserted returned IETT stops as `bus_stop` geo features.
- Added connector and service tests.
- Added `.env.example`, `Dockerfile`, `railway.json`, Railway deploy notes, and tool reference.
- Updated README with tool/deploy documentation pointers.

## Verification

```txt
.venv/bin/pytest
29 passed, 1 warning
```

Live IETT smoke check:

```txt
1 IETT line record(s) found for 34A.
38 stop record(s) found for line 34A.
fresh
```

Docker smoke check:

```txt
docker build -t istanbul-mcp:phase4 .
docker run ... istanbul-mcp:phase4
GET /healthz -> 200
GET /readyz -> 200
```

Railway CLI/MCP auth check failed with `invalid_grant` / not authenticated, so live Railway deployment was not executed. Deployment config is present and Docker runtime is verified.

## Requirements Covered

- TRN-01
- TRN-02
- TRN-03
- REL-01
- REL-02
- REL-03
