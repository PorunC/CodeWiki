import re
from pathlib import Path

from tree_sitter import Language, Parser
import tree_sitter_java

from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.common import content_hash, relative_path
from backend.app.services.ast_parsers.ecma.tree import descendants_of_type, field_text, node_text


JAVA_TYPE_DECLARATIONS = {
    "annotation_type_declaration",
    "class_declaration",
    "enum_declaration",
    "interface_declaration",
    "record_declaration",
}
JAVA_METHOD_DECLARATIONS = {
    "compact_constructor_declaration",
    "constructor_declaration",
    "method_declaration",
}
JAVA_ROUTE_ANNOTATIONS = {
    "DeleteMapping": "DELETE",
    "GetMapping": "GET",
    "PatchMapping": "PATCH",
    "PostMapping": "POST",
    "PutMapping": "PUT",
}
JAVA_REQUEST_MAPPING_METHOD_RE = re.compile(r"RequestMethod\.(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)")


class TreeSitterJavaParser:
    language = "java"

    def __init__(self) -> None:
        self.parser = Parser(Language(tree_sitter_java.language()))

    def parse(self, path: Path, *, repo_root: Path | None = None) -> list[AstSymbol]:
        content = path.read_text(encoding="utf-8", errors="replace")
        source = content.encode("utf-8")
        tree = self.parser.parse(source)
        root = tree.root_node
        file_path = relative_path(path, repo_root)
        file_hash = content_hash(content)
        lines = content.splitlines()
        package_name = java_package_name(root, source)
        imports = java_import_names(root, source)

        symbols = [
            AstSymbol(
                id=f"file:{file_path}",
                type="file",
                name=path.name,
                file_path=file_path,
                language=self.language,
                start_line=1,
                end_line=max(len(lines), 1),
                imports=imports,
                hash=file_hash,
                metadata={"package": package_name, "tree_sitter": True, "root_type": root.type},
            )
        ]
        exported_names: set[str] = set()
        for declaration in root.named_children:
            if declaration.type not in JAVA_TYPE_DECLARATIONS:
                continue
            extracted = java_type_symbols(
                declaration,
                source=source,
                file_path=file_path,
                file_hash=file_hash,
                package_name=package_name,
                parent_id=None,
            )
            symbols.extend(extracted)
            for symbol in extracted:
                if symbol.parent_id is None and symbol.type != "method":
                    exported_names.add(symbol.name)

        symbols[0] = AstSymbol(**{**symbols[0].__dict__, "exports": sorted(exported_names)})
        return symbols


def java_package_name(root, source: bytes) -> str:
    for child in root.named_children:
        if child.type == "package_declaration":
            for named_child in child.named_children:
                if named_child.type in {"identifier", "scoped_identifier"}:
                    return node_text(named_child, source)
    return ""


def java_import_names(root, source: bytes) -> list[str]:
    imports: set[str] = set()
    for node in root.named_children:
        if node.type != "import_declaration":
            continue
        text = node_text(node, source).strip().removeprefix("import").strip()
        text = text.removesuffix(";").strip()
        if text.startswith("static "):
            text = text.removeprefix("static ").strip()
        if text:
            imports.add(text)
    return sorted(imports)


