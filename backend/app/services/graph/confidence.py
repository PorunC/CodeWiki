from dataclasses import dataclass
from typing import Literal

ResolutionTier = Literal["same_file", "import_scoped", "global"]

CONFIDENCE_TIERS: dict[ResolutionTier, float] = {
    "same_file": 0.95,
    "import_scoped": 0.90,
    "global": 0.50,
}

TIER_REASONS: dict[ResolutionTier, str] = {
    "same_file": "local-call",
    "import_scoped": "import-resolved",
    "global": "global",
}

STRUCTURAL_EDGE_REASONS: dict[str, str] = {
    "contains": "structural",
    "defines": "definition",
    "exports": "exported",
    "uses_config": "config-reference",
}


@dataclass(frozen=True)
class EdgeResolution:
    target_id: str
    tier: ResolutionTier
    confidence: float
    reason: str
    is_inferred: bool = False


def edge_resolution(
    target_id: str,
    tier: ResolutionTier,
    *,
    same_file_reason: str | None = None,
    is_inferred: bool = False,
) -> EdgeResolution:
    reason = same_file_reason if tier == "same_file" and same_file_reason else TIER_REASONS[tier]
    return EdgeResolution(
        target_id=target_id,
        tier=tier,
        confidence=CONFIDENCE_TIERS[tier],
        reason=reason,
        is_inferred=is_inferred,
    )
