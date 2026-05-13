import json
import uuid
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from backend.app.database import DocCatalogRecord, DocPageRecord, SQLiteStore, get_store
from backend.app.services.graph_rag import GraphRAGRetriever
from backend.app.services.llm_gateway import LLMGateway, LLMResult
from backend.app.services.repo_context import RepositoryContextBuilder
from backend.app.services.wiki.catalog import (
    _catalog_context_for_page,
    _catalog_items_for_generation,
    _normalize_catalog_payload,
    _source_chunk_summaries,
    _source_hints_from_item,
    _slugify,
    _trace_with_source_hint_chunks,
    _validate_catalog_payload,
)
from backend.app.services.wiki.diagrams import (
    MAX_MERMAID_EDGES,
    SOURCE_EDGE_TYPES,
    _graph_refs_from_trace,
    _mermaid_from_trace,
)
from backend.app.services.wiki.markdown import _strip_llm_mermaid, _validate_page_markdown
from backend.app.services.wiki.prompts import (
    _catalog_messages,
    _json_object,
    _load_prompt,
    _page_messages,
)
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

CATALOG_GENERATION_ATTEMPTS = 3
PAGE_GENERATION_ATTEMPTS = 2


@dataclass(frozen=True)
class PageGenerationResult:
    page: DocPageRecord
    validation_errors: list[str]


