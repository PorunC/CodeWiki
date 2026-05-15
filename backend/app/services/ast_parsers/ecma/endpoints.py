from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.common import HTTP_METHODS
from backend.app.services.ast_parsers.tree import (
    descendants_of_type,
    end_line,
    node_text,
    start_line,
    strip_quotes,
)


def endpoint_symbols(
    root,
    source: bytes,
    *,
    file_path: str,
    file_hash: str,
    language: str,
) -> list[AstSymbol]:
    endpoints: list[AstSymbol] = []
    for call in descendants_of_type(root, {"call_expression"}):
        route = route_call(call, source)
        if route is None:
            continue
        endpoint_id = f"{file_path}::endpoint:{route['method']}:{route['path']}:{start_line(call)}"
        endpoints.append(
            AstSymbol(
                id=endpoint_id,
                type="endpoint",
                name=f"{route['method']} {route['path']}",
                file_path=file_path,
                language=language,
                start_line=start_line(call),
                end_line=end_line(call),
                calls=[route["handler"]] if route.get("handler") else [],
                hash=file_hash,
                metadata={
                    "route_method": route["method"],
                    "route_path": route["path"],
                    "handler": route.get("handler"),
                    "framework_hint": route["object"],
                    "tree_sitter_type": call.type,
                },
            )
        )
    return endpoints


def route_call(node, source: bytes) -> dict[str, str] | None:
    function_node = node.child_by_field_name("function")
    if function_node is None or function_node.type != "member_expression":
        return None
    object_node = function_node.child_by_field_name("object")
    property_node = function_node.child_by_field_name("property")
    if object_node is None or property_node is None:
        return None
    route_object = node_text(object_node, source)
    method = node_text(property_node, source).lower()
    if route_object not in {"app", "router", "api"} or method not in HTTP_METHODS:
        return None
    arguments = node.child_by_field_name("arguments")
    if arguments is None:
        return None
    args = [child for child in arguments.named_children]
    if not args or args[0].type != "string":
        return None
    handler = route_handler_name(args[1], source) if len(args) > 1 else ""
    return {
        "object": route_object,
        "method": method.upper(),
        "path": strip_quotes(node_text(args[0], source)),
        "handler": handler,
    }


def route_handler_name(node, source: bytes) -> str:
    if node.type == "identifier":
        return node_text(node, source)
    if node.type == "member_expression":
        property_node = node.child_by_field_name("property")
        if property_node is not None:
            return node_text(property_node, source)
    return ""
