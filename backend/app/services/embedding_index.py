from dataclasses import dataclass

from backend.app.database import (
    CodeChunkEmbeddingRecord,
    CodeChunkRecord,
    CodeChunkSearchHit,
    CodeWikiStore,
)
from backend.app.services.graphrag.utils import batched, embedding_text, stable_id
from backend.app.services.llm.gateway import LLMGateway


@dataclass(frozen=True)
class EmbeddingIndexBuildResult:
    count: int
    model: str


class EmbeddingIndex:
    def __init__(
        self,
        store: CodeWikiStore,
        llm: LLMGateway,
        *,
        batch_size: int = 32,
    ) -> None:
        self.store = store
        self.llm = llm
        self.batch_size = batch_size

    async def build(
        self,
        repo_id: str,
        chunks: list[CodeChunkRecord],
    ) -> EmbeddingIndexBuildResult:
        model = self.model
        unique_chunks = _dedupe_chunks_by_content_hash(chunks)
        vectors_by_hash = {
            embedding.content_hash: embedding.embedding
            for embedding in self.store.list_code_chunk_embeddings(repo_id, model=model)
            if embedding.embedding
        }
        missing_chunks = [
            chunk for chunk in unique_chunks
            if chunk.content_hash not in vectors_by_hash
        ]
        for batch in batched(missing_chunks, self.batch_size):
            texts = [embedding_text(chunk) for chunk in batch]
            vectors = await self.llm.embed(texts, task_type="embedding")
            for chunk, vector in zip(batch, vectors, strict=True):
                vectors_by_hash[chunk.content_hash] = vector

        records: list[CodeChunkEmbeddingRecord] = []
        for chunk in chunks:
            vector = vectors_by_hash[chunk.content_hash]
            records.append(
                CodeChunkEmbeddingRecord(
                    id=stable_id(repo_id, "embedding", model, chunk.id, chunk.content_hash),
                    repo_id=repo_id,
                    chunk_id=chunk.id,
                    model=model,
                    dimensions=len(vector),
                    embedding=vector,
                    content_hash=chunk.content_hash,
                    created_at=None,
                )
            )
        self.store.sync_code_chunk_embeddings(repo_id, model=model, embeddings=records)
        return EmbeddingIndexBuildResult(count=len(records), model=model)

    async def ensure(
        self,
        repo_id: str,
        chunks: list[CodeChunkRecord],
    ) -> EmbeddingIndexBuildResult | None:
        model = self.model
        if not chunks:
            return None
        existing_chunk_ids = {
            embedding.chunk_id
            for embedding in self.store.list_code_chunk_embeddings(repo_id, model=model)
        }
        if {chunk.id for chunk in chunks} <= existing_chunk_ids:
            return None
        return await self.build(repo_id, chunks)

    async def search(
        self,
        repo_id: str,
        query: str,
        chunks: list[CodeChunkRecord],
        *,
        limit: int,
    ) -> list[CodeChunkSearchHit]:
        await self.ensure(repo_id, chunks)
        vectors = await self.llm.embed([query], task_type="embedding")
        if not vectors:
            return []
        return self.store.search_code_chunk_embeddings(
            repo_id,
            model=self.model,
            query_embedding=vectors[0],
            limit=limit,
        )

    @property
    def model(self) -> str:
        return self.llm.router.profile_for("embedding").model


async def embed_chunks(
    store: CodeWikiStore,
    llm: LLMGateway,
    repo_id: str,
    chunks: list[CodeChunkRecord],
) -> tuple[int, str]:
    result = await EmbeddingIndex(store, llm).build(repo_id, chunks)
    return result.count, result.model


def _dedupe_chunks_by_content_hash(chunks: list[CodeChunkRecord]) -> list[CodeChunkRecord]:
    unique_chunks: list[CodeChunkRecord] = []
    seen_hashes: set[str] = set()
    for chunk in chunks:
        if chunk.content_hash in seen_hashes:
            continue
        seen_hashes.add(chunk.content_hash)
        unique_chunks.append(chunk)
    return unique_chunks
