# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import ast

from ..edits import Edit
from ..rule import Invalid, Rule, Valid
from ..text import Span
from ._asserts import argument_span, arguments, assertion, method_span, value

# The method to call instead of comparing with True, False or None, with the
# first argument alone.
_CONSTANTS = {"True": "assertTrue", "False": "assertFalse", "None": "assertIsNone"}


class NoAssertTrueForComparisons(Rule):
    """
    Finds incorrect use of ``assertTrue`` when the intention is to compare two values.
    These calls are replaced with ``assertEqual``.
    Comparisons with True, False and None are replaced with one-argument
    calls to ``assertTrue``, ``assertFalse`` and ``assertIsNone``.
    """

    MESSAGE = (
        '"assertTrue" does not compare its arguments, use "assertEqual" or other '
        "appropriate functions."
    )

    VALID = (
        Valid("self.assertTrue(a == b)\n"),
        Valid('self.assertTrue(data.is_valid(), "is_valid() method")\n'),
        Valid("self.assertTrue(validate(len(obj.getName(type=SHORT))))\n"),
        Valid("self.assertTrue(condition, message_string)\n"),
        Valid("self.assertTrue(a, -1)\n"),
        Valid("self.assertTrue(a, ...)\n"),
        Valid("self.assertTrue(a, 3, 'message')\n"),
        Valid("self.assertFalse(a, 3)\n"),
    )

    INVALID = (
        Invalid("self.assertTrue(a, 3)\n", expected_replacement="self.assertEqual(a, 3)\n"),
        Invalid(
            "self.assertTrue(hash(s[:4]), 0x1234)\n",
            expected_replacement="self.assertEqual(hash(s[:4]), 0x1234)\n",
        ),
        Invalid("self.assertTrue(list, [1, 3])\n", expected_replacement="self.assertEqual(list, [1, 3])\n"),
        Invalid("self.assertTrue(optional, None)\n", expected_replacement="self.assertIsNone(optional)\n"),
        Invalid("self.assertTrue(b == a, True)\n", expected_replacement="self.assertTrue(b == a)\n"),
        Invalid("self.assertTrue(b == a, False)\n", expected_replacement="self.assertFalse(b == a)\n"),
        Invalid("self.assertTrue(a, 1)\n", expected_replacement="self.assertEqual(a, 1)\n"),
        Invalid("self.assertTrue(a, 0)\n", expected_replacement="self.assertEqual(a, 0)\n"),
        Invalid("self.assertTrue(a, 1.5)\n", expected_replacement="self.assertEqual(a, 1.5)\n"),
        Invalid("self.assertTrue(a, 2j)\n", expected_replacement="self.assertEqual(a, 2j)\n"),
        Invalid("self.assertTrue(a, (1, 2))\n", expected_replacement="self.assertEqual(a, (1, 2))\n"),
        Invalid("self.assertTrue(a, {1})\n", expected_replacement="self.assertEqual(a, {1})\n"),
        Invalid("self.assertTrue(a, {1: 2})\n", expected_replacement="self.assertEqual(a, {1: 2})\n"),
        Invalid("self.assertTrue(a, None,)\n", expected_replacement="self.assertIsNone(a)\n"),
        Invalid("self.assertTrue((a), (None))\n", expected_replacement="self.assertIsNone((a))\n"),
        Invalid(
            "self.assertTrue(\n    a,  # c\n    3,\n)\n",
            expected_replacement="self.assertEqual(\n    a,  # c\n    3,\n)\n",
        ),
        Invalid(
            "self.assertTrue(\n    a,\n    None,  # c\n)\n",
            expected_replacement="self.assertIsNone(\n    a  # c\n)\n",
        ),
    )  # fmt: skip

    def visit_Call(self, node: ast.Call) -> None:
        given = arguments(node)
        if assertion(node, ("assertTrue",)) is None or len(given) != 2:
            return
        second = value(given[1])
        if isinstance(second, ast.Constant):
            if not (
                second.value is None
                or isinstance(second.value, bool | int | float | complex)
            ):
                return
        elif not isinstance(second, ast.Tuple | ast.List | ast.Set | ast.Dict):
            return
        method = "assertEqual"
        edits = []
        constant = isinstance(second, ast.Constant) and (
            second.value is None or isinstance(second.value, bool)
        )
        if constant:
            method = _CONSTANTS[repr(second.value)]  # type: ignore[union-attr]
            # Drop the second argument and its comma, from the end of the first.
            first = argument_span(self.source, node, given[0])
            end = argument_span(self.source, node, given[1]).end
            rest = self.source.text[end:]
            if rest.lstrip(" \t").startswith(","):
                end += len(rest) - len(rest.lstrip(" \t")) + 1
            edits.append(Edit(Span(first.end, end), ""))
        if method != "assertTrue":
            edits.append(Edit(method_span(self.source, node), method))
        self.report(node, edits=edits)
