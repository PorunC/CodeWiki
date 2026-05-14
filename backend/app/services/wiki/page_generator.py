import uuid
from dataclasses import dataclass
from typing import Any

from backend.app.database import DocPageRecord, SQLiteStore
from backend.app.services.graph_rag import GraphRAGRetriever, RetrievalTrace
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.llm_run_recorder import complete_with_cache
from backend.app.services.repo_scanner import RepoDescriptor
from backend.app.services.wiki.catalog import (
    _catalog_context_for_page,
    _slugify,
    _source_hints_from_item,
    _trace_with_source_hint_chunks,
)
from backend.app.services.wiki.diagrams import (
    MAX_MERMAID_EDGES,
    SOURCE_EDGE_TYPES,
    _graph_refs_from_trace,
    _mermaid_from_trace,
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
    _source_url_base,
    _strip_unknown_citation_markers,
    _validate_citation_markers,
    _validate_source_refs,
)

PAGE_GENERATION_ATTEMPTS = 2


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
        parent_slug: str | None = None,
    ) -> PageGenerationResult:
        repo = self.store.get_repo(repo_id)
        if repo is None:
            raise ValueError(f"Repository not found: {repo_id}")

        title = str(item.get("title") or "Untitled")
        slug = _slugify(str(item.get("slug") or item.get("path") or title))
        topic = str(item.get("topic") or title)
        source_hints = _source_hints_from_item(item)
        trace = await self.retriever.retrieve(repo_id, topic, max_hops=2)
        trace = _trace_with_source_hint_chunks(trace, self.store, repo_id, source_hints)
        graph_refs = _graph_refs_from_trace(trace)
        allowed_source_refs = _source_refs_from_chunks(trace.source_chunks)
        user_payload = self._page_payload(
            repo,
            item,
            trace,
            title=title,
            slug=slug,
            topic=topic,
            parent_slug=parent_slug,
            source_hints=source_hints,
            allowed_source_refs=allowed_source_refs,
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
                cache_key=f"page:{slug}:{trace.trace_id}:attempt:{attempt + 1}",
                model_alias="page",
                prompt_version="page:deepwiki:v2",
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
            graph_markdown = _mermaid_from_trace(trace, title=title, source_refs=source_refs)
            markdown = _compose_page_markdown(markdown, graph_markdown, source_refs)
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
        source_hints: list[str],
        allowed_source_refs: list[dict[str, object]],
    ) -> dict[str, Any]:
        catalog = self.store.get_latest_doc_catalog(repo.id)
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
            "documentation_style": {
                "name": "DeepWiki",
                "workflow": [
                    "gather evidence from source_chunks and graph_facts",
                    "think through subsystem boundaries and verified relationships",
                    "write concise Markdown with section-level Sources lines",
                ],
                "required_sections": [
                    "Purpose and Scope",
                    "source-grounded subsystem explanation",
                    "compact tables for components or flows when useful",
                ],
                "server_injected_sections": [
                    "Relevant source files",
                    "Graph",
                    "Sources",
                ],
            },
            "detail_expectations": {
                "minimum_depth": (
                    "Cover responsibility, lifecycle/control flow, dependencies, data surfaces, "
                    "APIs or UI routes, configuration, extension points, and failure handling "
                    "when those details are present in the evidence."
                ),
                "preferred_tables": [
                    "component/file/responsibility/evidence",
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
            },
            "context_pack": trace.context_pack,
            "source_chunks": trace.source_chunks,
            "allowed_source_refs": allowed_source_refs,
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
                    "sequence": "sequenceDiagram for request/response or multi-agent interactions",
                    "data_model": "classDiagram for schemas, classes, DTOs, and inheritance",
                },
                "grouping": "Prefer subgraphs or grouped components over function-level calls.",
            },
            "required_json_shape": {
                "title": title,
                "markdown": (
                    "# Page title\n\n## Purpose and Scope\n\n"
                    "Grounded Markdown with inline [[S1]] citations and no Mermaid fences."
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
            validation_errors = []
            markdown = _strip_unknown_citation_markers(markdown, source_refs)

        validation_errors.extend(_validate_page_markdown(markdown, title))
        validation_errors.extend(_validate_citation_markers(markdown, source_refs))
        return markdown, source_refs, validation_errors


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
            "markdown, and source_refs. Do not include prose, comments, Markdown fences "
            "around the JSON, or trailing commas."
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
            "only use [[S#]] markers for source_refs you return."
        ),
    }
