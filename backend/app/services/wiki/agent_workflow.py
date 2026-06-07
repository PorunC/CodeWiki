from __future__ import annotations

import re
import uuid
from collections import Counter
from pathlib import PurePosixPath
from typing import Any

from backend.app.database import CodeWikiStore, DocCatalogRecord, DocPageRecord
from backend.app.services.file_roles import filter_wiki_graph
from backend.app.services.graphrag import GraphRAGRetriever, RetrievalTrace
from backend.app.services.wiki.language import normalize_language
from backend.app.services.wiki.tree import GenerationNode, generation_nodes
from backend.app.services.wiki.utils import ordered_unique, slugify


class WikiAgentWorkflow:
    """Agent-facing wiki workflow used by the CodeWiki skill.

    These methods intentionally avoid LLM-backed wiki generation. If no catalog
    exists yet, a deterministic directory-based catalog is created from the
    analyzed graph so an agent can plan, gather evidence, write, save, and
    validate pages itself.
    """

    def __init__(self, *, store: CodeWikiStore, retriever: GraphRAGRetriever) -> None:
        self.store = store
        self.retriever = retriever

    async def plan(self, repo_id: str, *, language_code: str = "en") -> dict[str, Any]:
        language = normalize_language(language_code)
        catalog = self._ensure_catalog(repo_id, language)
        nodes = generation_nodes(_catalog_items(catalog))
        return {
            "repo_id": repo_id,
            "language_code": language,
            "catalog": catalog.as_record_dict(),
            "pages": [_agent_page_queue_item(node) for node in nodes],
        }

    async def evidence(
        self,
        repo_id: str,
        slug: str,
        *,
        language_code: str = "en",
        limit: int = 12,
    ) -> dict[str, Any]:
        language = normalize_language(language_code)
        catalog = self._ensure_catalog(repo_id, language)
        nodes = generation_nodes(_catalog_items(catalog))
        node = _find_node(nodes, slug)
        if node is None:
            raise ValueError(f"Catalog page not found: {slug}")
        trace = await self.retriever.retrieve(repo_id, _agent_evidence_query(node))
        return _agent_evidence_payload(
            repo_id=repo_id,
            language_code=language,
            catalog=catalog,
            nodes=nodes,
            node=node,
            trace=trace,
            limit=_positive_int(limit, 12),
        )

    async def save_page(
        self,
        repo_id: str,
        slug: str,
        markdown: str,
        *,
        language_code: str = "en",
        title: str | None = None,
        parent_slug: str | None = None,
    ) -> dict[str, Any]:
        language = normalize_language(language_code)
        catalog = self._ensure_catalog(repo_id, language)
        nodes = generation_nodes(_catalog_items(catalog))
        node = _find_node(nodes, slug)
        validation_errors = _validate_agent_markdown(markdown)
        if node is None:
            validation_errors.append(f"Catalog page not found: {slug}")

        allowed_refs: list[dict[str, Any]] = []
        if node is not None:
            trace = await self.retriever.retrieve(repo_id, _agent_evidence_query(node))
            allowed_refs = _allowed_source_refs_from_trace(trace)

        allowed_by_citation = {
            ref["citation_id"]: ref
            for ref in allowed_refs
            if isinstance(ref.get("citation_id"), str)
        }
        citations = _extract_markdown_citations(markdown)
        source_refs: list[dict[str, Any]] = []
        for citation_id in citations:
            source_ref = allowed_by_citation.get(citation_id)
            if source_ref is None:
                validation_errors.append(f"Unknown source citation: [[{citation_id}]]")
                continue
            source_refs.append(source_ref)
        if not citations:
            validation_errors.append("Markdown must cite at least one evidence source.")

        status = "draft" if validation_errors else "generated"
        page = self.store.upsert_doc_page(
            DocPageRecord(
                id=uuid.uuid4().hex,
                repo_id=repo_id,
                language_code=language,
                slug=slug,
                title=(title or "").strip()
                or (_catalog_item_title(node.item) if node is not None else _title_from_slug(slug)),
                parent_slug=parent_slug if parent_slug is not None else (node.parent_slug if node else None),
                markdown=markdown,
                source_refs=_unique_source_refs(source_refs),
                graph_refs=[],
                status=status,
                updated_at=None,
            )
        )
        return {
            "status": status,
            "validation_errors": ordered_unique(validation_errors),
            "page": page.as_record_dict(),
        }

    async def validate_page(
        self,
        repo_id: str,
        slug: str,
        *,
        language_code: str = "en",
    ) -> dict[str, Any]:
        language = normalize_language(language_code)
        catalog = self._ensure_catalog(repo_id, language)
        nodes = generation_nodes(_catalog_items(catalog))
        validation_errors: list[str] = []
        if _find_node(nodes, slug) is None:
            validation_errors.append(f"Catalog page not found: {slug}")

        page = self.store.get_doc_page(repo_id, slug, language_code=language)
        if page is None:
            validation_errors.append(f"Wiki page not found: {slug}")
            return {
                "repo_id": repo_id,
                "language_code": language,
                "status": "invalid",
                "validation_errors": ordered_unique(validation_errors),
                "page": None,
            }

        validation_errors.extend(_validate_agent_markdown(page.markdown))
        if not page.title.strip():
            validation_errors.append("Page title must not be empty.")
        source_citation_ids = {
            str(ref.get("citation_id"))
            for ref in page.source_refs
            if isinstance(ref.get("citation_id"), str)
        }
        for citation_id in _extract_markdown_citations(page.markdown):
            if citation_id not in source_citation_ids:
                validation_errors.append(f"Unknown source citation: [[{citation_id}]]")
        if not source_citation_ids:
            validation_errors.append("Page must include source references.")

        return {
            "repo_id": repo_id,
            "language_code": language,
            "status": "invalid" if validation_errors else "valid",
            "validation_errors": ordered_unique(validation_errors),
            "page": page.as_record_dict(),
        }

    def _ensure_catalog(self, repo_id: str, language_code: str) -> DocCatalogRecord:
        catalog = self.store.get_latest_doc_catalog(repo_id, language_code=language_code)
        if catalog is not None:
            return catalog

        repo = self.store.get_repo(repo_id)
        if repo is None:
            raise ValueError(f"Repository not found: {repo_id}")
        nodes, edges = self.store.get_graph(repo_id)
        wiki_nodes, _wiki_edges = filter_wiki_graph(nodes, edges)
        return self.store.save_doc_catalog(
            repo_id,
            title=f"{repo.name} Wiki",
            structure={"items": _build_local_catalog_items(wiki_nodes)},
            language_code=language_code,
        )


def _build_local_catalog_items(nodes: list[Any]) -> list[dict[str, Any]]:
    directories: Counter[str] = Counter()
    for node in nodes:
        if getattr(node, "type", "") not in {"file", "config"}:
            continue
        file_path = str(getattr(node, "file_path", "") or "")
        if not file_path:
            continue
        directories[_directory_name(file_path)] += 1

    items: list[dict[str, Any]] = []
    for order, (directory, count) in enumerate(sorted(directories.items())):
        items.append(
            {
                "title": _title_from_slug(directory),
                "slug": slugify(directory),
                "path": None if directory == "root" else directory,
                "order": order,
                "kind": "page",
                "topic": f"{count} files",
                "source_hints": [] if directory == "root" else [directory],
                "children": [],
            }
        )
    return items


def _directory_name(file_path: str) -> str:
    parent = str(PurePosixPath(file_path).parent)
    return "root" if parent in {"", "."} else parent


def _catalog_items(catalog: DocCatalogRecord) -> list[Any]:
    items = catalog.structure.get("items", [])
    return items if isinstance(items, list) else []


def _find_node(nodes: list[GenerationNode], slug: str | None) -> GenerationNode | None:
    return next((node for node in nodes if node.slug == slug), None)


def _agent_page_queue_item(node: GenerationNode) -> dict[str, Any]:
    return {
        "slug": node.slug,
        "title": _catalog_item_title(node.item),
        "parent_slug": node.parent_slug,
        "kind": str(node.item.get("kind") or "page"),
        "topic": _wiki_page_topic(node.item),
        "path": node.item.get("path"),
        "source_hints": _wiki_page_source_hints(node.item),
        "order": node.order,
        "has_children": node.has_children,
    }


def _agent_evidence_query(node: GenerationNode) -> str:
    return " ".join(
        value
        for value in [
            _catalog_item_title(node.item),
            _wiki_page_topic(node.item),
            *_wiki_page_source_hints(node.item),
            node.slug,
        ]
        if value
    )


