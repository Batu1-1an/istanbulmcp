from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.storage.db import connect, init_database


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class CatalogRepository:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        init_database(database_path)

    def upsert_dataset(self, dataset: dict[str, Any]) -> None:
        dataset_id = dataset.get("id") or dataset["name"]
        slug = dataset.get("name") or dataset_id
        tags = [tag.get("name", "") for tag in dataset.get("tags", []) if isinstance(tag, dict)]
        organization = dataset.get("organization") or {}
        resources = dataset.get("resources") or []

        with connect(self.database_path) as conn:
            conn.execute(
                """
                INSERT INTO datasets (
                  id, ckan_id, slug, title, description, organization,
                  groups_json, tags_json, license, source_url, metadata_json, last_modified
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  ckan_id=excluded.ckan_id,
                  slug=excluded.slug,
                  title=excluded.title,
                  description=excluded.description,
                  organization=excluded.organization,
                  groups_json=excluded.groups_json,
                  tags_json=excluded.tags_json,
                  license=excluded.license,
                  source_url=excluded.source_url,
                  metadata_json=excluded.metadata_json,
                  last_modified=excluded.last_modified,
                  retrieved_at=CURRENT_TIMESTAMP
                """,
                (
                    dataset_id,
                    dataset.get("id"),
                    slug,
                    dataset.get("title") or slug,
                    dataset.get("notes") or dataset.get("description"),
                    organization.get("title") or organization.get("name"),
                    _json(dataset.get("groups") or []),
                    _json(tags),
                    dataset.get("license_title") or dataset.get("license_id"),
                    dataset.get("url") or dataset.get("metadata_url"),
                    _json(dataset),
                    dataset.get("metadata_modified") or dataset.get("revision_timestamp"),
                ),
            )
            conn.execute("DELETE FROM dataset_fts WHERE dataset_id = ?", (dataset_id,))
            conn.execute(
                "INSERT INTO dataset_fts(dataset_id, title, description, tags) VALUES (?, ?, ?, ?)",
                (
                    dataset_id,
                    dataset.get("title") or slug,
                    dataset.get("notes") or "",
                    " ".join(tags),
                ),
            )
            for resource in resources:
                self.upsert_resource(conn, dataset_id, resource)
            conn.commit()

    def upsert_resource(
        self,
        conn: sqlite3.Connection,
        dataset_id: str,
        resource: dict[str, Any],
    ) -> None:
        resource_id = resource.get("id")
        if not resource_id:
            return
        conn.execute(
            """
            INSERT INTO resources (
              id, dataset_id, ckan_resource_id, name, format, url,
              datastore_active, schema_json, size_bytes, hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              dataset_id=excluded.dataset_id,
              ckan_resource_id=excluded.ckan_resource_id,
              name=excluded.name,
              format=excluded.format,
              url=excluded.url,
              datastore_active=excluded.datastore_active,
              schema_json=excluded.schema_json,
              size_bytes=excluded.size_bytes,
              hash=excluded.hash,
              retrieved_at=CURRENT_TIMESTAMP
            """,
            (
                resource_id,
                dataset_id,
                resource_id,
                resource.get("name") or resource.get("description"),
                (resource.get("format") or "").upper(),
                resource.get("url"),
                1 if resource.get("datastore_active") else 0,
                _json(resource.get("schema") or resource.get("fields") or []),
                resource.get("size"),
                resource.get("hash"),
            ),
        )

    def search_local(self, query: str, limit: int) -> list[dict[str, Any]]:
        expression = query.strip().replace('"', " ")
        if not expression:
            return []
        with connect(self.database_path) as conn:
            rows = conn.execute(
                """
                SELECT d.id, d.slug, d.title, d.description, d.license, d.last_modified
                FROM dataset_fts f
                JOIN datasets d ON d.id = f.dataset_id
                WHERE dataset_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (expression, limit),
            ).fetchall()
        return [dict(row) for row in rows]
