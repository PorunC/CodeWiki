import uuid
from dataclasses import dataclass
from typing import Any

from backend.app.database import DocPageRecord, SQLiteStore
from backend.app.services.graphrag import GraphRAGRetriever, RetrievalTrace
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.llm_run_recorder import complete_with_cache
from backend.app.services.repo_scanner import RepoDescriptor
from backend.app.services.wiki.agent_tools import ReadFileEvidence, readfile_evidence_for_page
from backend.app.services.wiki.catalog import (
    _catalog_context_for_page,
    _slugify,
    _source_hints_from_item,
    _trace_with_source_hint_chunks,
)
from backend.app.services.wiki.diagrams import (
    MAX_MERMAID_EDGES,
    SOURCE_EDGE_TYPES,
    _diagram_slots_payload,
    _graph_refs_from_trace,
    _mermaid_diagrams_from_trace,
)
from backend.app.services.wiki.markdown import _strip_llm_mermaid, _validate_page_markdown
from backend.app.services.wiki.mermaid_validation import validate_mermaid_blocks_async
from backend.app.services.wiki.prompts import _json_object, _load_prompt, _page_messages
from backend.app.services.wiki.sources import (
    _compose_page_markdown,
    _draft_markdown,
    _filter_unused_source_refs,
    _include_markdown_citation_refs,
    _replace_citation_markers,
    _source_refs_from_chunks,
    _source_url,
    _source_url_base,
    _strip_unknown_citation_markers,
    _validate_citation_markers,
    _validate_diagram_placeholders,
    _validate_source_refs,
)

PAGE_GENERATION_ATTEMPTS = 2
PAGE_RETRIEVAL_MAX_HOPS = 3
PAGE_CACHE_VERSION = "page:v4"
PAGE_PROMPT_VERSION = "page:deepwiki:v4"
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


@dataclass(frozen=True)
class PageGenerationResult:
    page: DocPageRecord
    validation_errors: list[str]


