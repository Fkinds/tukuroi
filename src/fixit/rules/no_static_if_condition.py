# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import ast

from ..core.rule import Invalid, Rule, Valid
from ..core.text import Position


def _static_bool(node: ast.expr) -> bool | None:
    """
    The value of ``node`` when it does not depend on anything: ``True`` or
    ``False``, ``not`` of one, an ``or`` with one true value, or an ``and``
    with one false value. ``None`` for anything else, and for a call.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        value = _static_bool(node.operand)
        return None if value is None else not value
    if isinstance(node, ast.BoolOp):
        values = [_static_bool(v) for v in node.values]
        if isinstance(node.op, ast.Or) and True in values:
            return True
        if isinstance(node.op, ast.And) and False in values:
            return False
    return None


class NoStaticIfCondition(Rule):
    """
    Discourages ``if`` conditions which evaluate to a static value (e.g. ``or True``, ``and False``, etc).
    """

    MESSAGE = (
        "Your if condition appears to evaluate to a static value (e.g. `or True`, `and False`). "
        "Please double check this logic and if it is actually temporary debug code."
    )

    VALID = (
        Valid(
            """
            if my_func() or not else_func():
                pass
            """
        ),
        Valid(
            """
            if function_call(True):
                pass
            """
        ),
        Valid(
            """
            # ew who would this???
            def true():
                return False


            if true() and else_call():  # True or False
                pass
            """
        ),
        Valid(
            """
            # ew who would this???
            if False or some_func():
                pass
            """
        ),
        Valid("if False or False:\n    pass\n"),
        Valid("if True and x:\n    pass\n"),
        Valid("if 1:\n    pass\n"),
        Valid("if None:\n    pass\n"),
        Valid("x = a if True else b\n"),
        Valid("while True:\n    pass\n"),
    )

    INVALID = (
        Invalid(
            """
            if True:
                do_something()
            """,
        ),
        Invalid(
            """
            if crazy_expression or True:
                do_something()
            """,
        ),
        Invalid(
            """
            if crazy_expression and False:
                do_something()
            """,
        ),
        Invalid(
            """
            if crazy_expression and not True:
                do_something()
            """,
        ),
        Invalid(
            """
            if crazy_expression or not False:
                do_something()
            """,
        ),
        Invalid(
            """
            if crazy_expression or (something() or True):
                do_something()
            """,
        ),
        Invalid(
            """
            if crazy_expression and (something() and (not True)):
                do_something()
            """,
        ),
        Invalid(
            """
            if crazy_expression and (something() and (other_func() and not True)):
                do_something()
            """,
        ),
        Invalid(
            """
            if (crazy_expression and (something() and (not True))) or True:
                do_something()
            """,
        ),
        Invalid(
            """
            async def some_func() -> none:
                if (await expression()) and False:
                    pass
            """,
        ),
        Invalid("if a or b or True:\n    pass\n"),
        Invalid("if True or x:\n    pass\n"),
        Invalid("if x and False and y:\n    pass\n"),
        Invalid("if not not True:\n    pass\n"),
        Invalid("if x:\n    pass\nelif False:\n    pass\n", position=Position(3, 0)),
    )

    def visit_If(self, node: ast.If) -> None:
        if _static_bool(node.test) is not None:
            self.report(node)
