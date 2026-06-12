# Phase 3 Plan: Geo & City Services

## Goal

Deliver the main user-facing Istanbul city-data demo path.

## Tasks

- [x] Live-check city-service endpoint shapes.
- [x] Add geo math helpers and SQLite RTree repository.
- [x] Add ISPark, Metro, air-quality, and traffic connectors.
- [x] Add city service methods for nearby, bbox, parking, metro, air quality, and traffic.
- [x] Register city MCP tools.
- [x] Add mocked unit tests for geo repository and city service behavior.
- [x] Run tests and live smoke checks for parking, metro, air quality, and traffic.

## Verification

- `.venv/bin/pytest`
- Live `istanbul_parking_nearby` near Kadikoy/Moda.
- Live `istanbul_traffic_status`.

## Risks

- Air-quality readings may be null or stale; return warnings instead of advice.
- Traffic endpoint content type may be misleading; parse JSON first, XML fallback second.
