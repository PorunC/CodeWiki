from backend.app.database import CodeChunkEmbeddingRecord, CodeChunkRecord, SQLiteStore
from backend.app.services.graphrag.utils import batched, embedding_text, stable_id
from backend.app.services.llm_gateway import LLMGateway


async def embed_chunks(
    store: SQLiteStore,
    llm: LLMGateway,
    repo_id: str,
    chunks: list[CodeChunkRecord],
) -> tuple[int, str]:
    model = llm.router.profile_for("embedding").model
    records: list[CodeChunkEmbeddingRecord] = []
    for batch in batched(chunks, 32):
        texts = [embedding_text(chunk) for chunk in batch]
        vectors = await llm.embed(texts, task_type="embedding")
        for chunk, vector in zip(batch, vectors, strict=True):
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
    store.replace_code_chunk_embeddings(repo_id, model=model, embeddings=records)
    return len(records), model
