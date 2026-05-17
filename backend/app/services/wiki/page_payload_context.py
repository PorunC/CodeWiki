from typing import Any

from backend.app.database import DocPageRecord
from backend.app.services.graphrag import RetrievalTrace

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


class MarkdownSectionParser:
    def section(self, markdown: str, heading: str) -> str:
        for current_heading, section in self.sections(markdown):
            if current_heading == heading:
                return section
        return ""

    def first_content_section(self, markdown: str) -> str:
        for heading in CHILD_SUMMARY_HEADINGS:
            section = self.section(markdown, heading)
            if section:
                return section

        for heading, section in self.sections(markdown):
            if heading not in SERVER_INJECTED_HEADINGS:
                return section
        return markdown.strip()

    def sections(self, markdown: str) -> list[tuple[str, str]]:
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


class ChildPageSummaryBuilder:
    def __init__(
        self,
        *,
        parser: MarkdownSectionParser | None = None,
        max_pages: int = MAX_CHILD_PAGE_SUMMARIES,
        max_chars: int = MAX_CHILD_PAGE_SUMMARY_CHARS,
    ) -> None:
        self.parser = parser or MarkdownSectionParser()
        self.max_pages = max_pages
        self.max_chars = max_chars

    def build(self, pages: list[DocPageRecord]) -> list[dict[str, object]]:
        return [
            {
                "title": page.title,
                "slug": page.slug,
                "status": page.status,
                "overview_markdown": self._trim(
                    self.parser.first_content_section(page.markdown),
                ),
                "source_refs": page.source_refs[:6],
                "graph_refs": page.graph_refs[:12],
            }
            for page in pages[: self.max_pages]
        ]

    def _trim(self, markdown: str) -> str:
        stripped = markdown.strip()
        if len(stripped) <= self.max_chars:
            return stripped
        return stripped[: self.max_chars].rstrip() + "\n..."


class EvidenceInventoryBuilder:
    def build(self, trace: RetrievalTrace) -> dict[str, object]:
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


class PageDepthProfiler:
    def build(
        self,
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
