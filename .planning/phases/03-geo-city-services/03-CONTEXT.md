# Phase 3: Geo & City Services - Context

**Gathered:** 2026-06-12
**Status:** Ready for planning
**Mode:** Auto-generated for autonomous execution

<domain>
## Phase Boundary

Deliver normalized geo search and the main city-service demo path: nearby parking, metro stations, air-quality stations/readings, and traffic status. Do not implement IETT SOAP or route planning in this phase.
</domain>

<decisions>
## Implementation Decisions

- Use SQLite `geo_features` plus RTree for radius/bbox prefiltering.
- Use Python haversine distance for final radius sorting.
- Fetch ISPark, Metro, air-quality stations, and traffic live through dedicated connectors.
- Treat traffic as citywide; do not invent road-level incidents.
- Treat missing air-quality AQI values as warnings, not health advice.
</decisions>

<code_context>
## Existing Code Insights

Phase 1 added the FastMCP shell, envelope, validation, and SQLite. Phase 2 added CKAN services and tool patterns. City services should reuse the same envelope and validation style.
</code_context>

<specifics>
## Specific Ideas

- Tools: `istanbul_nearby`, `istanbul_bbox_search`, `istanbul_parking_nearby`, `istanbul_metro_stations_nearby`, `istanbul_air_quality_nearby`, `istanbul_traffic_status`.
- Live endpoint check found traffic body is JSON despite XML content type.
- ISbike remains deferred because validation returned an empty list.
</specifics>

<deferred>
## Deferred Ideas

- Bus stops and IETT data move to Phase 4.
- Place-name resolution is v2.
- Air-quality health recommendations are out of scope.
</deferred>
