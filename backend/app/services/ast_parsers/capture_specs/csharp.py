CSHARP_CAPTURE_QUERY = """
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
