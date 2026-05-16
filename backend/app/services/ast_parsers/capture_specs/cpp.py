CPP_CAPTURE_QUERY = """
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
