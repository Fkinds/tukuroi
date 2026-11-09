.. _api:

API Reference
=============

.. module:: fixit


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

.. autoclass:: fixit.FileContent

.. autofunction:: fixit_bytes
.. autoclass:: fixit.util.capture

.. autoclass:: Config
.. autoclass:: Options
.. autoclass:: QualifiedRule
