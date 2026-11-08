# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import ast
import re

from ..core.edits import Edit
from ..core.rule import Invalid, Rule, Valid
from ..core.text import Position, Span

_LINE_END = re.compile(r"\r\n|\r|\n")
_LINES = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$")


class SortedAttributes(Rule):
    """
    Ever wanted to sort a bunch of class attributes alphabetically?
    Well now it's easy! Just add "@sorted-attributes" in the doc string of
    a class definition and lint will automatically sort all attributes alphabetically.

    Feel free to add other methods and such -- it should only affect class attributes.
    """

    INVALID = (
        Invalid(
            """
            class MyUnsortedConstants:
                \"\"\"
                @sorted-attributes
                \"\"\"
                z = "hehehe"
                B = 'aaa234'
                A = 'zzz123'
                cab = "foo bar"
                Daaa = "banana"

                @classmethod
                def get_foo(cls) -> str:
                    return "some random thing"
            """,
            expected_replacement="""
            class MyUnsortedConstants:
                \"\"\"
                @sorted-attributes
                \"\"\"

                A = "zzz123"
                B = "aaa234"
                Daaa = "banana"
                cab = "foo bar"
                z = "hehehe"

                @classmethod
                def get_foo(cls) -> str:
                    return "some random thing"
            """,
        ),
        Invalid(
            """
            class C:
                \"\"\"@sorted-attributes\"\"\"

                # about b
                b = 1  # b
                a = 2
            """,
            expected_replacement="""
            class C:
                \"\"\"@sorted-attributes\"\"\"

                a = 2

                # about b
                b = 1  # b
            """,
        ),
        Invalid(
            """
            class C:
                \"\"\"@sorted-attributes\"\"\"

                b = 1

                def f(self):
                    pass
                    # in f

                a = 2
            """,
            expected_replacement="""
            class C:
                \"\"\"@sorted-attributes\"\"\"

                a = 2

                b = 1

                def f(self):
                    pass
                    # in f
            """,
        ),
        Invalid(
            """
            class C:
                \"\"\"@sorted-attributes\"\"\"

                x.y = 1
                b = 1
                a = 2
            """,
            expected_replacement="""
            class C:
                \"\"\"@sorted-attributes\"\"\"

                x.y = 1
                a = 2
                b = 1
            """,
        ),
        Invalid(
            'class C:\n    """@sorted-attributes"""\n\n    b = 1\n    a = 2',
            expected_replacement='class C:\n    """@sorted-attributes"""\n\n    a = 2\n\n    b = 1\n',
        ),
    )

    MESSAGE = "It appears you are using the @sorted-attributes directive and the class variables are unsorted. See the lint autofix suggestion."

    VALID = (
        Valid(
            """
            class MyConstants:
                \"\"\"
                @sorted-attributes
                \"\"\"

                A = "zzz123"
                B = "aaa234"


            class MyUnsortedConstants:
                B = "aaa234"
                A = "zzz123"
            """
        ),
        Valid('class C:\n    """@sorted-attributes"""\n\n    b = 1; a = 2\n'),
        Valid(
            'class C:\n    """@sorted-attributes"""\n\n    b: int = 1\n    a: int = 2\n'
        ),
        Valid('class C:\n    """@sorted-attributes"""\n\n    b = c = 1\n    a = 2\n'),
        Valid('class C:\n    """Not sorted."""\n\n    b = 1\n    a = 2\n'),
        Valid('class C: """@sorted-attributes"""; b = 1; a = 2\n'),
    )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        doc = ast.get_docstring(node)
        if not doc or "@sorted-attributes" not in doc:
            return
        # A one-line body is one line of statements: it has no line to sort.
        units = self._units(node.body)
        first = next((i for i, (stmts, _) in enumerate(units) if _target(stmts)), None)
        if first is None:
            return
        assigns = [u for u in units[first:] if _target(u[0])]
        others = [u for u in units[first:] if not _target(u[0])]
        ordered = sorted(assigns, key=lambda u: _target(u[0]) or "")
        if ordered == assigns:
            return
        start, end = units[first][1].start, units[-1][1].end
        newline = _newline(self.source.text)
        texts = [self._text(span) for _, span in ordered + others]
        replacement = "".join(
            t if _LINE_END.search(t[-1:]) else t + newline for t in texts
        )
        self.report(node, edits=[Edit(Span(start, end), replacement)])

    def _units(self, body: list[ast.stmt]) -> list[tuple[list[ast.stmt], Span]]:
        """
        The lines of ``body``: the statements of each line (joined with ``;``),
        with the comment and blank lines above them, as libcst gives them.
        """
        groups: list[list[ast.stmt]] = []
        for statement in body:
            if groups and groups[-1][-1].end_lineno == statement.lineno:
                groups[-1].append(statement)
            else:
                groups.append([statement])
        units: list[tuple[list[ast.stmt], Span]] = []
        for index, group in enumerate(groups):
            end = self._line_end(group[-1].end_lineno or group[-1].lineno)
            if index == 0:
                start = self.source.lines.offset(Position(group[0].lineno, 0))
            else:
                start = units[-1][1].end
            units.append((group, Span(start, end)))
        # The comment lines after an indented block, up to the last one as deep as
        # that block, are the block's (libcst's footer): they stay before.
        for index in range(1, len(units)):
            indent = self._block_indent(units[index - 1][0][-1])
            group, span = units[index]
            if indent is None:
                continue
            cut = position = span.start
            for line in _LINES.findall(self.source.text[span.start : span.end]):
                stripped = line.lstrip(" \t\f")
                if stripped.strip() and not stripped.startswith("#"):
                    break
                position += len(line)
                if stripped.startswith("#") and len(line) - len(stripped) >= indent:
                    cut = position
            previous_group, previous = units[index - 1]
            units[index - 1] = (previous_group, Span(previous.start, cut))
            units[index] = (group, Span(cut, span.end))
        return units

    def _block_indent(self, statement: ast.stmt) -> int | None:
        """The indent of the block of ``statement``, if it has one on its own lines."""
        block = getattr(statement, "body", None)
        if not isinstance(block, list) or not block:
            return None
        start = self.source.lines.position(self.source.span(block[-1]).start)
        if (
            start.line
            == self.source.lines.position(self.source.span(statement).start).line
        ):
            return None
        return start.column

    def _line_end(self, line: int) -> int:
        """The offset after the end of ``line``, with its line end."""
        try:
            return self.source.lines.offset(Position(line + 1, 0))
        except ValueError:
            return len(self.source.text)

    def _text(self, span: Span) -> str:
        return self.source.text[span.start : span.end]


def _target(statements: list[ast.stmt]) -> str | None:
    """The name assigned, if ``statements`` is one assignment to one name."""
    if len(statements) != 1 or not isinstance(statements[0], ast.Assign):
        return None
    targets = statements[0].targets
    if len(targets) == 1 and isinstance(targets[0], ast.Name):
        return targets[0].id
    return None


def _newline(text: str) -> str:
    """The first line end of ``text``, or ``"\\n"``."""
    match = _LINE_END.search(text)
    return match.group() if match else "\n"
