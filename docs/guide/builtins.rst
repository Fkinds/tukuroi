
..
   THIS FILE IS GENERATED - DO NOT EDIT BY HAND!
   Run `make html` or `scripts/document_rules.py` to regenerate this file.

.. _builtin-rules:

Built-in Rules
--------------

- :mod:`fixit.rules`
- :mod:`fixit.rules.extra`
- :mod:`fixit.upgrade`


``fixit.rules``
^^^^^^^^^^^^^^^

.. automodule:: fixit.rules

- :class:`ComparePrimitivesByEqual`
- :class:`CompareSingletonPrimitivesByIs`
- :class:`NoAssertTrueForComparisons`
- :class:`NoInheritFromObject`
- :class:`NoNamedTuple`
- :class:`NoRedundantFString`
- :class:`NoStaticIfCondition`
- :class:`ReplaceUnionWithOptional`
- :class:`RewriteToComprehension`
- :class:`SortedAttributes`
- :class:`UseAssertIn`
- :class:`UseAssertIsNotNone`
- :class:`UseAsyncSleepInAsyncDef`
- :class:`VariadicCallableSyntax`

.. class:: ComparePrimitivesByEqual

    Enforces the use of ``==`` and ``!=`` in comparisons to primitives rather than ``is`` and ``is not``.
    The ``==`` operator checks equality (https://docs.python.org/3/reference/datamodel.html#object.__eq__),
    while ``is`` checks identity (https://docs.python.org/3/reference/expressions.html#is).

    .. attribute:: MESSAGE
        :no-index:

        Don't use `is` or `is not` to compare primitives, as they compare references. Use == or != instead.

    .. attribute:: AUTOFIX
        :no-index:
        :type: Yes


    .. attribute:: VALID
        :no-index:

        .. code:: python

            a == 1
        .. code:: python

            a == '1'

    .. attribute:: INVALID
        :no-index:

        .. code:: python

            a is 1

            # suggested fix
            a == 1

        .. code:: python

            a is '1'

            # suggested fix
            a == '1'

.. class:: CompareSingletonPrimitivesByIs

    Enforces the use of `is` and `is not` in comparisons to singleton primitives (None, True, False) rather than == and !=.
    The == operator checks equality, when in this scenario, we want to check identity.
    See Flake8 rules E711 (https://www.flake8rules.com/rules/E711.html) and E712 (https://www.flake8rules.com/rules/E712.html).

    .. attribute:: MESSAGE
        :no-index:

        Comparisons to singleton primitives should not be done with == or !=, as they check equality rather than identity. Use `is` or `is not` instead.

    .. attribute:: AUTOFIX
        :no-index:
        :type: Yes


    .. attribute:: VALID
        :no-index:

        .. code:: python

            if x: pass
        .. code:: python

            if not x: pass

    .. attribute:: INVALID
        :no-index:

        .. code:: python

            x != True

            # suggested fix
            x is not True

        .. code:: python

            x != False

            # suggested fix
            x is not False

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

.. class:: NoInheritFromObject

    In Python 3, a class is inherited from ``object`` by default.
    Explicitly inheriting from ``object`` is redundant, so removing it keeps the code simpler.

    .. attribute:: MESSAGE
        :no-index:

        Inheriting from object is a no-op.  'class Foo:' is just fine =)

    .. attribute:: AUTOFIX
        :no-index:
        :type: Yes


    .. attribute:: VALID
        :no-index:

        .. code:: python

            class A(something):    pass
        .. code:: python

            class A:
                pass

    .. attribute:: INVALID
        :no-index:

        .. code:: python

            class B(object):
                pass

            # suggested fix
            class B:
                pass

        .. code:: python

            class B(object, A):
                pass

            # suggested fix
            class B(A):
                pass

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

.. class:: NoRedundantFString

    Remove redundant f-string without placeholders.

    .. attribute:: MESSAGE
        :no-index:

        f-string doesn't have placeholders, remove redundant f-string.

    .. attribute:: AUTOFIX
        :no-index:
        :type: Yes


    .. attribute:: VALID
        :no-index:

        .. code:: python

            good: str = "good"
        .. code:: python

            good: str = f"with_arg{arg}"

    .. attribute:: INVALID
        :no-index:

        .. code:: python

            bad: str = f"bad" + "bad"

            # suggested fix
            bad: str = "bad" + "bad"

        .. code:: python

            bad: str = f'bad'

            # suggested fix
            bad: str = 'bad'

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
.. class:: ReplaceUnionWithOptional

    Enforces the use of ``Optional[T]`` over ``Union[T, None]`` and ``Union[None, T]``.
    See https://docs.python.org/3/library/typing.html#typing.Optional to learn more about Optionals.

    .. attribute:: MESSAGE
        :no-index:

        `Optional[T]` is preferred over `Union[T, None]` or `Union[None, T]`. Learn more: https://docs.python.org/3/library/typing.html#typing.Optional

    .. attribute:: AUTOFIX
        :no-index:
        :type: Yes


    .. attribute:: VALID
        :no-index:

        .. code:: python

            def func() -> Optional[str]:
                pass
        .. code:: python

            def func() -> Optional[Dict]:
                pass

    .. attribute:: INVALID
        :no-index:

        .. code:: python

            def func() -> Union[str, None]:
                pass
        .. code:: python

            from typing import Optional
            def func() -> Union[Dict[str, int], None]:
                pass

            # suggested fix
            from typing import Optional
            def func() -> Optional[Dict[str, int]]:
                pass

.. class:: RewriteToComprehension

    A derivative of flake8-comprehensions's C400-C402 and C403-C404.
    Comprehensions are more efficient than functions calls. This C400-C402
    suggest to use `dict/set/list` comprehensions rather than respective
    function calls whenever possible. C403-C404 suggest to remove unnecessary
    list comprehension in a set/dict call, and replace it with set/dict
    comprehension.

    .. attribute:: AUTOFIX
        :no-index:
        :type: Yes


    .. attribute:: VALID
        :no-index:

        .. code:: python

            [val for val in iterable]
        .. code:: python

            {val for val in iterable}

    .. attribute:: INVALID
        :no-index:

        .. code:: python

            list(val for val in iterable)

            # suggested fix
            [val for val in iterable]

        .. code:: python

            list(val for row in matrix for val in row)

            # suggested fix
            [val for row in matrix for val in row]

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

.. class:: UseAsyncSleepInAsyncDef

    Detect if asyncio.sleep is used in an async function

    .. attribute:: MESSAGE
        :no-index:

        Use asyncio.sleep in async function


    .. attribute:: VALID
        :no-index:

        .. code:: python

            import time
            def func():
                time.sleep(1)
        .. code:: python

            from time import sleep
            def func():
                sleep(1)

    .. attribute:: INVALID
        :no-index:

        .. code:: python

            import time
            async def func():
                time.sleep(1)
        .. code:: python

            from time import sleep
            async def func():
                sleep(1)
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


``fixit.rules.extra``
^^^^^^^^^^^^^^^^^^^^^

.. automodule:: fixit.rules.extra

- :class:`ExplicitFrozenDataclass`
- :class:`UseLintFixmeComment`

.. class:: ExplicitFrozenDataclass

    Encourages the use of frozen dataclass objects by telling users to specify the
    kwarg.

    Without this lint rule, most users of dataclass won't know to use the kwarg, and
    may unintentionally end up with mutable objects.

    .. attribute:: MESSAGE
        :no-index:

        When using dataclasses, explicitly specify a frozen keyword argument. Example: `@dataclass(frozen=True)` or `@dataclass(frozen=False)`. Docs: https://docs.python.org/3/library/dataclasses.html

    .. attribute:: AUTOFIX
        :no-index:
        :type: Yes


    .. attribute:: VALID
        :no-index:

        .. code:: python

            @some_other_decorator
            class Cls: pass
        .. code:: python

            from dataclasses import dataclass
            @dataclass(frozen=False)
            class Cls: pass

    .. attribute:: INVALID
        :no-index:

        .. code:: python

            from dataclasses import dataclass
            @some_unrelated_decorator
            @dataclass  # not called as a function
            @another_unrelated_decorator
            class Cls: pass

            # suggested fix
            from dataclasses import dataclass
            @some_unrelated_decorator
            @dataclass(frozen=True)  # not called as a function
            @another_unrelated_decorator
            class Cls: pass

        .. code:: python

            from dataclasses import dataclass
            @dataclass()  # called as a function, no kwargs
            class Cls: pass

            # suggested fix
            from dataclasses import dataclass
            @dataclass(frozen=True)  # called as a function, no kwargs
            class Cls: pass

.. class:: UseLintFixmeComment

    To silence a lint warning, use ``lint-fixme`` (when plans to fix the issue later) or ``lint-ignore``
    (when the lint warning is not valid) comments.
    The comment requires to be in a standalone comment line and follows the format ``lint-fixme: RULE_NAMES EXTRA_COMMENTS``.
    It suppresses the lint warning with the RULE_NAMES in the next line.
    RULE_NAMES can be one or more lint rule names separated by comma.
    ``noqa`` is deprecated and not supported because explicitly providing lint rule names to be suppressed
    in lint-fixme comment is preferred over implicit noqa comments. Implicit noqa suppression comments
    sometimes accidentally silence warnings unexpectedly.

    .. attribute:: MESSAGE
        :no-index:

        noqa is deprecated. Use `lint-fixme` or `lint-ignore` instead.


    .. attribute:: VALID
        :no-index:

        .. code:: python

            # lint-fixme: UseFstringRule
            "%s" % "hi"
        .. code:: python

            # lint-ignore: UsePlusForStringConcatRule
            'ab' 'cd'

    .. attribute:: INVALID
        :no-index:

        .. code:: python

            fn() # noqa
        .. code:: python

            (
             1,
             2,  # noqa
            )

``fixit.upgrade``
^^^^^^^^^^^^^^^^^

.. automodule:: fixit.upgrade

- :class:`FixitDeprecatedImport`
- :class:`FixitDeprecatedTestCaseKeywords`
- :class:`FixitRemoveRuleSuffix`

.. class:: FixitDeprecatedImport

    Upgrade lint rules to replace deprecated imports with their replacements.

    .. attribute:: MESSAGE
        :no-index:

        Fixit deprecated import {old_name}, use {new_name} instead

    .. attribute:: AUTOFIX
        :no-index:
        :type: Yes


    .. attribute:: VALID
        :no-index:

        .. code:: python

            from fixit import LintRule
        .. code:: python

            from fixit import Invalid

    .. attribute:: INVALID
        :no-index:

        .. code:: python

            from fixit import CstLintRule

            # suggested fix
            from fixit import LintRule

        .. code:: python

            from fixit import CSTLintRule

            # suggested fix
            from fixit import LintRule

.. class:: FixitDeprecatedTestCaseKeywords

    Modify lint rule test cases from Fixit 1 to remove deprecated keyword arguments
    and convert the line and column values into a CodeRange.

    .. important::
       The use of ``fixit.ValidTestCase`` and ``fixit.InvalidTestCase`` have been
       deprecated. This rule provides upgrades only to the temporary aliases.

    .. attribute:: MESSAGE
        :no-index:

        Fix deprecated ValidTestCase/InvalidTestCase keyword arguments

    .. attribute:: AUTOFIX
        :no-index:
        :type: Yes


    .. attribute:: VALID
        :no-index:

        .. code:: python

            from fixit import InvalidTestCase

            InvalidTestCase(
                "print('hello')",
                message="oops",
            )

    .. attribute:: INVALID
        :no-index:

        .. code:: python

            from fixit import InvalidTestCase

            InvalidTestCase(
                "print('hello')",
                line=3,
                column=10,
                config=None,
                filename="hello.py",
                kind="X123",
            )

            # suggested fix
            from fixit import InvalidTestCase

            InvalidTestCase(
                "print('hello')",
                range = CodeRange(start=CodePosition(3, 10), end=CodePosition(1 + 3, 0)))

.. class:: FixitRemoveRuleSuffix

    Remove the "Rule" suffix from lint rule class names

    .. attribute:: MESSAGE
        :no-index:

        Do not end lint rule subclasses with 'Rule'


    .. attribute:: VALID
        :no-index:

        .. code:: python

            import fixit
            class DontTryThisAtHome(fixit.LintRule): ...
        .. code:: python

            from fixit import LintRule
            class CatsRuleDogsDrool(LintRule): ...

    .. attribute:: INVALID
        :no-index:

        .. code:: python

            import fixit
            class DontTryThisAtHomeRule(fixit.LintRule): ...
        .. code:: python

            from fixit import LintRule
            class CatsRuleDogsDroolRule(LintRule): ...
    