import json
from pathlib import Path

import pytest

from backend.app.database import SQLiteStore
from backend.app.services.analyzer import AnalysisService
from backend.app.services.graph_rag import GraphRAGRetriever
from backend.app.services.llm_gateway import LLMResult
from backend.app.services.repo_scanner import RepoScanner
from backend.app.services.wiki_generator import WikiGenerator


@pytest.mark.asyncio
async def test_wiki_generator_saves_catalog_and_grounded_page(tmp_path: Path) -> None:
    store, repo = _analyzed_repo(tmp_path)
    llm = _FakeWikiLLM(
        page_payload={
            "title": "Request Handler",
            "markdown": "\n".join(
                [
                    "# Request Handler",
                    "",
                    "The handler delegates to answer().",
                    "",
                    "```mermaid",
                    "flowchart TD",
                    "  fake --> invented",
                    "```",
                ]
            ),
            "source_refs": [{"file_path": "api.py", "start_line": 3, "end_line": 4}],
        }
    )
    generator = WikiGenerator(GraphRAGRetriever(store=store), llm, store=store)

    catalog = await generator.generate_catalog(repo.id)
    results = await generator.generate_all_pages(repo.id)

    assert catalog.structure["items"][0]["slug"] == "request-handler"
    page = results[0].page
    assert page.status == "generated"
    assert page.source_refs[0]["file_path"] == "api.py"
    assert "fake --> invented" not in page.markdown
    assert "```mermaid" in page.markdown
    assert "-->|calls|" in page.markdown
    assert "[api.py:L3-L4](source-link)" in page.markdown
    assert page.graph_refs
    assert store.get_latest_doc_catalog(repo.id) is not None
    assert store.get_doc_page(repo.id, "request-handler") == page
    assert store.list_llm_runs(repo.id, task_type="catalog")
    assert store.list_llm_runs(repo.id, task_type="page")


@pytest.mark.asyncio
async def test_wiki_generator_marks_page_draft_when_source_refs_are_invalid(
    tmp_path: Path,
) -> None:
    store, repo = _analyzed_repo(tmp_path)
    llm = _FakeWikiLLM(
        page_payload={
            "title": "Request Handler",
            "markdown": "# Request Handler\n\nUnsupported generated claim.",
            "source_refs": [{"file_path": "missing.py", "start_line": 1, "end_line": 1}],
        }
    )
    generator = WikiGenerator(GraphRAGRetriever(store=store), llm, store=store)

    result = await generator.generate_page(
        repo.id,
        {"title": "Request Handler", "slug": "request-handler", "topic": "handler answer"},
    )

    assert result.page.status == "draft"
    assert result.page.source_refs == []
    assert "Unsupported generated claim" not in result.page.markdown
    assert "Validation Errors" in result.page.markdown
    assert result.validation_errors


def _analyzed_repo(tmp_path: Path):
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
    return store, repo


class _FakeWikiLLM:
    def __init__(self, *, page_payload: dict[str, object]) -> None:
        self.page_payload = page_payload

    async def complete(
        self,
        task_type: str,
        messages: list[dict[str, str]],
        *,
        response_format: str | None = None,
    ) -> LLMResult:
        assert response_format == "json_object"
        assert messages
        if task_type == "catalog":
            payload = {
                "title": "Repo Wiki",
                "items": [
                    {
                        "title": "Request Handler",
                        "slug": "request-handler",
                        "topic": "handler answer",
                        "children": [],
                    }
                ],
            }
        elif task_type == "page":
            payload = self.page_payload
        else:
            raise AssertionError(f"Unexpected task type: {task_type}")
        return LLMResult(content=json.dumps(payload), model="fake/wiki", usage={})
