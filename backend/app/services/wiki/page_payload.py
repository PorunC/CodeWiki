from typing import Any

from backend.app.database import DocPageRecord, SQLiteStore
from backend.app.services.graphrag import RetrievalTrace
from backend.app.services.repo_scanner import RepoDescriptor
from backend.app.services.wiki.agent_tools import ReadFileEvidence
from backend.app.services.wiki.catalog import _catalog_context_for_page
from backend.app.services.wiki.page_payload_template import PagePayloadTemplate

MAX_CHILD_PAGE_SUMMARIES = 8
MAX_CHILD_PAGE_SUMMARY_CHARS = 1600
CHILD_SUMMARY_HEADINGS = ("## Purpose and Scope", "## Overview")
SERVER_INJECTED_HEADINGS = {
    "## Relevant source files",
    "## Graph",
    "## Diagrams",
    "## Sources",
    "## Validation Errors",
}


class PageGenerationPayloadBuilder:
    def __init__(
        self,
        *,
        store: SQLiteStore,
        template: PagePayloadTemplate | None = None,
    ) -> None:
        self.store = store
        self.template = template or PagePayloadTemplate()

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
        child_page_summaries = _child_page_summaries(child_pages)
        evidence_inventory = _evidence_inventory(trace)
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
            "page_depth_profile": _page_depth_profile(
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


def _page_depth_profile(
    item: dict[str, Any],
    *,
    child_page_summaries: list[dict[str, object]],
    evidence_inventory: dict[str, object],
) -> dict[str, object]:
    kind = str(item.get("kind") or "page").lower()
    is_parent = bool(child_page_summaries) or kind == "category"
    if is_parent:
        emphasis = [
            "synthesize child page responsibilities without duplicating every child detail",
            "explain the section mental model and cross-child relationships",
            "point out integration boundaries and shared data or control flow",
        ]
    else:
        emphasis = [
            "drill into concrete files, symbols, call paths, and data contracts",
            "include implementation tables for components, workflows, APIs, and failure modes",
            "describe lifecycle steps from entry point through downstream collaborators",
        ]
    return {
        "kind": "parent_synthesis" if is_parent else "implementation_deep_dive",
        "expected_detail_level": "high" if not is_parent else "medium_high",
        "evidence_counts": evidence_inventory.get("counts", {}),
        "available_edge_types": evidence_inventory.get("edge_types", []),
        "available_node_types": evidence_inventory.get("node_types", []),
        "emphasis": emphasis,
    }


def _evidence_inventory(trace: RetrievalTrace) -> dict[str, object]:
    node_type_counts: dict[str, int] = {}
    edge_type_counts: dict[str, int] = {}
    file_paths: list[str] = []
    seen_files: set[str] = set()
    for node in [*trace.seed_nodes, *trace.expanded_nodes]:
        node_type = str(node.get("type") or "unknown")
        node_type_counts[node_type] = node_type_counts.get(node_type, 0) + 1
        file_path = str(node.get("file_path") or "")
        if file_path and file_path not in seen_files:
            seen_files.add(file_path)
            file_paths.append(file_path)
    for edge in trace.related_edges:
        edge_type = str(edge.get("type") or "unknown")
        edge_type_counts[edge_type] = edge_type_counts.get(edge_type, 0) + 1

    return {
        "counts": {
            "seed_nodes": len(trace.seed_nodes),
            "expanded_nodes": len(trace.expanded_nodes),
            "related_edges": len(trace.related_edges),
            "source_chunks": len(trace.source_chunks),
            "communities": len(trace.community_summaries),
        },
        "node_types": sorted(node_type_counts),
        "edge_types": sorted(edge_type_counts),
        "top_files": file_paths[:12],
    }


def _child_page_summaries(pages: list[DocPageRecord]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for page in pages[:MAX_CHILD_PAGE_SUMMARIES]:
        summaries.append(
            {
                "title": page.title,
                "slug": page.slug,
                "status": page.status,
                "overview_markdown": _trim_child_summary(_extract_child_overview(page.markdown)),
                "source_refs": page.source_refs[:6],
                "graph_refs": page.graph_refs[:12],
            }
        )
    return summaries


def _extract_child_overview(markdown: str) -> str:
    for heading in CHILD_SUMMARY_HEADINGS:
        section = _markdown_section(markdown, heading)
        if section:
            return section

    for heading, section in _markdown_sections(markdown):
        if heading not in SERVER_INJECTED_HEADINGS:
            return section
    return markdown.strip()


def _markdown_section(markdown: str, heading: str) -> str:
    for current_heading, section in _markdown_sections(markdown):
        if current_heading == heading:
            return section
    return ""


def _markdown_sections(markdown: str) -> list[tuple[str, str]]:
    lines = markdown.splitlines()
    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []

    for line in lines:
        if line.startswith("## "):
            if current_heading:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = line.strip()
            current_lines = [line]
            continue
        if current_heading:
            current_lines.append(line)

    if current_heading:
        sections.append((current_heading, "\n".join(current_lines).strip()))
    return [(heading, section) for heading, section in sections if section]


def _trim_child_summary(markdown: str) -> str:
    stripped = markdown.strip()
    if len(stripped) <= MAX_CHILD_PAGE_SUMMARY_CHARS:
        return stripped
    return stripped[:MAX_CHILD_PAGE_SUMMARY_CHARS].rstrip() + "\n..."
