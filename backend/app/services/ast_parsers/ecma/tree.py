def descendants_of_type(node, types: set[str]):
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type in types:
            yield current
        stack.extend(reversed(current.named_children))


def first_descendant_of_type(node, types: set[str]):
    if node is None:
        return None
    return next(descendants_of_type(node, types), None)


def first_named_child(node):
    return node.named_children[0] if node.named_children else None


def field_text(node, field: str, source: bytes) -> str:
    child = node.child_by_field_name(field)
    return node_text(child, source) if child is not None else ""


def node_text(node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] in {"'", '"', "`"} and value[-1] == value[0]:
        return value[1:-1]
    return value


def start_line(node) -> int:
    return node.start_point.row + 1


def end_line(node) -> int:
    return node.end_point.row + 1
