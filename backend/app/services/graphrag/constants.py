SOURCE_NODE_TYPES = {"file", "class", "function", "method", "schema", "endpoint"}
SEED_NODE_TYPES = SOURCE_NODE_TYPES | {"module"}
EDGE_WEIGHTS = {
    "calls": 1.0,
    "routes_to": 1.0,
    "inherits": 0.9,
    "imports": 0.82,
    "exports": 0.78,
    "defines": 0.72,
    "contains": 0.58,
}
MAX_SEED_NODES = 12
MAX_EXPANDED_NODES = 60
MAX_RELATED_EDGES = 140
DEFAULT_MAX_SOURCE_CHUNKS = 20
DEFAULT_CONTEXT_TOKENS = 8000
