from backend.app.services.ast_parsers.query.models import DefinitionRecord


def nearest_container(
    node,
    containers: list[DefinitionRecord],
) -> DefinitionRecord | None:
    candidates = [
        container
        for container in containers
        if contains(container.node, node) and container.node != node
    ]
    return min(candidates, key=lambda item: span(item.node), default=None)


def innermost_owner(node, records: list[DefinitionRecord]) -> DefinitionRecord | None:
    candidates = [record for record in records if contains(record.node, node)]
    return min(candidates, key=lambda item: span(item.node), default=None)


def contains(container, node) -> bool:
    return container.start_byte <= node.start_byte and node.end_byte <= container.end_byte


def span(node) -> int:
    return node.end_byte - node.start_byte
