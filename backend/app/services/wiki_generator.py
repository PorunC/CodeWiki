import json
import re
import uuid
from dataclasses import dataclass, replace
from hashlib import sha256
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import quote

from backend.app.database import DocCatalogRecord, DocPageRecord, SQLiteStore, get_store
from backend.app.services.graph_rag import GraphRAGRetriever, RetrievalTrace
from backend.app.services.llm_gateway import LLMGateway, LLMResult
from backend.app.services.repo_context import RepositoryContextBuilder

MERMAID_FENCE_RE = re.compile(r"```mermaid.*?```", re.DOTALL | re.IGNORECASE)
CITATION_MARKER_RE = re.compile(r"\[\[(S\d+)\]\]")
ABSTRACT_DIAGRAM_EDGE_TYPES = {"routes_to", "calls", "imports", "inherits", "exports"}
SOURCE_EDGE_TYPES = ABSTRACT_DIAGRAM_EDGE_TYPES | {"contains", "defines"}
SURFACE_NODE_TYPES = {"endpoint", "class", "schema", "interface"}
EDGE_LABEL_ORDER = ("routes_to", "calls", "imports", "inherits", "exports")
MAX_CATALOG_ITEMS = 14
MAX_MERMAID_EDGES = 28
MAX_MERMAID_COMPONENTS = 10
MAX_MERMAID_ABSTRACT_EDGES = 14
MAX_MERMAID_SURFACES = 10
MAX_SOURCE_HINT_CHUNKS = 10
MAX_SOURCE_HINT_CHUNKS_PER_FILE = 3
CATALOG_GENERATION_ATTEMPTS = 3
PAGE_GENERATION_ATTEMPTS = 2
REQUIRED_PAGE_HEADINGS = ("## Purpose and Scope",)


@dataclass(frozen=True)
class PageGenerationResult:
    page: DocPageRecord
    validation_errors: list[str]


@dataclass(frozen=True)
class _MermaidGroup:
    key: str
    label: str
    kind: str
    rank: int


@dataclass
class _MermaidEdgeAggregate:
    source_key: str
    target_key: str
    counts: dict[str, int]
    confidence_total: float = 0.0
    evidence_count: int = 0


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


def _page_messages(
    prompt: str,
    user_payload: dict[str, Any],
    validation_errors: list[str],
) -> list[dict[str, str]]:
    instruction = (
        "Return only a JSON object. Do not include Mermaid blocks; the server "
        "will generate abstract diagrams from validated graph facts. source_refs must "
        "be selected from allowed_source_refs. Use [[S#]] citation markers only "
        "for source refs you return. Use catalog_context.related_pages only for "
        "real related-page mentions; do not invent wiki pages or links."
    )
    if validation_errors:
        instruction = (
            f"{instruction}\nRepair the previous response. Validation errors: "
            f"{json.dumps(validation_errors, ensure_ascii=False)}"
        )
    return [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": f"{instruction}\n{json.dumps(user_payload, ensure_ascii=False)}",
        },
    ]


def _catalog_messages(
    prompt: str,
    user_payload: dict[str, Any],
    validation_errors: list[str],
) -> list[dict[str, str]]:
    instruction = (
        "Return only a valid JSON object. The object must contain `title` and `items`; "
        "`items` must be an array of catalog items. Do not include Markdown fences, "
        "comments, trailing commas, or prose outside JSON."
    )
    if validation_errors:
        instruction = (
            f"{instruction}\nRepair the previous response. Validation errors: "
            f"{json.dumps(validation_errors, ensure_ascii=False)}"
        )
    return [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": f"{instruction}\n{json.dumps(user_payload, ensure_ascii=False)}",
        },
    ]


def _load_prompt(name: str) -> str:
    return resources.files("backend.app.prompts").joinpath(name).read_text(encoding="utf-8")


def _json_object(content: str) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise ValueError("LLM did not return a JSON object.") from exc
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("LLM response must be a JSON object.")
    return payload


def _normalize_catalog_payload(payload: dict[str, Any], repo_name: str) -> tuple[str, list[dict[str, Any]]]:
    root = payload.get("catalog") if isinstance(payload.get("catalog"), dict) else payload
    title = str(root.get("title") or f"{repo_name} Wiki")
    raw_items = root.get("items") or root.get("pages") or []
    if not isinstance(raw_items, list):
        raise ValueError("Catalog response must contain an items array.")
    used_slugs: set[str] = set()
    items = [
        item
        for item in (
            _normalize_catalog_item(raw_item, used_slugs)
            for raw_item in raw_items[:MAX_CATALOG_ITEMS]
        )
        if item is not None
    ]
    if not items:
        items = [
            {
                "title": "Overview",
                "slug": "overview",
                "path": "overview",
                "order": 0,
                "kind": "page",
                "topic": "repository overview",
                "children": [],
            }
        ]
    items = _sort_catalog_items(items)
    return title, items


