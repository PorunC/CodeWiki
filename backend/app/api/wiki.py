from fastapi import APIRouter

router = APIRouter()


@router.post("/{repo_id}/wiki/catalog")
async def generate_catalog(repo_id: str) -> dict[str, str]:
    return {"repo_id": repo_id, "status": "queued"}


@router.post("/{repo_id}/wiki/pages/generate")
async def generate_pages(repo_id: str) -> dict[str, str]:
    return {"repo_id": repo_id, "status": "queued"}


@router.get("/{repo_id}/wiki")
async def get_wiki(repo_id: str) -> dict[str, object]:
    return {"repo_id": repo_id, "items": []}


@router.get("/{repo_id}/wiki/pages/{slug}")
async def get_page(repo_id: str, slug: str) -> dict[str, str]:
    return {"repo_id": repo_id, "slug": slug, "markdown": ""}

