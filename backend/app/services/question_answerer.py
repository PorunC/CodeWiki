import json
from dataclasses import dataclass
from hashlib import sha256
from importlib import resources
from typing import Any

from backend.app.database import SQLiteStore, get_store
from backend.app.schemas.ask import AskRequest, AskResponse, SourceRef
from backend.app.services.graph_rag import GraphRAGRetriever
from backend.app.services.llm_gateway import LLMGateway, LLMResult


@dataclass(frozen=True)
class QAPromptContext:
    question: str
    context_pack: dict[str, object]
    source_chunks: list[dict[str, object]]
    related_nodes: list[dict[str, object]]
    related_edges: list[dict[str, object]]


class QuestionAnswerer:
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
        sources = _source_refs(trace.source_chunks) if request.include_sources else []
        prompt_context = QAPromptContext(
            question=request.question,
            context_pack=trace.context_pack,
            source_chunks=trace.source_chunks if request.include_sources else [],
            related_nodes=related_nodes,
            related_edges=related_edges,
        )
        result = await self.llm.complete(
            "qa",
            [
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
        )
        self._record_llm_run(
            repo_id,
            result=result,
            input_payload=prompt_context.__dict__,
            cache_key=f"qa:{trace.trace_id}:{sha256(request.question.encode('utf-8')).hexdigest()[:16]}",
        )
        return AskResponse(
            answer=result.content.strip() or "I could not produce an answer from the retrieved context.",
            sources=sources,
            related_nodes=related_nodes,
            related_edges=related_edges,
            trace_id=trace.trace_id,
        )

    def _record_llm_run(
        self,
        repo_id: str,
        *,
        result: LLMResult,
        input_payload: dict[str, Any],
        cache_key: str,
    ) -> None:
        usage = result.usage or {}
        self.store.record_llm_run(
            repo_id,
            task_type="qa",
            provider=result.model.split("/", 1)[0] if "/" in result.model else None,
            model=result.model,
            model_alias="qa",
            prompt_version="qa:v1",
            input_hash=sha256(json.dumps(input_payload, sort_keys=True).encode("utf-8")).hexdigest(),
            cache_key=cache_key,
            tokens_in=int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
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
    return resources.files("backend.app.prompts").joinpath(name).read_text(encoding="utf-8")
