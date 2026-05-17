from typing import Any

from backend.app.database import DocPageRecord, SQLiteStore
from backend.app.services.graphrag import RetrievalTrace
from backend.app.services.repo_scanner import RepoDescriptor
from backend.app.services.wiki.agent_tools import ReadFileEvidence
from backend.app.services.wiki.catalog import _catalog_context_for_page
from backend.app.services.wiki.diagrams import MAX_MERMAID_EDGES, SOURCE_EDGE_TYPES

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
    def __init__(self, *, store: SQLiteStore) -> None:
        self.store = store

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
            "source_linking": {
                "source_refs": "Use only file_path/start_line/end_line values from allowed_source_refs.",
                "source_urls": (
                    "The server will convert validated source refs into clickable source URLs "
                    "when repository git metadata is available."
                ),
                "inline_citations": (
                    "Use [[S1]] style markers from allowed_source_refs after source-grounded "
                    "sentences. The server validates and converts markers to source links."
                ),
            },
            "catalog_context": catalog_context,
            "parent_synthesis": {
                "has_child_pages": bool(child_page_summaries),
                "instructions": (
                    "When child_page_summaries is non-empty, synthesize this parent page "
                    "primarily from the generated child page overviews. Use source_chunks "
                    "and graph_facts to ground citations, fill gaps, and avoid unsupported "
                    "claims rather than re-deriving the whole parent topic from scratch."
                ),
            },
            "child_page_summaries": child_page_summaries,
            "documentation_style": {
                "name": "DeepWiki",
                "workflow": [
                    "GATHER with mandatory ReadFile evidence, source_chunks, and graph_facts",
                    "think through subsystem boundaries, lifecycle, contracts, and failure paths",
                    "write detailed Markdown with compact tables and inline citations",
                ],
                "required_sections": [
                    "Purpose and Scope",
                    "Architecture or System Context when relationships are evidenced",
                    "Control Flow or Lifecycle when runtime behavior is evidenced",
                    "Data Model, API Surface, Configuration, or Failure Handling when evidenced",
                ],
                "server_injected_sections": [
                    "Relevant source files",
                    "validated Mermaid diagrams at requested diagram placeholders or near matching headings",
                    "grouped Sources",
                ],
            },
            "page_depth_profile": _page_depth_profile(
                item,
                child_page_summaries=child_page_summaries,
                evidence_inventory=evidence_inventory,
            ),
            "citation_style": {
                "inline_markers": (
                    "Use compact [[S#]] markers near concrete claims. The server renders "
                    "them as short citations and groups full source ranges separately."
                ),
                "avoid_noise": (
                    "Do not repeat long source file labels in prose. Avoid section-level "
                    "Sources lines; the server renders grouped source ranges once at the end."
                ),
            },
            "diagram_slots": diagram_slots,
            "diagram_placement": {
                "placeholder_format": "[[DIAGRAM:<slot>]]",
                "instructions": (
                    "The server generates Mermaid from graph facts. When a listed diagram slot "
                    "would clarify a section, place the exact placeholder on its own line near "
                    "the paragraph that introduces that relationship. Do not invent slots. If no "
                    "slot fits naturally, omit placeholders and the server will place diagrams near "
                    "matching headings."
                ),
            },
            "detail_expectations": {
                "minimum_depth": (
                    "For non-trivial pages, go beyond a summary. Cover responsibility, "
                    "lifecycle/control flow, dependencies, inputs and outputs, data surfaces, "
                    "APIs or UI routes, configuration, validation, extension points, failure "
                    "handling, and operational implications when those details are present."
                ),
                "preferred_tables": [
                    "component/file/responsibility/evidence",
                    "symbol/function/caller/callee/evidence",
                    "route or API/symbol/purpose/evidence",
                    "data structure/owner/fields or role/evidence",
                    "configuration key/default or source/effect/evidence",
                    "workflow step/owner/input/output/evidence",
                    "failure mode/trigger/handling/evidence",
                ],
                "code_examples": (
                    "Use exact source snippets only when source_chunks provide them; otherwise "
                    "prefer prose over invented examples."
                ),
                "related_pages": (
                    "Mention related pages only from catalog_context.related_pages and only when "
                    "the relationship is supported by the retrieved evidence."
                ),
                "missing_information": (
                    "If a detail is expected but absent from source evidence, state the gap briefly "
                    "instead of filling it with assumptions."
                ),
                "depth_targets": [
                    "explain how the subsystem is entered and what it returns or mutates",
                    "name important collaborators and why each boundary exists",
                    "describe data contracts, persistence records, schemas, DTOs, or component props",
                    "trace at least one end-to-end workflow when graph_facts or source_chunks support it",
                    "call out validation, retry, fallback, draft/error state, or cleanup behavior",
                    "include representative tests only when they clarify observable behavior",
                ],
            },
            "evidence_inventory": evidence_inventory,
            "context_pack": trace.context_pack,
            "source_chunks": trace.source_chunks,
            "allowed_source_refs": allowed_source_refs,
            "agent_tools": {
                "available": [
                    {
                        "name": "ReadFile",
                        "purpose": "Read exact repository source ranges before writing.",
                    }
                ],
                "required_for_page_generation": ["ReadFile"],
            },
            "readfile_evidence": readfile_evidence.as_payload(),
            "graph_facts": {
                "seed_nodes": trace.seed_nodes,
                "expanded_nodes": trace.expanded_nodes,
                "related_edges": trace.related_edges,
                "community_summaries": trace.community_summaries,
            },
            "graph_edges_for_mermaid": [
                edge for edge in trace.related_edges if edge.get("type") in SOURCE_EDGE_TYPES
            ][:MAX_MERMAID_EDGES],
            "server_diagram_strategy": {
                "diagram_generation": "server_generated_from_graph_facts_only",
                "llm_must_not_emit_mermaid": True,
                "strategies": {
                    "component": "graph TD for high-level component dependency maps",
                    "data_flow": "flowchart LR for data moving between components",
                    "control_flow": "flowchart TD for hierarchical control or route flow",
                    "symbol_flow": "flowchart TD for concrete endpoints, functions, methods, and calls",
                    "sequence": "sequenceDiagram for request/response or multi-agent interactions",
                    "data_model": "classDiagram for schemas, classes, DTOs, and inheritance",
                },
                "grouping": (
                    "Prefer flexible subsystem/file labels over raw community names when the graph "
                    "group name is too generic. Diagrams are inserted in context rather than as a "
                    "fixed Graph section at the end."
                ),
            },
            "required_json_shape": {
                "title": title,
                "markdown": (
                    "# Page title\n\n## Purpose and Scope\n\n"
                    "Grounded Markdown with inline [[S1]] citations, optional [[DIAGRAM:slot]] "
                    "placeholders from diagram_slots, and no Mermaid fences."
                ),
                "source_refs": [
                    {
                        "citation_id": "S1",
                        "file_path": "path.py",
                        "start_line": 1,
                        "end_line": 5,
                    }
                ],
            },
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
