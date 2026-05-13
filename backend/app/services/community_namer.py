import json
import re
import uuid
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Any

from backend.app.database import GraphCommunityRecord, SQLiteStore, get_store
from backend.app.services.graph_builder import CodeGraphEdge, CodeGraphNode
from backend.app.services.llm_gateway import LLMGateway, LLMResult

MAX_COMMUNITIES_PER_LLM_CALL = 40
COMMUNITIES_PER_BATCH = 8
MAX_COMMUNITY_FILES = 12
MAX_COMMUNITY_SYMBOLS = 16
MAX_COMMUNITY_EDGES = 10
MAX_NAME_LENGTH = 64


@dataclass(frozen=True)
class CommunityNamingResult:
    repo_id: str
    status: str
    renamed_count: int
    community_count: int
    llm_run_id: str | None = None
    llm_run_ids: list[str] | None = None
    errors: list[str] | None = None


class CommunityNamer:
    def __init__(
        self,
        llm: LLMGateway,
        *,
        store: SQLiteStore | None = None,
    ) -> None:
        self.llm = llm
        self.store = store or get_store()

    async def name_communities(
        self,
        repo_id: str,
        *,
        max_communities: int = MAX_COMMUNITIES_PER_LLM_CALL,
    ) -> CommunityNamingResult:
        repo = self.store.get_repo(repo_id)
        if repo is None:
            raise ValueError(f"Repository not found: {repo_id}")

        communities = self.store.list_graph_communities(repo_id)
        if not communities:
            return CommunityNamingResult(
                repo_id=repo_id,
                status="no_communities",
                renamed_count=0,
                community_count=0,
                errors=[],
            )

        nodes, edges = self.store.get_graph(repo_id)
        node_by_id = {node.id: node for node in nodes}
        target_communities = communities[: max(1, min(max_communities, MAX_COMMUNITIES_PER_LLM_CALL))]
        renamed = communities
        errors: list[str] = []
        llm_run_ids: list[str] = []
        for batch_index, batch in enumerate(_batches(target_communities, COMMUNITIES_PER_BATCH), start=1):
            payload = _naming_payload(repo.id, repo.name, repo.path, batch, node_by_id, edges)
            fallback_names = {
                str(item["id"]): _fallback_name_from_payload(item)
                for item in payload["communities"]
                if isinstance(item, dict)
            }
            result = await self.llm.complete(
                "community_summary",
                [
                    {
                        "role": "system",
                        "content": (
                            "You name code graph communities for a Code Wiki. "
                            "You must stay grounded in provided graph evidence and return only JSON."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
                response_format="json_object",
            )
            renamed, batch_errors = _apply_llm_names(
                renamed,
                batch,
                result.content,
                fallback_names=fallback_names,
            )
            errors.extend(f"batch {batch_index}: {error}" for error in batch_errors)
            llm_run = self._record_llm_run(
                repo_id,
                result=result,
                input_payload=payload,
                renamed_count=_renamed_count(communities, renamed),
                errors=batch_errors,
                batch_index=batch_index,
            )
            llm_run_ids.append(llm_run.id)

        self.store.replace_graph_communities(repo_id, renamed)
        renamed_count = _renamed_count(communities, renamed)
        return CommunityNamingResult(
            repo_id=repo_id,
            status="renamed" if not errors else "partial",
            renamed_count=renamed_count,
            community_count=len(renamed),
            llm_run_id=llm_run_ids[0] if llm_run_ids else None,
            llm_run_ids=llm_run_ids,
            errors=errors,
        )

    def _record_llm_run(
        self,
        repo_id: str,
        *,
        result: LLMResult,
        input_payload: dict[str, Any],
        renamed_count: int,
        errors: list[str],
        batch_index: int,
    ):
        usage = result.usage or {}
        status = "success" if not errors else "partial"
        return self.store.record_llm_run(
            repo_id,
            task_type="community_summary",
            provider=result.model.split("/", 1)[0] if "/" in result.model else None,
            model=result.model,
            model_alias="community_namer",
            prompt_version="community_naming:v1",
            input_hash=sha256(json.dumps(input_payload, sort_keys=True).encode("utf-8")).hexdigest(),
            cache_key=f"community_naming:batch:{batch_index}:{uuid.uuid4().hex}",
            tokens_in=int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
            status=status,
            error="; ".join(errors) if errors else None,
        )


def _naming_payload(
    repo_id: str,
    repo_name: str,
    repo_path: str,
    communities: list[GraphCommunityRecord],
    node_by_id: dict[str, CodeGraphNode],
    edges: list[CodeGraphEdge],
) -> dict[str, Any]:
    return {
        "repo": {
            "id": repo_id,
            "name": repo_name,
            "path": repo_path,
        },
        "task": (
            "Rename graph communities using only the provided files, symbols, summaries, "
            "and graph relationships. Keep node membership unchanged."
        ),
        "communities": [
            _community_payload(community, node_by_id, edges)
            for community in communities
        ],
        "naming_rules": [
            "Use concise developer-facing subsystem names, 2-6 words.",
            "Prefer capability/workflow names over generic layer names.",
            "Avoid names like Backend Subsystem, Frontend Subsystem, Community 1, Cluster, Misc, Core.",
            "Do not invent modules, products, files, or dependencies.",
            "Return one object per input community id.",
        ],
        "required_json_shape": {
            "communities": [
                {
                    "id": "community-id",
                    "name": "GraphRAG Retrieval",
                    "summary": "One source-grounded sentence describing responsibility and boundaries.",
                }
            ]
        },
    }


def _community_payload(
    community: GraphCommunityRecord,
    node_by_id: dict[str, CodeGraphNode],
    edges: list[CodeGraphEdge],
) -> dict[str, Any]:
    node_ids = set(community.node_ids)
    files = sorted(
        {
            node.file_path
            for node_id in community.node_ids
            if (node := node_by_id.get(node_id)) is not None and node.file_path
        }
    )
    symbols = [
        {
            "name": node.name,
            "type": node.type,
            "file_path": node.file_path,
        }
        for node_id in community.node_ids
        if (node := node_by_id.get(node_id)) is not None and node.type != "file"
    ]
    internal_edges = [
        _edge_payload(edge, node_by_id)
        for edge in edges
        if edge.source_id in node_ids and edge.target_id in node_ids
    ][:MAX_COMMUNITY_EDGES]
    boundary_edges = [
        _edge_payload(edge, node_by_id)
        for edge in edges
        if (edge.source_id in node_ids) ^ (edge.target_id in node_ids)
    ][:MAX_COMMUNITY_EDGES]
    return {
        "id": community.id,
        "current_name": community.name,
        "node_count": len(community.node_ids),
        "files": files[:MAX_COMMUNITY_FILES],
        "symbols": symbols[:MAX_COMMUNITY_SYMBOLS],
        "deterministic_summary": community.summary,
        "internal_edges": internal_edges,
        "boundary_edges": boundary_edges,
    }


def _edge_payload(
    edge: CodeGraphEdge,
    node_by_id: dict[str, CodeGraphNode],
) -> dict[str, Any]:
    source = node_by_id.get(edge.source_id)
    target = node_by_id.get(edge.target_id)
    return {
        "type": edge.type,
        "source": source.name if source else edge.source_id,
        "source_type": source.type if source else "",
        "target": target.name if target else edge.target_id,
        "target_type": target.type if target else "",
        "confidence": edge.confidence,
    }


def _apply_llm_names(
    all_communities: list[GraphCommunityRecord],
    target_communities: list[GraphCommunityRecord],
    content: str,
    *,
    fallback_names: dict[str, str] | None = None,
) -> tuple[list[GraphCommunityRecord], list[str]]:
    errors: list[str] = []
    by_id = {community.id: community for community in all_communities}
    target_ids = {community.id for community in target_communities}
    try:
        payload = _json_object(content)
    except ValueError as exc:
        errors.append(str(exc))
        return all_communities, errors

    raw_items = payload.get("communities")
    if not isinstance(raw_items, list):
        errors.append("LLM response must contain a communities array.")
        return all_communities, errors

    updates: dict[str, GraphCommunityRecord] = {}
    seen_names: set[str] = set()
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            errors.append(f"communities[{index}] must be an object.")
            continue
        community_id = str(raw_item.get("id") or "")
        if community_id not in target_ids:
            errors.append(f"communities[{index}] uses unknown community id.")
            continue
        community = by_id[community_id]
        name = _normalize_name(raw_item.get("name"), fallback=community.name)
        if _is_generic_name(name):
            fallback_name = (fallback_names or {}).get(community_id) or community.name
            name = _normalize_name(fallback_name, fallback=f"Subsystem {index + 1}")
        name = _dedupe_name(name, seen_names)
        seen_names.add(name.lower())
        summary = _normalize_summary(raw_item.get("summary"), fallback=community.summary or "")
        updates[community_id] = replace(
            community,
            name=name,
            summary=summary,
            summary_hash=sha256(summary.encode("utf-8")).hexdigest(),
        )

    return [updates.get(community.id, community) for community in all_communities], errors


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


def _normalize_name(value: Any, *, fallback: str) -> str:
    name = re.sub(r"\s+", " ", str(value or "").strip())
    name = re.sub(r"^community\s+\d+\s*[:\-]\s*", "", name, flags=re.IGNORECASE)
    if not name:
        name = fallback
    name = name[:MAX_NAME_LENGTH].strip(" :-")
    return name or fallback


def _normalize_summary(value: Any, *, fallback: str) -> str:
    summary = re.sub(r"\s+", " ", str(value or "").strip())
    if not summary:
        summary = fallback
    return summary[:800].strip()


def _is_generic_name(name: str) -> bool:
    normalized = name.lower().strip()
    return normalized in {
        "backend subsystem",
        "frontend subsystem",
        "core subsystem",
        "core",
        "misc",
        "miscellaneous",
        "cluster",
        "community",
    } or normalized.startswith(("community ", "cluster "))


def _fallback_name_from_payload(item: dict[str, Any]) -> str:
    files = [
        str(file_path)
        for file_path in item.get("files", [])
        if isinstance(file_path, str)
    ]
    stems = [
        _humanize_name(file_path.rsplit("/", 1)[-1].rsplit(".", 1)[0])
        for file_path in files
        if not file_path.rsplit("/", 1)[-1].startswith("__init__")
    ]
    stems = [stem for stem in stems if stem and stem.lower() not in {"index", "main"}]
    if stems:
        unique = _unique_preserve_order(stems)
        if len(unique) == 1:
            return unique[0]
        return f"{unique[0]} and {unique[1]}"

    symbols = item.get("symbols", [])
    if isinstance(symbols, list):
        for symbol in symbols:
            if not isinstance(symbol, dict):
                continue
            name = str(symbol.get("name") or "")
            if name and not name.startswith("_"):
                return _humanize_name(name)
    current = str(item.get("current_name") or "").strip()
    return current or "Subsystem"


def _humanize_name(value: str) -> str:
    value = re.sub(r"^test_", "", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    value = value.replace("_", " ").replace("-", " ").strip()
    return " ".join(word if word.isupper() else word.capitalize() for word in value.split())


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return unique


def _dedupe_name(name: str, seen_names: set[str]) -> str:
    if name.lower() not in seen_names:
        return name
    suffix = 2
    candidate = f"{name} {suffix}"
    while candidate.lower() in seen_names:
        suffix += 1
        candidate = f"{name} {suffix}"
    return candidate


def _renamed_count(
    before: list[GraphCommunityRecord],
    after: list[GraphCommunityRecord],
) -> int:
    before_by_id = {community.id: community for community in before}
    return sum(
        1
        for community in after
        if (previous := before_by_id.get(community.id)) is not None
        and (previous.name != community.name or previous.summary != community.summary)
    )


def _batches(items: list[GraphCommunityRecord], size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]
