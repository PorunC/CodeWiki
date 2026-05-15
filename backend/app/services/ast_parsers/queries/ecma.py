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
