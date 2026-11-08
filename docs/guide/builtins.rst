
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

- :class:`NoAssertTrueForComparisons`
- :class:`NoNamedTuple`
- :class:`NoStaticIfCondition`
- :class:`SortedAttributes`
- :class:`UseAssertIn`
- :class:`UseAssertIsNotNone`
- :class:`VariadicCallableSyntax`

.. class:: NoAssertTrueForComparisons

    Finds incorrect use of ``assertTrue`` when the intention is to compare two values.
    These calls are replaced with ``assertEqual``.
    Comparisons with True, False and None are replaced with one-argument
    calls to ``assertTrue``, ``assertFalse`` and ``assertIsNone``.

    .. attribute:: MESSAGE
        :no-index:

        "assertTrue" does not compare its arguments, use "assertEqual" or other appropriate functions.

    .. attribute:: AUTOFIX
        :no-index:
        :type: Yes


    .. attribute:: VALID
        :no-index:

        .. code:: python

            self.assertTrue(a == b)
        .. code:: python

            self.assertTrue(data.is_valid(), "is_valid() method")

    .. attribute:: INVALID
        :no-index:

        .. code:: python

            self.assertTrue(a, 3)

            # suggested fix
            self.assertEqual(a, 3)

        .. code:: python

            self.assertTrue(hash(s[:4]), 0x1234)

            # suggested fix
            self.assertEqual(hash(s[:4]), 0x1234)

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

.. class:: NoStaticIfCondition

    Discourages ``if`` conditions which evaluate to a static value (e.g. ``or True``, ``and False``, etc).

    .. attribute:: MESSAGE
        :no-index:

        Your if condition appears to evaluate to a static value (e.g. `or True`, `and False`). Please double check this logic and if it is actually temporary debug code.


    .. attribute:: VALID
        :no-index:

        .. code:: python

            if my_func() or not else_func():
                pass
        .. code:: python

            if function_call(True):
                pass

    .. attribute:: INVALID
        :no-index:

        .. code:: python

            if True:
                do_something()
        .. code:: python

            if crazy_expression or True:
                do_something()
.. class:: SortedAttributes

    Ever wanted to sort a bunch of class attributes alphabetically?
    Well now it's easy! Just add "@sorted-attributes" in the doc string of
    a class definition and lint will automatically sort all attributes alphabetically.

    Feel free to add other methods and such -- it should only affect class attributes.

    .. attribute:: MESSAGE
        :no-index:

        It appears you are using the @sorted-attributes directive and the class variables are unsorted. See the lint autofix suggestion.

    .. attribute:: AUTOFIX
        :no-index:
        :type: Yes


    .. attribute:: VALID
        :no-index:

        .. code:: python

            class MyConstants:
                """
                @sorted-attributes
                """
                A = 'zzz123'
                B = 'aaa234'

            class MyUnsortedConstants:
                B = 'aaa234'
                A = 'zzz123'

    .. attribute:: INVALID
        :no-index:

        .. code:: python

            class MyUnsortedConstants:
                """
                @sorted-attributes
                """
                z = "hehehe"
                B = 'aaa234'
                A = 'zzz123'
                cab = "foo bar"
                Daaa = "banana"

                @classmethod
                def get_foo(cls) -> str:
                    return "some random thing"

            # suggested fix
            class MyUnsortedConstants:
                """
                @sorted-attributes
                """
                A = 'zzz123'
                B = 'aaa234'
                Daaa = "banana"
                cab = "foo bar"
                z = "hehehe"

                @classmethod
                def get_foo(cls) -> str:
                    return "some random thing"

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

.. class:: UseAssertIsNotNone

    Discourages use of ``assertTrue(x is not None)`` and ``assertFalse(x is not None)`` as it is deprecated (https://docs.python.org/3.8/library/unittest.html#deprecated-aliases).
    Use ``assertIsNotNone(x)`` and ``assertIsNone(x)``) instead.

    .. attribute:: MESSAGE
        :no-index:

        "assertTrue" and "assertFalse" are deprecated. Use "assertIsNotNone" and "assertIsNone" instead.
        See https://docs.python.org/3.8/library/unittest.html#deprecated-aliases

    .. attribute:: AUTOFIX
        :no-index:
        :type: Yes


    .. attribute:: VALID
        :no-index:

        .. code:: python

            self.assertIsNotNone(x)
        .. code:: python

            self.assertIsNone(x)

    .. attribute:: INVALID
        :no-index:

        .. code:: python

            self.assertTrue(a is not None)

            # suggested fix
            self.assertIsNotNone(a)

        .. code:: python

            self.assertTrue(not x is None)

            # suggested fix
            self.assertIsNotNone(x)

.. class:: VariadicCallableSyntax

    Callable types with arbitrary parameters should be written as `Callable[..., T]`

    .. attribute:: AUTOFIX
        :no-index:
        :type: Yes


    .. attribute:: VALID
        :no-index:

        .. code:: python

            from typing import Callable
            x: Callable[[int], int]
        .. code:: python

            from typing import Callable
            x: Callable[[int, int, ...], int]

    .. attribute:: INVALID
        :no-index:

        .. code:: python

            from typing import Callable
            x: Callable[[...], int] = ...

            # suggested fix
            from typing import Callable
            x: Callable[..., int] = ...

        .. code:: python

            import typing as t
            x: t.Callable[[...], int] = ...

            # suggested fix
            import typing as t
            x: t.Callable[..., int] = ...

    