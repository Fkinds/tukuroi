.. _api:

API Reference
=============

.. module:: tukuroi


Lint Rules
----------

.. autoclass:: Rule
    :members: report, name

.. autoclass:: Valid
.. autoclass:: Invalid
.. autoclass:: Edit
.. autoclass:: Position
.. autoclass:: Span
.. autoclass:: Range
.. autoclass:: Source
    :members: span, tokens_in
.. autoclass:: Token
.. autoclass:: Comment
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
.. autoclass:: Result
.. autoclass:: Error


Advanced API
^^^^^^^^^^^^

.. autoclass:: tukuroi.FileContent

.. autofunction:: tukuroi_bytes
.. autoclass:: tukuroi.util.capture

.. autoclass:: Config
.. autoclass:: Options
.. autoclass:: QualifiedRule
