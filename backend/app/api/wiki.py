from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.api.dependencies import IncrementalUpdaterDep, StoreDep, WikiGeneratorDep
from backend.app.database import DocCatalogRecord, DocPageRecord
from backend.app.services.async_tasks import repo_write_lock, run_blocking
from backend.app.services.incremental.models import IncrementalUpdateResult
from backend.app.services.llm_run_recorder import LLMCallError
from backend.app.services.wiki import PageGenerationResult, WikiUpdateResult

router = APIRouter()


class TranslateWikiRequest(BaseModel):
    target_language: str
    source_language: str = "en"


class UpdateWikiPagesRequest(BaseModel):
    refresh_chunks: bool = True


@router.post("/{repo_id}/wiki/catalog")
async def generate_catalog(
    repo_id: str,
    generator: WikiGeneratorDep,
    language: str = "en",
) -> dict[str, object]:
    try:
        async with repo_write_lock(repo_id):
            catalog = await generator.generate_catalog(repo_id, language_code=language)
    except LLMCallError as exc:
        raise _llm_http_error(exc) from exc
    except ValueError as exc:
        raise _http_error(exc) from exc
    return _catalog_payload(catalog)


@router.post("/{repo_id}/wiki/pages/generate")
async def generate_pages(
    repo_id: str,
    generator: WikiGeneratorDep,
    language: str = "en",
) -> dict[str, object]:
    try:
        async with repo_write_lock(repo_id):
            results = await generator.generate_all_pages(repo_id, language_code=language)
    except LLMCallError as exc:
        raise _llm_http_error(exc) from exc
    except ValueError as exc:
        raise _http_error(exc) from exc
    return {
        "repo_id": repo_id,
        "status": "generated" if all(not result.validation_errors for result in results) else "partial",
        "page_count": len(results),
        "pages": [_page_result_payload(result) for result in results],
    }


@router.post("/{repo_id}/wiki/pages/update")
async def update_pages(
    repo_id: str,
    store: StoreDep,
    updater: IncrementalUpdaterDep,
    generator: WikiGeneratorDep,
    language: str = "en",
    payload: UpdateWikiPagesRequest | None = None,
) -> dict[str, object]:
    request = payload or UpdateWikiPagesRequest()
    try:
        async with repo_write_lock(repo_id):
            if store.get_repo(repo_id) is None:
                raise HTTPException(status_code=404, detail=f"Repository not found: {repo_id}")
            incremental_update = await run_blocking(
                updater.update,
                repo_id,
                refresh_chunks=request.refresh_chunks,
            )
            wiki_update = await generator.update_pages(repo_id, language_code=language)
    except LLMCallError as exc:
        raise _llm_http_error(exc) from exc
    except ValueError as exc:
        raise _http_error(exc) from exc
    return _wiki_update_payload(repo_id, wiki_update, incremental_update)


@router.post("/{repo_id}/wiki/pages/{slug}/regenerate")
async def regenerate_page(
    repo_id: str,
    slug: str,
    generator: WikiGeneratorDep,
    language: str = "en",
) -> dict[str, object]:
    try:
        async with repo_write_lock(repo_id):
            result = await generator.regenerate_page(repo_id, slug, language_code=language)
    except LLMCallError as exc:
        raise _llm_http_error(exc) from exc
    except ValueError as exc:
        raise _http_error(exc) from exc
    return _page_result_payload(result)


@router.post("/{repo_id}/wiki/translate")
async def translate_wiki(
    repo_id: str,
    payload: TranslateWikiRequest,
    generator: WikiGeneratorDep,
) -> dict[str, object]:
    try:
        async with repo_write_lock(repo_id):
            result = await generator.translate_wiki(
                repo_id,
                source_language=payload.source_language,
                target_language=payload.target_language,
            )
    except LLMCallError as exc:
        raise _llm_http_error(exc) from exc
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
async def get_wiki(repo_id: str, store: StoreDep, language: str = "en") -> dict[str, object]:
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
async def get_page(repo_id: str, slug: str, store: StoreDep, language: str = "en") -> dict[str, object]:
    page = store.get_doc_page(repo_id, slug, language_code=language)
    if page is None:
        raise HTTPException(status_code=404, detail=f"Wiki page not found: {slug}")
    return _page_payload(page)


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


def _wiki_update_payload(
    repo_id: str,
    update: WikiUpdateResult,
    incremental_update: IncrementalUpdateResult,
) -> dict[str, object]:
    generated_count = len(update.results)
    return {
        "repo_id": repo_id,
        "language_code": update.language_code,
        "status": "updated" if generated_count or update.deleted_page_count else "up_to_date",
        "page_count": generated_count + len(update.reused_pages),
        "generated_count": generated_count,
        "reused_count": len(update.reused_pages),
        "stale_pages": update.stale_slugs,
        "missing_pages": update.missing_slugs,
        "metadata_changed_pages": update.metadata_changed_slugs,
        "generated_pages": update.generated_slugs,
        "deleted_page_count": update.deleted_page_count,
        "pages": [_page_result_payload(result) for result in update.results],
        "incremental_update": {
            "run_id": incremental_update.run_id,
            "status": incremental_update.status,
            "affected_files": incremental_update.plan.affected_files,
            "changed_files": incremental_update.plan.changed_files,
            "new_files": incremental_update.plan.new_files,
            "deleted_files": incremental_update.plan.deleted_files,
            "stale_pages": incremental_update.stale_pages,
            "chunk_count": incremental_update.chunk_count,
            "errors": incremental_update.errors,
        },
    }


def _http_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    status_code = 404 if message.startswith("Repository not found") else 400
    return HTTPException(status_code=status_code, detail=message)


def _llm_http_error(exc: LLMCallError) -> HTTPException:
    detail = {
        "message": str(exc),
        "task_type": exc.task_type,
        "run_id": exc.run_id,
    }
    return HTTPException(status_code=502, detail=detail)
