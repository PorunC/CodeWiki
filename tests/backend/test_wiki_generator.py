import json
from pathlib import Path

import pytest

from backend.app.database import DocPageRecord, SQLiteStore
from backend.app.services.analyzer import AnalysisService
from backend.app.services.graph_rag import GraphRAGRetriever
from backend.app.services.llm_gateway import LLMResult
from backend.app.services.repo_scanner import RepoScanner
from backend.app.services.wiki_generator import (
    WikiGenerator,
    _include_markdown_citation_refs,
    _replace_citation_markers,
    _source_url,
    _source_url_base,
    _validate_source_refs,
)


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
                    "## Purpose and Scope",
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
            "graph_refs": ["llm-invented-node", "llm-invented-edge"],
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
    assert "## Relevant source files\n- [api.py](source-link)" in page.markdown
    assert "Title: Request Handler graph overview" in page.markdown
    assert "### Component map" in page.markdown
    assert "### Interaction flow" in page.markdown
    assert "```mermaid" in page.markdown
    assert "-->|calls / imports|" in page.markdown
    assert 'C0["Api"]' in page.markdown
    assert 'C1["Service"]' in page.markdown
    assert "handler (function)" not in page.markdown
    assert "answer (function)" not in page.markdown
    assert "Sources: [api.py:L3-L4](source-link)" in page.markdown
    assert "[api.py:L3-L4](source-link)" in page.markdown
    assert page.graph_refs
    assert "llm-invented-node" not in page.graph_refs
    assert any(":edge:" in graph_ref for graph_ref in page.graph_refs)
    assert any(graph_ref.endswith("api.py::handler") for graph_ref in page.graph_refs)
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
            "markdown": "# Request Handler\n\n## Purpose and Scope\n\nUnsupported generated claim.",
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


@pytest.mark.asyncio
async def test_wiki_generator_generates_leaf_pages_for_category_catalog(
    tmp_path: Path,
) -> None:
    store, repo = _analyzed_repo(tmp_path)
    llm = _FakeWikiLLM(
        catalog_payload={
            "title": "Repo Wiki",
            "items": [
                {
                    "title": "Core Runtime",
                    "slug": "core-runtime",
                    "path": "core-runtime",
                    "order": 0,
                    "kind": "category",
                    "topic": "handler answer",
                    "source_hints": ["api.py"],
                    "children": [
                        {
                            "title": "Request Handler",
                            "slug": "request-handler",
                            "path": "core-runtime/request-handler",
                            "order": 0,
                            "kind": "page",
                            "topic": "handler answer",
                            "children": [],
                        }
                    ],
                }
            ],
        },
        page_payload={
            "title": "Request Handler",
            "markdown": "# Request Handler\n\n## Purpose and Scope\n\nThe handler delegates to answer().",
            "source_refs": [{"file_path": "api.py", "start_line": 3, "end_line": 4}],
        },
    )
    generator = WikiGenerator(GraphRAGRetriever(store=store), llm, store=store)

    await generator.generate_catalog(repo.id)
    results = await generator.generate_all_pages(repo.id)

    assert [result.page.slug for result in results] == ["core-runtime", "request-handler"]
    assert results[0].page.parent_slug is None
    assert results[1].page.parent_slug == "core-runtime"


@pytest.mark.asyncio
async def test_wiki_generator_prunes_pages_removed_from_catalog(tmp_path: Path) -> None:
    store, repo = _analyzed_repo(tmp_path)
    old_page = store.upsert_doc_page(
        DocPageRecord(
            id="old-page",
            repo_id=repo.id,
            slug="old-page",
            title="Old Page",
            parent_slug=None,
            markdown="# Old Page\n\n## Purpose and Scope\n\nOld.",
            source_refs=[],
            graph_refs=[],
            status="generated",
            updated_at=None,
        )
    )
    assert old_page.slug == "old-page"
    llm = _FakeWikiLLM(
        page_payload={
            "title": "Request Handler",
            "markdown": "# Request Handler\n\n## Purpose and Scope\n\nThe handler delegates to answer().",
            "source_refs": [{"file_path": "api.py", "start_line": 3, "end_line": 4}],
        },
    )
    generator = WikiGenerator(GraphRAGRetriever(store=store), llm, store=store)

    await generator.generate_catalog(repo.id)
    await generator.generate_all_pages(repo.id)

    assert store.get_doc_page(repo.id, "old-page") is None


