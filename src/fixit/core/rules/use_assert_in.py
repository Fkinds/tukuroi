# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import ast

from ..edits import Edit
from ..rule import Invalid, Rule, Valid
from ._asserts import argument_span, arguments, assertion, method_span, text, value

# The method to call instead, by the method called, "not" in the argument, and
# the operator of the comparison.
_METHODS: dict[tuple[str, bool, type[ast.cmpop]], str] = {
    ("assertTrue", False, ast.In): "assertIn",
    ("assertTrue", False, ast.NotIn): "assertNotIn",
    ("assertTrue", True, ast.In): "assertNotIn",
    ("assertFalse", False, ast.In): "assertNotIn",
}


class UseAssertIn(Rule):
    """
    Discourages use of ``assertTrue(x in y)`` and ``assertFalse(x in y)``
    as it is deprecated (https://docs.python.org/3.8/library/unittest.html#deprecated-aliases).
    Use ``assertIn(x, y)`` and ``assertNotIn(x, y)``) instead.
    """

    MESSAGE = (
        "Use assertIn/assertNotIn instead of assertTrue/assertFalse for inclusion check.\n"
        "See https://docs.python.org/3/library/unittest.html#unittest.TestCase.assertIn)"
    )

    VALID = (
        Valid("self.assertIn(a, b)\n"),
        Valid("self.assertIn(f(), b)\n"),
        Valid("self.assertIn(f(x), b)\n"),
        Valid("self.assertIn(f(g(x)), b)\n"),
        Valid("self.assertNotIn(a, b)\n"),
        Valid("self.assertNotIn(f(), b)\n"),
        Valid("self.assertNotIn(f(x), b)\n"),
        Valid("self.assertNotIn(f(g(x)), b)\n"),
        Valid("self.assertTrue(a in b, 'message')\n"),
        Valid("self.assertTrue(a in b in c)\n"),
        Valid("self.assertFalse(a not in b)\n"),
        Valid("other.assertTrue(a in b)\n"),
    )

    INVALID = (
        Invalid(
            "self.assertTrue(a in b)\n", expected_replacement="self.assertIn(a, b)\n"
        ),
        Invalid(
            "self.assertTrue(f() in b)\n",
            expected_replacement="self.assertIn(f(), b)\n",
        ),
        Invalid(
            "self.assertTrue(f(x) in b)\n",
            expected_replacement="self.assertIn(f(x), b)\n",
        ),
        Invalid(
            "self.assertTrue(f(g(x)) in b)\n",
            expected_replacement="self.assertIn(f(g(x)), b)\n",
        ),
        Invalid(
            "self.assertTrue(a not in b)\n",
            expected_replacement="self.assertNotIn(a, b)\n",
        ),
        Invalid(
            "self.assertTrue(not a in b)\n",
            expected_replacement="self.assertNotIn(a, b)\n",
        ),
        Invalid(
            "self.assertFalse(a in b)\n",
            expected_replacement="self.assertNotIn(a, b)\n",
        ),
        Invalid(
            "self.assertTrue((a in b))\n", expected_replacement="self.assertIn(a, b)\n"
        ),
        Invalid(
            "self.assertTrue(expr=a in b)\n",
            expected_replacement="self.assertIn(a, b)\n",
        ),
        Invalid(
            "self.assertTrue(\n    a in b  # c\n)\n",
            expected_replacement="self.assertIn(\n    a,\n    b,  # c\n)\n",
        ),
    )

    def visit_Call(self, node: ast.Call) -> None:
        method = assertion(node, ("assertTrue", "assertFalse"))
        given = arguments(node)
        if method is None or len(given) != 1 or isinstance(given[0], ast.Starred):
            return
        argument = value(given[0])
        negated = isinstance(argument, ast.UnaryOp) and isinstance(argument.op, ast.Not)
        compare = argument.operand if negated else argument  # type: ignore[union-attr]
        if not (isinstance(compare, ast.Compare) and len(compare.ops) == 1):
            return
        replacement = _METHODS.get((method, negated, type(compare.ops[0])))
        if replacement is None:
            return
        left, right = compare.left, compare.comparators[0]
        operands = f"{text(self.source, left)}, {text(self.source, right)}"
        self.report(
            node,
            edits=[
                Edit(method_span(self.source, node), replacement),
                Edit(argument_span(self.source, node, given[0]), operands),
            ],
        )
