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
    :members: span
.. autoclass:: ImportTable
    :members: qualified_names


Frontends
---------

Simple API
^^^^^^^^^^

.. autofunction:: fixit_paths
.. autofunction:: fixit_file
.. autofunction:: print_result

.. autoclass:: Violation
.. autoclass:: Result
.. autoclass:: Error


Advanced API
^^^^^^^^^^^^

.. autoclass:: tukuroi.FileContent

.. autofunction:: fixit_bytes
.. autoclass:: tukuroi.util.capture

.. autoclass:: Config
.. autoclass:: Options
.. autoclass:: QualifiedRule
