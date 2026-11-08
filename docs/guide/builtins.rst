
..
   THIS FILE IS GENERATED - DO NOT EDIT BY HAND!
   Run `make html` or `scripts/document_rules.py` to regenerate this file.

.. _builtin-rules:

Built-in Rules
--------------

- :mod:`fixit.rules`


``fixit.rules``
^^^^^^^^^^^^^^^

.. automodule:: fixit.rules

- :class:`NoNamedTuple`
- :class:`UseAssertIn`

.. class:: NoNamedTuple

    Enforce the use of ``dataclasses.dataclass`` decorator instead of ``NamedTuple`` for cleaner customization and
    inheritance. It supports default value, combining fields for inheritance, and omitting optional fields at
    instantiation. See `PEP 557 <https://www.python.org/dev/peps/pep-0557>`_.
    ``@dataclass`` is faster at reading an object's nested properties and executing its methods. (`benchmark <https://medium.com/@jacktator/dataclass-vs-namedtuple-vs-object-for-performance-optimization-in-python-691e234253b9>`_)

    .. attribute:: MESSAGE
        :no-index:

        Instead of NamedTuple, consider using the @dataclass decorator from dataclasses instead for simplicity, efficiency and consistency.

    .. attribute:: AUTOFIX
        :no-index:
        :type: Yes


    .. attribute:: VALID
        :no-index:

        .. code:: python

            @dataclass(frozen=True)
            class Foo:
                pass
        .. code:: python

            @dataclass(frozen=False)
            class Foo:
                pass

    .. attribute:: INVALID
        :no-index:

        .. code:: python

            from typing import NamedTuple

            class Foo(NamedTuple):
                pass

            # suggested fix
            from typing import NamedTuple

            @dataclass(frozen=True)
            class Foo:
                pass

        .. code:: python

            from typing import NamedTuple as NT

            class Foo(NT):
                pass

            # suggested fix
            from typing import NamedTuple as NT

            @dataclass(frozen=True)
            class Foo:
                pass

.. class:: UseAssertIn

    Discourages use of ``assertTrue(x in y)`` and ``assertFalse(x in y)``
    as it is deprecated (https://docs.python.org/3.8/library/unittest.html#deprecated-aliases).
    Use ``assertIn(x, y)`` and ``assertNotIn(x, y)``) instead.

    .. attribute:: MESSAGE
        :no-index:

        Use assertIn/assertNotIn instead of assertTrue/assertFalse for inclusion check.
        See https://docs.python.org/3/library/unittest.html#unittest.TestCase.assertIn)

    .. attribute:: AUTOFIX
        :no-index:
        :type: Yes


    .. attribute:: VALID
        :no-index:

        .. code:: python

            self.assertIn(a, b)
        .. code:: python

            self.assertIn(f(), b)

    .. attribute:: INVALID
        :no-index:

        .. code:: python

            self.assertTrue(a in b)

            # suggested fix
            self.assertIn(a, b)

        .. code:: python

            self.assertTrue(f() in b)

            # suggested fix
            self.assertIn(f(), b)

    