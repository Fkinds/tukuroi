# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Helpers for the rules on the assertions of ``unittest`` (``self.assertTrue``):
their fixes edit the name of the method and the arguments, and keep the rest of
the call (its parentheses, line ends and comments) as it is.
"""

import ast
from collections.abc import Collection

from ..core.source import Source
from ..core.text import Span


def assertion(call: ast.Call, methods: Collection[str]) -> str | None:
    """The method of ``call`` if it is ``self.<method>(...)``, one of ``methods``."""
    func = call.func
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "self"
        and func.attr in methods
    ):
        return func.attr
    return None


def method_span(source: Source, call: ast.Call) -> Span:
    """The span of the name of the method of ``call``, ``self.<method>``."""
    func = call.func
    assert isinstance(func, ast.Attribute)
    end = source.span(func).end
    return Span(end - len(func.attr), end)


def arguments(call: ast.Call) -> list[ast.expr | ast.keyword]:
    """The arguments of ``call``, positional and keyword, in their order."""
    return sorted([*call.args, *call.keywords], key=lambda a: (a.lineno, a.col_offset))


def value(argument: ast.expr | ast.keyword) -> ast.expr:
    """The expression of ``argument``."""
    return argument.value if isinstance(argument, ast.keyword) else argument


def text(source: Source, node: ast.AST) -> str:
    """The text of ``node``."""
    span = source.span(node)
    return source.text[span.start : span.end]


def argument_span(source: Source, call: ast.Call, argument: ast.AST) -> Span:
    """The span of ``argument``, with its parentheses, not those of ``call``."""
    code = source.text
    opening = code.index("(", source.span(call.func).end)
    span = source.span(argument)
    start, end = span.start, span.end
    while True:
        before = len(code[:start].rstrip())
        after = len(code) - len(code[end:].lstrip())
        if before - 1 > opening and code[before - 1] == "(" and code[after] == ")":
            start, end = before - 1, after + 1
        else:
            return Span(start, end)
