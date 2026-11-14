# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``tukuroi.core.names``. The cases come from equivalence partitioning
(ISO/IEC/IEEE 29119-4) of the kinds of imports and of expressions, and from the
cases where libcst, which the old engine uses, follows scopes.
"""

import ast
from unittest import TestCase

from ..core.names import ImportTable
from ..core.source import Source

TC = "typing.Callable"


def resolve(code: str, expression: str) -> frozenset[str]:
    """The qualified names of ``expression`` with the imports of ``code``."""
    table = ImportTable.from_tree(ast.parse(code))
    node = ast.parse(expression, mode="eval").body
    return table.qualified_names(node)


def scoped(code: str, line: int, name: str) -> frozenset[str]:
    """
    The qualified names of the last ``name`` read on ``line`` of ``code``, with
    the table of the scopes of ``code`` (#146).
    """
    source = Source.from_text(code)
    table = ImportTable.from_source(source)
    found = [
        node
        for node in ast.walk(source.tree)
        if isinstance(node, ast.Name)
        and node.id == name
        and node.lineno == line
        and isinstance(node.ctx, ast.Load)
    ]
    return table.qualified_names(max(found, key=lambda n: n.col_offset))


RM, RS, OP = "re.match", "re.search", "os.path"


class ScopedImportTableTest(TestCase):
    def test_scopes(self) -> None:
        cases = (
            # (label, code, line and name read there, qualified names)
            ("import of the module", "from re import match\nmatch(1)\n", (2, "match"), {RM}),
            # The three that the import table of the whole module got wrong.
            ("a parameter hides the import", "from re import match\ndef f(match):\n    return match(1)\n", (3, "match"), set()),
            ("an import in a function, read outside", "def f():\n    from re import search\nsearch(1)\n", (3, "search"), set()),
            ("an import in a class, read in a method", "class A:\n    from re import search\n    def m(self):\n        return search(1)\n", (4, "search"), set()),
            ("an import in a function, read in it", "def f():\n    from re import search\n    return search(1)\n", (3, "search"), {RS}),
            ("an import in a class, read in its body", "class A:\n    from re import search\n    x = search(1)\n", (3, "search"), {RS}),
            ("an import of the module, read in a method", "from re import search\nclass A:\n    def m(self):\n        return search(1)\n", (4, "search"), {RS}),
            ("an assignment in a function hides the import", "from re import match\ndef f():\n    match = 1\n    return match\n", (4, "match"), set()),
            ("a global statement", "from re import match\ndef f():\n    global match\n    match = 1\n    return match\n", (5, "match"), {RM}),
            ("an import of an enclosing function", "def f():\n    from os import path\n    def g():\n        return path\n", (4, "path"), {OP}),
            ("a parameter of an enclosing function", "from os import path\ndef f(path):\n    def g():\n        return path\n", (4, "path"), set()),
            ("nonlocal", "from os import path\ndef f():\n    path = 1\n    def g():\n        nonlocal path\n        return path\n", (6, "path"), set()),
            ("an import two functions out", "def f():\n    from os import path\n    def g():\n        def h():\n            return path\n", (5, "path"), {OP}),
            ("an import of a function around a generic one", "def f():\n    from os import path\n    def g[T]():\n        return path\n", (4, "path"), {OP}),
            ("a class between a function and its use", "def f():\n    from os import path\n    class A:\n        def m(self):\n            return path\n", (5, "path"), {OP}),
            ("a parameter of a lambda", "from re import match\ng = lambda match: match(1)\n", (2, "match"), set()),
            ("the target of a comprehension", "from re import match\nxs = [match for match in ys]\n", (2, "match"), set()),
            ("a lambda in a function", "from re import match\ndef f(x):\n    return lambda: match(x)\n", (3, "match"), {RM}),
            ("a generator expression that reads a parameter", "from re import match\ndef f(match):\n    return (match(y) for y in ys)\n", (3, "match"), set()),
            ("the target of a generator expression", "from re import match\nxs = (match for match in ys)\n", (2, "match"), set()),
            ("the first iterable of a comprehension", "from re import match\nxs = [x for x in match]\n", (2, "match"), {RM}),
            ("a comprehension in a class does not see the class", "class A:\n    from re import match\n    xs = [match(y) for y in ys]\n", (3, "match"), set()),
            ("a default, outside the function", "from functools import cache\ndef f(cache=cache):\n    return cache\n", (2, "cache"), {"functools.cache"}),
            ("a parameter with a default", "from functools import cache\ndef f(cache=cache):\n    return cache\n", (3, "cache"), set()),
            ("a decorator", "import functools\n@functools.cache\ndef f():\n    pass\n", (2, "functools"), {"functools"}),
            ("an annotation", "import typing as t\ndef f(x: t.Any) -> t.Any:\n    pass\n", (2, "t"), {"typing"}),
            ("a type parameter hides the import", "from re import match\ndef f[match](x: match) -> None:\n    return match\n", (3, "match"), set()),
            ("a base of a class", "from typing import NamedTuple\nclass A(NamedTuple):\n    x: int\n", (2, "NamedTuple"), {"typing.NamedTuple"}),
        )  # fmt: skip
        for label, code, (line, name), names in cases:
            with self.subTest(label):
                self.assertEqual(scoped(code, line, name), names)

    def test_bindings_of_the_module_scope(self) -> None:
        code = "import a\ndef f():\n    import b\nclass C:\n    import c\nif x:\n    import d\n"
        table = ImportTable.from_source(Source.from_text(code))
        self.assertEqual(dict(table.bindings), {"a": {"a"}, "d": {"d"}})

    def test_text_that_symtable_refuses(self) -> None:
        # ast parses it, symtable does not: one table for the whole module.
        code = "def f():\n    from re import search\nnonlocal x\nsearch(1)\n"
        self.assertEqual(scoped(code, 4, "search"), {RS})

    def test_name_not_in_the_tree(self) -> None:
        # A name that a rule makes is a name of the module scope.
        code = "from re import match\ndef f(match):\n    pass\n"
        table = ImportTable.from_source(Source.from_text(code))
        made = ast.Name(id="match", ctx=ast.Load())
        self.assertEqual(table.qualified_names(made), {RM})


class ImportTableTest(TestCase):
    def test_kinds_of_imports(self) -> None:
        cases = (
            # (label, code, expression, qualified names)
            ("from", "from typing import Callable", "Callable", {TC}),
            ("from, as", "from typing import Callable as C", "C", {TC}),
            ("module", "import typing", "typing.Callable", {TC}),
            ("module, as", "import typing as t", "t.Callable", {TC}),
            (
                "dotted module",
                "import collections.abc",
                "collections.abc.Callable",
                {"collections.abc.Callable"},
            ),
            ("dotted module, as", "import a.b.c as d", "d.X", {"a.b.c.X"}),
            ("dotted module binds the top", "import os.path", "os", {"os"}),
            ("relative", "from .typing import Callable", "Callable", {".typing.Callable"}),
            ("relative, no module", "from . import x", "x", {".x"}),
            ("relative, 2 levels", "from ..a import b", "b", {"..a.b"}),
            ("2 names in one import", "from typing import Any, Callable", "Any", {"typing.Any"}),
        )  # fmt: skip
        for label, code, expression, names in cases:
            with self.subTest(label):
                self.assertEqual(resolve(code, expression), names)

    def test_not_resolved(self) -> None:
        cases = (
            # (label, code, expression)
            ("no import", "x = 1", "Callable"),
            ("built-in", "x = 1", "print"),
            ("star import", "from typing import *", "Callable"),
            ("other name", "from typing import Callable", "Any"),
            ("attribute of a call", "import typing", "typing.get()().Callable"),
            ("attribute of a subscript", "import typing", "typing.x[0].y"),
            ("call", "from typing import Callable", "Callable()"),
            ("constant", "import typing", "1"),
        )
        for label, code, expression in cases:
            with self.subTest(label):
                self.assertEqual(resolve(code, expression), frozenset())

    def test_whole_module_without_scopes(self) -> None:
        # from_tree: one table for the whole module, without its scopes.
        cases = (
            # (label, code, expression, qualified names)
            # libcst follows scopes and does not resolve this one.
            (
                "import in a function, used outside",
                "def f():\n    from typing import Callable\n",
                "Callable",
                {TC},
            ),
            (
                "import in if TYPE_CHECKING",
                "if TYPE_CHECKING:\n    from typing import Callable\n",
                "Callable",
                {TC},
            ),
            (
                "import in a class",
                "class A:\n    import typing as t\n",
                "t.Callable",
                {TC},
            ),
            # Neither the order nor the name assigned again is followed.
            (
                "import after the use",
                "x: Callable\nfrom typing import Callable\n",
                "Callable",
                {TC},
            ),
            (
                "assigned again",
                "from typing import Callable\nCallable = int\n",
                "Callable",
                {TC},
            ),
            # libcst resolves neither one at the module level.
            (
                "imported twice",
                (
                    "def f():\n    from a import X as C\n"
                    "def g():\n    from typing import Callable as C\n"
                ),
                "C",
                {"a.X", TC},
            ),
            (
                "imported twice, as a module",
                "import typing as t\nimport collections.abc as t\n",
                "t.Callable",
                {TC, "collections.abc.Callable"},
            ),
        )
        for label, code, expression, names in cases:
            with self.subTest(label):
                self.assertEqual(resolve(code, expression), names)

    def test_bindings(self) -> None:
        code = "import typing as t\nfrom a import b, c as d\nfrom e import *\n"
        table = ImportTable.from_tree(ast.parse(code))
        expected = {"t": {"typing"}, "b": {"a.b"}, "d": {"a.c"}}
        self.assertEqual(dict(table.bindings), expected)
        with self.assertRaises(TypeError):
            table.bindings["x"] = frozenset()  # type: ignore[index]

    def test_empty_module(self) -> None:
        table = ImportTable.from_tree(ast.parse(""))
        self.assertEqual(dict(table.bindings), {})