def test_source_refs_accept_citation_ids_and_replace_markers(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "api.py").write_text("def handler():\n    return 42\n")
    source_chunks = [
        {
            "id": "chunk-1",
            "file_path": "api.py",
            "start_line": 1,
            "end_line": 2,
            "content": "def handler():\n    return 42\n",
        }
    ]
    allowed_source_refs = [
        {
            "citation_id": "S1",
            "file_path": "api.py",
            "start_line": 1,
            "end_line": 2,
            "chunk_id": "chunk-1",
        }
    ]

    refs, errors = _validate_source_refs(
        repo_path=str(repo_dir),
        requested_refs=[{"citation_id": "S1"}],
        source_chunks=source_chunks,
        allowed_source_refs=allowed_source_refs,
    )
    markdown = _replace_citation_markers("The handler returns a constant. [[S1]]", refs)

    assert errors == []
    assert refs[0]["citation_id"] == "S1"
    assert "[api.py:L1-L2](source-link)" in markdown


def test_source_refs_force_allowed_range_and_auto_include_markers(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "api.py").write_text("def handler():\n    return 42\n")
    source_chunks = [
        {
            "id": "chunk-1",
            "file_path": "api.py",
            "start_line": 1,
            "end_line": 2,
            "content": "def handler():\n    return 42\n",
        }
    ]
    allowed_source_refs = [
        {
            "citation_id": "S1",
            "file_path": "api.py",
            "start_line": 1,
            "end_line": 2,
            "chunk_id": "chunk-1",
        }
    ]

    refs, errors = _validate_source_refs(
        repo_path=str(repo_dir),
        requested_refs=[{"citation_id": "S1", "file_path": "api.py", "start_line": 1, "end_line": 99}],
        source_chunks=source_chunks,
        allowed_source_refs=allowed_source_refs,
    )
    auto_refs = _include_markdown_citation_refs("The handler returns a constant. [[S1]]", [], allowed_source_refs)

    assert errors == []
    assert refs[0]["start_line"] == 1
    assert refs[0]["end_line"] == 2
    assert refs[0]["citation_id"] == "S1"
    assert auto_refs[0]["citation_id"] == "S1"


def test_source_urls_normalize_git_remotes_and_quote_paths() -> None:
    base = _source_url_base("git@github.com:owner/repo.git", "abc123")

    assert base == "https://github.com/owner/repo/blob/abc123"
    assert _source_url(base, "src/has space.py", 4, 6).endswith("src/has%20space.py#L4-L6")


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
    def __init__(
        self,
        *,
        page_payload: dict[str, object],
        catalog_payload: dict[str, object] | None = None,
    ) -> None:
        self.page_payload = page_payload
        self.catalog_payload = catalog_payload

    async def complete(
        self,
        task_type: str,
        messages: list[dict[str, str]],
        *,
        response_format: str | None = None,
    ) -> LLMResult:
        assert response_format == "json_object"
        assert messages
        message_text = "\n".join(message["content"] for message in messages)
        if task_type == "catalog":
            assert "catalog_design_requirements" in message_text
            assert "leaf pages for implementation detail" in message_text
            payload = self.catalog_payload or {
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
            assert '"catalog_context"' in message_text
            assert '"detail_expectations"' in message_text
            assert "do not invent wiki pages or links" in message_text
            payload = self.page_payload
        else:
            raise AssertionError(f"Unexpected task type: {task_type}")
        return LLMResult(content=json.dumps(payload), model="fake/wiki", usage={})
