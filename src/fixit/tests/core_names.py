# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``fixit.core.names``. The cases come from equivalence partitioning
(ISO/IEC/IEEE 29119-4) of the kinds of imports and of expressions, and from the
cases where libcst, which the old engine uses, follows scopes.
"""

import ast
from unittest import TestCase

from ..core.names import ImportTable

TC = "typing.Callable"


def resolve(code: str, expression: str) -> frozenset[str]:
    """The qualified names of ``expression`` with the imports of ``code``."""
    table = ImportTable.from_tree(ast.parse(code))
    node = ast.parse(expression, mode="eval").body
    return table.qualified_names(node)


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
