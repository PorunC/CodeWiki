from typing import Any

from backend.app.database import DocPageRecord, CodeWikiStore
from backend.app.services.graphrag import RetrievalTrace
from backend.app.services.repo_scanner import RepoDescriptor
from backend.app.services.wiki.agent_tools import ReadFileEvidence
from backend.app.services.wiki.catalog import _catalog_context_for_page
from backend.app.services.wiki.page_payload_context import (
    ChildPageSummaryBuilder,
    EvidenceInventoryBuilder,
    PageDepthProfiler,
)
from backend.app.services.wiki.page_payload_template import PagePayloadTemplate


class PageGenerationPayloadBuilder:
    def __init__(
        self,
        *,
        store: CodeWikiStore,
        template: PagePayloadTemplate | None = None,
        child_summary_builder: ChildPageSummaryBuilder | None = None,
        evidence_inventory_builder: EvidenceInventoryBuilder | None = None,
        depth_profiler: PageDepthProfiler | None = None,
    ) -> None:
        self.store = store
        self.template = template or PagePayloadTemplate()
        self.child_summary_builder = child_summary_builder or ChildPageSummaryBuilder()
        self.evidence_inventory_builder = evidence_inventory_builder or EvidenceInventoryBuilder()
        self.depth_profiler = depth_profiler or PageDepthProfiler()

    def prompt_contract(self) -> dict[str, Any]:
        return {
            "source_linking": self.template.source_linking(),
            "documentation_style": self.template.documentation_style(),
            "citation_style": self.template.citation_style(),
            "diagram_placement": self.template.diagram_placement(),
            "detail_expectations": self.template.detail_expectations(),
            "agent_tools": self.template.agent_tools(),
            "server_diagram_strategy": self.template.server_diagram_strategy(),
            "required_json_shape": self.template.required_json_shape(),
        }

    def stable_repo_context(
        self,
        repo: RepoDescriptor,
        *,
        language_code: str,
    ) -> dict[str, Any]:
        catalog = self.store.get_latest_doc_catalog(repo.id, language_code=language_code)
        return {
            "repository": {
                "id": repo.id,
                "name": repo.name,
                "path": repo.path,
                "source_type": repo.source_type,
                "git_url": repo.git_url,
                "commit_hash": repo.commit_hash,
            },
            "language_code": language_code,
            "catalog": _stable_catalog_context(catalog.structure if catalog else None),
        }

    def build(
        self,
        repo: RepoDescriptor,
        item: dict[str, Any],
        trace: RetrievalTrace,
        *,
        title: str,
        slug: str,
        topic: str,
        parent_slug: str | None,
        language_code: str,
        source_hints: list[str],
        allowed_source_refs: list[dict[str, object]],
        readfile_evidence: ReadFileEvidence,
        child_pages: list[DocPageRecord],
        diagram_slots: list[dict[str, object]],
    ) -> dict[str, Any]:
        catalog = self.store.get_latest_doc_catalog(repo.id, language_code=language_code)
        catalog_context = _catalog_context_for_page(
            catalog.structure.get("items", []) if catalog else [],
            slug=slug,
            parent_slug=parent_slug,
        )
        child_page_summaries = self.child_summary_builder.build(child_pages)
        evidence_inventory = self.evidence_inventory_builder.build(trace)
        prompt_source_chunks = _source_chunk_metadata(trace.source_chunks)
        return {
            "title": title,
            "slug": slug,
            "path": item.get("path") or slug,
            "topic": topic,
            "language_code": language_code,
            "source_hints": source_hints,
            "catalog_context": catalog_context,
            "parent_synthesis": self.template.parent_synthesis(
                has_child_pages=bool(child_page_summaries),
            ),
            "child_page_summaries": child_page_summaries,
            "page_depth_profile": self.depth_profiler.build(
                item,
                child_page_summaries=child_page_summaries,
                evidence_inventory=evidence_inventory,
            ),
            "diagram_slots": diagram_slots,
            "evidence_inventory": evidence_inventory,
            "context_pack": trace.context_pack,
            "source_chunks": prompt_source_chunks,
            "allowed_source_refs": allowed_source_refs,
            "readfile_evidence": readfile_evidence.as_payload(),
            "graph_facts": self.template.prompt_graph_facts(trace),
        }


def _source_chunk_metadata(chunks: list[dict[str, object]]) -> list[dict[str, object]]:
    """Trim chunk body to avoid duplicating full code in both context_pack and source_chunks."""
    kept_keys = (
        "id",
        "node_id",
        "file_path",
        "start_line",
        "end_line",
        "content_hash",
        "token_count",
        "score",
        "score_components",
        "reasons",
    )
    return [{key: chunk[key] for key in kept_keys if key in chunk} for chunk in chunks]


def _stable_catalog_context(structure: dict[str, Any] | None) -> dict[str, Any] | None:
    if not structure:
        return None
    return {
        "title": structure.get("title"),
        "description": structure.get("description"),
        "items": [_stable_catalog_item(item) for item in structure.get("items", [])],
    }


def _stable_catalog_item(item: dict[str, Any]) -> dict[str, Any]:
    children = item.get("children") or []
    return {
        key: value
        for key, value in {
            "title": item.get("title"),
            "slug": item.get("slug"),
            "path": item.get("path"),
            "topic": item.get("topic"),
            "kind": item.get("kind"),
            "children": [_stable_catalog_item(child) for child in children],
        }.items()
        if value not in (None, [], "")
    }
