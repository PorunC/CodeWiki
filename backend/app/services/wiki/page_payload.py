from typing import Any

from backend.app.database import DocPageRecord, SQLiteStore
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
        store: SQLiteStore,
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
        return {
            "title": title,
            "slug": slug,
            "path": item.get("path") or slug,
            "topic": topic,
            "language_code": language_code,
            "source_hints": source_hints,
            "source_linking": self.template.source_linking(),
            "catalog_context": catalog_context,
            "parent_synthesis": self.template.parent_synthesis(
                has_child_pages=bool(child_page_summaries),
            ),
            "child_page_summaries": child_page_summaries,
            "documentation_style": self.template.documentation_style(),
            "page_depth_profile": self.depth_profiler.build(
                item,
                child_page_summaries=child_page_summaries,
                evidence_inventory=evidence_inventory,
            ),
            "citation_style": self.template.citation_style(),
            "diagram_slots": diagram_slots,
            "diagram_placement": self.template.diagram_placement(),
            "detail_expectations": self.template.detail_expectations(),
            "evidence_inventory": evidence_inventory,
            "context_pack": trace.context_pack,
            "source_chunks": trace.source_chunks,
            "allowed_source_refs": allowed_source_refs,
            "agent_tools": self.template.agent_tools(),
            "readfile_evidence": readfile_evidence.as_payload(),
            "graph_facts": self.template.graph_facts(trace),
            "graph_edges_for_mermaid": self.template.graph_edges_for_mermaid(trace),
            "server_diagram_strategy": self.template.server_diagram_strategy(),
            "required_json_shape": self.template.required_json_shape(title=title),
        }
