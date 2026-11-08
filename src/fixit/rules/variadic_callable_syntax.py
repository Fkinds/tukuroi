# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import ast

from ..core.edits import Edit
from ..core.rule import Invalid, Rule, Valid

# ruff's UP035 replaces typing.Callable with collections.abc.Callable, so the
# rule takes both (#21).
_CALLABLES = {"typing.Callable", "collections.abc.Callable"}


class VariadicCallableSyntax(Rule):
    """
    Callable types with arbitrary parameters should be written as `Callable[..., T]`
    """

    INVALID = (
        Invalid(
            """
            from typing import Callable

            x: Callable[[...], int] = ...
            """,
            expected_replacement="""
            from typing import Callable

            x: Callable[..., int] = ...
            """,
        ),
        Invalid(
            """
            import typing as t

            x: t.Callable[[...], int] = ...
            """,
            expected_replacement="""
            import typing as t

            x: t.Callable[..., int] = ...
            """,
        ),
        Invalid(
            """
            from typing import Callable as C

            x: C[[...], int] = ...
            """,
            expected_replacement="""
            from typing import Callable as C

            x: C[..., int] = ...
            """,
        ),
        Invalid(
            """
            from typing import Callable


            def foo(bar: Optional[Callable[[...], int]]) -> Callable[[...], int]: ...
            """,
            expected_replacement="""
            from typing import Callable


            def foo(bar: Optional[Callable[..., int]]) -> Callable[..., int]: ...
            """,
        ),
        Invalid(
            """
            from collections.abc import Callable

            x: Callable[[...], int] = ...
            """,
            expected_replacement="""
            from collections.abc import Callable

            x: Callable[..., int] = ...
            """,
        ),
        Invalid(
            """
            import collections.abc

            x: collections.abc.Callable[[...], int] = ...
            """,
            expected_replacement="""
            import collections.abc

            x: collections.abc.Callable[..., int] = ...
            """,
        ),
    )

    # The docstring, as the message of the libcst rule was, newlines and all.
    MESSAGE = (
        "\nCallable types with arbitrary parameters should be written as"
        " `Callable[..., T]`\n"
    )

    VALID = (
        Valid(
            """
            from typing import Callable

            x: Callable[[int], int]
            """
        ),
        Valid(
            """
            from typing import Callable

            x: Callable[[int, int, ...], int]
            """
        ),
        Valid(
            """
            from typing import Callable

            x: Callable
            """
        ),
        Valid(
            """
            from typing import Callable as C

            x: C[..., int] = ...
            """
        ),
        Valid(
            """
            from typing import Callable


            def foo(bar: Optional[Callable[..., int]]) -> Callable[..., int]: ...
            """
        ),
        Valid(
            """
            import typing as t

            x: t.Callable[..., int] = ...
            """
        ),
        Valid(
            """
            from typing import Callable

            x: Callable[..., int] = ...
            """
        ),
        Valid("x: Callable[[...], int] = ...\n"),
        Valid("from typing import Callable\n\nx: Callable[([...], int)] = ...\n"),
        Valid("from typing import Callable\n\nx: Callable[[...]] = ...\n"),
        Valid("from typing import Callable\n\nx: Callable[[..., ...], int] = ...\n"),
        Valid("from typing import Callable\n\nx: Callable[[...], int, str] = ...\n"),
        Valid("from typing import Callable\n\nx: Callable[[None], int] = ...\n"),
    )

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if not (self.imports.qualified_names(node.value) & _CALLABLES):
            return
        elements = node.slice
        if not (isinstance(elements, ast.Tuple) and len(elements.elts) == 2):
            return
        span = self.source.span(elements)
        if self.source.text[span.start] == "(":
            return  # Callable[([...], int)]: one element, a tuple.
        first = elements.elts[0]
        if (
            isinstance(first, ast.List)
            and len(first.elts) == 1
            and isinstance(first.elts[0], ast.Constant)
            and first.elts[0].value is Ellipsis
        ):
            self.report(node, edits=[Edit(self.source.span(first), "...")])