def _validate_catalog_payload(payload: dict[str, Any]) -> None:
    root = payload.get("catalog") if isinstance(payload.get("catalog"), dict) else payload
    raw_items = root.get("items") or root.get("pages")
    if not isinstance(raw_items, list):
        raise ValueError("Catalog response must contain an items array.")


def _normalize_catalog_item(raw_item: Any, used_slugs: set[str]) -> dict[str, Any] | None:
    if not isinstance(raw_item, dict):
        return None
    title = str(raw_item.get("title") or "").strip()
    if not title:
        return None
    slug = _unique_slug(_slugify(str(raw_item.get("slug") or raw_item.get("path") or title)), used_slugs)
    path = str(raw_item.get("path") or slug).strip().strip("/") or slug
    topic = str(raw_item.get("topic") or title)
    raw_kind = str(raw_item.get("kind") or "").strip().lower()
    kind = raw_kind if raw_kind in {"page", "category"} else "page"
    raw_order = raw_item.get("order")
    order = raw_order if isinstance(raw_order, int) and raw_order >= 0 else len(used_slugs) - 1
    source_hints = raw_item.get("source_hints") if isinstance(raw_item.get("source_hints"), list) else []
    raw_children = raw_item.get("children") or []
    children = []
    if isinstance(raw_children, list):
        children = [
            child
            for child in (_normalize_catalog_item(child, used_slugs) for child in raw_children[:8])
            if child is not None
        ]
    return {
        "title": title,
        "slug": slug,
        "path": path,
        "order": order,
        "kind": kind,
        "topic": topic,
        "source_hints": [str(hint) for hint in source_hints[:8]],
        "children": children,
    }


def _sort_catalog_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in items:
        children = item.get("children")
        if isinstance(children, list):
            item["children"] = _sort_catalog_items(children)
    return sorted(items, key=lambda item: (int(item.get("order") or 0), str(item.get("title") or "")))


def _catalog_context_for_page(
    items: list[Any],
    *,
    slug: str,
    parent_slug: str | None,
) -> dict[str, Any]:
    summaries = _catalog_item_summaries(items)
    current = next((item for item in summaries if item["slug"] == slug), None)
    parent = next((item for item in summaries if item["slug"] == parent_slug), None) if parent_slug else None
    related_pages = _related_catalog_pages(summaries, slug=slug, parent_slug=parent_slug)
    return {
        "current": current
        or {
            "title": "",
            "slug": slug,
            "path": slug,
            "kind": "page",
            "parent_slug": parent_slug,
            "depth": 0,
        },
        "parent": parent,
        "related_pages": related_pages,
        "page_count": sum(1 for item in summaries if item["kind"] == "page"),
    }


def _catalog_item_summaries(
    items: list[Any],
    *,
    parent_slug: str | None = None,
    depth: int = 0,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        slug = _catalog_slug(raw_item)
        summary = {
            "title": str(raw_item.get("title") or ""),
            "slug": slug,
            "path": str(raw_item.get("path") or slug),
            "kind": str(raw_item.get("kind") or "page").lower(),
            "topic": str(raw_item.get("topic") or raw_item.get("title") or ""),
            "parent_slug": parent_slug,
            "order": int(raw_item.get("order") or 0),
            "depth": depth,
            "source_hints": _source_hints_from_item(raw_item)[:4],
        }
        summaries.append(summary)
        children = raw_item.get("children") or []
        if isinstance(children, list):
            summaries.extend(
                _catalog_item_summaries(children, parent_slug=slug, depth=depth + 1)
            )
    return summaries[:48]


def _related_catalog_pages(
    summaries: list[dict[str, Any]],
    *,
    slug: str,
    parent_slug: str | None,
) -> list[dict[str, Any]]:
    page_summaries = [
        item
        for item in summaries
        if item["kind"] == "page" and item["slug"] != slug
    ]
    ranked = sorted(
        page_summaries,
        key=lambda item: (
            0 if item["parent_slug"] == parent_slug else 1,
            item["depth"],
            item["order"],
            item["title"],
        ),
    )
    return ranked[:12]


def _flatten_catalog_items(
    items: list[Any],
    *,
    parent_slug: str | None = None,
):
    for item in items:
        if not isinstance(item, dict):
            continue
        yield item, parent_slug
        slug = _catalog_slug(item)
        children = item.get("children") or []
        if isinstance(children, list):
            yield from _flatten_catalog_items(children, parent_slug=slug)


def _catalog_items_for_generation(
    items: list[Any],
    *,
    parent_slug: str | None = None,
):
    for item in items:
        if not isinstance(item, dict):
            continue
        children = item.get("children") or []
        has_children = isinstance(children, list) and bool(children)
        kind = str(item.get("kind") or "").lower()
        if kind == "page" or not has_children:
            yield item, parent_slug
        if isinstance(children, list):
            yield from _catalog_items_for_generation(children, parent_slug=_catalog_slug(item))


def _catalog_slug(item: dict[str, Any]) -> str:
    return _slugify(str(item.get("slug") or item.get("path") or item.get("title") or ""))


def _source_chunk_summaries(chunks: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "id": chunk.get("id"),
            "node_id": chunk.get("node_id"),
            "file_path": chunk.get("file_path"),
            "start_line": chunk.get("start_line"),
            "end_line": chunk.get("end_line"),
            "reasons": chunk.get("reasons"),
        }
        for chunk in chunks
    ]


