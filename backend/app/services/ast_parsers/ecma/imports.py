from backend.app.services.ast_parsers.tree import (
    descendants_of_type,
    first_descendant_of_type,
    node_text,
    strip_quotes,
)


def import_names(root, source: bytes) -> list[str]:
    imports: set[str] = set()
    for node in descendants_of_type(root, {"import_statement", "export_statement"}):
        string_node = node.child_by_field_name("source")
        if string_node is None and node.type == "import_statement":
            string_node = first_descendant_of_type(node, {"string"})
        if string_node is None and node.type == "export_statement" and " from " in node_text(node, source):
            string_node = first_descendant_of_type(node, {"string"})
        if string_node is not None:
            imports.add(strip_quotes(node_text(string_node, source)))
    for node in descendants_of_type(root, {"call_expression"}):
        function_node = node.child_by_field_name("function")
        if function_node is None or node_text(function_node, source) not in {"require", "import"}:
            continue
        arguments = node.child_by_field_name("arguments")
        string_node = first_descendant_of_type(arguments, {"string"}) if arguments else None
        if string_node is not None:
            imports.add(strip_quotes(node_text(string_node, source)))
    return sorted(imports)
