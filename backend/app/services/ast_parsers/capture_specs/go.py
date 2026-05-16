GO_CAPTURE_QUERY = """
(import_spec
  path: (_) @import.source)

(type_spec
  name: (type_identifier) @definition.name
  type: (struct_type)) @definition.class

(type_spec
  name: (type_identifier) @definition.name
  type: (interface_type)) @definition.interface

(type_alias
  name: (type_identifier) @definition.name) @definition.schema

(function_declaration
  name: (identifier) @definition.name) @definition.function

(method_declaration
  receiver: (parameter_list
    (parameter_declaration
      type: (type_identifier) @definition.parent))
  name: (field_identifier) @definition.name) @definition.method

(method_declaration
  receiver: (parameter_list
    (parameter_declaration
      type: (pointer_type
        (type_identifier) @definition.parent)))
  name: (field_identifier) @definition.name) @definition.method

(method_elem
  name: (field_identifier) @definition.name) @definition.method

(call_expression
  function: (identifier) @call.name)

(call_expression
  function: (selector_expression
    field: (field_identifier) @call.name))

(type_identifier) @reference.name
"""
