from typing import Any

from backend.app.database import DocCatalogRecord, SQLiteStore
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

        trace = await self.retriever.retrieve(repo_id, "repository overview", max_hops=2)
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
                cache_key=f"catalog:v3:{trace.trace_id}:attempt:{attempt + 1}",
                model_alias="catalog",
                prompt_version="catalog:deepwiki:v3",
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
                    "avoid file-by-file catalogs unless a file is the public surface",
                    "exclude tests/docs/generated output from core feature pages unless explicitly scoped",
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
                        "children": [],
                    },
                    {
                        "title": "Architecture",
                        "slug": "architecture",
                        "path": "architecture",
                        "order": 1,
                        "kind": "page",
                        "topic": "repository architecture, runtime layers, and core components",
                        "source_hints": [],
                        "children": [],
                    },
                    {
                        "title": "Reading Guide",
                        "slug": "reading-guide",
                        "path": "reading-guide",
                        "order": 2,
                        "kind": "page",
                        "topic": "recommended reading order for repository comprehension",
                        "source_hints": ["README.md"],
                        "children": [],
                    },
                    {
                        "title": "Dependencies",
                        "slug": "dependencies",
                        "path": "dependencies",
                        "order": 3,
                        "kind": "page",
                        "topic": "internal and external dependency relationships",
                        "source_hints": [],
                        "children": [],
                    }
                ],
            },
        }
