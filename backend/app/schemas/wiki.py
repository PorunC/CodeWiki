from pydantic import BaseModel, Field

from backend.app.schemas.ask import SourceRef


class WikiCatalogItem(BaseModel):
    title: str
    slug: str
    path: str | None = None
    order: int | None = None
    kind: str = "page"
    children: list["WikiCatalogItem"] = Field(default_factory=list)


class WikiPage(BaseModel):
    slug: str
    title: str
    markdown: str
    source_refs: list[SourceRef] = Field(default_factory=list)
    graph_refs: list[str] = Field(default_factory=list)
    status: str = "draft"


WikiCatalogItem.model_rebuild()
