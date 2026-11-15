.. _api:

API Reference
=============

.. module:: tukuroi


Lint Rules
----------

.. autoclass:: Rule
    :members: report, name, MESSAGE, VALID, INVALID

.. autoclass:: Valid
    :members:
.. autoclass:: Invalid
    :members:
.. autoclass:: Edit
    :members:
.. autoclass:: Position
    :members:
.. autoclass:: Span
    :members:
.. autoclass:: Range
    :members:
.. autoclass:: Source
    :members: path, text, tree, tokens, comments, span, tokens_in
.. autoclass:: Token
    :members:
.. autoclass:: Comment
    :members:
.. autoclass:: ImportTable
    :members: qualified_names


Plugins
-------

.. autoclass:: FormatterPlugin
    :members: available, format

.. autoclass:: OutputFormatPlugin
    :members: start, result, end


Frontends
---------

Simple API
^^^^^^^^^^

.. autofunction:: tukuroi_paths
.. autofunction:: tukuroi_file
.. autofunction:: print_result

.. autoclass:: Violation
    :members:
.. autoclass:: Result
    :members:
.. autoclass:: Error
    :members:


Advanced API
^^^^^^^^^^^^

.. autoclass:: tukuroi.FileContent

.. autofunction:: tukuroi_bytes
.. autoclass:: tukuroi.util.capture
    :members:

.. autoclass:: Config
    :members:
.. autoclass:: Options
    :members:
.. autoclass:: QualifiedRule
    :members:
