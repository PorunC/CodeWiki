import json
import re
import uuid
from dataclasses import dataclass
from hashlib import sha256
from importlib import resources
from pathlib import Path
from typing import Any

from backend.app.database import DocCatalogRecord, DocPageRecord, SQLiteStore, get_store
from backend.app.services.graph_rag import GraphRAGRetriever, RetrievalTrace
from backend.app.services.llm_gateway import LLMGateway, LLMResult

MERMAID_FENCE_RE = re.compile(r"```mermaid.*?```", re.DOTALL | re.IGNORECASE)
SOURCE_EDGE_TYPES = {"calls", "imports", "contains"}
MAX_CATALOG_ITEMS = 14
MAX_MERMAID_EDGES = 28


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
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        self.store = store or get_store()

    async def generate_catalog(self, repo_id: str) -> DocCatalogRecord:
        repo = self.store.get_repo(repo_id)
        if repo is None:
            raise ValueError(f"Repository not found: {repo_id}")

        trace = await self.retriever.retrieve(repo_id, "repository overview", max_hops=2)
        prompt = _load_prompt("catalog.md")
        user_payload = {
            "repo": {"id": repo.id, "name": repo.name},
            "context_pack": trace.context_pack,
            "seed_nodes": trace.seed_nodes,
            "expanded_nodes": trace.expanded_nodes[:40],
            "source_chunks": _source_chunk_summaries(trace.source_chunks),
            "required_json_shape": {
                "title": "Code Wiki",
                "items": [
                    {
                        "title": "Overview",
                        "slug": "overview",
                        "topic": "repository overview",
                        "children": [],
                    }
                ],
            },
        }
        result = await self.llm.complete(
            "catalog",
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        "Return only a JSON object. Keep pages grounded in the provided "
                        f"nodes/chunks.\n{json.dumps(user_payload, ensure_ascii=False)}"
                    ),
                },
            ],
            response_format="json_object",
        )
        self._record_llm_run(
            repo_id,
            task_type="catalog",
            result=result,
            input_payload=user_payload,
            cache_key=f"catalog:{trace.trace_id}",
        )
        payload = _json_object(result.content)
        title, items = _normalize_catalog_payload(payload, repo.name)
        return self.store.save_doc_catalog(repo_id, title=title, structure={"items": items})

    async def generate_all_pages(self, repo_id: str) -> list[PageGenerationResult]:
        catalog = self.store.get_latest_doc_catalog(repo_id)
        if catalog is None:
            catalog = await self.generate_catalog(repo_id)
        results: list[PageGenerationResult] = []
        for item, parent_slug in _flatten_catalog_items(catalog.structure.get("items", [])):
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
        slug = _slugify(str(item.get("slug") or title))
        topic = str(item.get("topic") or title)
        trace = await self.retriever.retrieve(repo_id, topic, max_hops=2)
        graph_markdown = _mermaid_from_trace(trace)
        graph_refs = _graph_refs_from_trace(trace)
        allowed_source_refs = _source_refs_from_chunks(trace.source_chunks)
        prompt = _load_prompt("page.md")
        user_payload = {
            "title": title,
            "slug": slug,
            "topic": topic,
            "context_pack": trace.context_pack,
            "source_chunks": trace.source_chunks,
            "allowed_source_refs": allowed_source_refs,
            "graph_facts": {
                "seed_nodes": trace.seed_nodes,
                "expanded_nodes": trace.expanded_nodes,
                "related_edges": trace.related_edges,
            },
            "graph_edges_for_mermaid": [
                edge
                for edge in trace.related_edges
                if edge.get("type") in SOURCE_EDGE_TYPES
            ][:MAX_MERMAID_EDGES],
            "required_json_shape": {
                "title": title,
                "markdown": "# Page title\n\nGrounded Markdown without Mermaid fences.",
                "source_refs": [{"file_path": "path.py", "start_line": 1, "end_line": 5}],
            },
        }
        result = await self.llm.complete(
            "page",
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        "Return only a JSON object. Do not include Mermaid blocks; the server "
                        "will generate diagrams from graph_edges_for_mermaid. source_refs must "
                        "be selected from allowed_source_refs.\n"
                        f"{json.dumps(user_payload, ensure_ascii=False)}"
                    ),
                },
            ],
            response_format="json_object",
        )
        self._record_llm_run(
            repo_id,
            task_type="page",
            result=result,
            input_payload=user_payload,
            cache_key=f"page:{slug}:{trace.trace_id}",
        )

        payload = _json_object(result.content)
        markdown = _strip_llm_mermaid(str(payload.get("markdown") or ""))
        source_refs, validation_errors = _validate_source_refs(
            repo_path=repo.path,
            requested_refs=payload.get("source_refs"),
            source_chunks=trace.source_chunks,
        )
        if not source_refs:
            validation_errors.append("At least one valid source_ref is required.")

        status = "generated" if not validation_errors else "draft"
        if status == "generated":
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
        for item, parent_slug in _flatten_catalog_items(catalog.structure.get("items", [])):
            if _slugify(str(item.get("slug") or item.get("title") or "")) == slug:
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
            prompt_version=f"{task_type}:v1",
            input_hash=sha256(json.dumps(input_payload, sort_keys=True).encode("utf-8")).hexdigest(),
            cache_key=cache_key,
            tokens_in=int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
        )


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
                "topic": "repository overview",
                "children": [],
            }
        ]
    return title, items


def _normalize_catalog_item(raw_item: Any, used_slugs: set[str]) -> dict[str, Any] | None:
    if not isinstance(raw_item, dict):
        return None
    title = str(raw_item.get("title") or "").strip()
    if not title:
        return None
    slug = _unique_slug(_slugify(str(raw_item.get("slug") or title)), used_slugs)
    topic = str(raw_item.get("topic") or title)
    raw_children = raw_item.get("children") or []
    children = []
    if isinstance(raw_children, list):
        children = [
            child
            for child in (_normalize_catalog_item(child, used_slugs) for child in raw_children[:8])
            if child is not None
        ]
    return {"title": title, "slug": slug, "topic": topic, "children": children}


def _flatten_catalog_items(
    items: list[Any],
    *,
    parent_slug: str | None = None,
):
    for item in items:
        if not isinstance(item, dict):
            continue
        yield item, parent_slug
        slug = _slugify(str(item.get("slug") or item.get("title") or ""))
        children = item.get("children") or []
        if isinstance(children, list):
            yield from _flatten_catalog_items(children, parent_slug=slug)


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


def _source_refs_from_chunks(chunks: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "file_path": chunk["file_path"],
            "start_line": chunk["start_line"],
            "end_line": chunk["end_line"],
            "chunk_id": chunk["id"],
        }
        for chunk in chunks
        if isinstance(chunk.get("file_path"), str)
        and isinstance(chunk.get("start_line"), int)
        and isinstance(chunk.get("end_line"), int)
    ]


def _validate_source_refs(
    *,
    repo_path: str,
    requested_refs: Any,
    source_chunks: list[dict[str, object]],
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(requested_refs, list):
        return [], ["source_refs must be an array."]

    repo_root = Path(repo_path).resolve()
    chunk_ranges = _chunk_ranges(source_chunks)
    valid_refs: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[tuple[str, int, int]] = set()

    for index, raw_ref in enumerate(requested_refs):
        if not isinstance(raw_ref, dict):
            errors.append(f"source_refs[{index}] must be an object.")
            continue
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
        valid_refs.append(
            {
                "file_path": file_path,
                "start_line": start_line,
                "end_line": end_line,
                "chunk_id": matching_chunk["id"],
            }
        )
    return valid_refs, errors


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


def _compose_page_markdown(
    markdown: str,
    mermaid: str,
    source_refs: list[dict[str, Any]],
) -> str:
    sections = [markdown.strip()]
    if mermaid:
        sections.append(mermaid.strip())
    sections.append(_sources_markdown(source_refs))
    return "\n\n".join(section for section in sections if section)


def _sources_markdown(source_refs: list[dict[str, Any]]) -> str:
    lines = ["## Sources"]
    for ref in source_refs:
        lines.append(
            f"- [{ref['file_path']}:L{ref['start_line']}-L{ref['end_line']}](source-link)"
        )
    return "\n".join(lines)


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


def _mermaid_from_trace(trace: RetrievalTrace) -> str:
    nodes = {
        str(node["id"]): node
        for node in [*trace.seed_nodes, *trace.expanded_nodes]
        if "id" in node
    }
    edges = [
        edge
        for edge in trace.related_edges
        if edge.get("type") in SOURCE_EDGE_TYPES
        and edge.get("source_id") in nodes
        and edge.get("target_id") in nodes
    ][:MAX_MERMAID_EDGES]
    if not edges:
        return ""

    node_aliases: dict[str, str] = {}
    lines = ["## Graph", "", "```mermaid", "flowchart TD"]
    for edge in edges:
        source_id = str(edge["source_id"])
        target_id = str(edge["target_id"])
        source_alias = node_aliases.setdefault(source_id, f"N{len(node_aliases)}")
        target_alias = node_aliases.setdefault(target_id, f"N{len(node_aliases)}")
        source_label = _mermaid_label(nodes[source_id])
        target_label = _mermaid_label(nodes[target_id])
        edge_type = _mermaid_text(str(edge["type"]))
        lines.append(f'  {source_alias}["{source_label}"] -->|{edge_type}| {target_alias}["{target_label}"]')
    lines.append("```")
    return "\n".join(lines)


def _mermaid_label(node: dict[str, object]) -> str:
    name = str(node.get("name") or node.get("id") or "")
    node_type = str(node.get("type") or "")
    return _mermaid_text(f"{name} ({node_type})")


def _mermaid_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', "'").replace("\n", " ")[:80]


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
