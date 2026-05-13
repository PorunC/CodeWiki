from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.ecma.tree import (
    end_line,
    field_text,
    first_descendant_of_type,
    node_text,
    start_line,
)


def schema_symbol(
    node,
    *,
    source: bytes,
    file_path: str,
    file_hash: str,
    language: str,
    exported: bool,
) -> AstSymbol:
    name = field_text(node, "name", source) or "anonymous_schema"
    return AstSymbol(
        id=f"{file_path}::{name}",
        type="schema",
        name=name,
        file_path=file_path,
        language=language,
        start_line=start_line(node),
        end_line=end_line(node),
        signature=node_text(node, source).split("{", 1)[0].strip(),
        hash=file_hash,
        metadata={
            "exported": exported,
            "schema_kind": node.type.removesuffix("_declaration"),
            "fields": schema_fields(node, source),
            "tree_sitter_type": node.type,
        },
    )


def schema_fields(node, source: bytes) -> list[str]:
    body = node.child_by_field_name("body")
    if body is None:
        return []
    fields: list[str] = []
    for child in body.named_children:
        if child.type not in {"property_signature", "public_field_definition"}:
            continue
        name = field_text(child, "name", source)
        if name:
            fields.append(name)
        else:
            identifier = first_descendant_of_type(child, {"property_identifier", "identifier"})
            if identifier is not None:
                fields.append(node_text(identifier, source))
    return fields
