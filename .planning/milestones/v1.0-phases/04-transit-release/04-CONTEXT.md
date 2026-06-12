# Phase 4: Transit & Release - Context

**Gathered:** 2026-06-12
**Status:** Ready for planning
**Mode:** Auto-generated for autonomous execution

<domain>
## Phase Boundary

Add narrow IETT transit capability and ship release documentation/configuration. This phase owns IETT SOAP adapter, line info, stops-for-line, tests, README/tool docs, `.env.example`, Dockerfile, and Railway notes.
</domain>

<decisions>
## Implementation Decisions

- Keep Zeep as dependency and documented research, but use raw SOAP because the IETT WSDL fails Zeep loading with an `AuthHeader` issue.
- Use `GetHat_json` for basic line information.
- Use `DurakDetay_GYY_wYonAdi` from the `iett/ibb/ibb.asmx` service for stops-for-line.
- Upsert returned stops as `bus_stop` geo features.
- Do not implement route planning or realtime arrivals.
</decisions>

<code_context>
## Existing Code Insights

Phase 1 created server/envelope/storage. Phase 2 created CKAN tools. Phase 3 created city connectors and geo repository. Transit should reuse the same envelope and geo feature model.
</code_context>

<specifics>
## Specific Ideas

- Tools: `istanbul_transit_line_info`, `istanbul_stops_for_line`.
- Release docs: README, tool reference, Railway deploy guide, `.env.example`.
- Include live smoke checks for `34A`.
</specifics>

<deferred>
## Deferred Ideas

- `lines_for_stop`, realtime arrivals, and full routing are v2+.
</deferred>
