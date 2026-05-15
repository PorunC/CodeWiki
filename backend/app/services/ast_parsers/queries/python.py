PYTHON_QUERY = """
(import_statement
  (dotted_name) @import.source)

(import_from_statement
  module_name: (dotted_name) @import.source)

(class_definition
  name: (identifier) @definition.name
  superclasses: (argument_list
    (identifier) @heritage.base)?) @definition.class

(function_definition
  name: (identifier) @definition.name) @definition.function

(call
  function: (identifier) @call.name)

(call
  function: (attribute
    attribute: (identifier) @call.name))

(identifier) @reference.name
"""
