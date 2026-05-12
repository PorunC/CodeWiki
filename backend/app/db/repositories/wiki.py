import json
import uuid
from typing import Any

from backend.app.db.mappers import doc_catalog_from_row, doc_page_from_row
from backend.app.db.records import DocCatalogRecord, DocPageRecord
from backend.app.db.utils import now_iso


class WikiRepositoryMixin:
    def save_doc_catalog(
        self,
        repo_id: str,
        *,
        title: str,
        structure: dict[str, Any],
        catalog_id: str | None = None,
    ) -> DocCatalogRecord:
        record = DocCatalogRecord(
            id=catalog_id or uuid.uuid4().hex,
            repo_id=repo_id,
            title=title,
            structure=structure,
            generated_at=now_iso(),
        )
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO doc_catalog (id, repo_id, title, structure_json, generated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  title = excluded.title,
                  structure_json = excluded.structure_json,
                  generated_at = excluded.generated_at
                """,
                (
                    record.id,
                    record.repo_id,
                    record.title,
                    json.dumps(record.structure, sort_keys=True),
                    record.generated_at,
                ),
            )
        return record

    def get_latest_doc_catalog(self, repo_id: str) -> DocCatalogRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, repo_id, title, structure_json, generated_at
                FROM doc_catalog
                WHERE repo_id = ?
                ORDER BY generated_at DESC
                LIMIT 1
                """,
                (repo_id,),
            ).fetchone()
        return doc_catalog_from_row(row) if row is not None else None

    def upsert_doc_page(self, page: DocPageRecord) -> DocPageRecord:
        updated_at = page.updated_at or now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO doc_page (
                  id, repo_id, slug, title, parent_slug, markdown,
                  source_refs_json, graph_refs_json, status, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repo_id, slug) DO UPDATE SET
                  title = excluded.title,
                  parent_slug = excluded.parent_slug,
                  markdown = excluded.markdown,
                  source_refs_json = excluded.source_refs_json,
                  graph_refs_json = excluded.graph_refs_json,
                  status = excluded.status,
                  updated_at = excluded.updated_at
                """,
                (
                    page.id,
                    page.repo_id,
                    page.slug,
                    page.title,
                    page.parent_slug,
                    page.markdown,
                    json.dumps(page.source_refs, sort_keys=True),
                    json.dumps(page.graph_refs, sort_keys=True),
                    page.status,
                    updated_at,
                ),
            )
        return DocPageRecord(**{**page.__dict__, "updated_at": updated_at})

    def get_doc_page(self, repo_id: str, slug: str) -> DocPageRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, repo_id, slug, title, parent_slug, markdown,
                       source_refs_json, graph_refs_json, status, updated_at
                FROM doc_page
                WHERE repo_id = ? AND slug = ?
                """,
                (repo_id, slug),
            ).fetchone()
        return doc_page_from_row(row) if row is not None else None

    def list_doc_pages(self, repo_id: str) -> list[DocPageRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, repo_id, slug, title, parent_slug, markdown,
                       source_refs_json, graph_refs_json, status, updated_at
                FROM doc_page
                WHERE repo_id = ?
                ORDER BY parent_slug, slug
                """,
                (repo_id,),
            ).fetchall()
        return [doc_page_from_row(row) for row in rows]

    def mark_doc_pages_stale(
        self,
        repo_id: str,
        *,
        file_paths: list[str],
        graph_refs: list[str],
    ) -> list[str]:
        file_path_set = set(file_paths)
        graph_ref_set = set(graph_refs)
        stale_slugs: list[str] = []

        for page in self.list_doc_pages(repo_id):
            references_file = any(
                str(source_ref.get("file_path", "")) in file_path_set
                for source_ref in page.source_refs
            )
            references_graph = bool(set(page.graph_refs) & graph_ref_set)
            if not references_file and not references_graph:
                continue

            stale_slugs.append(page.slug)
            if page.status == "draft":
                continue
            self.upsert_doc_page(
                DocPageRecord(
                    id=page.id,
                    repo_id=page.repo_id,
                    slug=page.slug,
                    title=page.title,
                    parent_slug=page.parent_slug,
                    markdown=page.markdown,
                    source_refs=page.source_refs,
                    graph_refs=page.graph_refs,
                    status="draft",
                    updated_at=None,
                )
            )

        return stale_slugs
