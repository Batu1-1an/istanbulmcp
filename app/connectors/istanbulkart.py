from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.connectors.ckan import CkanClient, CkanError
from app.core.rate_limit import SourceRateLimitExceeded


class IstanbulkartError(RuntimeError):
    """Base error for the İstanbulkart CKAN source."""


class IstanbulkartSourceError(IstanbulkartError):
    """The catalog or DataStore endpoint could not be read."""


class IstanbulkartPayloadError(IstanbulkartError):
    """The source returned a malformed CKAN payload."""


class IstanbulkartSchemaError(IstanbulkartPayloadError):
    """The selected annual resource does not expose the supported schema."""


class IstanbulkartPaginationError(IstanbulkartPayloadError):
    """A DataStore page was incomplete or inconsistent with its total."""


SUPPORTED_FIELDS = frozenset(
    {
        "terminal_id",
        "terminal_subtype_definition_desc_cd",
        "town_id",
        "longitude",
        "latitude",
    }
)


@dataclass(frozen=True)
class IstanbulkartPayload:
    rows: tuple[dict[str, Any], ...]
    dataset_id: str
    resource_id: str
    resource_year: int | None
    source_updated_at: str | None
    package_updated_at: str | None
    schema_fields: tuple[str, ...]
    reported_total: int


class IstanbulkartClient:
    def __init__(
        self,
        *,
        dataset_id: str = "istanbulkart-dolum-merkezi-bilgileri",
        resource_id: str | None = None,
        page_size: int = 100,
        ckan_client: CkanClient | None = None,
    ) -> None:
        self.dataset_id = dataset_id
        self.resource_id = resource_id
        self.page_size = max(1, min(int(page_size), 1000))
        self.ckan = ckan_client or CkanClient()

    async def fetch(self) -> IstanbulkartPayload:
        try:
            package = await self.ckan.package_show(self.dataset_id)
        except IstanbulkartError:
            raise
        except SourceRateLimitExceeded:
            raise
        except CkanError as exc:
            raise IstanbulkartSourceError(f"CKAN package_show failed: {exc}") from exc
        except Exception as exc:
            raise IstanbulkartSourceError("CKAN package_show request failed") from exc

        resources = self._resources(package)
        candidates = self._select_candidates(resources)
        if not candidates:
            raise IstanbulkartPayloadError("No active annual İstanbulkart DataStore resource found")

        # The newest annual resource is authoritative.  Falling back silently to
        # an older schema would make the response look current while serving old
        # coverage, so an unsupported newest resource is surfaced as a source error.
        return await self._fetch_resource(candidates[0])

    async def _fetch_resource(self, resource: dict[str, Any]) -> IstanbulkartPayload:
        resource_id = self._text(resource.get("id"))
        if not resource_id:
            raise IstanbulkartPayloadError("Selected resource has no id")
        first = await self._datastore_page(resource_id, offset=0)
        fields = self._field_names(first)
        missing = sorted(SUPPORTED_FIELDS.difference(fields))
        if missing:
            raise IstanbulkartSchemaError(
                f"Unsupported İstanbulkart resource schema; missing fields: {', '.join(missing)}"
            )

        result = self._result(first)
        total = self._total(result)
        records = self._records(result)
        rows = list(records)
        offset = len(records)
        while offset < total:
            page = await self._datastore_page(resource_id, offset=offset)
            page_result = self._result(page)
            page_records = self._records(page_result)
            if not page_records:
                raise IstanbulkartPaginationError(
                    f"DataStore pagination ended at offset {offset} before total {total}"
                )
            rows.extend(page_records)
            offset += len(page_records)
            if offset > total:
                raise IstanbulkartPaginationError(
                    f"DataStore returned more rows than reported total {total}"
                )

        if len(rows) != total:
            raise IstanbulkartPaginationError(
                f"DataStore returned {len(rows)} rows but reported total {total}"
            )
        package_updated_at = self._text(resource.get("package_metadata_modified"))
        source_updated_at = self._text(resource.get("last_modified")) or package_updated_at
        return IstanbulkartPayload(
            rows=tuple(rows),
            dataset_id=self.dataset_id,
            resource_id=resource_id,
            resource_year=self._resource_year(resource),
            source_updated_at=source_updated_at,
            package_updated_at=package_updated_at,
            schema_fields=tuple(sorted(fields)),
            reported_total=total,
        )

    async def _datastore_page(self, resource_id: str, *, offset: int) -> dict[str, Any]:
        try:
            return await self.ckan.datastore_search(
                resource_id=resource_id,
                limit=self.page_size,
                offset=offset,
            )
        except IstanbulkartError:
            raise
        except SourceRateLimitExceeded:
            raise
        except CkanError as exc:
            raise IstanbulkartSourceError(f"CKAN datastore_search failed: {exc}") from exc
        except Exception as exc:
            raise IstanbulkartSourceError("CKAN datastore_search request failed") from exc

    def _resources(self, package: Any) -> list[dict[str, Any]]:
        if not isinstance(package, dict):
            raise IstanbulkartPayloadError("CKAN package result must be an object")
        resources = package.get("resources")
        if not isinstance(resources, list):
            raise IstanbulkartPayloadError("CKAN package result has no resources list")
        package_modified = self._text(package.get("metadata_modified"))
        normalized: list[dict[str, Any]] = []
        for resource in resources:
            if not isinstance(resource, dict) or not resource.get("datastore_active"):
                continue
            row = dict(resource)
            row["package_metadata_modified"] = package_modified
            normalized.append(row)
        return normalized

    def _select_candidates(self, resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.resource_id is not None:
            selected = [resource for resource in resources if resource.get("id") == self.resource_id]
            if not selected:
                raise IstanbulkartPayloadError("Configured İstanbulkart resource override was not found")
            return selected

        annual_resources = [
            resource for resource in resources if self._resource_year(resource) is not None
        ]
        candidates = annual_resources or resources
        return sorted(
            candidates,
            key=lambda resource: (
                self._resource_year(resource) or 0,
                self._text(resource.get("last_modified")) or "",
            ),
            reverse=True,
        )

    def _result(self, page: Any) -> dict[str, Any]:
        if not isinstance(page, dict):
            raise IstanbulkartPayloadError("CKAN DataStore result must be an object")
        return page

    def _field_names(self, page: dict[str, Any]) -> set[str]:
        fields = page.get("fields")
        if not isinstance(fields, list):
            raise IstanbulkartSchemaError("CKAN DataStore response has no fields list")
        names = {str(item.get("id")) for item in fields if isinstance(item, dict) and item.get("id")}
        return names

    def _records(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        records = result.get("records")
        if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
            raise IstanbulkartPayloadError("CKAN DataStore response has invalid records")
        return records

    def _total(self, result: dict[str, Any]) -> int:
        total = result.get("total")
        if isinstance(total, bool):
            raise IstanbulkartPayloadError("CKAN DataStore total is invalid")
        try:
            total_int = int(total)
        except (TypeError, ValueError) as exc:
            raise IstanbulkartPayloadError("CKAN DataStore total is missing") from exc
        if total_int < 0:
            raise IstanbulkartPayloadError("CKAN DataStore total is negative")
        return total_int

    def _resource_year(self, resource: dict[str, Any]) -> int | None:
        text = self._text(resource.get("name")) or ""
        match = re.search(r"\b(20\d{2})\b", text)
        return int(match.group(1)) if match else None

    def _text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