def _agent_evidence_payload(
    *,
    repo_id: str,
    language_code: str,
    catalog: DocCatalogRecord,
    nodes: list[GenerationNode],
    node: GenerationNode,
    trace: RetrievalTrace,
    limit: int,
) -> dict[str, Any]:
    parent = _find_node(nodes, node.parent_slug) if node.parent_slug else None
    return {
        "repo_id": repo_id,
        "language_code": language_code,
        "page": _agent_page_queue_item(node),
        "catalog_context": {
            "catalog": catalog.as_record_dict(),
            "parent": _agent_page_queue_item(parent) if parent else None,
            "children": [
                _agent_page_queue_item(candidate)
                for candidate in nodes
                if candidate.parent_slug == node.slug
            ],
            "siblings": [
                _agent_page_queue_item(candidate)
                for candidate in nodes
                if candidate.parent_slug == node.parent_slug and candidate.slug != node.slug
            ],
        },
        "retrieval_trace": _retrieval_trace_payload(trace),
        "allowed_source_refs": _allowed_source_refs_from_trace(trace)[:limit],
        "instructions": (
            "Only write claims supported by evidence; cite with [[S#]] using "
            "allowed_source_refs."
        ),
    }


def _retrieval_trace_payload(trace: RetrievalTrace) -> dict[str, Any]:
    source_chunks = _source_chunks_with_citations(trace.source_chunks)
    nodes = [*trace.seed_nodes, *trace.expanded_nodes]
    return {
        "repo_id": trace.repo_id,
        "query": trace.query,
        "max_hops": trace.max_hops,
        "trace_id": trace.trace_id,
        "seed_nodes": trace.seed_nodes,
        "expanded_nodes": trace.expanded_nodes,
        "source_chunks": source_chunks,
        "related_edges": trace.related_edges,
        "community_summaries": trace.community_summaries,
        "community_edges": trace.community_edges,
        "context_pack": trace.context_pack,
        "chunks": source_chunks,
        "nodes": nodes,
        "edges": trace.related_edges,
        "communities": trace.community_summaries,
        "context": trace.context_pack.get("text"),
    }


def _allowed_source_refs_from_trace(trace: RetrievalTrace) -> list[dict[str, Any]]:
    return [
        {
            "citation_id": str(chunk.get("citation_id") or f"S{index + 1}"),
            "file_path": str(chunk.get("file_path") or ""),
            "start_line": _number_or_none(chunk.get("start_line")),
            "end_line": _number_or_none(chunk.get("end_line")),
        }
        for index, chunk in enumerate(_source_chunks_with_citations(trace.source_chunks))
    ]


def _source_chunks_with_citations(chunks: list[dict[str, object]]) -> list[dict[str, Any]]:
    return [
        {
            **chunk,
            "citation_id": chunk.get("citation_id") or f"S{index + 1}",
        }
        for index, chunk in enumerate(chunks)
    ]


def _validate_agent_markdown(markdown: str) -> list[str]:
    errors: list[str] = []
    trimmed = markdown.strip()
    if not trimmed:
        errors.append("Markdown must not be empty.")
    if trimmed and not re.search(r"^#\s+\S", trimmed, flags=re.MULTILINE):
        errors.append("Markdown must include an H1 title.")
    if trimmed and len(trimmed) < 40:
        errors.append("Markdown is too short to be useful.")
    return errors


def _extract_markdown_citations(markdown: str) -> list[str]:
    return ordered_unique(re.findall(r"\[\[(S\d+)]]", markdown))


def _unique_source_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_citation: dict[str, dict[str, Any]] = {}
    for ref in refs:
        citation_id = ref.get("citation_id")
        if isinstance(citation_id, str) and citation_id not in by_citation:
            by_citation[citation_id] = ref
    return list(by_citation.values())


def _catalog_item_title(item: dict[str, Any]) -> str:
    title = item.get("title")
    if isinstance(title, str) and title:
        return title
    return _title_from_slug(slugify(str(item.get("slug") or "")))


def _title_from_slug(value: str) -> str:
    if value == "root":
        return "Overview"
    return " ".join(part.capitalize() for part in re.split(r"[/-]+", value) if part) or "Overview"


def _wiki_page_topic(item: dict[str, Any]) -> str:
    topic = item.get("topic")
    if isinstance(topic, str) and topic.strip():
        return topic.strip()
    title = _catalog_item_title(item)
    path = item.get("path")
    return " ".join(part for part in [title, str(path) if isinstance(path, str) else ""] if part)


def _wiki_page_source_hints(item: dict[str, Any]) -> list[str]:
    hints = item.get("source_hints")
    if not isinstance(hints, list):
        return []
    return [hint for hint in hints if isinstance(hint, str) and hint.strip()]


def _number_or_none(value: object) -> int | float | None:
    return value if isinstance(value, int | float) and not isinstance(value, bool) else None


def _positive_int(value: int, fallback: int) -> int:
    return value if isinstance(value, int) and value > 0 else fallback
