from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.geo import haversine_m, radius_bbox
from app.storage.db import connect, init_database


class GeoRepository:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        init_database(database_path)

    def upsert_features(self, features: list[dict[str, Any]]) -> None:
        with connect(self.database_path) as conn:
            for feature in features:
                conn.execute(
                    """
                    INSERT INTO geo_features (
                      id, source, feature_type, source_id, name, lat, lon,
                      geometry_json, district, neighborhood, properties_json, valid_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                      source=excluded.source,
                      feature_type=excluded.feature_type,
                      source_id=excluded.source_id,
                      name=excluded.name,
                      lat=excluded.lat,
                      lon=excluded.lon,
                      geometry_json=excluded.geometry_json,
                      district=excluded.district,
                      neighborhood=excluded.neighborhood,
                      properties_json=excluded.properties_json,
                      valid_at=excluded.valid_at,
                      retrieved_at=CURRENT_TIMESTAMP
                    """,
                    (
                        feature["id"],
                        feature["source"],
                        feature["feature_type"],
                        feature["source_id"],
                        feature["name"],
                        feature["lat"],
                        feature["lon"],
                        json.dumps(feature.get("geometry"), ensure_ascii=False),
                        feature.get("district"),
                        feature.get("neighborhood"),
                        json.dumps(feature.get("properties") or {}, ensure_ascii=False),
                        feature.get("valid_at"),
                    ),
                )
                rowid = conn.execute(
                    "SELECT rowid FROM geo_features WHERE id = ?",
                    (feature["id"],),
                ).fetchone()[0]
                lon = feature["lon"]
                lat = feature["lat"]
                conn.execute(
                    """
                    INSERT OR REPLACE INTO geo_features_rtree(rowid, min_lon, max_lon, min_lat, max_lat)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (rowid, lon, lon, lat, lat),
                )
            conn.commit()

    def nearby(
        self,
        *,
        lat: float,
        lon: float,
        radius_m: int,
        limit: int,
        types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        min_lon, min_lat, max_lon, max_lat = radius_bbox(lat, lon, radius_m)
        rows = self._bbox_rows(min_lon, min_lat, max_lon, max_lat, types)
        results = []
        for row in rows:
            item = self._row_to_dict(row)
            distance = haversine_m(lat, lon, item["lat"], item["lon"])
            if distance <= radius_m:
                item["distance_m"] = round(distance)
                results.append(item)
        results.sort(key=lambda item: item["distance_m"])
        return results[:limit]

    def bbox_search(
        self,
        *,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        limit: int,
        types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return [self._row_to_dict(row) for row in self._bbox_rows(min_lon, min_lat, max_lon, max_lat, types)[:limit]]

    def _bbox_rows(
        self,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        types: list[str] | None,
    ):
        type_filter = ""
        params: list[Any] = [min_lon, max_lon, min_lat, max_lat]
        if types:
            placeholders = ",".join("?" for _ in types)
            type_filter = f" AND g.feature_type IN ({placeholders})"
            params.extend(types)
        with connect(self.database_path) as conn:
            return conn.execute(
                f"""
                SELECT g.*
                FROM geo_features g
                JOIN geo_features_rtree r ON r.rowid = g.rowid
                WHERE r.max_lon >= ?
                  AND r.min_lon <= ?
                  AND r.max_lat >= ?
                  AND r.min_lat <= ?
                  {type_filter}
                """,
                params,
            ).fetchall()

    def _row_to_dict(self, row) -> dict[str, Any]:
        item = dict(row)
        item["properties"] = json.loads(item.pop("properties_json") or "{}")
        item.pop("geometry_json", None)
        return item
