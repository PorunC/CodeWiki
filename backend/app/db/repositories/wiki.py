import uuid
from typing import Any

from sqlalchemy import delete, select

from backend.app.models import DocCatalogRecord, DocPageRecord
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
        with self.orm_session() as session:
            existing = session.get(DocCatalogRecord, record.id)
            if existing is None:
                session.add(record)
            else:
                existing.title = record.title
                existing.structure = record.structure
                existing.generated_at = record.generated_at
        return record

    def get_latest_doc_catalog(self, repo_id: str) -> DocCatalogRecord | None:
        with self.orm_session() as session:
            return session.scalars(
                select(DocCatalogRecord)
                .where(DocCatalogRecord.repo_id == repo_id)
                .order_by(DocCatalogRecord.generated_at.desc())
                .limit(1)
            ).first()

    def upsert_doc_page(self, page: DocPageRecord) -> DocPageRecord:
        updated_at = page.updated_at or now_iso()
        with self.orm_session() as session:
            existing = session.scalars(
                select(DocPageRecord).where(
                    DocPageRecord.repo_id == page.repo_id,
                    DocPageRecord.slug == page.slug,
                )
            ).first()
            if existing is None:
                saved = DocPageRecord(**{**page.as_record_dict(), "updated_at": updated_at})
                session.add(saved)
                return saved

            existing.title = page.title
            existing.parent_slug = page.parent_slug
            existing.markdown = page.markdown
            existing.source_refs = page.source_refs
            existing.graph_refs = page.graph_refs
            existing.status = page.status
            existing.updated_at = updated_at
            return existing

    def get_doc_page(self, repo_id: str, slug: str) -> DocPageRecord | None:
        with self.orm_session() as session:
            return session.scalars(
                select(DocPageRecord).where(
                    DocPageRecord.repo_id == repo_id,
                    DocPageRecord.slug == slug,
                )
            ).first()

    def list_doc_pages(self, repo_id: str) -> list[DocPageRecord]:
        with self.orm_session() as session:
            return list(
                session.scalars(
                    select(DocPageRecord)
                    .where(DocPageRecord.repo_id == repo_id)
                    .order_by(DocPageRecord.parent_slug, DocPageRecord.slug)
                )
            )

    def delete_doc_pages_not_in(self, repo_id: str, slugs: list[str]) -> int:
        if not slugs:
            return 0
        with self.orm_session() as session:
            result = session.execute(
                delete(DocPageRecord).where(
                    DocPageRecord.repo_id == repo_id,
                    DocPageRecord.slug.not_in(slugs),
                )
            )
        return int(result.rowcount or 0)

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
