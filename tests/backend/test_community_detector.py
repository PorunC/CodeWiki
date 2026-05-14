import networkx as nx

from backend.app.services.community_detector import _partition


def test_partition_prefers_graspologic_leiden_when_available() -> None:
    graph = nx.Graph()
    graph.add_edge("api.py", "service.py", weight=1.0)
    graph.add_edge("service.py", "models.py", weight=0.8)
    graph.add_edge("ui.tsx", "hooks.ts", weight=1.0)
    graph.add_edge("api.py", "ui.tsx", weight=0.05)

    communities, algorithm = _partition(graph)

    assert algorithm == "graspologic_leiden"
    assert set().union(*communities) == set(graph.nodes)
