# ISKI Live Relay Design

## Goal

Return current ISKI outage and dam data even when Railway egress to ISKI hosts times out, while preserving accurate provenance, bounded fallbacks, and safe diagnostics.

## Architecture

A Cloudflare Worker exposes two authenticated, fixed-purpose routes:

- `GET /iski/faults` reads the official e-Devlet outage table and falls back to the public ISKI active-fault GeoJSON.
- `GET /iski/dams` reads the public ISKI dam JSON and falls back to the official e-Devlet dam table when that table is available without CAPTCHA.

The Worker never accepts an arbitrary target URL. It validates a shared bearer token, uses fixed upstream URLs, applies request timeouts, and emits no credentials or response bodies in logs. Successful payloads are shared across Cloudflare colos through Workers KV. Cached payloads use stale-while-revalidate, expose their capture time and stale status to the MCP service, and upstream error responses are never cached. KV failures degrade to direct upstream access instead of failing the request.

The Python connector receives optional relay settings. For faults it tries the relay first, then the direct public GeoJSON, then the bearer-protected official regional-fault API, and finally a configured snapshot. Dams follow the equivalent relay, direct JSON, official API, snapshot chain.

## Source Metadata

Every successful load records a source mode such as `relay_geojson`, `live_geojson`, `official_api`, or `snapshot`. MCP envelopes derive source labels, limits, warnings, and freshness from that mode instead of claiming every result is live GeoJSON.

Connector diagnostics record the source name, elapsed time, and exception class. URLs containing secrets, authorization headers, bearer tokens, and response bodies are never logged.

## Snapshot Safety

Snapshot JSON uses an envelope containing `captured_at` and `payload`. Legacy bare payloads remain parseable only when a separately configured capture timestamp is present. A configurable maximum snapshot age is enforced before serving the data. Expired or undated snapshots are rejected rather than presented as active data.

Snapshot freshness uses `captured_at` as `source_updated_at`. The MCP response remains marked stale and explicitly identifies snapshot fallback.

## Error Behavior

Each source is attempted independently. HTTP and payload failures move to the next configured source. If every source fails, the MCP tool returns the existing source-unavailable envelope. Logs retain one safe diagnostic event per failed source attempt.

The relay returns:

- `401` for missing or invalid relay authorization.
- `404` for unsupported routes.
- `502` for upstream HTTP or payload failures.
- `504` for upstream timeouts.

## Security

- Fixed route-to-upstream mapping prevents SSRF.
- A constant-time comparison protects the relay bearer token.
- Only `GET` is accepted for data routes.
- Responses set JSON content type and disable caching of authorization failures.
- Secrets are configured with Wrangler and Railway environment variables, never committed.
- Request and response size/time limits bound resource use.

## Tests

Worker tests cover authorization, unsupported routes, successful proxying, timeout mapping, upstream errors, and the absence of arbitrary proxy behavior.

Python tests cover relay precedence, fallback order, official fault API normalization, source metadata, safe logging, fresh snapshot acceptance, expired/undated snapshot rejection, and final source-unavailable behavior. Existing connector and service tests remain green.

Production verification calls both relay routes directly with authentication, invokes both MCP tools, checks current dates and source modes, and inspects Railway latency and logs.
