from pathlib import Path

import pytest

from backend.app.database import SQLiteStore
from backend.app.schemas.ask import AskRequest
from backend.app.services.analyzer import AnalysisService
from backend.app.services.graph_rag import GraphRAGRetriever
from backend.app.services.llm_gateway import LLMResult
from backend.app.services.question_answerer import QuestionAnswerer
from backend.app.services.repo_scanner import RepoScanner


@pytest.mark.asyncio
async def test_question_answerer_returns_answer_sources_and_related_graph(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "service.py").write_text("def answer():\n    return 42\n")
    (repo_dir / "api.py").write_text(
        "\n".join(
            [
                "from service import answer",
                "",
                "def handler():",
                "    return answer()",
            ]
        )
        + "\n"
    )
    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    AnalysisService(store=store).analyze(repo.id)

    response = await QuestionAnswerer(GraphRAGRetriever(store=store), _FakeQALLM(), store=store).answer(
        repo.id,
        AskRequest(question="What does handler call?"),
    )

    assert "answer" in response.answer
    assert response.sources
    assert any(source.file_path == "api.py" for source in response.sources)
    assert response.related_nodes
    assert any(node["name"] == "handler" for node in response.related_nodes)
    assert response.related_edges
    assert store.list_llm_runs(repo.id, task_type="qa")


class _FakeQALLM:
    async def complete(
        self,
        task_type: str,
        messages: list[dict[str, str]],
        *,
        response_format: str | None = None,
    ) -> LLMResult:
        assert task_type == "qa"
        assert response_format is None
        assert "GraphRAG context" in messages[-1]["content"]
        return LLMResult(
            content="`handler` calls `answer`, which returns 42. See api.py and service.py.",
            model="fake/qa",
            usage={"prompt_tokens": 10, "completion_tokens": 12},
        )
