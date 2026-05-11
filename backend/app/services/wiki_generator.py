from backend.app.services.graph_rag import GraphRAGRetriever
from backend.app.services.llm_gateway import LLMGateway


class WikiGenerator:
    def __init__(self, retriever: GraphRAGRetriever, llm: LLMGateway) -> None:
        self.retriever = retriever
        self.llm = llm

    async def generate_catalog(self, repo_id: str) -> str:
        trace = await self.retriever.retrieve(repo_id, "repository overview")
        result = await self.llm.complete(
            "catalog",
            [
                {
                    "role": "system",
                    "content": "Generate a source-grounded wiki catalog from the provided graph context.",
                },
                {"role": "user", "content": f"Context: {trace}"},
            ],
        )
        return result.content

