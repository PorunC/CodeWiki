JAVA_QUERY = """
(import_declaration
  (scoped_identifier) @import.source)

(class_declaration
  name: (identifier) @definition.name) @definition.class

(interface_declaration
  name: (identifier) @definition.name) @definition.interface

(record_declaration
  name: (identifier) @definition.name) @definition.schema

(enum_declaration
  name: (identifier) @definition.name) @definition.schema

(annotation_type_declaration
  name: (identifier) @definition.name) @definition.schema

(method_declaration
  name: (identifier) @definition.name) @definition.method

(constructor_declaration
  name: (identifier) @definition.name) @definition.method

(method_invocation
  name: (identifier) @call.name)

(object_creation_expression
  type: (_) @call.name)

(type_identifier) @reference.name

(scoped_type_identifier) @reference.name
"""