def java_type_symbols(
    node,
    *,
    source: bytes,
    file_path: str,
    file_hash: str,
    package_name: str,
    parent_id: str | None,
) -> list[AstSymbol]:
    name = field_text(node, "name", source)
    if not name:
        return []
    symbol_id = f"{file_path}::{name}" if parent_id is None else f"{parent_id}.{name}"
    bases, implements = java_type_heritage(node, source)
    symbol_type = java_symbol_type(node)
    annotations = java_annotations(node, source)
    symbols = [
        AstSymbol(
            id=symbol_id,
            type=symbol_type,
            name=name,
            file_path=file_path,
            language="java",
            start_line=start_line(node),
            end_line=end_line(node),
            parent_id=parent_id,
            signature=java_signature(node, source),
            bases=bases,
            implements=implements,
            decorators=annotations,
            calls=java_call_names(node, source),
            references=java_reference_names(node, source),
            hash=file_hash,
            metadata={
                "exported": parent_id is None,
                "package": package_name,
                "schema_kind": java_schema_kind(node),
                "tree_sitter_type": node.type,
            },
        )
    ]

    body = node.child_by_field_name("body")
    if body is None:
        return symbols

    route_prefix = java_route_path_prefix(node, source)
    for child in body.named_children:
        if child.type in JAVA_METHOD_DECLARATIONS:
            method_symbols = java_method_symbols(
                child,
                source=source,
                file_path=file_path,
                file_hash=file_hash,
                parent_id=symbol_id,
                class_name=name,
                route_prefix=route_prefix,
            )
            symbols.extend(method_symbols)
        elif child.type in JAVA_TYPE_DECLARATIONS:
            symbols.extend(
                java_type_symbols(
                    child,
                    source=source,
                    file_path=file_path,
                    file_hash=file_hash,
                    package_name=package_name,
                    parent_id=symbol_id,
                )
            )
    return symbols


def java_symbol_type(node) -> str:
    if node.type == "class_declaration":
        return "class"
    if node.type == "interface_declaration":
        return "interface"
    return "schema"


def java_schema_kind(node) -> str | None:
    if node.type in {"annotation_type_declaration", "enum_declaration", "record_declaration"}:
        return node.type.removesuffix("_declaration")
    return None


def java_method_symbols(
    node,
    *,
    source: bytes,
    file_path: str,
    file_hash: str,
    parent_id: str,
    class_name: str,
    route_prefix: str,
) -> list[AstSymbol]:
    name = field_text(node, "name", source) or class_name
    method_id = f"{parent_id}.{name}"
    symbol = AstSymbol(
        id=method_id,
        type="method",
        name=name,
        file_path=file_path,
        language="java",
        start_line=start_line(node),
        end_line=end_line(node),
        parent_id=parent_id,
        signature=java_signature(node, source),
        decorators=java_annotations(node, source),
        calls=java_call_names(node, source),
        references=java_reference_names(node, source),
        hash=file_hash,
        metadata={"tree_sitter_type": node.type},
    )
    return [
        symbol,
        *java_endpoint_symbols(
            node,
            source=source,
            file_path=file_path,
            file_hash=file_hash,
            parent_id=method_id,
            handler=name,
            route_prefix=route_prefix,
        ),
    ]


def java_type_heritage(node, source: bytes) -> tuple[list[str], list[str]]:
    bases: set[str] = set()
    implements: set[str] = set()
    superclass = node.child_by_field_name("superclass")
    if superclass is not None:
        bases.update(java_type_names(superclass, source))
    interfaces = node.child_by_field_name("interfaces")
    if interfaces is not None:
        implements.update(java_type_names(interfaces, source))
    for child in node.named_children:
        if child.type == "extends_interfaces":
            bases.update(java_type_names(child, source))
    return sorted(bases), sorted(implements)


def java_type_names(node, source: bytes) -> set[str]:
    names: set[str] = set()
    for descendant in descendants_of_type(
        node,
        {
            "generic_type",
            "scoped_type_identifier",
            "type_identifier",
        },
    ):
        text = node_text(descendant, source)
        if text:
            names.add(text.split("<", 1)[0].rsplit(".", 1)[-1])
    return names


def java_annotations(node, source: bytes) -> list[str]:
    annotations: set[str] = set()
    modifiers = next((child for child in node.named_children if child.type == "modifiers"), None)
    if modifiers is None:
        return []
    for annotation in descendants_of_type(modifiers, {"annotation", "marker_annotation"}):
        name = field_text(annotation, "name", source)
        if name:
            annotations.add(name.rsplit(".", 1)[-1])
    return sorted(annotations)