def _source_hints_from_item(item: dict[str, Any]) -> list[str]:
    hints = item.get("source_hints")
    if not isinstance(hints, list):
        return []
    return [
        hint.strip().strip("/")
        for hint in (str(value) for value in hints)
        if hint.strip().strip("/")
    ][:8]


def _trace_with_source_hint_chunks(
    trace: RetrievalTrace,
    store: SQLiteStore,
    repo_id: str,
    source_hints: list[str],
) -> RetrievalTrace:
    if not source_hints:
        return trace

    hinted_chunks: list[dict[str, object]] = []
    per_file_counts: dict[str, int] = {}
    for chunk in store.list_code_chunks(repo_id):
        if not _matches_source_hint(chunk.file_path, source_hints):
            continue
        if per_file_counts.get(chunk.file_path, 0) >= MAX_SOURCE_HINT_CHUNKS_PER_FILE:
            continue
        per_file_counts[chunk.file_path] = per_file_counts.get(chunk.file_path, 0) + 1
        hinted_chunks.append(
            {
                "id": chunk.id,
                "node_id": chunk.node_id,
                "file_path": chunk.file_path,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "content": chunk.content,
                "content_hash": chunk.content_hash,
                "token_count": chunk.token_count,
                "score": 0.45,
                "reasons": ["source_hint"],
            }
        )
        if len(hinted_chunks) >= MAX_SOURCE_HINT_CHUNKS:
            break

    if not hinted_chunks:
        return trace
    return replace(
        trace,
        source_chunks=_dedupe_source_chunks([*trace.source_chunks, *hinted_chunks]),
    )


def _matches_source_hint(file_path: str, source_hints: list[str]) -> bool:
    normalized = file_path.strip("/")
    return any(normalized == hint or normalized.startswith(f"{hint.rstrip('/')}/") for hint in source_hints)


