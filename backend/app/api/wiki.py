from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.config import get_settings
from backend.app.database import DocCatalogRecord, DocPageRecord, get_store
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.wiki import PageGenerationResult, WikiGenerator

router = APIRouter()


class TranslateWikiRequest(BaseModel):
    target_language: str
    source_language: str = "en"


@router.post("/{repo_id}/wiki/catalog")
async def generate_catalog(repo_id: str, language: str = "en") -> dict[str, object]:
    try:
        catalog = await _generator().generate_catalog(repo_id, language_code=language)
    except ValueError as exc:
        raise _http_error(exc) from exc
    return _catalog_payload(catalog)


@router.post("/{repo_id}/wiki/pages/generate")
async def generate_pages(repo_id: str, language: str = "en") -> dict[str, object]:
    try:
        results = await _generator().generate_all_pages(repo_id, language_code=language)
    except ValueError as exc:
        raise _http_error(exc) from exc
    return {
        "repo_id": repo_id,
        "status": "generated" if all(not result.validation_errors for result in results) else "partial",
        "page_count": len(results),
        "pages": [_page_result_payload(result) for result in results],
    }


@router.post("/{repo_id}/wiki/pages/{slug}/regenerate")
async def regenerate_page(repo_id: str, slug: str, language: str = "en") -> dict[str, object]:
    try:
        result = await _generator().regenerate_page(repo_id, slug, language_code=language)
    except ValueError as exc:
        raise _http_error(exc) from exc
    return _page_result_payload(result)


@router.post("/{repo_id}/wiki/translate")
async def translate_wiki(repo_id: str, payload: TranslateWikiRequest) -> dict[str, object]:
    try:
        result = await _generator().translate_wiki(
            repo_id,
            source_language=payload.source_language,
            target_language=payload.target_language,
        )
    except ValueError as exc:
        raise _http_error(exc) from exc
    return {
        "repo_id": repo_id,
        "source_language": result.source_language,
        "target_language": result.target_language,
        "catalog": _catalog_payload(result.catalog),
        "page_count": len(result.pages),
        "pages": [_page_payload(page) for page in result.pages],
    }


@router.get("/{repo_id}/wiki")
async def get_wiki(repo_id: str, language: str = "en") -> dict[str, object]:
    store = get_store()
    if store.get_repo(repo_id) is None:
        raise HTTPException(status_code=404, detail=f"Repository not found: {repo_id}")
    catalog = store.get_latest_doc_catalog(repo_id, language_code=language)
    pages = store.list_doc_pages(repo_id, language_code=language)
    return {
        "repo_id": repo_id,
        "catalog": _catalog_payload(catalog) if catalog else None,
        "items": catalog.structure.get("items", []) if catalog else [],
        "pages": [_page_payload(page) for page in pages],
    }


@router.get("/{repo_id}/wiki/pages/{slug}")
async def get_page(repo_id: str, slug: str, language: str = "en") -> dict[str, object]:
    page = get_store().get_doc_page(repo_id, slug, language_code=language)
    if page is None:
        raise HTTPException(status_code=404, detail=f"Wiki page not found: {slug}")
    return _page_payload(page)


def _generator() -> WikiGenerator:
    settings = get_settings()
    store = get_store()
    return WikiGenerator(
        GraphRAGRetriever(store=store, settings=settings),
        LLMGateway(settings),
        store=store,
        settings=settings,
    )


def _catalog_payload(catalog: DocCatalogRecord) -> dict[str, object]:
    return {
        "id": catalog.id,
        "repo_id": catalog.repo_id,
        "language_code": catalog.language_code,
        "title": catalog.title,
        "structure": catalog.structure,
        "generated_at": catalog.generated_at,
    }


def _page_payload(page: DocPageRecord) -> dict[str, object]:
    return {
        "id": page.id,
        "repo_id": page.repo_id,
        "language_code": page.language_code,
        "slug": page.slug,
        "title": page.title,
        "parent_slug": page.parent_slug,
        "markdown": page.markdown,
        "source_refs": page.source_refs,
        "graph_refs": page.graph_refs,
        "status": page.status,
        "updated_at": page.updated_at,
    }


def _page_result_payload(result: PageGenerationResult) -> dict[str, object]:
    payload = _page_payload(result.page)
    payload["validation_errors"] = result.validation_errors
    return payload


def _http_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    status_code = 404 if message.startswith("Repository not found") else 400
    return HTTPException(status_code=status_code, detail=message)
