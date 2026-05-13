import json

from backend.app.database import SQLiteStore, get_store
from backend.app.services.community_naming import (
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
from backend.app.services.llm_run_recorder import record_llm_run, unique_cache_key


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
        for batch_index, batch in enumerate(batches(target_communities, COMMUNITIES_PER_BATCH), start=1):
            payload = naming_payload(repo.id, repo.name, repo.path, batch, node_by_id, edges)
            fallback_names = {
                str(item["id"]): fallback_name_from_payload(item)
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
            renamed, batch_errors = apply_llm_names(
                renamed,
                batch,
                result.content,
                fallback_names=fallback_names,
            )
            errors.extend(f"batch {batch_index}: {error}" for error in batch_errors)
            llm_run = record_llm_run(
                self.store,
                repo_id,
                task_type="community_summary",
                result=result,
                input_payload=payload,
                cache_key=unique_cache_key("community_naming", "batch", batch_index),
                model_alias="community_namer",
                prompt_version="community_naming:v1",
                status="success" if not batch_errors else "partial",
                error="; ".join(batch_errors) if batch_errors else None,
            )
            llm_run_ids.append(llm_run.id)

        self.store.replace_graph_communities(repo_id, renamed)
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