def java_endpoint_symbols(
    node,
    *,
    source: bytes,
    file_path: str,
    file_hash: str,
    parent_id: str,
    handler: str,
    route_prefix: str,
) -> list[AstSymbol]:
    symbols: list[AstSymbol] = []
    for annotation in java_annotation_nodes(node):
        mapping = java_route_mapping(annotation, source)
        if mapping is None:
            continue
        method, route_path = mapping
        route_path = join_route_paths(route_prefix, route_path)
        route_line = start_line(annotation)
        symbols.append(
            AstSymbol(
                id=f"{file_path}::endpoint:{method}:{route_path}:{route_line}",
                type="endpoint",
                name=f"{method} {route_path}",
                file_path=file_path,
                language="java",
                start_line=route_line,
                end_line=end_line(node),
                parent_id=parent_id,
                calls=[handler],
                hash=file_hash,
                metadata={
                    "handler": handler,
                    "route_method": method,
                    "route_path": route_path,
                    "tree_sitter_type": annotation.type,
                },
            )
        )
    return symbols


def java_route_path_prefix(node, source: bytes) -> str:
    for annotation in java_annotation_nodes(node):
        name = field_text(annotation, "name", source).rsplit(".", 1)[-1]
        if name != "RequestMapping":
            continue
        return java_annotation_path(annotation, source) or ""
    return ""


def java_route_mapping(node, source: bytes) -> tuple[str, str] | None:
    name = field_text(node, "name", source).rsplit(".", 1)[-1]
    if name in JAVA_ROUTE_ANNOTATIONS:
        return JAVA_ROUTE_ANNOTATIONS[name], java_annotation_path(node, source) or "/"
    if name != "RequestMapping":
        return None
    annotation_text = node_text(node, source)
    method_match = JAVA_REQUEST_MAPPING_METHOD_RE.search(annotation_text)
    method = method_match.group(1) if method_match else "GET"
    return method, java_annotation_path(node, source) or "/"


def java_annotation_path(node, source: bytes) -> str | None:
    for string_node in descendants_of_type(node, {"string_literal"}):
        path = java_string_literal(string_node, source)
        if path.startswith("/"):
            return path
    return None


def java_annotation_nodes(node):
    modifiers = next((child for child in node.named_children if child.type == "modifiers"), None)
    if modifiers is None:
        return []
    return list(descendants_of_type(modifiers, {"annotation", "marker_annotation"}))


def java_string_literal(node, source: bytes) -> str:
    text = node_text(node, source).strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return text[1:-1]
    return text


def join_route_paths(prefix: str, path: str) -> str:
    if not prefix:
        return path if path.startswith("/") else f"/{path}"
    if not path or path == "/":
        return prefix if prefix.startswith("/") else f"/{prefix}"
    left = prefix.rstrip("/")
    right = path if path.startswith("/") else f"/{path}"
    return f"{left}{right}" if left.startswith("/") else f"/{left}{right}"


def java_call_names(node, source: bytes) -> list[str]:
    calls: set[str] = set()
    for call in descendants_of_type(node, {"method_invocation"}):
        name = field_text(call, "name", source)
        if name:
            calls.add(name.rsplit(".", 1)[-1])
    for creation in descendants_of_type(node, {"object_creation_expression"}):
        type_node = creation.child_by_field_name("type")
        if type_node is not None:
            calls.add(node_text(type_node, source).split("<", 1)[0].rsplit(".", 1)[-1])
    return sorted(calls)


def java_reference_names(node, source: bytes) -> list[str]:
    references: set[str] = set()
    for descendant in descendants_of_type(
        node,
        {
            "identifier",
            "scoped_identifier",
            "scoped_type_identifier",
            "type_identifier",
        },
    ):
        text = node_text(descendant, source).strip()
        if text and text not in {"public", "private", "protected", "static", "final"}:
            references.add(text.split("<", 1)[0].rsplit(".", 1)[-1])
    return sorted(references)


def java_signature(node, source: bytes) -> str:
    text = node_text(node, source).strip()
    if "{" in text:
        return text.split("{", 1)[0].strip()
    return text.removesuffix(";").strip()


def start_line(node) -> int:
    return node.start_point.row + 1


def end_line(node) -> int:
    return node.end_point.row + 1
