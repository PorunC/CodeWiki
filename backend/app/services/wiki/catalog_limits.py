from dataclasses import dataclass

from backend.app.services.graph import CodeGraphEdge, CodeGraphNode


@dataclass(frozen=True)
class CatalogScaleLimits:
    label: str
    target_top_level_sections: str
    target_total_pages: str
    target_depth: str
    max_top_level_items: int
    max_total_items: int
    max_children_per_item: int
    max_depth: int
    file_count: int = 0
    node_count: int = 0
    edge_count: int = 0
    chunk_count: int = 0
    community_count: int = 0

    def with_metrics(
        self,
        *,
        file_count: int,
        node_count: int,
        edge_count: int,
        chunk_count: int,
        community_count: int,
    ) -> "CatalogScaleLimits":
        return CatalogScaleLimits(
            label=self.label,
            target_top_level_sections=self.target_top_level_sections,
            target_total_pages=self.target_total_pages,
            target_depth=self.target_depth,
            max_top_level_items=self.max_top_level_items,
            max_total_items=self.max_total_items,
            max_children_per_item=self.max_children_per_item,
            max_depth=self.max_depth,
            file_count=file_count,
            node_count=node_count,
            edge_count=edge_count,
            chunk_count=chunk_count,
            community_count=community_count,
        )

    def as_prompt_payload(self) -> dict[str, object]:
        return {
            "scale": self.label,
            "metrics": {
                "file_count": self.file_count,
                "node_count": self.node_count,
                "edge_count": self.edge_count,
                "chunk_count": self.chunk_count,
                "community_count": self.community_count,
            },
            "target_top_level_sections": self.target_top_level_sections,
            "target_total_pages": self.target_total_pages,
            "target_depth": self.target_depth,
            "hard_limits": {
                "max_top_level_items": self.max_top_level_items,
                "max_total_items": self.max_total_items,
                "max_children_per_item": self.max_children_per_item,
                "max_depth": self.max_depth,
            },
        }


TINY_CATALOG_LIMITS = CatalogScaleLimits(
    label="tiny",
    target_top_level_sections="4-6 high-signal sections including required special pages",
    target_total_pages="4-8 focused pages; keep tiny repositories compact",
    target_depth="1-2 levels; avoid drill-down pages unless evidence is strong",
    max_top_level_items=8,
    max_total_items=10,
    max_children_per_item=6,
    max_depth=2,
)
SMALL_CATALOG_LIMITS = CatalogScaleLimits(
    label="small",
    target_top_level_sections="5-8 high-signal sections including required special pages",
    target_total_pages="8-16 focused pages; split only clear subsystems",
    target_depth="2 levels for most areas; use 3 only for clear subsystem boundaries",
    max_top_level_items=10,
    max_total_items=22,
    max_children_per_item=8,
    max_depth=3,
)
MEDIUM_CATALOG_LIMITS = CatalogScaleLimits(
    label="medium",
    target_top_level_sections="6-10 high-signal sections including required special pages",
    target_total_pages=(
        "16-32 focused pages; use fewer only when the evidence is genuinely small, "
        "and more when distinct subsystems are visible"
    ),
    target_depth="2-3 levels for complex areas; never deeper than 4 levels",
    max_top_level_items=12,
    max_total_items=40,
    max_children_per_item=12,
    max_depth=4,
)
LARGE_CATALOG_LIMITS = CatalogScaleLimits(
    label="large",
    target_top_level_sections="8-12 high-signal sections including required special pages",
    target_total_pages="28-56 focused pages; split major workflows and public surfaces",
    target_depth="2-3 levels; use 4 only for large, strongly evidenced subsystems",
    max_top_level_items=14,
    max_total_items=72,
    max_children_per_item=14,
    max_depth=4,
)
XLARGE_CATALOG_LIMITS = CatalogScaleLimits(
    label="xlarge",
    target_top_level_sections="10-14 high-signal sections including required special pages",
    target_total_pages="44-88 focused pages; prefer subsystem drill-downs over broad pages",
    target_depth="3 levels for complex areas; use 4 only where the graph shows clear boundaries",
    max_top_level_items=16,
    max_total_items=110,
    max_children_per_item=16,
    max_depth=4,
)

DEFAULT_CATALOG_LIMITS = MEDIUM_CATALOG_LIMITS


def catalog_limits_for_repo(
    nodes: list[CodeGraphNode],
    edges: list[CodeGraphEdge],
    *,
    chunk_count: int = 0,
    community_count: int = 0,
) -> CatalogScaleLimits:
    file_count = _file_count(nodes)
    node_count = len(nodes)
    edge_count = len(edges)
    scale_index = max(
        _bucket(file_count, (12, 40, 120, 300)),
        _bucket(node_count, (80, 250, 800, 2000)),
        _bucket(edge_count, (120, 500, 1800, 5000)),
        _bucket(chunk_count, (30, 120, 350, 900)),
        _bucket(community_count, (4, 12, 30, 80)),
    )
    profile = (
        TINY_CATALOG_LIMITS,
        SMALL_CATALOG_LIMITS,
        MEDIUM_CATALOG_LIMITS,
        LARGE_CATALOG_LIMITS,
        XLARGE_CATALOG_LIMITS,
    )[scale_index]
    return profile.with_metrics(
        file_count=file_count,
        node_count=node_count,
        edge_count=edge_count,
        chunk_count=chunk_count,
        community_count=community_count,
    )


def _file_count(nodes: list[CodeGraphNode]) -> int:
    file_paths = {
        node.file_path
        for node in nodes
        if node.file_path and node.type not in {"directory", "module", "repository"}
    }
    if file_paths:
        return len(file_paths)
    return sum(1 for node in nodes if node.type == "file")


def _bucket(value: int, thresholds: tuple[int, int, int, int]) -> int:
    for index, threshold in enumerate(thresholds):
        if value <= threshold:
            return index
    return len(thresholds)
