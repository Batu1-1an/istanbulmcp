"""An explicit ``limit=0`` is invalid input, not a missing argument."""
from types import SimpleNamespace

import pytest

from app.core.settings import Settings
from app.core.validation import InputValidationError, resolve_limit
from app.services.catalog import CatalogService
from app.services.city import CityService
from app.services.iski import IskiService
from app.services.neighborhood import NeighborhoodService
from app.storage.geo import GeoRepository


async def _forbidden(*_args, **_kwargs):
    raise AssertionError("limit validation must run before any source access")


def _client(*methods: str) -> SimpleNamespace:
    return SimpleNamespace(**{name: _forbidden for name in methods})


def _rejected(envelope: dict) -> bool:
    row = envelope["data"][0]
    return (
        envelope["ok"] is False
        and row["error_code"] == "validation_error"
        and row["field"] == "limit"
        and envelope["warnings"]
        and envelope["limits"]
    )


def test_resolve_limit_distinguishes_missing_from_zero():
    assert resolve_limit(None, 20, 100) == 20
    assert resolve_limit(7, 20, 100) == 7
    with pytest.raises(InputValidationError) as excinfo:
        resolve_limit(0, 20, 100)
    assert excinfo.value.field == "limit"


@pytest.mark.asyncio
async def test_explicit_zero_limit_is_rejected_before_every_source(tmp_path):
    settings = Settings(database_path=tmp_path / "limits.sqlite3")
    catalog = CatalogService(settings=settings,
                             client=_client("package_search", "package_show", "datastore_search"))
    iski = IskiService(settings=settings, client=_client("active_faults", "dams"))
    city = CityService(settings=settings, geo_repository=GeoRepository(settings.database_path))
    city._parks = _forbidden
    city._metro_stations = _forbidden
    city._air_quality_stations = _forbidden
    neighborhood = NeighborhoodService(settings=settings, ckan_client=_client("datastore_search"))

    assert _rejected(await catalog.search_datasets(query="otopark", limit=0))
    assert _rejected(await catalog.query_resource(resource_id="fixture-resource", limit=0))
    assert _rejected(await iski.active_faults(limit=0))
    assert _rejected(await iski.dam_occupancy(limit=0))
    assert _rejected(await city.parking_by_district(district="Kadıköy", limit=0))
    assert _rejected(await city.nearby(lat=41.0, lon=29.0, limit=0))
    assert _rejected(await city.bbox_search(bbox=[28.9, 40.9, 29.1, 41.1], limit=0))
    assert _rejected(await neighborhood.profile(district="Kadıköy", limit=0))