class WikiGenerator:
    def __init__(
        self,
        retriever: GraphRAGRetriever,
        llm: LLMGateway,
        *,
        store: SQLiteStore | None = None,
        context_builder: RepositoryContextBuilder | None = None,
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        self.store = store or get_store()
        self.context_builder = context_builder or RepositoryContextBuilder()

    async def generate_catalog(self, repo_id: str) -> DocCatalogRecord:
        repo = self.store.get_repo(repo_id)
        if repo is None:
            raise ValueError(f"Repository not found: {repo_id}")

        trace = await self.retriever.retrieve(repo_id, "repository overview", max_hops=2)
        repo_context = self.context_builder.build(repo.path)
        prompt = _load_prompt("catalog.md")
        user_payload = {
            "repo": {
                "id": repo.id,
                "name": repo.name,
                "path": repo.path,
                "git_url": repo.git_url,
                "commit_hash": repo.commit_hash,
            },
            "documentation_style": {
                "name": "DeepWiki",
                "shape": (
                    "hierarchical developer wiki with Overview first, subsystem pages, "
                    "workflow drill-downs, and source-grounded topics"
                ),
                "audiences": [
                    "new developers who need orientation and getting-started guidance",
                    "users who need how-to-use pages for API or UI surfaces",
                    "contributors who need architecture and developer guide pages",
                    "operators who need configuration, deployment, and operations pages when evidenced",
                ],
                "preferred_top_level_flow": [
                    "Overview",
                    "Getting Started or User Guide",
                    "System Architecture",
                    "Core Workflows",
                    "API Reference",
                    "Developer Guide",
                    "Operations",
                ],
                "catalog_design": [
                    "group related files and symbols into logical feature or subsystem pages",
                    "use parent categories for navigation and leaf pages for implementation detail",
                    "avoid file-by-file catalogs unless a file is the public surface",
                    "exclude tests/docs/generated output from core feature pages unless explicitly scoped",
                ],
            },
            "catalog_design_requirements": {
                "coverage": [
                    "runtime entry points and bootstrapping",
                    "public API or UI surfaces",
                    "core services, workflows, pipelines, and background jobs",
                    "data models, persistence, schemas, and migrations",
                    "configuration, deployment, and operational concerns when evidenced",
                ],
                "source_hint_priorities": [
                    "P0 primary implementation files",
                    "P1 public contracts, schemas, routes, and UI entry points",
                    "P2 configuration and environment files",
                    "P3 representative tests only when they clarify behavior",
                ],
            },
            "repository_context": repo_context.as_dict(),
            "context_pack": trace.context_pack,
            "seed_nodes": trace.seed_nodes,
            "expanded_nodes": trace.expanded_nodes[:40],
            "community_summaries": trace.community_summaries,
            "source_chunks": _source_chunk_summaries(trace.source_chunks),
            "required_json_shape": {
                "title": "Code Wiki",
                "items": [
                    {
                        "title": "Overview",
                        "slug": "overview",
                        "path": "overview",
                        "order": 0,
                        "kind": "page",
                        "topic": "repository overview",
                        "source_hints": ["README.md"],
                        "children": [
                            {
                                "title": "Architecture",
                                "slug": "architecture",
                                "path": "architecture",
                                "order": 1,
                                "kind": "page",
                                "topic": "repository architecture and core components",
                                "source_hints": [],
                                "children": [],
                            }
                        ],
                    }
                ],
            },
        }
        payload: dict[str, Any] | None = None
        validation_errors: list[str] = []
        attempt_payload = user_payload
        for attempt in range(CATALOG_GENERATION_ATTEMPTS):
            result = await self.llm.complete(
                "catalog",
                _catalog_messages(prompt, attempt_payload, validation_errors),
                response_format="json_object",
            )
            self._record_llm_run(
                repo_id,
                task_type="catalog",
                result=result,
                input_payload=attempt_payload,
                cache_key=f"catalog:{trace.trace_id}:attempt:{attempt + 1}",
            )
            try:
                payload = _json_object(result.content)
                _validate_catalog_payload(payload)
                validation_errors = []
                break
            except ValueError as exc:
                validation_errors = [str(exc)]
                attempt_payload = {
                    **user_payload,
                    "previous_response": result.content[:6000],
                    "validation_errors": validation_errors,
                    "repair_instructions": (
                        "Repair the catalog. Return valid JSON only, with a top-level object "
                        "containing title and items. Do not include Markdown or comments."
                    ),
                }
        if payload is None:
            raise ValueError(
                "LLM did not return a valid catalog JSON object after repair attempts: "
                + "; ".join(validation_errors)
            )
        title, items = _normalize_catalog_payload(payload, repo.name)
        return self.store.save_doc_catalog(repo_id, title=title, structure={"items": items})

    async def generate_all_pages(self, repo_id: str) -> list[PageGenerationResult]:
        catalog = self.store.get_latest_doc_catalog(repo_id)
        if catalog is None:
            catalog = await self.generate_catalog(repo_id)
        results: list[PageGenerationResult] = []
        for item, parent_slug in _catalog_items_for_generation(catalog.structure.get("items", [])):
            results.append(await self.generate_page(repo_id, item, parent_slug=parent_slug))
        self.store.delete_doc_pages_not_in(
            repo_id,
            [result.page.slug for result in results],
        )
        return results

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
        catalog = self.store.get_latest_doc_catalog(repo_id)
        catalog_context = _catalog_context_for_page(
            catalog.structure.get("items", []) if catalog else [],
            slug=slug,
            parent_slug=parent_slug,
        )
        prompt = _load_prompt("page.md")
        user_payload = {
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

        payload: dict[str, Any] = {}
        markdown = ""
        source_refs: list[dict[str, Any]] = []
        validation_errors: list[str] = []
        attempt_payload = user_payload
        for attempt in range(PAGE_GENERATION_ATTEMPTS):
            result = await self.llm.complete(
                "page",
                _page_messages(prompt, attempt_payload, validation_errors if attempt else []),
                response_format="json_object",
            )
            self._record_llm_run(
                repo_id,
                task_type="page",
                result=result,
                input_payload=attempt_payload,
                cache_key=f"page:{slug}:{trace.trace_id}:attempt:{attempt + 1}",
            )

            payload = _json_object(result.content)
            markdown = _strip_llm_mermaid(str(payload.get("markdown") or ""))
            source_refs, source_ref_errors = _validate_source_refs(
                repo_path=repo.path,
                requested_refs=payload.get("source_refs"),
                source_chunks=trace.source_chunks,
                allowed_source_refs=allowed_source_refs,
                source_url_base=_source_url_base(repo.git_url, repo.commit_hash),
            )
            source_refs = _include_markdown_citation_refs(
                markdown,
                source_refs,
                allowed_source_refs,
                source_url_base=_source_url_base(repo.git_url, repo.commit_hash),
            )
            source_refs = _filter_unused_source_refs(markdown, source_refs)
            if not source_refs:
                validation_errors = source_ref_errors
                validation_errors.append("At least one valid source_ref is required.")
            else:
                validation_errors = []
                markdown = _strip_unknown_citation_markers(markdown, source_refs)

            validation_errors.extend(_validate_page_markdown(markdown, title))
            validation_errors.extend(_validate_citation_markers(markdown, source_refs))
            if not validation_errors:
                break
            attempt_payload = {
                **user_payload,
                "previous_response": payload,
                "validation_errors": validation_errors,
                "repair_instructions": (
                    "Repair the page so it validates. Keep the same title, include the required "
                    "Purpose and Scope section, choose source_refs from allowed_source_refs, and "
                    "only use [[S#]] markers for source_refs you return."
                ),
            }

        status = "generated" if not validation_errors else "draft"
        if status == "generated":
            markdown = _replace_citation_markers(markdown, source_refs)
            graph_markdown = _mermaid_from_trace(trace, title=title, source_refs=source_refs)
            markdown = _compose_page_markdown(markdown, graph_markdown, source_refs)
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

    async def regenerate_page(self, repo_id: str, slug: str) -> PageGenerationResult:
        catalog = self.store.get_latest_doc_catalog(repo_id)
        if catalog is None:
            raise ValueError("Generate a catalog before regenerating pages.")
        for item, parent_slug in _catalog_items_for_generation(catalog.structure.get("items", [])):
            if _slugify(str(item.get("slug") or item.get("path") or item.get("title") or "")) == slug:
                return await self.generate_page(repo_id, item, parent_slug=parent_slug)
        raise ValueError(f"Catalog page not found: {slug}")

    def _record_llm_run(
        self,
        repo_id: str,
        *,
        task_type: str,
        result: LLMResult,
        input_payload: dict[str, Any],
        cache_key: str,
    ) -> None:
        usage = result.usage or {}
        self.store.record_llm_run(
            repo_id,
            task_type=task_type,
            provider=result.model.split("/", 1)[0] if "/" in result.model else None,
            model=result.model,
            model_alias=task_type,
            prompt_version=f"{task_type}:deepwiki:v2",
            input_hash=sha256(json.dumps(input_payload, sort_keys=True).encode("utf-8")).hexdigest(),
            cache_key=cache_key,
            tokens_in=int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
        )

