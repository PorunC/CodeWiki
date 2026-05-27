import json
from dataclasses import dataclass
from hashlib import sha256

from backend.app.database import CodeWikiStore
from backend.app.schemas.ask import AskRequest, AskResponse, SourceRef
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.llm.gateway import LLMGateway
from backend.app.services.llm.operations import CachedLLMService, LLMOperation
from backend.app.services.prompts import load_prompt


@dataclass(frozen=True)
class QAPromptContext:
    question: str
    context_pack: dict[str, object]
    source_chunks: list[dict[str, object]]
    related_nodes: list[dict[str, object]]
    related_edges: list[dict[str, object]]
    community_summaries: list[dict[str, object]]


class QuestionAnswerer:
    def __init__(
        self,
        retriever: GraphRAGRetriever,
        llm: LLMGateway,
        *,
        store: CodeWikiStore,
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        self.store = store
        self.llm_service = CachedLLMService(store=self.store, llm=self.llm)

    async def answer(self, repo_id: str, request: AskRequest) -> AskResponse:
        if self.store.get_repo(repo_id) is None:
            raise ValueError(f"Repository not found: {repo_id}")
        if request.mode != "graph_rag":
            raise ValueError(f"Unsupported ask mode: {request.mode}")

        trace = await self.retriever.retrieve(
            repo_id,
            request.question,
            max_hops=request.max_hops,
        )
        related_nodes = [*trace.seed_nodes, *trace.expanded_nodes] if request.include_graph else []
        related_edges = trace.related_edges if request.include_graph else []
        related_communities = trace.community_summaries if request.include_graph else []
        sources = _source_refs(trace.source_chunks) if request.include_sources else []
        prompt_context = QAPromptContext(
            question=request.question,
            context_pack=trace.context_pack,
            source_chunks=trace.source_chunks if request.include_sources else [],
            related_nodes=related_nodes,
            related_edges=related_edges,
            community_summaries=related_communities,
        )
        completion = await self.llm_service.complete(
            repo_id,
            LLMOperation(
                task_type="qa",
                messages=[
                    {"role": "system", "content": _load_prompt("qa.md")},
                    {
                        "role": "user",
                        "content": (
                            "Use only this GraphRAG context. Cite files and lines from sources "
                            "when making code claims.\n"
                            f"{json.dumps(prompt_context.__dict__, ensure_ascii=False)}"
                        ),
                    },
                ],
                input_payload=prompt_context.__dict__,
                cache_namespace="qa",
                cache_parts=(trace.trace_id, sha256(request.question.encode("utf-8")).hexdigest()[:16]),
                model_alias="qa",
                prompt_version="qa:v1",
            ),
        )
        result = completion.result
        return AskResponse(
            answer=result.content.strip() or "I could not produce an answer from the retrieved context.",
            sources=sources,
            related_nodes=related_nodes,
            related_edges=related_edges,
            related_communities=related_communities,
            trace_id=trace.trace_id,
        )

def _source_refs(chunks: list[dict[str, object]]) -> list[SourceRef]:
    refs: list[SourceRef] = []
    seen: set[tuple[str, int, int]] = set()
    for chunk in chunks:
        file_path = chunk.get("file_path")
        start_line = chunk.get("start_line")
        end_line = chunk.get("end_line")
        if not isinstance(file_path, str) or not isinstance(start_line, int) or not isinstance(end_line, int):
            continue
        key = (file_path, start_line, end_line)
        if key in seen:
            continue
        seen.add(key)
        refs.append(SourceRef(file_path=file_path, start_line=start_line, end_line=end_line))
    return refs


def _load_prompt(name: str) -> str:
    return load_prompt(name)
