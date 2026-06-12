# Phase 4 Plan: Transit & Release

## Goal

Add narrow IETT SOAP integration and ship a documented Railway MVP.

## Tasks

- [x] Check Zeep docs and live WSDL behavior.
- [x] Add raw SOAP IETT adapter with JSON/XML result parsing.
- [x] Add transit service for line info and stops-for-line.
- [x] Register transit MCP tools.
- [x] Add connector and service tests.
- [x] Add `.env.example`, Dockerfile, Railway config, deploy notes, and tool reference.
- [x] Run tests, live IETT smoke checks, local server health smoke, and Docker smoke.

## Verification

- `.venv/bin/pytest`
- Live IETT `34A` line and stops check.
- Local server `/healthz` and `/readyz` smoke.

## Risks

- IETT SOAP services may be unavailable during nightly maintenance.
- WSDL parsing is brittle; raw SOAP is used intentionally for MVP reliability.
