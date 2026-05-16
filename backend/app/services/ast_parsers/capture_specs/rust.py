RUST_CAPTURE_QUERY = """
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
