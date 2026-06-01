import asyncio
import json
from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.database import DocPageRecord, SQLiteStore
from backend.app.services.analyzer import AnalysisService
from backend.app.services.llm.gateway import LLMResult
from backend.app.services.repo_scanner import RepoScanner
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.graph import CodeGraphEdge, CodeGraphNode
from backend.app.services.wiki.catalog import _normalize_catalog_payload
from backend.app.services.wiki.catalog_limits import CatalogScaleLimits, catalog_limits_for_repo
from backend.app.services.wiki.diagrams import MermaidDiagram
from backend.app.services.wiki.generator import WikiGenerator
from backend.app.services.wiki.sources import (
    _compose_page_markdown,
    _include_markdown_citation_refs,
    _replace_citation_markers,
    _source_url,
    _source_url_base,
    _validate_diagram_placeholders,
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
    generator = WikiGenerator(
        GraphRAGRetriever(store=store),
        llm,
        store=store,
        settings=_wiki_settings(),
    )

    catalog = await generator.generate_catalog(repo.id)
    results = await generator.generate_all_pages(repo.id)

    catalog_request = llm.catalog_requests[0]
    assert "text" not in catalog_request["context_pack"]
    assert all("metadata" not in node and "provenance" not in node for node in catalog_request["seed_nodes"])
    assert all(
        "metadata" not in node and "provenance" not in node
        for node in catalog_request["expanded_nodes"]
    )
    catalog_slugs = [item["slug"] for item in catalog.structure["items"]]
    assert catalog_slugs[:4] == ["overview", "architecture", "reading-guide", "dependencies"]
    assert "request-handler" in catalog_slugs
    page = _page_by_slug(results, "request-handler")
    assert page.status == "generated"
    assert page.source_refs[0]["file_path"] == "api.py"
    assert any(source_ref.get("read_via") == "ReadFile" for source_ref in page.source_refs)
    assert "fake --> invented" not in page.markdown
    assert "## Relevant source files\n- [api.py](source-link)" in page.markdown
    assert "## Graph" not in page.markdown
    assert "### Request Handler component relationships" in page.markdown
    assert "### Request Handler implementation flow" in page.markdown
    assert "### Request Handler interaction sequence" in page.markdown
    assert "```mermaid" in page.markdown
    assert "-->|calls / imports|" in page.markdown
    assert 'C0["api.py"]' in page.markdown
    assert 'C1["service.py"]' in page.markdown
    assert "handler (function)" in page.markdown
    assert "answer (function)" in page.markdown
    assert "Sources:" not in page.markdown
    assert "  - S1 [L3-L4](source-link)" in page.markdown
    assert page.graph_refs
    assert "llm-invented-node" not in page.graph_refs
    assert any(":edge:" in graph_ref for graph_ref in page.graph_refs)
    assert any(graph_ref.endswith("api.py::handler") for graph_ref in page.graph_refs)
    request_payload = next(
        request for request in llm.page_requests if request.get("slug") == "request-handler"
    )
    assert "graph_edges_for_mermaid" not in request_payload
    graph_facts = request_payload["graph_facts"]
    assert isinstance(graph_facts, dict)
    assert all(
        {"id", "type", "name", "file_path", "line", "hop", "score", "confidence"} >= set(node)
        and "metadata" not in node
        and "provenance" not in node
        for node in graph_facts["seed_nodes"]
    )
    assert all(
        {"id", "source", "target", "type", "confidence", "reason"} >= set(edge)
        and "metadata" not in edge
        and "provenance" not in edge
        for edge in graph_facts["related_edges"]
    )
    assert "community_edges" in graph_facts
    assert all(
        {"id", "source", "target", "type", "confidence", "reason"} >= set(edge)
        for edge in graph_facts["community_edges"]
    )
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
    generator = WikiGenerator(
        GraphRAGRetriever(store=store),
        llm,
        store=store,
        settings=_wiki_settings(),
    )

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
async def test_wiki_generator_marks_page_draft_when_llm_provider_fails(
    tmp_path: Path,
) -> None:
    store, repo = _analyzed_repo(tmp_path)
    generator = WikiGenerator(
        GraphRAGRetriever(store=store),
        _FailingPageLLM(),
        store=store,
        settings=_wiki_settings(),
    )

    result = await generator.generate_page(
        repo.id,
        {"title": "Request Handler", "slug": "request-handler", "topic": "handler answer"},
    )

    runs = store.list_llm_runs(repo.id, task_type="page")
    assert result.page.status == "draft"
    assert result.page.source_refs == []
    assert "LLM provider call failed" in result.page.markdown
    assert result.validation_errors == [f"LLM provider call failed: {runs[0].error}"]
    assert len(runs) == 1
    assert runs[0].status == "error"
    assert runs[0].model == "page"


@pytest.mark.asyncio
async def test_wiki_generator_omits_invalid_server_mermaid_without_drafting_page(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store, repo = _analyzed_repo(tmp_path)
    llm = _FakeWikiLLM(
        page_payload={
            "title": "Request Handler",
            "markdown": "# Request Handler\n\n## Purpose and Scope\n\nThe handler delegates to answer().",
            "source_refs": [{"file_path": "api.py", "start_line": 3, "end_line": 4}],
        }
    )
    monkeypatch.setattr(
        "backend.app.services.wiki.page_generator._mermaid_diagrams_from_trace",
        lambda *_args, **_kwargs: [
            MermaidDiagram(
                slot="broken",
                kind="component",
                title="Broken graph",
                heading_hint="System Context",
                reason="test invalid diagram",
                lines=["flowchart TD", "  A -->"],
            )
        ],
    )
    generator = WikiGenerator(
        GraphRAGRetriever(store=store),
        llm,
        store=store,
        settings=_wiki_settings(),
    )

    result = await generator.generate_page(
        repo.id,
        {"title": "Request Handler", "slug": "request-handler", "topic": "handler answer"},
    )

    assert result.page.status == "generated"
    assert result.validation_errors == []
    assert "Validation Errors" not in result.page.markdown
    assert "```mermaid" not in result.page.markdown
    assert "The handler delegates to answer()." in result.page.markdown


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
    generator = WikiGenerator(
        GraphRAGRetriever(store=store),
        llm,
        store=store,
        settings=_wiki_settings(),
    )

    await generator.generate_catalog(repo.id)
    results = await generator.generate_all_pages(repo.id)

    slugs = [result.page.slug for result in results]
    assert slugs[:4] == ["overview", "architecture", "reading-guide", "dependencies"]
    assert slugs[-2:] == ["core-runtime", "request-handler"]
    assert _page_by_slug(results, "core-runtime").parent_slug is None
    assert _page_by_slug(results, "request-handler").parent_slug == "core-runtime"


@pytest.mark.asyncio
async def test_wiki_generator_synthesizes_parent_from_generated_child_pages(
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
            "markdown": (
                "# Request Handler\n\n"
                "## Purpose and Scope\n\n"
                "The child handler delegates to answer(). [[S1]]"
            ),
            "source_refs": [{"citation_id": "S1", "file_path": "api.py", "start_line": 3, "end_line": 4}],
        },
        page_payloads_by_slug={
            "core-runtime": {
                "title": "Core Runtime",
                "markdown": (
                    "# Core Runtime\n\n"
                    "## Purpose and Scope\n\n"
                    "The parent page summarizes the generated child page. [[S1]]"
                ),
                "source_refs": [{"citation_id": "S1", "file_path": "api.py", "start_line": 3, "end_line": 4}],
            }
        },
    )
    generator = WikiGenerator(
        GraphRAGRetriever(store=store),
        llm,
        store=store,
        settings=_wiki_settings(),
    )

    await generator.generate_catalog(repo.id)
    results = await generator.generate_all_pages(repo.id)

    assert [result.page.slug for result in results][-2:] == ["core-runtime", "request-handler"]
    assert llm.page_call_slugs.index("request-handler") < llm.page_call_slugs.index("core-runtime")
    parent_request = next(request for request in llm.page_requests if request["slug"] == "core-runtime")
    assert parent_request["parent_synthesis"]["has_child_pages"] is True
    assert parent_request["child_page_summaries"][0]["slug"] == "request-handler"
    assert "The child handler delegates to answer()." in parent_request["child_page_summaries"][0]["overview_markdown"]


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
    generator = WikiGenerator(
        GraphRAGRetriever(store=store),
        llm,
        store=store,
        settings=_wiki_settings(),
    )

    await generator.generate_catalog(repo.id)
    await generator.generate_all_pages(repo.id)

    assert store.get_doc_page(repo.id, "old-page") is None


@pytest.mark.asyncio
async def test_wiki_generator_translates_catalog_and_pages(tmp_path: Path) -> None:
    store, repo = _analyzed_repo(tmp_path)
    llm = _FakeWikiLLM(
        page_payload={
            "title": "Request Handler",
            "markdown": (
                "# Request Handler\n\n"
                "## Purpose and Scope\n\n"
                "The handler delegates to answer(). [[S1]]"
            ),
            "source_refs": [{"citation_id": "S1", "file_path": "api.py", "start_line": 3, "end_line": 4}],
        },
        translation_payloads={
            "catalog": {
                "title": "Translated Wiki",
                "items": [{"path": "request-handler", "title": "Translated Handler"}],
            },
            "page": {
                "title": "Translated Handler",
                "markdown": (
                    "# Translated Handler\n\n"
                    "## Purpose and Scope\n\n"
                    "Translated handler text. [api.py:L3-L4](source-link)"
                ),
            },
        },
    )
    generator = WikiGenerator(
        GraphRAGRetriever(store=store),
        llm,
        store=store,
        settings=_wiki_settings(),
    )

    await generator.generate_catalog(repo.id)
    await generator.generate_all_pages(repo.id)
    result = await generator.translate_wiki(repo.id, source_language="en", target_language="zh")

    assert result.catalog.language_code == "zh"
    assert result.catalog.title == "Translated Wiki"
    translated_catalog_item = next(
        item for item in result.catalog.structure["items"] if item["slug"] == "request-handler"
    )
    assert translated_catalog_item["title"] == "Translated Handler"
    translated_page = next(page for page in result.pages if page.slug == "request-handler")
    assert translated_page.language_code == "zh"
    assert translated_page.source_refs[0]["file_path"] == "api.py"
    assert store.get_latest_doc_catalog(repo.id, language_code="zh") == result.catalog
    assert store.get_doc_page(repo.id, "request-handler", language_code="zh") == translated_page
    assert llm.translation_requests[0]["content_type"] == "catalog"
    assert [request["content_type"] for request in llm.translation_requests[1:]] == ["page"] * len(result.pages)


@pytest.mark.asyncio
async def test_wiki_translation_reuses_existing_generated_pages(tmp_path: Path) -> None:
    store, repo = _analyzed_repo(tmp_path)
    _save_source_catalog_and_pages(
        store,
        repo.id,
        {
            "stable": "# Stable\n\n## Purpose and Scope\n\nAlready translated.",
            "target": "# Target\n\n## Purpose and Scope\n\nAlready translated too.",
        },
    )
    llm = _FakeWikiLLM(
        page_payload={
            "title": "Unused",
            "markdown": "# Unused\n\n## Purpose and Scope\n\nUnused.",
            "source_refs": [],
        },
        translation_payloads={
            "catalog": {
                "title": "中文 Wiki",
                "items": [
                    {"path": "stable", "title": "稳定页面"},
                    {"path": "target", "title": "目标页面"},
                ],
            },
            "page": {
                "title": "已翻译页面",
                "markdown": "# 已翻译页面\n\n## Purpose and Scope\n\n复用测试。",
            },
        },
    )
    generator = WikiGenerator(
        GraphRAGRetriever(store=store),
        llm,
        store=store,
        settings=_wiki_settings(),
    )

    first = await generator.translate_wiki(repo.id, source_language="en", target_language="zh")
    run_count = len(store.list_llm_runs(repo.id, task_type="translation"))
    llm.translation_requests.clear()
    second = await generator.translate_wiki(repo.id, source_language="en", target_language="zh")

    assert [page.slug for page in first.pages] == ["stable", "target"]
    assert [page.slug for page in second.pages] == ["stable", "target"]
    assert len(store.list_llm_runs(repo.id, task_type="translation")) == run_count + 1
    assert llm.translation_requests == []


@pytest.mark.asyncio
async def test_wiki_translation_limits_page_concurrency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, repo = _analyzed_repo(tmp_path)
    page_markdown_by_slug = {
        f"page-{index}": f"# Page {index}\n\n## Purpose and Scope\n\nPage {index}."
        for index in range(5)
    }
    _save_source_catalog_and_pages(store, repo.id, page_markdown_by_slug)
    generator = WikiGenerator(
        GraphRAGRetriever(store=store),
        _FakeWikiLLM(
            page_payload={
                "title": "Unused",
                "markdown": "# Unused\n\n## Purpose and Scope\n\nUnused.",
                "source_refs": [],
            }
        ),
        store=store,
        settings=_wiki_settings(),
    )
    active = 0
    max_active = 0

    async def fake_translate_page(
        page: DocPageRecord,
        *,
        source_language: str,
        target_language: str,
    ) -> DocPageRecord:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return store.upsert_doc_page(
            DocPageRecord(
                id=f"translated-{page.slug}",
                repo_id=page.repo_id,
                language_code=target_language,
                slug=page.slug,
                title=page.title,
                parent_slug=page.parent_slug,
                markdown=page.markdown,
                source_refs=page.source_refs,
                graph_refs=page.graph_refs,
                status=page.status,
                updated_at=None,
            )
        )

    monkeypatch.setattr(generator.translator, "_translate_page", fake_translate_page)

    translated_pages = await generator.translator.translate_page_slugs(
        repo.id,
        source_language="en",
        target_language="zh",
        slugs=list(page_markdown_by_slug),
    )

    assert len(translated_pages) == 5
    assert max_active == 3


@pytest.mark.asyncio
async def test_wiki_generator_generates_requested_non_base_language_via_translation(
    tmp_path: Path,
) -> None:
    store, repo = _analyzed_repo(tmp_path)
    llm = _FakeWikiLLM(
        page_payload={
            "title": "Request Handler",
            "markdown": (
                "# Request Handler\n\n"
                "## Purpose and Scope\n\n"
                "The handler delegates to answer(). [[S1]]"
            ),
            "source_refs": [{"citation_id": "S1", "file_path": "api.py", "start_line": 3, "end_line": 4}],
        },
        translation_payloads={
            "catalog": {
                "title": "中文 Wiki",
                "items": [{"path": "request-handler", "title": "请求处理器"}],
            },
            "page": {
                "title": "请求处理器",
                "markdown": "# 请求处理器\n\n## Purpose and Scope\n\n处理器会调用 answer().",
            },
        },
    )
    generator = WikiGenerator(
        GraphRAGRetriever(store=store),
        llm,
        store=store,
        settings=_wiki_settings(),
    )

    results = await generator.generate_all_pages(repo.id, language_code="zh")

    translated_page = _page_by_slug(results, "request-handler")
    assert translated_page.language_code == "zh"
    assert translated_page.title == "请求处理器"
    assert store.get_latest_doc_catalog(repo.id, language_code="en") is not None
    assert store.get_latest_doc_catalog(repo.id, language_code="zh") is not None
    assert store.get_doc_page(repo.id, "request-handler", language_code="en") is not None
    assert store.get_doc_page(repo.id, "request-handler", language_code="zh") == translated_page
    assert llm.translation_requests[0]["content_type"] == "catalog"
    assert [request["content_type"] for request in llm.translation_requests[1:]] == ["page"] * len(results)


@pytest.mark.asyncio
async def test_wiki_update_generates_only_missing_and_draft_pages(tmp_path: Path) -> None:
    store, repo = _analyzed_repo(tmp_path)
    store.save_doc_catalog(
        repo.id,
        title="Repo Wiki",
        structure={
            "items": [
                {"title": "Stable", "slug": "stable", "topic": "handler answer", "children": []},
                {"title": "Handler", "slug": "handler", "topic": "handler answer", "children": []},
                {"title": "Missing", "slug": "missing", "topic": "handler answer", "children": []},
            ]
        },
    )
    store.upsert_doc_page(
        DocPageRecord(
            id="stable-page",
            repo_id=repo.id,
            slug="stable",
            title="Stable",
            parent_slug=None,
            markdown="# Stable\n\n## Purpose and Scope\n\nAlready generated.",
            source_refs=[{"file_path": "api.py", "start_line": 3, "end_line": 4}],
            graph_refs=[],
            status="generated",
            updated_at=None,
        )
    )
    store.upsert_doc_page(
        DocPageRecord(
            id="draft-page",
            repo_id=repo.id,
            slug="handler",
            title="Handler",
            parent_slug=None,
            markdown="# Handler\n\nDraft.",
            source_refs=[{"file_path": "api.py", "start_line": 3, "end_line": 4}],
            graph_refs=[],
            status="draft",
            updated_at=None,
        )
    )
    llm = _FakeWikiLLM(
        page_payload={
            "title": "Handler",
            "markdown": "# Handler\n\n## Purpose and Scope\n\nThe handler delegates to answer(). [[S1]]",
            "source_refs": [{"citation_id": "S1", "file_path": "api.py", "start_line": 3, "end_line": 4}],
        }
    )
    generator = WikiGenerator(
        GraphRAGRetriever(store=store),
        llm,
        store=store,
        settings=_wiki_settings(),
    )

    update = await generator.update_pages(repo.id)

    assert update.generated_slugs == ["handler", "missing"]
    assert update.stale_slugs == ["handler"]
    assert update.missing_slugs == ["missing"]
    assert [page.slug for page in update.reused_pages] == ["stable"]
    assert set(llm.page_call_slugs) == {"handler", "missing"}
    assert store.get_doc_page(repo.id, "stable").markdown.startswith("# Stable")
    assert store.get_doc_page(repo.id, "handler").status == "generated"
    assert store.get_doc_page(repo.id, "missing").status == "generated"


@pytest.mark.asyncio
async def test_wiki_generator_repairs_translation_json_for_requested_language(
    tmp_path: Path,
) -> None:
    store, repo = _analyzed_repo(tmp_path)
    valid_page_translation = {
        "title": "请求处理器",
        "markdown": "# 请求处理器\n\n## Purpose and Scope\n\n处理器会调用 answer().",
    }
    llm = _FakeWikiLLM(
        page_payload={
            "title": "Request Handler",
            "markdown": (
                "# Request Handler\n\n"
                "## Purpose and Scope\n\n"
                "The handler delegates to answer(). [[S1]]"
            ),
            "source_refs": [{"citation_id": "S1", "file_path": "api.py", "start_line": 3, "end_line": 4}],
        },
        translation_payloads={
            "catalog": [
                "I translated the catalog, but forgot JSON.",
                {
                    "title": "中文 Wiki",
                    "items": [{"path": "request-handler", "title": "请求处理器"}],
                },
            ],
            "page": [
                "Plain Markdown is not accepted here.",
                valid_page_translation,
                valid_page_translation,
                valid_page_translation,
                valid_page_translation,
                valid_page_translation,
            ],
        },
    )
    generator = WikiGenerator(
        GraphRAGRetriever(store=store),
        llm,
        store=store,
        settings=_wiki_settings(),
    )

    results = await generator.generate_all_pages(repo.id, language_code="zh")

    translated_page = _page_by_slug(results, "request-handler")
    assert translated_page.language_code == "zh"
    assert translated_page.title == "请求处理器"
    assert store.get_latest_doc_catalog(repo.id, language_code="en") is not None
    assert store.get_doc_page(repo.id, "request-handler", language_code="en") is not None
    assert len([request for request in llm.translation_requests if request["content_type"] == "catalog"]) == 2
    assert len([request for request in llm.translation_requests if request["content_type"] == "page"]) == len(results) + 1
    errored_translation_runs = [
        run
        for run in store.list_llm_runs(repo.id, task_type="translation")
        if run.status == "error"
    ]
    assert len(errored_translation_runs) == 2


@pytest.mark.asyncio
async def test_wiki_translation_failure_saves_draft_and_continues(tmp_path: Path) -> None:
    store, repo = _analyzed_repo(tmp_path)
    _save_source_catalog_and_pages(
        store,
        repo.id,
        {
            "broken": "# Broken\n\n## Purpose and Scope\n\nThis page will fail translation.",
            "stable": "# Stable\n\n## Purpose and Scope\n\nThis page translates successfully.",
        },
    )
    llm = _FakeWikiLLM(
        page_payload={
            "title": "Unused",
            "markdown": "# Unused\n\n## Purpose and Scope\n\nUnused.",
            "source_refs": [],
        },
        translation_payloads={
            "catalog": {
                "title": "中文 Wiki",
                "items": [
                    {"path": "broken", "title": "失败页面"},
                    {"path": "stable", "title": "稳定页面"},
                ],
            },
            "page": [
                "not json",
                "still not json",
                "not json either",
                {
                    "title": "稳定页面",
                    "markdown": "# 稳定页面\n\n## Purpose and Scope\n\n翻译成功。",
                },
            ],
        },
    )
    generator = WikiGenerator(
        GraphRAGRetriever(store=store),
        llm,
        store=store,
        settings=_wiki_settings(),
    )

    result = await generator.translate_wiki(repo.id, source_language="en", target_language="zh")

    broken = next(page for page in result.pages if page.slug == "broken")
    stable = next(page for page in result.pages if page.slug == "stable")
    assert broken.status == "draft"
    assert "Translation failed after repair attempts" in broken.markdown
    assert "This page will fail translation." in broken.markdown
    assert stable.status == "generated"
    assert stable.title == "稳定页面"
    assert store.get_doc_page(repo.id, "broken", language_code="zh") == broken
    assert store.get_doc_page(repo.id, "stable", language_code="zh") == stable


@pytest.mark.asyncio
async def test_wiki_translation_splits_long_markdown_into_chunks(tmp_path: Path) -> None:
    store, repo = _analyzed_repo(tmp_path)
    long_markdown = "\n\n".join(
        [
            "# Long Page",
            "## Section 1\n\n" + "Alpha sentence. " * 500,
            "## Section 2\n\n" + "Beta sentence. " * 500,
            "## Section 3\n\n" + "Gamma sentence. " * 500,
        ]
    )
    _save_source_catalog_and_pages(store, repo.id, {"long": long_markdown})
    llm = _FakeWikiLLM(
        page_payload={
            "title": "Unused",
            "markdown": "# Unused\n\n## Purpose and Scope\n\nUnused.",
            "source_refs": [],
        },
        translation_payloads={
            "catalog": {
                "title": "中文 Wiki",
                "items": [{"path": "long", "title": "长页面"}],
            },
            "page": {
                "title": "长页面",
                "markdown": "# 已翻译块\n\n翻译后的内容。",
            },
        },
    )
    generator = WikiGenerator(
        GraphRAGRetriever(store=store),
        llm,
        store=store,
        settings=_wiki_settings(),
    )

    await generator.translate_wiki(repo.id, source_language="en", target_language="zh")

    page_requests = [
        request for request in llm.translation_requests if request["content_type"] == "page"
    ]
    assert len(page_requests) > 1
    assert all("translation_chunk" in request for request in page_requests)
    assert all(len(str(request["markdown"])) < len(long_markdown) for request in page_requests)


@pytest.mark.asyncio
async def test_regenerate_translated_page_only_translates_requested_slug(tmp_path: Path) -> None:
    store, repo = _analyzed_repo(tmp_path)
    _save_source_catalog_and_pages(
        store,
        repo.id,
        {
            "stable": "# Stable\n\n## Purpose and Scope\n\nAlready translated.",
            "target": "# Target\n\n## Purpose and Scope\n\nNeeds regeneration.",
        },
    )
    llm = _FakeWikiLLM(
        page_payload={
            "title": "Target",
            "markdown": "# Target\n\n## Purpose and Scope\n\nRegenerated target. [[S1]]",
            "source_refs": [{"citation_id": "S1", "file_path": "api.py", "start_line": 3, "end_line": 4}],
        },
        translation_payloads={
            "catalog": {
                "title": "中文 Wiki",
                "items": [
                    {"path": "stable", "title": "稳定页面"},
                    {"path": "target", "title": "目标页面"},
                ],
            },
            "page": {
                "title": "目标页面",
                "markdown": "# 目标页面\n\n## Purpose and Scope\n\n只翻译目标页面。",
            },
        },
    )
    generator = WikiGenerator(
        GraphRAGRetriever(store=store),
        llm,
        store=store,
        settings=_wiki_settings(),
    )

    result = await generator.regenerate_page(repo.id, "target", language_code="zh")

    page_requests = [
        request for request in llm.translation_requests if request["content_type"] == "page"
    ]
    assert result.page.slug == "target"
    assert result.page.language_code == "zh"
    assert len(page_requests) == 1
    assert page_requests[0]["title"] == "Target"
    assert store.get_doc_page(repo.id, "stable", language_code="zh") is None


@pytest.mark.asyncio
async def test_wiki_generator_auto_translates_configured_languages_after_base_generation(
    tmp_path: Path,
) -> None:
    store, repo = _analyzed_repo(tmp_path)
    llm = _FakeWikiLLM(
        page_payload={
            "title": "Request Handler",
            "markdown": (
                "# Request Handler\n\n"
                "## Purpose and Scope\n\n"
                "The handler delegates to answer(). [[S1]]"
            ),
            "source_refs": [{"citation_id": "S1", "file_path": "api.py", "start_line": 3, "end_line": 4}],
        },
        translation_payloads={
            "catalog": {
                "title": "中文 Wiki",
                "items": [{"path": "request-handler", "title": "请求处理器"}],
            },
            "page": {
                "title": "请求处理器",
                "markdown": "# 请求处理器\n\n## Purpose and Scope\n\n处理器会调用 answer().",
            },
        },
    )
    generator = WikiGenerator(
        GraphRAGRetriever(store=store),
        llm,
        store=store,
        settings=_wiki_settings(wiki_translation_languages="zh"),
    )

    await generator.generate_catalog(repo.id)
    await generator.generate_all_pages(repo.id)

    assert store.get_latest_doc_catalog(repo.id, language_code="zh") is not None
    translated_page = store.get_doc_page(repo.id, "request-handler", language_code="zh")
    assert translated_page is not None
    assert translated_page.title == "请求处理器"
    assert llm.translation_requests[0]["content_type"] == "catalog"
    assert all(request["content_type"] == "page" for request in llm.translation_requests[1:])


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
    assert '[S1](source-link "api.py:L1-L2")' in markdown


def test_adjacent_citation_markers_render_as_separate_links() -> None:
    source_refs = [
        {"citation_id": "S4", "file_path": "api.py", "start_line": 4, "end_line": 8},
        {"citation_id": "S16", "file_path": "service.py", "start_line": 16, "end_line": 22},
    ]

    markdown = _replace_citation_markers("The flow crosses both modules. [[S4]][[S16]]", source_refs)

    assert '[S4](source-link "api.py:L4-L8") [S16](source-link "service.py:L16-L22")' in markdown
    assert "S4S16" not in markdown


def test_code_wrapped_citation_markers_render_as_links() -> None:
    source_refs = [
        {"citation_id": "S1", "file_path": "api.py", "start_line": 1, "end_line": 2},
    ]

    markdown = _replace_citation_markers("The handler is cited as `[[S1]]`.", source_refs)

    assert '[S1](source-link "api.py:L1-L2")' in markdown
    assert "`[S1]" not in markdown
    assert "[S1]`" not in markdown


def test_redundant_source_labels_are_removed_around_citations() -> None:
    source_refs = [
        {"citation_id": "S1", "file_path": "src/utils/serial-queue.ts", "start_line": 22, "end_line": 125},
        {"citation_id": "S5", "file_path": "src/utils/serial-queue.ts", "start_line": 59, "end_line": 69},
    ]

    markdown = _replace_citation_markers(
        "### `SerialQueue`（src/utils/serial-queue.ts 第22–125行 [[S1]]）\n\n"
        "The queue calls `drain()` [[S5]]（第59–69行）.",
        source_refs,
    )

    assert '### `SerialQueue` [S1](source-link "src/utils/serial-queue.ts:L22-L125")' in markdown
    assert '`drain()` [S5](source-link "src/utils/serial-queue.ts:L59-L69").' in markdown
    assert "src/utils/serial-queue.ts 第22" not in markdown
    assert "第59" not in markdown


def test_redundant_english_source_labels_are_removed_around_citations() -> None:
    source_refs = [
        {"citation_id": "S1", "file_path": "src/utils/serial-queue.ts", "start_line": 22, "end_line": 125},
    ]

    markdown = _replace_citation_markers(
        "### `SerialQueue` (src/utils/serial-queue.ts, lines 22-125 [[S1]])\n\n"
        "It drains tasks [[S1]] (lines 100-124).",
        source_refs,
    )

    assert '### `SerialQueue` [S1](source-link "src/utils/serial-queue.ts:L22-L125")' in markdown
    assert 'It drains tasks [S1](source-link "src/utils/serial-queue.ts:L22-L125").' in markdown
    assert "lines 22" not in markdown
    assert "lines 100" not in markdown


def test_malformed_citation_markers_are_normalized_or_removed() -> None:
    source_refs = [
        {"citation_id": "S1", "file_path": "index.ts", "start_line": 131, "end_line": 132},
        {"citation_id": "S13", "file_path": "core.ts", "start_line": 10, "end_line": 12},
    ]

    markdown = _replace_citation_markers(
        "Start [[S1:131-132]]. Combined [[S1:281-295, S13]]. "
        "Graph edge [[S13#edges]]. Missing [[S??]] [[S?]] [[S#]].",
        source_refs,
    )

    assert '[S1](source-link "index.ts:L131-L132")' in markdown
    assert '[S13](source-link "core.ts:L10-L12")' in markdown
    assert "[[S" not in markdown
    assert "S??" not in markdown
    assert "S#" not in markdown


def test_diagram_placeholders_insert_server_diagrams_in_body() -> None:
    diagram = MermaidDiagram(
        slot="data-flow",
        kind="data_flow",
        title="Handler data and call flow",
        heading_hint="Control Flow",
        reason="test diagram",
        lines=["flowchart LR", "  A --> B"],
    )
    source_refs = [
        {"citation_id": "S1", "file_path": "api.py", "start_line": 3, "end_line": 4}
    ]
    markdown = (
        "# Request Handler\n\n"
        "## Purpose and Scope\n\n"
        "The handler coordinates the flow. [[S1]]\n\n"
        "## Control Flow\n\n"
        "The following path is graph-backed.\n\n"
        "[[DIAGRAM:data-flow]]\n\n"
        "Sources: [api.py:L3-L4](source-link)\n\n"
        "The flow ends after delegation."
    )

    rendered = _compose_page_markdown(markdown, [diagram], source_refs)

    assert "[[DIAGRAM:" not in rendered
    assert rendered.index("## Control Flow") < rendered.index("### Handler data and call flow")
    assert rendered.index("### Handler data and call flow") < rendered.index("The flow ends")
    assert "Diagram rationale:" not in rendered
    assert "test diagram" not in rendered
    assert "Sources:" not in rendered
    assert "## Sources" in rendered
    assert "- api.py" in rendered
    assert "  - S1 [L3-L4](source-link)" in rendered


def test_page_markdown_repairs_conjoined_mermaid_fence_headings() -> None:
    source_refs: list[dict[str, object]] = []
    markdown = "\n".join(
        [
            "# Training a Skill",
            "",
            "## Purpose and Scope",
            "",
            "```mermaid",
            "sequenceDiagram",
            "  User->>Skill: train",
            "```### Training a Skill interaction sequence",
            "",
            "The interaction continues.",
        ]
    )

    rendered = _compose_page_markdown(markdown, [], source_refs)

    assert "```### Training a Skill interaction sequence" not in rendered
    assert "```\n### Training a Skill interaction sequence" in rendered


def test_unknown_diagram_placeholders_are_validation_errors() -> None:
    errors = _validate_diagram_placeholders(
        "# Page\n\n## Purpose and Scope\n\n[[DIAGRAM:invented]]",
        {"data-flow"},
    )

    assert errors == ["markdown contains unknown diagram placeholders: invented."]


def test_catalog_normalization_preserves_deeper_drilldown_children() -> None:
    payload = {
        "title": "Detailed Wiki",
        "items": [
            {
                "title": "Backend Services",
                "slug": "backend-services",
                "kind": "category",
                "children": [
                    {
                        "title": f"Service Area {index}",
                        "slug": f"service-area-{index}",
                        "kind": "category",
                        "children": [
                            {
                                "title": f"Workflow Detail {index}",
                                "slug": f"workflow-detail-{index}",
                                "kind": "page",
                                "topic": f"workflow detail {index}",
                                "source_hints": [f"backend/app/services/area_{index}.py"],
                                "children": [],
                            }
                        ],
                    }
                    for index in range(10)
                ],
            }
        ],
    }

    _title, items = _normalize_catalog_payload(payload, "repo")

    backend = next(item for item in items if item["slug"] == "backend-services")
    assert len(backend["children"]) == 10
    assert backend["children"][0]["children"][0]["slug"] == "workflow-detail-0"


def test_catalog_limits_scale_with_repo_size() -> None:
    tiny_nodes = _graph_nodes(6)
    large_nodes = _graph_nodes(350)
    large_edges = [
        CodeGraphEdge(
            id=f"edge-{index}",
            repo_id="repo",
            source_id=large_nodes[index % len(large_nodes)].id,
            target_id=large_nodes[(index + 1) % len(large_nodes)].id,
            type="calls",
        )
        for index in range(2000)
    ]

    tiny = catalog_limits_for_repo(tiny_nodes, [], chunk_count=8, community_count=1)
    large = catalog_limits_for_repo(large_nodes, large_edges, chunk_count=1200, community_count=90)

    assert tiny.label == "tiny"
    assert large.label == "xlarge"
    assert tiny.max_total_items < large.max_total_items
    assert tiny.max_depth < large.max_depth


def test_catalog_normalization_applies_adaptive_total_budget() -> None:
    payload = {
        "title": "Budgeted Wiki",
        "items": [
            {
                "title": f"Feature {index}",
                "slug": f"feature-{index}",
                "kind": "page",
                "children": [],
            }
            for index in range(20)
        ],
    }
    limits = CatalogScaleLimits(
        label="test",
        target_top_level_sections="test",
        target_total_pages="test",
        target_depth="test",
        max_top_level_items=20,
        max_total_items=6,
        max_children_per_item=3,
        max_depth=3,
    )

    _title, items = _normalize_catalog_payload(payload, "repo", limits=limits)

    assert _catalog_item_count(items) == 6
    assert [item["slug"] for item in items[:4]] == [
        "overview",
        "architecture",
        "reading-guide",
        "dependencies",
    ]


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


def _graph_nodes(count: int) -> list[CodeGraphNode]:
    return [
        CodeGraphNode(
            id=f"node-{index}",
            repo_id="repo",
            type="file",
            name=f"module_{index}.py",
            file_path=f"module_{index}.py",
        )
        for index in range(count)
    ]


def _catalog_item_count(items: list[dict[str, object]]) -> int:
    total = 0
    for item in items:
        children = item.get("children")
        total += 1
        if isinstance(children, list):
            total += _catalog_item_count(
                [child for child in children if isinstance(child, dict)]
            )
    return total


def _save_source_catalog_and_pages(
    store: SQLiteStore,
    repo_id: str,
    pages: dict[str, str],
) -> None:
    store.save_doc_catalog(
        repo_id,
        title="Repo Wiki",
        structure={
            "items": [
                {
                    "title": slug.replace("-", " ").title(),
                    "slug": slug,
                    "path": slug,
                    "topic": slug,
                    "children": [],
                }
                for slug in pages
            ]
        },
    )
    for slug, markdown in pages.items():
        store.upsert_doc_page(
            DocPageRecord(
                id=f"{slug}-en",
                repo_id=repo_id,
                slug=slug,
                title=slug.replace("-", " ").title(),
                parent_slug=None,
                markdown=markdown,
                source_refs=[],
                graph_refs=[],
                status="generated",
                updated_at=None,
            )
        )


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


def _wiki_settings(**overrides: object) -> Settings:
    values = {
        "wiki_base_language": "en",
        "wiki_translation_languages": None,
    }
    return Settings(_env_file=None, **(values | overrides))


def _page_by_slug(results: list[object], slug: str) -> DocPageRecord:
    for result in results:
        page = getattr(result, "page", result)
        if page.slug == slug:
            return page
    raise AssertionError(f"Missing page: {slug}")


type _FakeTranslationPayload = dict[str, object] | str


class _FailingPageLLM:
    async def complete(
        self,
        task_type: str,
        messages: list[dict[str, str]],
        *,
        response_format: str | None = None,
    ) -> LLMResult:
        assert task_type == "page"
        assert messages
        assert response_format == "json_object"
        raise RuntimeError("provider returned an empty response body")


class _FakeWikiLLM:
    def __init__(
        self,
        *,
        page_payload: dict[str, object],
        catalog_payload: dict[str, object] | None = None,
        page_payloads_by_slug: dict[str, dict[str, object]] | None = None,
        translation_payloads: (
            dict[str, _FakeTranslationPayload | list[_FakeTranslationPayload]] | None
        ) = None,
    ) -> None:
        self.page_payload = page_payload
        self.catalog_payload = catalog_payload
        self.page_payloads_by_slug = page_payloads_by_slug or {}
        self.translation_payloads = {
            key: list(value) if isinstance(value, list) else value
            for key, value in (translation_payloads or {}).items()
        }
        self.page_requests: list[dict[str, object]] = []
        self.catalog_requests: list[dict[str, object]] = []
        self.page_call_slugs: list[str] = []
        self.translation_requests: list[dict[str, object]] = []

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
            assert "catalog_scale" in message_text
            assert "granularity_contract" in message_text
            assert "module_candidates" in message_text
            assert "leaf pages for implementation detail" in message_text
            self.catalog_requests.append(_request_payload_from_message(messages[-1]["content"]))
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
            assert '"diagram_slots"' in message_text
            assert '"page_depth_profile"' in message_text
            assert '"evidence_inventory"' in message_text
            assert '"readfile_evidence"' in message_text
            assert '"ReadFile"' in message_text
            assert "do not invent wiki pages or links" in message_text
            assert "at least four evidence-backed detail blocks" in message_text
            request_payload = _page_request_payload_from_messages(messages)
            self.page_requests.append(request_payload)
            slug = str(request_payload.get("slug") or "")
            self.page_call_slugs.append(slug)
            payload = self.page_payloads_by_slug.get(slug, self._page_payload_for_request(request_payload))
        elif task_type == "translation":
            request_payload = _request_payload_from_message(messages[-1]["content"])
            self.translation_requests.append(request_payload)
            content_type = str(request_payload.get("content_type") or "")
            payload = self.translation_payloads.get(content_type)
            if payload is None:
                raise AssertionError(f"Missing translation payload for: {content_type}")
            if isinstance(payload, list):
                if not payload:
                    raise AssertionError(f"Missing translation payload for: {content_type}")
                payload = payload.pop(0)
        else:
            raise AssertionError(f"Unexpected task type: {task_type}")
        content = payload if isinstance(payload, str) else json.dumps(payload)
        return LLMResult(content=content, model="fake/wiki", usage={})

    def _page_payload_for_request(self, request_payload: dict[str, object]) -> dict[str, object]:
        title = str(request_payload.get("title") or self.page_payload.get("title") or "Page")
        payload_title = str(self.page_payload.get("title") or "")
        if title == payload_title:
            return self.page_payload
        source_refs = self.page_payload.get("source_refs") or [
            {"citation_id": "S1", "file_path": "api.py", "start_line": 3, "end_line": 4}
        ]
        return {
            "title": title,
            "markdown": (
                f"# {title}\n\n"
                "## Purpose and Scope\n\n"
                f"{title} summarizes repository evidence for this page. [[S1]]"
            ),
            "source_refs": source_refs,
        }


def _request_payload_from_message(message_text: str) -> dict[str, object]:
    start = message_text.find("{")
    assert start >= 0
    payload = json.loads(message_text[start:])
    assert isinstance(payload, dict)
    return payload


def _page_request_payload_from_messages(messages: list[dict[str, str]]) -> dict[str, object]:
    for message in reversed(messages):
        content = message["content"]
        if content.startswith("Page payload:"):
            return _request_payload_from_message(content)
    raise AssertionError("Missing page payload message")
