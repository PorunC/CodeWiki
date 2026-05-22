from typing import Any

from backend.app.database import DocCatalogRecord, CodeWikiStore
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.graph import CodeGraphEdge, CodeGraphNode
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.llm_operations import CachedLLMService, LLMOperation
from backend.app.services.repo_context import RepositoryContextBuilder
from backend.app.services.wiki.catalog import (
    _normalize_catalog_payload,
    _source_chunk_summaries,
    _validate_catalog_payload,
)
from backend.app.services.wiki.catalog_limits import (
    CatalogScaleLimits,
    catalog_limits_for_repo,
)
from backend.app.services.wiki.catalog_planner import CatalogModuleCandidatePlanner
from backend.app.services.wiki.page_payload_template import prompt_graph_facts
from backend.app.services.wiki.prompts import _catalog_messages, _json_object, _load_prompt

CATALOG_GENERATION_ATTEMPTS = 3


class WikiCatalogGenerator:
    def __init__(
        self,
        retriever: GraphRAGRetriever,
        llm: LLMGateway,
        *,
        store: CodeWikiStore,
        context_builder: RepositoryContextBuilder,
        candidate_planner: CatalogModuleCandidatePlanner | None = None,
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        self.store = store
        self.context_builder = context_builder
        self.candidate_planner = candidate_planner or CatalogModuleCandidatePlanner()
        self.llm_service = CachedLLMService(store=self.store, llm=self.llm)

    async def generate_catalog(
        self,
        repo_id: str,
        *,
        language_code: str = "en",
    ) -> DocCatalogRecord:
        repo = self.store.get_repo(repo_id)
        if repo is None:
            raise ValueError(f"Repository not found: {repo_id}")

        trace = await self.retriever.retrieve(repo_id, "repository overview", max_hops=3)
        nodes, edges = self.store.get_graph(repo.id)
        catalog_limits = catalog_limits_for_repo(
            nodes,
            edges,
            chunk_count=len(self.store.list_code_chunks(repo.id)),
            community_count=len(self.store.list_graph_communities(repo.id)),
        )
        user_payload = self._catalog_payload(
            repo,
            trace,
            language_code=language_code,
            nodes=nodes,
            edges=edges,
            catalog_limits=catalog_limits,
        )
        prompt = _load_prompt("catalog.md")
        payload: dict[str, Any] | None = None
        validation_errors: list[str] = []
        attempt_payload = user_payload

        for attempt in range(CATALOG_GENERATION_ATTEMPTS):
            completion = await self.llm_service.complete(
                repo_id,
                LLMOperation(
                    task_type="catalog",
                    messages=_catalog_messages(prompt, attempt_payload, validation_errors),
                    input_payload=attempt_payload,
                    cache_namespace="catalog:v4",
                    cache_parts=(trace.trace_id, "attempt", attempt + 1),
                    model_alias="catalog",
                    prompt_version="catalog:deepwiki:v4",
                    response_format="json_object",
                ),
            )
            result = completion.result
            try:
                payload = _json_object(result.content)
                _validate_catalog_payload(payload)
                validation_errors = []
                break
            except ValueError as exc:
                validation_errors = [str(exc)]
                self.store.update_llm_run_status(
                    completion.run.id,
                    status="error",
                    error=str(exc),
                )
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
        title, items = _normalize_catalog_payload(payload, repo.name, limits=catalog_limits)
        return self.store.save_doc_catalog(
            repo_id,
            title=title,
            structure={"items": items},
            language_code=language_code,
        )

    def _catalog_payload(
        self,
        repo: Any,
        trace: Any,
        *,
        language_code: str,
        nodes: list[CodeGraphNode],
        edges: list[CodeGraphEdge],
        catalog_limits: CatalogScaleLimits,
    ) -> dict[str, Any]:
        repo_context = self.context_builder.build(repo.path)
        graph_facts = prompt_graph_facts(trace)
        return {
            "repo": {
                "id": repo.id,
                "name": repo.name,
                "path": repo.path,
                "git_url": repo.git_url,
                "commit_hash": repo.commit_hash,
            },
            "language_code": language_code,
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
                    "Architecture",
                    "Reading Guide",
                    "Dependencies",
                    "Getting Started or User Guide",
                    "Core Workflows",
                    "API Reference",
                    "Developer Guide",
                    "Operations",
                ],
                "catalog_design": [
                    "group related files and symbols into logical feature or subsystem pages",
                    "use parent categories for navigation and leaf pages for implementation detail",
                    (
                        "split broad modules into child pages by workflow, API surface, data "
                        "contract, UI surface, provider, or operational concern"
                    ),
                    "avoid file-by-file catalogs unless a file is the public surface",
                    "exclude tests/docs/generated output from core feature pages unless explicitly scoped",
                ],
            },
            "catalog_scale": catalog_limits.as_prompt_payload(),
            "granularity_contract": {
                "target_top_level_sections": catalog_limits.target_top_level_sections,
                "target_total_pages": catalog_limits.target_total_pages,
                "target_depth": catalog_limits.target_depth,
                "split_triggers": [
                    "a directory or subsystem owns 3+ source files",
                    "a module mixes routes/controllers, services, models, configuration, and UI",
                    "a workflow has separate ingestion, planning, execution, validation, and rendering stages",
                    "a public API or UI surface has multiple screens, endpoints, commands, or export formats",
                    "a data layer has separate schema, repositories, persistence, migrations, or caching concerns",
                ],
                "leaf_page_scope": (
                    "Each leaf should cover one concrete subsystem, workflow stage, public surface, "
                    "data contract family, UI view, or extension point with narrow source_hints."
                ),
                "anti_patterns": [
                    "one huge Backend page that hides services, API routes, data models, and background jobs",
                    "one huge Frontend page that hides pages, hooks, rendering, graph UI, wiki UI, and exports",
                    "thin one-file pages for private helpers that should be part of a nearby workflow page",
                ],
            },
            "catalog_design_requirements": {
                "required_special_pages": [
                    "Overview",
                    "Architecture",
                    "Reading Guide",
                    "Dependencies",
                ],
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
            "module_candidates": self.candidate_planner.build(nodes, edges),
            "context_pack": _catalog_context_pack(trace.context_pack),
            "seed_nodes": graph_facts["seed_nodes"],
            "expanded_nodes": graph_facts["expanded_nodes"][:80],
            "community_edges": graph_facts.get("community_edges", []),
            "community_summaries": graph_facts["community_summaries"],
            "community_hierarchy": graph_facts.get("community_hierarchy", []),
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
                        "children": [],
                    },
                    {
                        "title": "Backend Services",
                        "slug": "backend-services",
                        "path": "backend-services",
                        "order": 4,
                        "kind": "category",
                        "topic": "backend service layer, API routes, storage, and background workflows",
                        "source_hints": [],
                        "children": [
                            {
                                "title": "API Routes",
                                "slug": "api-routes",
                                "path": "backend-services/api-routes",
                                "order": 0,
                                "kind": "page",
                                "topic": "FastAPI route modules, request payloads, response payloads, and service boundaries",
                                "source_hints": ["backend/app/api"],
                                "children": [],
                            },
                            {
                                "title": "Wiki Generation",
                                "slug": "wiki-generation",
                                "path": "backend-services/wiki-generation",
                                "order": 1,
                                "kind": "category",
                                "topic": "catalog generation, page generation, translation, sources, and diagrams",
                                "source_hints": ["backend/app/services/wiki"],
                                "children": [
                                    {
                                        "title": "Catalog Planning",
                                        "slug": "catalog-planning",
                                        "path": "backend-services/wiki-generation/catalog-planning",
                                        "order": 0,
                                        "kind": "page",
                                        "topic": (
                                            "wiki catalog generation, hierarchy planning, "
                                            "source hints, and module candidates"
                                        ),
                                        "source_hints": ["backend/app/services/wiki/catalog_generator.py"],
                                        "children": [],
                                    }
                                ],
                            },
                        ],
                    }
                ],
            },
        }


def _catalog_context_pack(context_pack: dict[str, object]) -> dict[str, object]:
    return {
        key: context_pack[key]
        for key in (
            "token_count",
            "node_count",
            "edge_count",
            "chunk_count",
            "community_count",
            "source_chunk_ids",
            "node_ids",
            "edge_ids",
            "community_ids",
        )
        if key in context_pack
    }