def _dedupe_source_chunks(chunks: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    deduped: list[dict[str, object]] = []
    for chunk in chunks:
        chunk_id = str(chunk.get("id") or "")
        key = chunk_id or (
            f"{chunk.get('file_path')}:{chunk.get('start_line')}:{chunk.get('end_line')}"
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(chunk)
    return deduped


def _source_refs_from_chunks(chunks: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "citation_id": f"S{index + 1}",
            "file_path": chunk["file_path"],
            "start_line": chunk["start_line"],
            "end_line": chunk["end_line"],
            "chunk_id": chunk["id"],
        }
        for index, chunk in enumerate(chunks)
        if isinstance(chunk.get("file_path"), str)
        and isinstance(chunk.get("start_line"), int)
        and isinstance(chunk.get("end_line"), int)
    ]


def _validate_source_refs(
    *,
    repo_path: str,
    requested_refs: Any,
    source_chunks: list[dict[str, object]],
    allowed_source_refs: list[dict[str, object]],
    source_url_base: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(requested_refs, list):
        return [], ["source_refs must be an array."]

    repo_root = Path(repo_path).resolve()
    chunk_ranges = _chunk_ranges(source_chunks)
    allowed_by_citation_id = _allowed_refs_by_citation_id(allowed_source_refs)
    valid_refs: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[tuple[str, int, int]] = set()

    for index, raw_ref in enumerate(requested_refs):
        if not isinstance(raw_ref, dict):
            errors.append(f"source_refs[{index}] must be an object.")
            continue
        citation_id = str(raw_ref.get("citation_id") or "").strip()
        if citation_id:
            allowed_ref = allowed_by_citation_id.get(citation_id)
            if allowed_ref is None:
                errors.append(f"source_refs[{index}] uses unknown citation_id: {citation_id}.")
                continue
            file_path = str(allowed_ref.get("file_path") or "").strip()
            start_line = allowed_ref.get("start_line")
            end_line = allowed_ref.get("end_line")
        else:
            file_path = str(raw_ref.get("file_path") or "").strip()
            start_line = raw_ref.get("start_line")
            end_line = raw_ref.get("end_line")
        if not file_path or not isinstance(start_line, int) or not isinstance(end_line, int):
            errors.append(f"source_refs[{index}] must include file_path, start_line, end_line.")
            continue
        if start_line < 1 or end_line < start_line:
            errors.append(f"source_refs[{index}] has invalid line range.")
            continue

        absolute_path = (repo_root / file_path).resolve()
        if not absolute_path.is_file() or not absolute_path.is_relative_to(repo_root):
            errors.append(f"source_refs[{index}] file does not exist in repo: {file_path}.")
            continue

        lines = absolute_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if end_line > len(lines):
            errors.append(f"source_refs[{index}] line range exceeds file length: {file_path}.")
            continue

        content = "\n".join(lines[start_line - 1 : end_line])
        matching_chunk = next(
            (
                chunk
                for chunk in chunk_ranges.get(file_path, [])
                if start_line >= chunk["start_line"]
                and end_line <= chunk["end_line"]
                and content in str(chunk["content"])
            ),
            None,
        )
        if matching_chunk is None:
            errors.append(
                f"source_refs[{index}] is not covered by the retrieved source_chunks: "
                f"{file_path}:{start_line}-{end_line}."
            )
            continue

        key = (file_path, start_line, end_line)
        if key in seen:
            continue
        seen.add(key)
        citation_id = citation_id or _citation_id_for_range(
            allowed_source_refs,
            file_path,
            start_line,
            end_line,
        )
        ref = {
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "chunk_id": matching_chunk["id"],
        }
        if citation_id:
            ref["citation_id"] = citation_id
        if source_url_base:
            ref["source_url"] = _source_url(source_url_base, file_path, start_line, end_line)
        valid_refs.append(ref)
    return valid_refs, errors


def _include_markdown_citation_refs(
    markdown: str,
    source_refs: list[dict[str, Any]],
    allowed_source_refs: list[dict[str, object]],
    *,
    source_url_base: str | None = None,
) -> list[dict[str, Any]]:
    refs_by_citation_id = {
        str(ref["citation_id"]): ref
        for ref in source_refs
        if isinstance(ref.get("citation_id"), str)
    }
    allowed_by_citation_id = _allowed_refs_by_citation_id(allowed_source_refs)
    for citation_id in sorted(CITATION_MARKER_RE.findall(markdown), key=_citation_sort_key):
        if citation_id in refs_by_citation_id:
            continue
        allowed = allowed_by_citation_id.get(citation_id)
        if allowed is None:
            continue
        file_path = allowed.get("file_path")
        start_line = allowed.get("start_line")
        end_line = allowed.get("end_line")
        chunk_id = allowed.get("chunk_id")
        if not isinstance(file_path, str) or not isinstance(start_line, int) or not isinstance(end_line, int):
            continue
        ref: dict[str, Any] = {
            "citation_id": citation_id,
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
        }
        if isinstance(chunk_id, str):
            ref["chunk_id"] = chunk_id
        if source_url_base:
            ref["source_url"] = _source_url(source_url_base, file_path, start_line, end_line)
        refs_by_citation_id[citation_id] = ref
    return list(refs_by_citation_id.values())


def _citation_sort_key(citation_id: str) -> tuple[int, str]:
    suffix = citation_id.removeprefix("S")
    return (int(suffix), citation_id) if suffix.isdigit() else (10**9, citation_id)


def _allowed_refs_by_citation_id(
    allowed_source_refs: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    refs: dict[str, dict[str, object]] = {}
    for ref in allowed_source_refs:
        citation_id = ref.get("citation_id")
        if isinstance(citation_id, str) and citation_id:
            refs[citation_id] = ref
    return refs


def _citation_id_for_range(
    allowed_source_refs: list[dict[str, object]],
    file_path: str,
    start_line: int,
    end_line: int,
) -> str | None:
    for ref in allowed_source_refs:
        if (
            ref.get("file_path") == file_path
            and ref.get("start_line") == start_line
            and ref.get("end_line") == end_line
            and isinstance(ref.get("citation_id"), str)
        ):
            return str(ref["citation_id"])
    return None


def _chunk_ranges(chunks: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    ranges: dict[str, list[dict[str, object]]] = {}
    for chunk in chunks:
        file_path = chunk.get("file_path")
        start_line = chunk.get("start_line")
        end_line = chunk.get("end_line")
        content = chunk.get("content")
        if (
            isinstance(file_path, str)
            and isinstance(start_line, int)
            and isinstance(end_line, int)
            and isinstance(content, str)
        ):
            ranges.setdefault(file_path, []).append(
                {
                    "id": chunk.get("id"),
                    "start_line": start_line,
                    "end_line": end_line,
                    "content": content,
                }
            )
    return ranges


def _strip_llm_mermaid(markdown: str) -> str:
    return MERMAID_FENCE_RE.sub("", markdown).strip()


def _validate_page_markdown(markdown: str, expected_title: str) -> list[str]:
    errors: list[str] = []
    stripped = markdown.strip()
    if not stripped.startswith("# "):
        errors.append("markdown must start with an H1 title.")
    if expected_title and f"# {expected_title}" not in stripped.splitlines()[:3]:
        errors.append(f"markdown H1 must match page title: {expected_title}.")
    for heading in REQUIRED_PAGE_HEADINGS:
        if heading not in stripped:
            errors.append(f"markdown must include required heading: {heading}.")
    return errors


def _validate_citation_markers(markdown: str, source_refs: list[dict[str, Any]]) -> list[str]:
    markers = set(CITATION_MARKER_RE.findall(markdown))
    if not markers:
        return []
    valid_markers = {
        citation_id
        for ref in source_refs
        if isinstance((citation_id := ref.get("citation_id")), str)
    }
    unknown = sorted(markers - valid_markers)
    return [f"markdown contains citation markers not present in source_refs: {', '.join(unknown)}."] if unknown else []


def _strip_unknown_citation_markers(markdown: str, source_refs: list[dict[str, Any]]) -> str:
    valid_markers = {
        citation_id
        for ref in source_refs
        if isinstance((citation_id := ref.get("citation_id")), str)
    }

    def replace_marker(match: re.Match[str]) -> str:
        return match.group(0) if match.group(1) in valid_markers else ""

    return CITATION_MARKER_RE.sub(replace_marker, markdown)


def _replace_citation_markers(markdown: str, source_refs: list[dict[str, Any]]) -> str:
    refs_by_citation_id = {
        citation_id: ref
        for ref in source_refs
        if isinstance((citation_id := ref.get("citation_id")), str)
    }

    def replace_marker(match: re.Match[str]) -> str:
        citation_id = match.group(1)
        ref = refs_by_citation_id.get(citation_id)
        if ref is None:
            return match.group(0)
        return f"[{_source_ref_label(ref)}]({_source_ref_href(ref)})"

    return CITATION_MARKER_RE.sub(replace_marker, markdown)


def _compose_page_markdown(
    markdown: str,
    mermaid: str,
    source_refs: list[dict[str, Any]],
) -> str:
    sections = [_insert_relevant_source_files(markdown.strip(), source_refs)]
    if mermaid:
        sections.append(mermaid.strip())
    sections.append(_sources_markdown(source_refs))
    return "\n\n".join(section for section in sections if section)


def _insert_relevant_source_files(markdown: str, source_refs: list[dict[str, Any]]) -> str:
    if "## Relevant source files" in markdown:
        return markdown

    relevant = _relevant_source_files_markdown(source_refs)
    lines = markdown.splitlines()
    if lines and lines[0].startswith("# "):
        rest = "\n".join(lines[1:]).strip()
        return "\n\n".join(section for section in [lines[0], relevant, rest] if section)
    return "\n\n".join(section for section in [relevant, markdown] if section)


def _relevant_source_files_markdown(source_refs: list[dict[str, Any]]) -> str:
    lines = ["## Relevant source files"]
    seen: set[str] = set()
    for ref in source_refs:
        file_path = str(ref["file_path"])
        if file_path in seen:
            continue
        seen.add(file_path)
        lines.append(f"- [{file_path}]({_source_file_href(ref)})")
    return "\n".join(lines)


def _sources_markdown(source_refs: list[dict[str, Any]]) -> str:
    lines = ["## Sources"]
    for ref in source_refs:
        href = _source_ref_href(ref)
        prefix = f"{ref['citation_id']} " if isinstance(ref.get("citation_id"), str) else ""
        lines.append(
            f"- {prefix}[{_source_ref_label(ref)}]({href})"
        )
    return "\n".join(lines)


def _source_ref_label(ref: dict[str, Any]) -> str:
    return f"{ref['file_path']}:L{ref['start_line']}-L{ref['end_line']}"


def _source_ref_href(ref: dict[str, Any]) -> str:
    source_url = ref.get("source_url")
    return source_url if isinstance(source_url, str) and source_url else "source-link"


def _source_file_href(ref: dict[str, Any]) -> str:
    source_url = ref.get("source_url")
    if not isinstance(source_url, str) or not source_url:
        return "source-link"
    return re.sub(r"#L\d+(?:-L\d+)?$", "", source_url)


def _source_url_base(git_url: str | None, commit_hash: str | None) -> str | None:
    if not git_url:
        return None
    normalized = git_url.strip().rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized.removesuffix(".git")
    if normalized.startswith("git@"):
        host_and_path = normalized.removeprefix("git@")
        host, _, repo_path = host_and_path.partition(":")
        if host and repo_path:
            normalized = f"https://{host}/{repo_path}"
    ref = commit_hash or "HEAD"
    if "gitlab" in normalized:
        return f"{normalized}/-/blob/{ref}"
    if "bitbucket.org" in normalized:
        return f"{normalized}/src/{ref}"
    return f"{normalized}/blob/{ref}"


def _source_url(source_url_base: str, file_path: str, start_line: int, end_line: int) -> str:
    return f"{source_url_base}/{quote(file_path, safe='/')}#L{start_line}-L{end_line}"


def _draft_markdown(title: str, errors: list[str]) -> str:
    lines = [
        f"# {title}",
        "",
        "This page was not promoted because source reference validation failed.",
        "",
        "## Validation Errors",
    ]
    lines.extend(f"- {error}" for error in errors)
    return "\n".join(lines)


def _graph_refs_from_trace(trace: RetrievalTrace) -> set[str]:
    refs: set[str] = set()
    for node in [*trace.seed_nodes, *trace.expanded_nodes]:
        node_id = node.get("id")
        if isinstance(node_id, str) and node_id:
            refs.add(node_id)
    for edge in trace.related_edges:
        for key in ("id", "source_id", "target_id", "source", "target"):
            value = edge.get(key)
            if isinstance(value, str) and value:
                refs.add(value)
    return refs


def _mermaid_from_trace(
    trace: RetrievalTrace,
    *,
    title: str | None = None,
    source_refs: list[dict[str, Any]] | None = None,
) -> str:
    nodes = {
        str(node["id"]): node
        for node in [*trace.seed_nodes, *trace.expanded_nodes]
        if "id" in node
    }
    if not nodes:
        return ""

    diagrams: list[tuple[str, list[str]]] = []
    component_diagram = _abstract_component_diagram(trace, nodes)
    if component_diagram:
        diagrams.append(("Component interaction", component_diagram))

    surface_diagram = _key_surface_diagram(trace, nodes)
    if surface_diagram:
        diagrams.append(("Key surfaces", surface_diagram))

    if not diagrams:
        return ""

    graph_title = f"{title} graph overview" if title else "Graph overview"
    lines = ["## Graph", "", f"Title: {graph_title}"]
    for diagram_title, diagram_lines in diagrams:
        lines.extend(["", f"### {diagram_title}", "", "```mermaid"])
        lines.extend(diagram_lines)
        lines.append("```")
    source_line = _section_sources_line(source_refs or [])
    if source_line:
        lines.extend(["", source_line])
    return "\n".join(lines)


def _abstract_component_diagram(
    trace: RetrievalTrace,
    nodes: dict[str, dict[str, object]],
) -> list[str]:
    community_groups, community_edges = _aggregate_component_edges(
        trace,
        nodes,
        group_mode="community",
    )
    if community_edges and len(community_groups) > 1:
        return _render_component_diagram(community_groups, community_edges)

    file_groups, file_edges = _aggregate_component_edges(
        trace,
        nodes,
        group_mode="file",
    )
    if not file_edges or len(file_groups) <= 1:
        return []
    return _render_component_diagram(file_groups, file_edges)


def _aggregate_component_edges(
    trace: RetrievalTrace,
    nodes: dict[str, dict[str, object]],
    *,
    group_mode: str,
) -> tuple[dict[str, _MermaidGroup], list[_MermaidEdgeAggregate]]:
    community_index = _community_index(trace.community_summaries)
    groups: dict[str, _MermaidGroup] = {}
    aggregates: dict[tuple[str, str], _MermaidEdgeAggregate] = {}

    for edge in trace.related_edges:
        edge_type = str(edge.get("type") or "")
        if edge_type not in ABSTRACT_DIAGRAM_EDGE_TYPES:
            continue
        source_id = _edge_endpoint(edge, "source_id", "source")
        target_id = _edge_endpoint(edge, "target_id", "target")
        source_node = nodes.get(source_id)
        target_node = nodes.get(target_id)
        if source_node is None or target_node is None:
            continue

        source_group = _abstract_group_for_node(
            source_node,
            community_index=community_index,
            group_mode=group_mode,
        )
        target_group = _abstract_group_for_node(
            target_node,
            community_index=community_index,
            group_mode=group_mode,
        )
        if source_group.key == target_group.key:
            continue

        groups[source_group.key] = source_group
        groups[target_group.key] = target_group
        aggregate_key = (source_group.key, target_group.key)
        aggregate = aggregates.setdefault(
            aggregate_key,
            _MermaidEdgeAggregate(
                source_key=source_group.key,
                target_key=target_group.key,
                counts={},
            ),
        )
        aggregate.counts[edge_type] = aggregate.counts.get(edge_type, 0) + 1
        aggregate.confidence_total += _edge_confidence(edge)
        aggregate.evidence_count += 1

    selected = _select_component_edges(list(aggregates.values()))
    selected_group_keys = {edge.source_key for edge in selected} | {edge.target_key for edge in selected}
    return (
        {key: group for key, group in groups.items() if key in selected_group_keys},
        selected,
    )


def _select_component_edges(edges: list[_MermaidEdgeAggregate]) -> list[_MermaidEdgeAggregate]:
    selected: list[_MermaidEdgeAggregate] = []
    selected_groups: set[str] = set()
    for edge in sorted(edges, key=_component_edge_sort_key):
        proposed_groups = selected_groups | {edge.source_key, edge.target_key}
        if selected and len(proposed_groups) > MAX_MERMAID_COMPONENTS:
            continue
        selected.append(edge)
        selected_groups = proposed_groups
        if len(selected) >= MAX_MERMAID_ABSTRACT_EDGES:
            break
    return selected


def _component_edge_sort_key(edge: _MermaidEdgeAggregate) -> tuple[float, str, str]:
    type_weight = {
        "routes_to": 6.0,
        "calls": 4.5,
        "imports": 3.5,
        "inherits": 2.8,
        "exports": 1.8,
    }
    score = sum(type_weight.get(edge_type, 1.0) * min(count, 4) for edge_type, count in edge.counts.items())
    if edge.evidence_count:
        score += edge.confidence_total / edge.evidence_count
    return (-score, edge.source_key, edge.target_key)


def _render_component_diagram(
    groups: dict[str, _MermaidGroup],
    edges: list[_MermaidEdgeAggregate],
) -> list[str]:
    aliases = {
        key: f"C{index}"
        for index, key in enumerate(
            sorted(groups, key=lambda key: (groups[key].rank, groups[key].label, key))
        )
    }
    lines = ["flowchart LR"]
    for key in aliases:
        group = groups[key]
        lines.append(f'  {aliases[key]}["{_mermaid_text(group.label)}"]')
    for edge in edges:
        source_alias = aliases.get(edge.source_key)
        target_alias = aliases.get(edge.target_key)
        if source_alias is None or target_alias is None:
            continue
        label = _edge_label(edge.counts)
        lines.append(f"  {source_alias} -->|{label}| {target_alias}")
    return lines


def _key_surface_diagram(
    trace: RetrievalTrace,
    nodes: dict[str, dict[str, object]],
) -> list[str]:
    community_index = _community_index(trace.community_summaries)
    surfaces = _select_surface_nodes([*trace.seed_nodes, *trace.expanded_nodes])
    if not surfaces:
        return []

    groups: dict[str, _MermaidGroup] = {}
    surface_aliases: dict[str, str] = {}
    lines = ["flowchart TD"]
    for surface in surfaces:
        node_id = str(surface.get("id") or "")
        if not node_id or node_id not in nodes:
            continue
        group = _abstract_group_for_node(
            surface,
            community_index=community_index,
            group_mode="community",
        )
        if group.kind != "community":
            group = _abstract_group_for_node(
                surface,
                community_index=community_index,
                group_mode="file",
            )
        groups[group.key] = group
        surface_aliases[node_id] = f"S{len(surface_aliases)}"

    group_aliases = {
        key: f"G{index}"
        for index, key in enumerate(
            sorted(groups, key=lambda key: (groups[key].rank, groups[key].label, key))
        )
    }
    for key in group_aliases:
        lines.append(f'  {group_aliases[key]}["{_mermaid_text(groups[key].label)}"]')
    for surface in surfaces:
        node_id = str(surface.get("id") or "")
        surface_alias = surface_aliases.get(node_id)
        if surface_alias is None:
            continue
        group = _abstract_group_for_node(
            surface,
            community_index=community_index,
            group_mode="community",
        )
        if group.kind != "community":
            group = _abstract_group_for_node(
                surface,
                community_index=community_index,
                group_mode="file",
            )
        group_alias = group_aliases.get(group.key)
        if group_alias is None:
            continue
        lines.append(f'  {surface_alias}["{_surface_label(surface)}"]')
        lines.append(f"  {group_alias} --> {surface_alias}")

    return lines if len(lines) > 1 else []


def _select_surface_nodes(nodes: list[dict[str, object]]) -> list[dict[str, object]]:
    candidates = [
        node
        for node in nodes
        if str(node.get("type") or "") in SURFACE_NODE_TYPES
    ]
    return sorted(
        candidates,
        key=lambda node: (
            _surface_rank(str(node.get("type") or "")),
            int(node.get("hop") or 0),
            -float(node.get("score") or 0.0),
            str(node.get("file_path") or ""),
            str(node.get("name") or ""),
        ),
    )[:MAX_MERMAID_SURFACES]


def _surface_rank(node_type: str) -> int:
    return {
        "endpoint": 0,
        "schema": 1,
        "class": 2,
        "interface": 3,
    }.get(node_type, 9)


def _surface_label(node: dict[str, object]) -> str:
    node_type = str(node.get("type") or "")
    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    if node_type == "endpoint":
        method = str(metadata.get("route_method") or "").upper()
        route_path = str(metadata.get("route_path") or "")
        if method or route_path:
            return _mermaid_text(" ".join(part for part in [method, route_path] if part))
    return _mermaid_label(node)


def _community_index(communities: list[dict[str, object]]) -> dict[str, _MermaidGroup]:
    index: dict[str, _MermaidGroup] = {}
    for rank, community in enumerate(communities):
        community_id = str(community.get("id") or "")
        if not community_id:
            continue
        label = str(community.get("name") or community_id.rsplit(":", 1)[-1])
        group = _MermaidGroup(
            key=f"community:{community_id}",
            label=label,
            kind="community",
            rank=rank,
        )
        raw_node_ids = [
            *_string_list(community.get("matched_node_ids")),
            *_string_list(community.get("node_ids")),
        ]
        for node_id in raw_node_ids:
            if node_id:
                index.setdefault(node_id, group)
    return index


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _abstract_group_for_node(
    node: dict[str, object],
    *,
    community_index: dict[str, _MermaidGroup],
    group_mode: str,
) -> _MermaidGroup:
    node_id = str(node.get("id") or "")
    if group_mode == "community" and node_id in community_index:
        return community_index[node_id]

    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    name = str(node.get("name") or node_id)
    if str(node.get("type") or "") == "module" and metadata.get("external"):
        return _MermaidGroup(
            key=f"external:{name}",
            label=f"External: {name}",
            kind="external",
            rank=90,
        )

    file_path = str(node.get("file_path") or "")
    if file_path:
        return _MermaidGroup(
            key=f"file:{file_path}",
            label=_component_label(file_path),
            kind="file",
            rank=20,
        )

    return _MermaidGroup(
        key=f"node:{node_id}",
        label=_mermaid_label(node),
        kind="node",
        rank=80,
    )


def _component_label(file_path: str) -> str:
    parts = [part for part in file_path.split("/") if part]
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}"
    return file_path


def _edge_endpoint(edge: dict[str, object], primary: str, fallback: str) -> str:
    value = edge.get(primary) or edge.get(fallback)
    return str(value or "")


def _edge_confidence(edge: dict[str, object]) -> float:
    confidence = edge.get("confidence")
    if isinstance(confidence, int | float):
        return float(confidence)
    return 1.0


def _edge_label(counts: dict[str, int]) -> str:
    labels = []
    for edge_type in EDGE_LABEL_ORDER:
        count = counts.get(edge_type, 0)
        if not count:
            continue
        label = edge_type.replace("_", " ")
        labels.append(f"{label} x{count}" if count > 1 else label)
    return _mermaid_edge_text(" / ".join(labels))


def _section_sources_line(source_refs: list[dict[str, Any]]) -> str:
    refs = [
        f"[{_source_ref_label(ref)}]({_source_ref_href(ref)})"
        for ref in source_refs[:6]
    ]
    return f"Sources: {' '.join(refs)}" if refs else ""


def _mermaid_label(node: dict[str, object]) -> str:
    name = str(node.get("name") or node.get("id") or "")
    node_type = str(node.get("type") or "")
    return _mermaid_text(f"{name} ({node_type})")


def _mermaid_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', "'").replace("\n", " ")[:80]


def _mermaid_edge_text(value: str) -> str:
    return _mermaid_text(value).replace("|", "/")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug or "page"


def _unique_slug(slug: str, used_slugs: set[str]) -> str:
    candidate = slug
    index = 2
    while candidate in used_slugs:
        candidate = f"{slug}-{index}"
        index += 1
    used_slugs.add(candidate)
    return candidate
