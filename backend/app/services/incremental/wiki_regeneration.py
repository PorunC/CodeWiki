from backend.app.config import get_settings
from backend.app.database import SQLiteStore
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.wiki import WikiGenerator


async def regenerate_stale_wiki_pages(
    store: SQLiteStore,
    repo_id: str,
    stale_pages: list[str],
) -> dict[str, object]:
    if not stale_pages:
        return {"requested": True, "pages": [], "errors": []}

    settings = get_settings()
    generator = WikiGenerator(
        GraphRAGRetriever(store=store, settings=settings),
        LLMGateway(settings),
        store=store,
        settings=settings,
    )
    pages: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    for slug in stale_pages:
        try:
            result = await generator.regenerate_page(repo_id, slug)
        except Exception as exc:
            errors.append({"slug": slug, "error": str(exc)})
            continue
        pages.append(
            {
                "slug": result.page.slug,
                "status": result.page.status,
                "validation_errors": result.validation_errors,
            }
        )
    return {"requested": True, "pages": pages, "errors": errors}


def skipped_wiki_regeneration(stale_pages: list[str]) -> dict[str, object]:
    return {
        "requested": False,
        "pages": [],
        "errors": [],
        "skipped_pages": stale_pages,
    }
