C_CAPTURE_QUERY = """
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
