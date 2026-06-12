# Phase 2 Plan: Catalog Core

## Goal

Make the IBB open-data catalog searchable and inspectable.

## Tasks

- [x] Verify CKAN API behavior with current documentation.
- [x] Add async CKAN connector for `package_search`, `package_show`, and `datastore_search`.
- [x] Add dataset/resource SQLite tables and FTS5 index.
- [x] Add catalog repository and service layer.
- [x] Register catalog MCP tools.
- [x] Add mocked unit tests for connector and service behavior.
- [x] Run tests and a small live CKAN smoke check.

## Verification

- `.venv/bin/pytest`
- Live `package_search` query for `trafik` with a small result limit.

## Risks

- CKAN format filters vary by portal; keep filter optional and search query primary.
- Some resources are not DataStore-backed; schema/query tools should return structured source errors in later hardening.
