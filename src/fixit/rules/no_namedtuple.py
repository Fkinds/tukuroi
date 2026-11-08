# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import ast
import re
import tokenize

from ..core.edits import Edit
from ..core.imports import add_import
from ..core.rule import Invalid, Rule, Valid
from ..core.text import Position, Span

_LINE_END = re.compile(r"\r\n|\r|\n")


class NoNamedTuple(Rule):
    """
    Enforce the use of ``dataclasses.dataclass`` decorator instead of ``NamedTuple`` for cleaner customization and
    inheritance. It supports default value, combining fields for inheritance, and omitting optional fields at
    instantiation. See `PEP 557 <https://www.python.org/dev/peps/pep-0557>`_.
    ``@dataclass`` is faster at reading an object's nested properties and executing its methods. (`benchmark <https://medium.com/@jacktator/dataclass-vs-namedtuple-vs-object-for-performance-optimization-in-python-691e234253b9>`_)
    """

    MESSAGE = "Instead of NamedTuple, consider using the @dataclass decorator from dataclasses instead for simplicity, efficiency and consistency."

    VALID = (
        Valid(
            """
            @dataclass(frozen=True)
            class Foo:
                pass
            """
        ),
        Valid(
            """
            @dataclass(frozen=False)
            class Foo:
                pass
            """
        ),
        Valid(
            """
            class Foo:
                pass
            """
        ),
        Valid(
            """
            class Foo(SomeOtherBase):
                pass
            """
        ),
        Valid(
            """
            @some_other_decorator
            class Foo:
                pass
            """
        ),
        Valid(
            """
            @some_other_decorator
            class Foo(SomeOtherBase):
                pass
            """
        ),
        Valid(
            """
            from collections import namedtuple


            class Foo(NamedTuple):
                pass
            """
        ),
    )

    INVALID = (
        Invalid(
            code="""
            from typing import NamedTuple

            class Foo(NamedTuple):
                pass
            """,
            expected_replacement="""
            from typing import NamedTuple
            from dataclasses import dataclass


            @dataclass(frozen=True)
            class Foo:
                pass
            """,
        ),
        Invalid(
            code="""
            from typing import NamedTuple as NT

            class Foo(NT):
                pass
            """,
            expected_replacement="""
            from typing import NamedTuple as NT
            from dataclasses import dataclass


            @dataclass(frozen=True)
            class Foo:
                pass
            """,
        ),
        Invalid(
            code="""
            import typing as typ

            class Foo(typ.NamedTuple):
                pass
            """,
            expected_replacement="""
            import typing as typ
            from dataclasses import dataclass


            @dataclass(frozen=True)
            class Foo:
                pass
            """,
        ),
        Invalid(
            code="""
            from typing import NamedTuple

            class Foo(NamedTuple, AnotherBase, YetAnotherBase):
                pass
            """,
            expected_replacement="""
            from typing import NamedTuple
            from dataclasses import dataclass


            @dataclass(frozen=True)
            class Foo(AnotherBase, YetAnotherBase):
                pass
            """,
        ),
        Invalid(
            code="""
            from typing import NamedTuple

            class OuterClass(SomeBase):
                class InnerClass(NamedTuple):
                    pass
            """,
            expected_replacement="""
            from typing import NamedTuple
            from dataclasses import dataclass


            class OuterClass(SomeBase):
                @dataclass(frozen=True)
                class InnerClass:
                    pass
            """,
        ),
        Invalid(
            code="""
            from typing import NamedTuple

            @some_other_decorator
            class Foo(NamedTuple):
                pass
            """,
            expected_replacement="""
            from typing import NamedTuple
            from dataclasses import dataclass


            @some_other_decorator
            @dataclass(frozen=True)
            class Foo:
                pass
            """,
        ),
        Invalid(
            code="""
            from typing import NamedTuple
            import dataclasses

            class Foo(Base, NamedTuple):
                pass
            """,
            expected_replacement="""
            from typing import NamedTuple
            import dataclasses


            @dataclasses.dataclass(frozen=True)
            class Foo(Base):
                pass
            """,
        ),
        Invalid(
            code="""
            from typing import NamedTuple

            class Foo(NamedTuple, metaclass=M):
                pass
            """,
            expected_replacement="""
            from typing import NamedTuple
            from dataclasses import dataclass


            @dataclass(frozen=True)
            class Foo(metaclass=M):
                pass
            """,
        ),
        Invalid(
            """
            from typing import NamedTuple

            dataclass = 1

            class Foo(NamedTuple):
                pass
            """,
        ),
    )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = [
            b
            for b in node.bases
            if "typing.NamedTuple" in self.imports.qualified_names(b)
        ]
        if not bases:
            return
        imported = add_import(self.source, self.imports, "dataclasses", "dataclass")
        if imported is None:
            self.report(node)
            return
        edits = self._without_bases(node, bases)
        start = self.source.span(node).start
        line = self.source.lines.position(start).line
        indent = self.source.text[self.source.lines.offset(Position(line, 0)) : start]
        match = _LINE_END.search(self.source.text)
        newline = match.group() if match else "\n"
        decorator = f"@{imported.name}(frozen=True){newline}{indent}"
        if imported.edit is not None and imported.edit.span == Span(start, start):
            edits.append(Edit(Span(start, start), imported.edit.text + decorator))
        else:
            edits.append(Edit(Span(start, start), decorator))
            if imported.edit is not None:
                edits.append(imported.edit)
        self.report(node, edits=edits)

    def _without_bases(self, node: ast.ClassDef, bases: list[ast.expr]) -> list[Edit]:
        """The edits that drop ``bases`` from the bases of ``node``."""
        items: list[ast.expr | ast.keyword] = [*node.bases, *node.keywords]
        items.sort(key=lambda item: (item.lineno, item.col_offset))
        opening, closing = self._parentheses(node)
        if len(items) == len(bases):
            return [Edit(Span(opening, closing), "")]
        edits = []
        for index, item in enumerate(items):
            if not any(item is base for base in bases):
                continue
            span = self.source.span(item)
            if index + 1 < len(items):
                # Up to the next item, with the comma.
                end = self.source.span(items[index + 1]).start
                edits.append(Edit(Span(span.start, end), ""))
            else:
                # From the item before, with the comma.
                start = self.source.span(items[index - 1]).end
                edits.append(Edit(Span(start, span.end), ""))
        return edits

    def _parentheses(self, node: ast.ClassDef) -> tuple[int, int]:
        """The offsets of the ``(`` of the bases of ``node``, and after its ``)``."""
        lines = self.source.lines
        start = self.source.span(node).start
        depth, opening = 0, -1
        for token in self.source.tokens:
            offset = lines.offset(Position(*token.start))
            if offset < start or token.type != tokenize.OP:
                continue
            if token.string == "(":
                if depth == 0 and opening < 0:
                    opening = offset
                depth += 1
            elif token.string == ")":
                depth -= 1
                if depth == 0 and opening >= 0:
                    return opening, offset + 1
        raise ValueError("no parentheses")
