from typing import Any

PROVENANCE_VERSION = "codewiki.provenance.v1"


def confidence_level(confidence: float, *, is_inferred: bool = False) -> str:
    if confidence >= 0.99 and not is_inferred:
        return "extracted"
    if confidence >= 0.8:
        return "resolved"
    if confidence >= 0.5:
        return "inferred"
    return "ambiguous"


def with_node_provenance(
    metadata: dict[str, Any] | None,
    *,
    source: str,
    kind: str,
    confidence: float = 1.0,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    normalized = dict(metadata or {})
    normalized.setdefault("confidence", confidence)
    normalized.setdefault(
        "provenance",
        provenance_payload(
            source=source,
            kind=kind,
            confidence=float(normalized["confidence"]),
            evidence=evidence,
        ),
    )
    return normalized


def with_edge_provenance(
    metadata: dict[str, Any] | None,
    *,
    edge_type: str,
    confidence: float,
    is_inferred: bool,
) -> dict[str, Any]:
    normalized = dict(metadata or {})
    level = confidence_level(confidence, is_inferred=is_inferred)
    normalized.setdefault("confidence_level", level)
    normalized.setdefault(
        "provenance",
        provenance_payload(
            source="graph_builder",
            kind=level,
            confidence=confidence,
            evidence=_edge_evidence(edge_type, normalized),
            strategy=edge_type,
        ),
    )
    return normalized


def provenance_payload(
    *,
    source: str,
    kind: str,
    confidence: float,
    evidence: list[str] | None = None,
    strategy: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": PROVENANCE_VERSION,
        "source": source,
        "kind": kind,
        "confidence": round(confidence, 4),
    }
    if evidence:
        payload["evidence"] = evidence
    if strategy:
        payload["strategy"] = strategy
    return payload


def node_confidence(metadata: dict[str, Any]) -> float:
    value = metadata.get("confidence", 1.0)
    if isinstance(value, (int, float)):
        return float(value)
    return 1.0


def node_provenance(metadata: dict[str, Any]) -> dict[str, Any]:
    value = metadata.get("provenance")
    if isinstance(value, dict):
        return value
    return provenance_payload(source="unknown", kind="unknown", confidence=node_confidence(metadata))


def edge_provenance(metadata: dict[str, Any]) -> dict[str, Any]:
    value = metadata.get("provenance")
    if isinstance(value, dict):
        return value
    return provenance_payload(source="unknown", kind="unknown", confidence=1.0)


def _edge_evidence(edge_type: str, metadata: dict[str, Any]) -> list[str]:
    evidence: list[str] = []
    for key in (
        "import",
        "base",
        "call",
        "handler",
        "route_method",
        "route_path",
        "resolved",
    ):
        value = metadata.get(key)
        if value is not None:
            evidence.append(f"{key}={value}")
    if not evidence:
        evidence.append(f"edge_type={edge_type}")
    return evidence