class WikiPageGenerator:
    def __init__(
        self,
        retriever: GraphRAGRetriever,
        llm: LLMGateway,
        *,
        store: SQLiteStore,
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        self.store = store

    async def generate_page(
        self,
        repo_id: str,
        item: dict[str, Any],
        *,
        language_code: str = "en",
        parent_slug: str | None = None,
        child_pages: list[DocPageRecord] | None = None,
    ) -> PageGenerationResult:
        repo = self.store.get_repo(repo_id)
        if repo is None:
            raise ValueError(f"Repository not found: {repo_id}")

        title = str(item.get("title") or "Untitled")
        slug = _slugify(str(item.get("slug") or item.get("path") or title))
        topic = str(item.get("topic") or title)
        source_hints = _source_hints_from_item(item)
        trace = await self.retriever.retrieve(repo_id, topic, max_hops=PAGE_RETRIEVAL_MAX_HOPS)
        trace = _trace_with_source_hint_chunks(trace, self.store, repo_id, source_hints)
        graph_refs = _graph_refs_from_trace(trace)
        allowed_source_refs = _source_refs_from_chunks(trace.source_chunks)
        diagram_plan = _mermaid_diagrams_from_trace(trace, title=title, source_refs=[])
        readfile_evidence = readfile_evidence_for_page(
            repo_path=repo.path,
            allowed_source_refs=allowed_source_refs,
            source_hints=source_hints,
        )
        child_page_summaries = _child_page_summaries(child_pages or [])
        user_payload = self._page_payload(
            repo,
            item,
            trace,
            title=title,
            slug=slug,
            topic=topic,
            parent_slug=parent_slug,
            language_code=language_code,
            source_hints=source_hints,
            allowed_source_refs=allowed_source_refs,
            readfile_evidence=readfile_evidence,
            child_page_summaries=child_page_summaries,
            diagram_slots=_diagram_slots_payload(diagram_plan),
        )

        payload: dict[str, Any] = {}
        markdown = ""
        source_refs: list[dict[str, Any]] = []
        validation_errors: list[str] = []
        attempt_payload = user_payload
        prompt = _load_prompt("page.md")

        for attempt in range(PAGE_GENERATION_ATTEMPTS):
            completion = await complete_with_cache(
                self.store,
                repo_id,
                llm=self.llm,
                task_type="page",
                messages=_page_messages(prompt, attempt_payload, validation_errors if attempt else []),
                input_payload=attempt_payload,
                cache_key=f"{PAGE_CACHE_VERSION}:{slug}:{trace.trace_id}:attempt:{attempt + 1}",
                model_alias="page",
                prompt_version=PAGE_PROMPT_VERSION,
                response_format="json_object",
            )
            result = completion.result

            try:
                payload = _json_object(result.content)
            except ValueError as exc:
                validation_errors = [str(exc)]
                self.store.update_llm_run_status(
                    completion.run.id,
                    status="error",
                    error=str(exc),
                )
                attempt_payload = _page_json_repair_payload(user_payload, result.content, validation_errors)
                continue

            markdown, source_refs, validation_errors = self._validate_page_response(
                repo=repo,
                payload=payload,
                title=title,
                trace=trace,
                allowed_source_refs=allowed_source_refs,
                read_source_refs=readfile_evidence.source_refs,
                available_diagram_slots={diagram.slot for diagram in diagram_plan},
            )
            if not validation_errors:
                break
            self.store.update_llm_run_status(
                completion.run.id,
                status="error",
                error="; ".join(validation_errors),
            )
            attempt_payload = _page_validation_repair_payload(user_payload, payload, validation_errors)

        status = "generated" if not validation_errors else "draft"
        if status == "generated":
            markdown = _replace_citation_markers(markdown, source_refs)
            diagrams = _mermaid_diagrams_from_trace(trace, title=title, source_refs=source_refs)
            markdown = _compose_page_markdown(markdown, diagrams, source_refs)
            mermaid_errors = await validate_mermaid_blocks_async(markdown)
            if mermaid_errors:
                validation_errors.extend(mermaid_errors)
                status = "draft"
                markdown = _draft_markdown(title, validation_errors)
        else:
            markdown = _draft_markdown(title, validation_errors)

        page = DocPageRecord(
            id=uuid.uuid4().hex,
            repo_id=repo_id,
            language_code=language_code,
            slug=slug,
            title=str(payload.get("title") or title),
            parent_slug=parent_slug,
            markdown=markdown,
            source_refs=source_refs,
            graph_refs=sorted(graph_refs),
            status=status,
            updated_at=None,
        )
        return PageGenerationResult(
            page=self.store.upsert_doc_page(page),
            validation_errors=validation_errors,
        )

    def _page_payload(
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
        child_page_summaries: list[dict[str, object]],
        diagram_slots: list[dict[str, object]],
    ) -> dict[str, Any]:
        catalog = self.store.get_latest_doc_catalog(repo.id, language_code=language_code)
        catalog_context = _catalog_context_for_page(
            catalog.structure.get("items", []) if catalog else [],
            slug=slug,
            parent_slug=parent_slug,
        )
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
                evidence_inventory=_evidence_inventory(trace),
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
            "evidence_inventory": _evidence_inventory(trace),
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
                edge
                for edge in trace.related_edges
                if edge.get("type") in SOURCE_EDGE_TYPES
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

    def _validate_page_response(
        self,
        *,
        repo: RepoDescriptor,
        payload: dict[str, Any],
        title: str,
        trace: RetrievalTrace,
        allowed_source_refs: list[dict[str, object]],
        read_source_refs: list[dict[str, Any]],
        available_diagram_slots: set[str],
    ) -> tuple[str, list[dict[str, Any]], list[str]]:
        markdown = _strip_llm_mermaid(str(payload.get("markdown") or ""))
        source_url_base = _source_url_base(repo.git_url, repo.commit_hash)
        source_refs, source_ref_errors = _validate_source_refs(
            repo_path=repo.path,
            requested_refs=payload.get("source_refs"),
            source_chunks=trace.source_chunks,
            allowed_source_refs=allowed_source_refs,
            source_url_base=source_url_base,
        )
        source_refs = _include_markdown_citation_refs(
            markdown,
            source_refs,
            allowed_source_refs,
            source_url_base=source_url_base,
        )
        source_refs = _filter_unused_source_refs(markdown, source_refs)
        if not source_refs:
            validation_errors = [*source_ref_errors, "At least one valid source_ref is required."]
        else:
            source_refs = _merge_recorded_source_refs(
                source_refs,
                read_source_refs,
                source_url_base=source_url_base,
            )
            validation_errors = []
            markdown = _strip_unknown_citation_markers(markdown, source_refs)

        validation_errors.extend(_validate_page_markdown(markdown, title))
        validation_errors.extend(_validate_citation_markers(markdown, source_refs))
        validation_errors.extend(_validate_diagram_placeholders(markdown, available_diagram_slots))
        return markdown, source_refs, validation_errors


def _merge_recorded_source_refs(
    source_refs: list[dict[str, Any]],
    read_source_refs: list[dict[str, Any]],
    *,
    source_url_base: str | None,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for ref in [*source_refs, *read_source_refs]:
        file_path = ref.get("file_path")
        start_line = ref.get("start_line")
        end_line = ref.get("end_line")
        if not isinstance(file_path, str) or not isinstance(start_line, int) or not isinstance(end_line, int):
            continue
        key = (file_path, start_line, end_line)
        if key in seen:
            if ref.get("read_via"):
                for existing_ref in merged:
                    if (
                        existing_ref.get("file_path"),
                        existing_ref.get("start_line"),
                        existing_ref.get("end_line"),
                    ) == key:
                        existing_ref.setdefault("read_via", ref["read_via"])
                        break
            continue
        seen.add(key)
        merged_ref = dict(ref)
        if source_url_base and "source_url" not in merged_ref:
            merged_ref["source_url"] = _source_url(source_url_base, file_path, start_line, end_line)
        merged.append(merged_ref)
    return merged


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


def _page_json_repair_payload(
    user_payload: dict[str, Any],
    previous_response: str,
    validation_errors: list[str],
) -> dict[str, Any]:
    return {
        **user_payload,
        "previous_response": previous_response[:6000],
        "validation_errors": validation_errors,
        "repair_instructions": (
            "Repair the page response. Return one valid JSON object only, with title, "
            "markdown, and source_refs. Use only diagram placeholders listed in diagram_slots. "
            "Do not include prose, comments, Markdown fences around the JSON, or trailing commas."
        ),
    }


def _page_validation_repair_payload(
    user_payload: dict[str, Any],
    previous_response: dict[str, Any],
    validation_errors: list[str],
) -> dict[str, Any]:
    return {
        **user_payload,
        "previous_response": previous_response,
        "validation_errors": validation_errors,
        "repair_instructions": (
            "Repair the page so it validates. Keep the same title, include the required "
            "Purpose and Scope section, choose source_refs from allowed_source_refs, and "
            "only use [[S#]] markers for source_refs you return. Remove any unknown diagram "
            "placeholder, or use exact placeholders from diagram_slots."
        ),
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
