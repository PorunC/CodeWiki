import json

from backend.app.database import CodeWikiStore, GraphCommunityRecord, get_store
from backend.app.services.community.edges import CommunityEdgeBuilder
from backend.app.services.community.naming import (
    COMMUNITIES_PER_BATCH,
    MAX_COMMUNITIES_PER_LLM_CALL,
    CommunityNamingResult,
    apply_llm_names,
    batches,
    fallback_name_from_payload,
    naming_payload,
    renamed_count,
)
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.llm_operations import CachedLLMService, LLMOperation
from backend.app.services.prompts import load_prompt


class CommunityNamer:
    """Generate LLM-backed names and summaries for graph communities."""

    def __init__(
        self,
        llm: LLMGateway,
        *,
        store: CodeWikiStore | None = None,
    ) -> None:
        self.llm = llm
        self.store = store or get_store()
        self.llm_service = CachedLLMService(store=self.store, llm=self.llm)

    async def summarize_communities(
        self,
        repo_id: str,
        *,
        max_communities: int = MAX_COMMUNITIES_PER_LLM_CALL,
    ) -> CommunityNamingResult:
        return await self.name_communities(repo_id, max_communities=max_communities)

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
        target_communities = _select_naming_targets(
            communities,
            max_communities=max_communities,
        )
        renamed = communities
        errors: list[str] = []
        llm_run_ids: list[str] = []
        prompt = load_prompt("community_summary.md")
        for batch_index, batch in enumerate(batches(target_communities, COMMUNITIES_PER_BATCH), start=1):
            payload = naming_payload(
                repo.id,
                repo.name,
                repo.path,
                batch,
                node_by_id,
                edges,
                all_communities=renamed,
            )
            fallback_names = {
                str(item["id"]): fallback_name_from_payload(item)
                for item in payload["communities"]
                if isinstance(item, dict)
            }
            completion = await self.llm_service.complete(
                repo_id,
                LLMOperation(
                    task_type="community_summary",
                    messages=[
                        {"role": "system", "content": prompt},
                        {
                            "role": "user",
                            "content": json.dumps(payload, ensure_ascii=False),
                        },
                    ],
                    input_payload=payload,
                    cache_namespace="community_naming",
                    cache_parts=("batch", batch_index),
                    model_alias="community_namer",
                    prompt_version="community_naming:v2",
                    response_format="json_object",
                ),
            )
            result = completion.result
            renamed, batch_errors = apply_llm_names(
                renamed,
                batch,
                result.content,
                fallback_names=fallback_names,
            )
            errors.extend(f"batch {batch_index}: {error}" for error in batch_errors)
            llm_run = completion.run
            if batch_errors:
                updated_run = self.store.update_llm_run_status(
                    llm_run.id,
                    status="partial",
                    error="; ".join(batch_errors),
                )
                if updated_run is not None:
                    llm_run = updated_run
            llm_run_ids.append(llm_run.id)

        self.store.replace_graph_communities(repo_id, renamed)
        self.store.replace_graph_community_edges(
            repo_id,
            CommunityEdgeBuilder().build(repo_id, renamed, edges),
        )
        renamed_total = renamed_count(communities, renamed)
        return CommunityNamingResult(
            repo_id=repo_id,
            status="renamed" if not errors else "partial",
            renamed_count=renamed_total,
            community_count=len(renamed),
            llm_run_id=llm_run_ids[0] if llm_run_ids else None,
            llm_run_ids=llm_run_ids,
            errors=errors,
        )


_naming_payload = naming_payload
_apply_llm_names = apply_llm_names
_fallback_name_from_payload = fallback_name_from_payload
_renamed_count = renamed_count
_batches = batches


def _select_naming_targets(
    communities: list[GraphCommunityRecord],
    *,
    max_communities: int,
) -> list[GraphCommunityRecord]:
    limit = max(1, min(max_communities, MAX_COMMUNITIES_PER_LLM_CALL))
    by_level: dict[int, list[GraphCommunityRecord]] = {}
    for community in communities:
        by_level.setdefault(int(community.level or 0), []).append(community)

    selected: list[GraphCommunityRecord] = []
    seen: set[str] = set()

    def add(candidates: list[GraphCommunityRecord]) -> None:
        for community in candidates:
            if len(selected) >= limit:
                return
            if community.id in seen:
                continue
            selected.append(community)
            seen.add(community.id)

    add(sorted(by_level.get(0, []), key=_parent_target_key))
    for level in sorted(level for level in by_level if level > 0):
        add(sorted(by_level[level], key=_leaf_target_key))
    add(communities)
    return selected


def _parent_target_key(community: GraphCommunityRecord) -> tuple[int, int, str]:
    return (int(community.rank or 0), -len(community.node_ids), community.name)


def _leaf_target_key(community: GraphCommunityRecord) -> tuple[int, int, int, str]:
    return (-len(community.node_ids), -_file_count(community), int(community.rank or 0), community.name)


def _file_count(community: GraphCommunityRecord) -> int:
    return len({node_id.rsplit(":", 1)[0] for node_id in community.node_ids})
