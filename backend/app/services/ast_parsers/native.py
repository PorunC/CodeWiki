from backend.app.services.ast_parsers.query import QueryLanguageSpec, TreeSitterQueryParser


RUST_QUERY = """
(use_declaration argument: (_) @import.source)

(struct_item
  name: (type_identifier) @definition.name) @definition.class

(enum_item
  name: (type_identifier) @definition.name) @definition.schema

(trait_item
  name: (type_identifier) @definition.name) @definition.interface

(function_item
  name: (identifier) @definition.name) @definition.function

(impl_item
  type: (type_identifier) @definition.parent
  body: (declaration_list
    (function_item
      name: (identifier) @definition.name) @definition.method))

(trait_item
  name: (type_identifier) @definition.parent
  body: (declaration_list
    (function_signature_item
      name: (identifier) @definition.name) @definition.method))

(call_expression
  function: (identifier) @call.name)

(call_expression
  function: (scoped_identifier
    name: (identifier) @call.name))
"""


C_QUERY = """
(preproc_include path: (_) @import.source)

(struct_specifier
  name: (type_identifier) @definition.name) @definition.class

(enum_specifier
  name: (type_identifier) @definition.name) @definition.schema

(function_definition
  declarator: (function_declarator
    declarator: (identifier) @definition.name)) @definition.function

(call_expression
  function: (identifier) @call.name)
"""


CPP_QUERY = """
(preproc_include path: (_) @import.source)

(class_specifier
  name: (type_identifier) @definition.name
  (base_class_clause
    (type_identifier) @heritage.base)*) @definition.class

(struct_specifier
  name: (type_identifier) @definition.name
  (base_class_clause
    (type_identifier) @heritage.base)*) @definition.class

(enum_specifier
  name: (type_identifier) @definition.name) @definition.schema

(function_definition
  declarator: (function_declarator
    declarator: (identifier) @definition.name)) @definition.function

(function_definition
  declarator: (function_declarator
    declarator: (qualified_identifier
      scope: (_) @definition.parent
      name: (identifier) @definition.name))) @definition.method

(field_declaration
  declarator: (function_declarator
    declarator: (field_identifier) @definition.name)) @definition.method

(call_expression
  function: (identifier) @call.name)

(call_expression
  function: (field_expression
    field: (field_identifier) @call.name))
"""


CSHARP_QUERY = """
(using_directive
  (identifier) @import.source)

(class_declaration
  name: (identifier) @definition.name
  (base_list
    (identifier) @heritage.base)*) @definition.class

(interface_declaration
  name: (identifier) @definition.name) @definition.interface

(struct_declaration
  name: (identifier) @definition.name) @definition.class

(record_declaration
  name: (identifier) @definition.name) @definition.schema

(enum_declaration
  name: (identifier) @definition.name) @definition.schema

(method_declaration
  name: (identifier) @definition.name) @definition.method

(constructor_declaration
  name: (identifier) @definition.name) @definition.method

(invocation_expression
  function: (identifier) @call.name)

(invocation_expression
  function: (member_access_expression
    name: (identifier) @call.name))
"""


class TreeSitterRustParser(TreeSitterQueryParser):
    def __init__(self) -> None:
        import tree_sitter_rust

        super().__init__(
            QueryLanguageSpec(
                language="rust",
                grammar=tree_sitter_rust.language,
                query=RUST_QUERY,
            )
        )


class TreeSitterCParser(TreeSitterQueryParser):
    def __init__(self) -> None:
        import tree_sitter_c

        super().__init__(
            QueryLanguageSpec(
                language="c",
                grammar=tree_sitter_c.language,
                query=C_QUERY,
            )
        )


class TreeSitterCppParser(TreeSitterQueryParser):
    def __init__(self) -> None:
        import tree_sitter_cpp

        super().__init__(
            QueryLanguageSpec(
                language="cpp",
                grammar=tree_sitter_cpp.language,
                query=CPP_QUERY,
            )
        )


class TreeSitterCSharpParser(TreeSitterQueryParser):
    def __init__(self) -> None:
        import tree_sitter_c_sharp

        super().__init__(
            QueryLanguageSpec(
                language="csharp",
                grammar=tree_sitter_c_sharp.language,
                query=CSHARP_QUERY,
            )
        )
