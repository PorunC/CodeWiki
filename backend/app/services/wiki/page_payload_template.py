from typing import Any

from backend.app.services.graphrag import RetrievalTrace
from backend.app.services.wiki.diagrams import MAX_MERMAID_EDGES, SOURCE_EDGE_TYPES


class PagePayloadTemplate:
    def source_linking(self) -> dict[str, str]:
        return {
            "source_refs": "Use only file_path/start_line/end_line values from allowed_source_refs.",
            "source_urls": (
                "The server will convert validated source refs into clickable source URLs "
                "when repository git metadata is available."
            ),
            "inline_citations": (
                "Use [[S1]] style markers from allowed_source_refs after source-grounded "
                "sentences. The server validates and converts markers to source links."
            ),
        }

    def parent_synthesis(self, *, has_child_pages: bool) -> dict[str, object]:
        return {
            "has_child_pages": has_child_pages,
            "instructions": (
                "When child_page_summaries is non-empty, synthesize this parent page "
                "primarily from the generated child page overviews. Use source_chunks "
                "and graph_facts to ground citations, fill gaps, and avoid unsupported "
                "claims rather than re-deriving the whole parent topic from scratch."
            ),
        }

    def documentation_style(self) -> dict[str, object]:
        return {
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
        }

    def citation_style(self) -> dict[str, str]:
        return {
            "inline_markers": (
                "Use compact [[S#]] markers near concrete claims. The server renders "
                "them as short citations and groups full source ranges separately."
            ),
            "avoid_noise": (
                "Do not repeat long source file labels in prose. Avoid section-level "
                "Sources lines; the server renders grouped source ranges once at the end."
            ),
        }

    def diagram_placement(self) -> dict[str, str]:
        return {
            "placeholder_format": "[[DIAGRAM:<slot>]]",
            "instructions": (
                "The server generates Mermaid from graph facts. When a listed diagram slot "
                "would clarify a section, place the exact placeholder on its own line near "
                "the paragraph that introduces that relationship. Do not invent slots. If no "
                "slot fits naturally, omit placeholders and the server will place diagrams near "
                "matching headings."
            ),
        }

    def detail_expectations(self) -> dict[str, object]:
        return {
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
        }

    def agent_tools(self) -> dict[str, object]:
        return {
            "available": [
                {
                    "name": "ReadFile",
                    "purpose": "Read exact repository source ranges before writing.",
                }
            ],
            "required_for_page_generation": ["ReadFile"],
        }

    def graph_facts(self, trace: RetrievalTrace) -> dict[str, object]:
        return {
            "seed_nodes": trace.seed_nodes,
            "expanded_nodes": trace.expanded_nodes,
            "related_edges": trace.related_edges,
            "community_summaries": trace.community_summaries,
        }

    def graph_edges_for_mermaid(self, trace: RetrievalTrace) -> list[dict[str, Any]]:
        return [
            edge for edge in trace.related_edges if edge.get("type") in SOURCE_EDGE_TYPES
        ][:MAX_MERMAID_EDGES]

    def server_diagram_strategy(self) -> dict[str, object]:
        return {
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
        }

    def required_json_shape(self, *, title: str) -> dict[str, object]:
        return {
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
        }
