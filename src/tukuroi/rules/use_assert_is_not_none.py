# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import ast

from ..core.edits import Edit
from ..core.rule import Invalid, Rule, Valid
from ._asserts import argument_span, arguments, assertion, method_span, text, value


class UseAssertIsNotNone(Rule):
    """
    Discourages use of ``assertTrue(x is not None)`` and ``assertFalse(x is not None)`` as it is deprecated (https://docs.python.org/3.8/library/unittest.html#deprecated-aliases).
    Use ``assertIsNotNone(x)`` and ``assertIsNone(x)``) instead.
    """

    MESSAGE = (
        '"assertTrue" and "assertFalse" are deprecated. Use "assertIsNotNone" and "assertIsNone" instead.\n'
        "See https://docs.python.org/3.8/library/unittest.html#deprecated-aliases"
    )

    VALID = (
        Valid("self.assertIsNotNone(x)\n"),
        Valid("self.assertIsNone(x)\n"),
        Valid("self.assertIsNone(None)\n"),
        Valid("self.assertIsNotNone(f(x))\n"),
        Valid("self.assertIsNone(f(x))\n"),
        Valid("self.assertIsNone(object.key)\n"),
        Valid("self.assertIsNotNone(object.key)\n"),
        Valid("self.assertTrue(x is None, 'message')\n"),
        Valid("self.assertTrue(x is y)\n"),
        Valid("self.assertTrue(x == None)\n"),
        Valid("self.assertTrue(x is True)\n"),
        Valid("other.assertTrue(x is None)\n"),
    )

    INVALID = (
        Invalid("self.assertTrue(a is not None)\n", expected_replacement="self.assertIsNotNone(a)\n"),
        Invalid("self.assertTrue(not x is None)\n", expected_replacement="self.assertIsNotNone(x)\n"),
        Invalid("self.assertTrue(f() is not None)\n", expected_replacement="self.assertIsNotNone(f())\n"),
        Invalid("self.assertTrue(not x is not None)\n", expected_replacement="self.assertIsNone(x)\n"),
        Invalid("self.assertTrue(f(x) is not None)\n", expected_replacement="self.assertIsNotNone(f(x))\n"),
        Invalid("self.assertTrue(x is None)\n", expected_replacement="self.assertIsNone(x)\n"),
        Invalid("self.assertFalse(x is not None)\n", expected_replacement="self.assertIsNone(x)\n"),
        Invalid("self.assertFalse(not x is None)\n", expected_replacement="self.assertIsNone(x)\n"),
        Invalid("self.assertFalse(f() is not None)\n", expected_replacement="self.assertIsNone(f())\n"),
        Invalid("self.assertFalse(not x is not None)\n", expected_replacement="self.assertIsNotNone(x)\n"),
        Invalid("self.assertFalse(f(x) is not None)\n", expected_replacement="self.assertIsNone(f(x))\n"),
        Invalid("self.assertFalse(x is None)\n", expected_replacement="self.assertIsNotNone(x)\n"),
        Invalid("self.assertTrue((x is None))\n", expected_replacement="self.assertIsNone(x)\n"),
        Invalid("self.assertTrue(expr=x is None)\n", expected_replacement="self.assertIsNone(x)\n"),
        Invalid(
            "self.assertTrue(\n    a is not None  # c\n)\n",
            expected_replacement="self.assertIsNotNone(\n    a  # c\n)\n",
        ),
    )  # fmt: skip

    def visit_Call(self, node: ast.Call) -> None:
        method = assertion(node, ("assertTrue", "assertFalse"))
        given = arguments(node)
        if method is None or len(given) != 1 or isinstance(given[0], ast.Starred):
            return
        argument = value(given[0])
        negated = isinstance(argument, ast.UnaryOp) and isinstance(argument.op, ast.Not)
        compare = argument.operand if negated else argument  # type: ignore[union-attr]
        if not (
            isinstance(compare, ast.Compare)
            and len(compare.ops) == 1
            and isinstance(compare.ops[0], ast.Is | ast.IsNot)
            and isinstance(compare.comparators[0], ast.Constant)
            and compare.comparators[0].value is None
        ):
            return
        negations = (
            (method == "assertFalse") + negated + isinstance(compare.ops[0], ast.IsNot)
        )
        replacement = "assertIsNone" if negations % 2 == 0 else "assertIsNotNone"
        self.report(
            node,
            edits=[
                Edit(method_span(self.source, node), replacement),
                Edit(
                    argument_span(self.source, node, given[0]),
                    text(self.source, compare.left),
                ),
            ],
        )
