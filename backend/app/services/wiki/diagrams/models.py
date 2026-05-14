from dataclasses import dataclass


ABSTRACT_DIAGRAM_EDGE_TYPES = {
    "routes_to",
    "calls",
    "imports",
    "uses_config",
    "inherits",
    "implements",
    "exports",
    "references",
}
SOURCE_EDGE_TYPES = ABSTRACT_DIAGRAM_EDGE_TYPES | {"contains", "defines"}
SURFACE_NODE_TYPES = {"endpoint", "class", "schema", "interface"}
EDGE_LABEL_ORDER = ("routes_to", "calls", "imports", "uses_config", "inherits", "implements", "exports", "references")
MAX_MERMAID_EDGES = 28
MAX_MERMAID_COMPONENTS = 10
MAX_MERMAID_ABSTRACT_EDGES = 14
MAX_MERMAID_SURFACES = 10
MAX_MERMAID_DIAGRAMS = 4
MAX_MERMAID_SEQUENCE_MESSAGES = 8
MAX_MERMAID_CLASS_NODES = 8
MAX_MERMAID_CLASS_FIELDS = 6


@dataclass(frozen=True)
class _MermaidGroup:
    key: str
    label: str
    kind: str
    rank: int


@dataclass
class _MermaidEdgeAggregate:
    source_key: str
    target_key: str
    counts: dict[str, int]
    confidence_total: float = 0.0
    evidence_count: int = 0
