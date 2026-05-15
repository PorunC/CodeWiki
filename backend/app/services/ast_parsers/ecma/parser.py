from dataclasses import replace

import tree_sitter_javascript
import tree_sitter_typescript

from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.ecma.declarations import declaration_symbols
from backend.app.services.ast_parsers.ecma.endpoints import endpoint_symbols
from backend.app.services.ast_parsers.ecma.imports import import_names
from backend.app.services.ast_parsers.query import (
    QueryLanguageSpec,
    QueryParseContext,
    TreeSitterQueryParser,
    merge_enhanced_symbols,
)


ECMA_SHARED_QUERY = """
(import_statement
  source: (string) @import.source)

(export_statement
  source: (string) @import.source)

(function_declaration
  name: (identifier) @definition.name) @definition.function

(variable_declarator
  name: (identifier) @definition.name
  value: (arrow_function)) @definition.function

(variable_declarator
  name: (identifier) @definition.name
  value: (function_expression)) @definition.function

(method_definition
  name: (property_identifier) @definition.name) @definition.method

(call_expression
  function: (identifier) @call.name)

(call_expression
  function: (member_expression
    property: (property_identifier) @call.name))
"""


JAVASCRIPT_QUERY = (
    ECMA_SHARED_QUERY
    + """
(class_declaration
  name: (identifier) @definition.name
  (class_heritage
    (identifier) @heritage.base)?) @definition.class
"""
)


TYPESCRIPT_QUERY = (
    ECMA_SHARED_QUERY
    + """
(class_declaration
  name: (type_identifier) @definition.name
  (class_heritage
    (extends_clause
      (identifier) @heritage.base)?
    (implements_clause
      (type_identifier) @heritage.implements)*)) @definition.class

(class_declaration
  name: (type_identifier) @definition.name) @definition.class

(interface_declaration
  name: (type_identifier) @definition.name) @definition.schema

(type_alias_declaration
  name: (type_identifier) @definition.name) @definition.schema

(enum_declaration
  name: (identifier) @definition.name) @definition.schema

(type_identifier) @reference.name
"""
)


class TreeSitterTypeScriptParser(TreeSitterQueryParser):
    def __init__(self, language: str) -> None:
        grammar = (
            tree_sitter_typescript.language_tsx
            if language == "tsx"
            else tree_sitter_typescript.language_typescript
        )
        super().__init__(
            QueryLanguageSpec(
                language=language,
                grammar=grammar,
                query=TYPESCRIPT_QUERY,
            )
        )

    def augment_symbols(
        self,
        symbols: list[AstSymbol],
        context: QueryParseContext,
    ) -> list[AstSymbol]:
        return _augment_ecma_symbols(symbols, context)


class TreeSitterJavaScriptParser(TreeSitterQueryParser):
    def __init__(self, language: str) -> None:
        super().__init__(
            QueryLanguageSpec(
                language=language,
                grammar=tree_sitter_javascript.language,
                query=JAVASCRIPT_QUERY,
            )
        )

    def augment_symbols(
        self,
        symbols: list[AstSymbol],
        context: QueryParseContext,
    ) -> list[AstSymbol]:
        return _augment_ecma_symbols(symbols, context)


def _augment_ecma_symbols(
    symbols: list[AstSymbol],
    context: QueryParseContext,
) -> list[AstSymbol]:
    exported_names: set[str] = set()
    declarations = declaration_symbols(
        root=context.root,
        source=context.source,
        file_path=context.file_path,
        file_hash=context.file_hash,
        language=context.language,
        exported_names=exported_names,
    )
    file_symbol = replace(
        symbols[0],
        imports=import_names(context.root, context.source),
        exports=sorted(exported_names),
        metadata={
            **symbols[0].metadata,
            "language_enhancer": "ecma",
        },
    )
    endpoints = endpoint_symbols(
        context.root,
        context.source,
        file_path=context.file_path,
        file_hash=context.file_hash,
        language=context.language,
    )
    return merge_enhanced_symbols(
        symbols,
        [file_symbol, *declarations, *endpoints],
        enhancer="ecma",
    )
