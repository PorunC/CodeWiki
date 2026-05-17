from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from backend.app.database import DocCatalogRecord, SQLiteStore
from backend.app.services.graph import CodeGraphEdge, CodeGraphNode
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.llm_run_recorder import complete_with_cache
from backend.app.services.repo_context import RepositoryContextBuilder
from backend.app.services.wiki.catalog import (
    _normalize_catalog_payload,
    _source_chunk_summaries,
    _validate_catalog_payload,
)
from backend.app.services.wiki.prompts import _catalog_messages, _json_object, _load_prompt

CATALOG_GENERATION_ATTEMPTS = 3


@dataclass
class _ModuleCandidateDraft:
    path: str
    files: set[str] = field(default_factory=set)
    node_types: Counter[str] = field(default_factory=Counter)
    symbols: list[dict[str, str]] = field(default_factory=list)
    edge_types: Counter[str] = field(default_factory=Counter)


class WikiCatalogGenerator:
    def __init__(
        self,
        retriever: GraphRAGRetriever,
        llm: LLMGateway,
        *,
        store: SQLiteStore,
        context_builder: RepositoryContextBuilder,
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        self.store = store
        self.context_builder = context_builder

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
        user_payload = self._catalog_payload(repo, trace, language_code=language_code)
        prompt = _load_prompt("catalog.md")
        payload: dict[str, Any] | None = None
        validation_errors: list[str] = []
        attempt_payload = user_payload

        for attempt in range(CATALOG_GENERATION_ATTEMPTS):
            completion = await complete_with_cache(
                self.store,
                repo_id,
                llm=self.llm,
                task_type="catalog",
                messages=_catalog_messages(prompt, attempt_payload, validation_errors),
                input_payload=attempt_payload,
                cache_key=f"catalog:v4:{trace.trace_id}:attempt:{attempt + 1}",
                model_alias="catalog",
                prompt_version="catalog:deepwiki:v4",
                response_format="json_object",
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
        title, items = _normalize_catalog_payload(payload, repo.name)
        return self.store.save_doc_catalog(
            repo_id,
            title=title,
            structure={"items": items},
            language_code=language_code,
        )

    def _catalog_payload(self, repo: Any, trace: Any, *, language_code: str) -> dict[str, Any]:
        repo_context = self.context_builder.build(repo.path)
        nodes, edges = self.store.get_graph(repo.id)
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
            "granularity_contract": {
                "target_top_level_sections": "6-10 high-signal sections including required special pages",
                "target_total_pages": (
                    "16-32 focused pages for medium repositories; use fewer only when the evidence "
                    "is genuinely small, and more when distinct subsystems are visible"
                ),
                "target_depth": "2-3 levels for complex areas; never deeper than 4 levels",
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
            "module_candidates": _module_candidates(nodes, edges),
            "context_pack": trace.context_pack,
            "seed_nodes": trace.seed_nodes,
            "expanded_nodes": trace.expanded_nodes[:80],
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


def _module_candidates(
    nodes: list[CodeGraphNode],
    edges: list[CodeGraphEdge],
) -> list[dict[str, object]]:
    groups: dict[str, _ModuleCandidateDraft] = {}
    node_module: dict[str, str] = {}
    for node in nodes:
        file_path = node.file_path or ""
        if not file_path:
            continue
        module_path = _module_path(file_path)
        node_module[node.id] = module_path
        group = groups.setdefault(module_path, _ModuleCandidateDraft(path=module_path))
        group.files.add(file_path)
        group.node_types[node.type] += 1
        if node.type != "file" and len(group.symbols) < 18:
            group.symbols.append(
                {
                    "name": node.name,
                    "type": node.type,
                    "file_path": file_path,
                }
            )

    for edge in edges:
        source_module = node_module.get(edge.source_id)
        target_module = node_module.get(edge.target_id)
        if not source_module or source_module != target_module:
            continue
        group = groups.get(source_module)
        if group is not None:
            group.edge_types[edge.type] += 1

    candidates = []
    for group in groups.values():
        files = sorted(group.files)
        candidates.append(
            {
                "path": group.path,
                "file_count": len(files),
                "files": files[:12],
                "node_types": dict(group.node_types.most_common(8)),
                "edge_types": dict(group.edge_types.most_common(8)),
                "symbols": group.symbols,
                "split_hint": _split_hint(group.path, files, group.node_types),
            }
        )
    return sorted(
        candidates,
        key=lambda item: (-int(item["file_count"]), str(item["path"])),
    )[:36]


def _module_path(file_path: str) -> str:
    parts = PurePosixPath(file_path).parts
    if len(parts) <= 1:
        return "."
    directory_parts = parts[:-1]
    if not directory_parts:
        return "."
    if directory_parts[0] in {"backend", "frontend"} and len(directory_parts) >= 3:
        return "/".join(directory_parts[:4])
    return "/".join(directory_parts[:3])


def _split_hint(path: str, files: list[str], node_types: Counter[str]) -> str:
    names = {PurePosixPath(file_path).name.lower() for file_path in files}
    if any("api" in file_path or "routes" in file_path for file_path in files):
        return "Consider separate pages for public routes, request/response contracts, and service delegation."
    if any(name in names for name in {"models.py", "schema.py", "schemas.py", "database.py"}):
        return "Consider separate pages for data models, repositories, persistence, and migrations."
    if any("component" in node_type or node_type in {"component", "hook"} for node_type in node_types):
        return "Consider separate pages for UI views, reusable components, hooks, and user workflows."
    if len(files) >= 6:
        return f"Large module {path}; split by workflow stage, public surface, and extension point."
    if len(files) >= 3:
        return f"Medium module {path}; use at least one focused implementation leaf page."
    return f"Small module {path}; merge into a nearby broader page unless it is a public surface."
