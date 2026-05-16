from dataclasses import dataclass, field


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
MAX_MERMAID_EDGES = 36
MAX_MERMAID_COMPONENTS = 12
MAX_MERMAID_ABSTRACT_EDGES = 18
MAX_MERMAID_SURFACES = 12
MAX_MERMAID_DIAGRAMS = 5
MAX_MERMAID_SEQUENCE_MESSAGES = 10
MAX_MERMAID_CLASS_NODES = 10
MAX_MERMAID_CLASS_FIELDS = 8
MAX_MERMAID_SYMBOL_FLOW_EDGES = 14
MAX_MERMAID_SYMBOL_FLOW_NODES = 14


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
    edge_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MermaidDiagram:
    slot: str
    kind: str
    title: str
    heading_hint: str
    reason: str
    lines: list[str]
    source_edge_ids: tuple[str, ...] = ()
