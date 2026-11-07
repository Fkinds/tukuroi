# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``fixit.core.suppression``. The cases are those of the
characterization tests of the libcst engine (``characterization_suppression.py``),
copied as they are: each source, and the positions of the violations that the
comments do not suppress. Here a rule is a function that finds the nodes it
would report, as the rule of the same name does.

The other cases (clauses, joined statements, decorators, multi-line strings)
were checked against the libcst engine too.
"""

import ast
from collections.abc import Callable, Iterator
from unittest import TestCase

from ..core.source import Source
from ..core.suppression import NodeComments, is_suppressed

Finder = Callable[[ast.Module], Iterator[ast.AST]]

CALL = "self.assertTrue(a in b)"


def assert_true(tree: ast.Module) -> Iterator[ast.AST]:
    """The calls of ``self.assertTrue``, as UseAssertIn and others report."""
    for node in ast.walk(tree):
        func = getattr(node, "func", None)
        if isinstance(func, ast.Attribute) and func.attr == "assertTrue":
            yield node


def static_if(tree: ast.Module) -> Iterator[ast.AST]:
    """The ``if`` and ``elif`` with a test of ``True``, as NoStaticIfCondition."""
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Constant):
            yield node


def named_tuple(tree: ast.Module) -> Iterator[ast.AST]:
    """The classes based on ``NamedTuple``, as NoNamedTuple reports."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and any(
            isinstance(base, ast.Name) and base.id == "NamedTuple"
            for base in node.bases
        ):
            yield node


def unsuppressed(text: str, finder: Finder, rule: str = "X") -> tuple[str, ...]:
    """The ``line:column`` of each node found that the comments do not suppress."""
    source = Source.from_text(text)
    comments = NodeComments(source)
    positions = []
    for node in finder(source.tree):
        if not is_suppressed(comments.of(node), rule):
            position = source.lines.position(source.span(node).start)
            positions.append((position.line, position.column))
    return tuple(f"{line}:{column}" for line, column in sorted(positions))


class SuppressionTestCase(TestCase):
    maxDiff = None

    def run_cases(
        self, finder: Finder, cases: tuple[tuple[str, str, tuple[str, ...]], ...]
    ) -> None:
        for label, text, positions in cases:
            with self.subTest(label, text=text):
                self.assertEqual(unsuppressed(text, finder), positions)


class StatementTest(SuppressionTestCase):
    def test_one_line_statement(self) -> None:
        cases = (
            ("no comment", f"x = 1\n{CALL}\n", ("2:0",)),
            ("other comment", f"x = 1\n{CALL}  # other\n", ("2:0",)),
            ("in a string", "x = 1\nself.assertTrue(a in '# lint-ignore')\n", ("2:0",)),
            ("end of line", f"x = 1\n{CALL}  # lint-ignore\n", ()),
            ("line above", f"x = 1\n# lint-ignore\n{CALL}\n", ()),
            ("above, 1 blank", f"x = 1\n# lint-ignore\n\n{CALL}\n", ()),
            ("above, 2 blanks", f"x = 1\n# lint-ignore\n\n\n{CALL}\n", ()),
            ("blank, then above", f"x = 1\n\n# lint-ignore\n{CALL}\n", ()),
            ("above, then other", f"x = 1\n# lint-ignore\n# other\n{CALL}\n", ()),
            ("other, then above", f"x = 1\n# other\n# lint-ignore\n{CALL}\n", ()),
            ("statement between", f"x = 1\n# lint-ignore\ny = 2\n{CALL}\n", ("4:0",)),
            ("end of previous", f"x = 1  # lint-ignore\n{CALL}\n", ("2:0",)),
            ("next line, EOF", f"x = 1\n{CALL}\n# lint-ignore\n", ("2:0",)),
            ("next line", f"x = 1\n{CALL}\n# lint-ignore\ny = 2\n", ("2:0",)),
            ("end, after ;", f"x = 1\n{CALL}; y = 2  # lint-ignore\n", ()),
            ("after ;, line above", f"# lint-ignore\nx = 1; {CALL}\n", ()),
            ("no line end at the end", f"x = 1\n{CALL}  # lint-ignore", ()),
            ("after ;, 1st statement on 2 lines", f"y = 0\n# lint-ignore\nx = (\n    1); {CALL}\n", ()),
            ("after ;, not the 1st statement", f"y = 0\n# lint-ignore\nx = 1; {CALL}\n", ()),
            ("end of a multi-line string above", f'x = """\n"""  # lint-ignore\n{CALL}\n', ("3:0",)),
            ("decorated one-line def, above", f"x = 1\n# lint-ignore\n@d\ndef f(): {CALL}\n", ()),
        )  # fmt: skip
        self.run_cases(assert_true, cases)

    def test_multi_line_call(self) -> None:
        cases = (
            ("no comment", "x = 1\nself.assertTrue(\n    a,\n    3,\n)\n", ("2:0",)),
            ("end of 1st line", "x = 1\nself.assertTrue(  # lint-ignore\n    a,\n    3,\n)\n", ("2:0",)),
            ("after 1st arg", "x = 1\nself.assertTrue(\n    a,  # lint-ignore\n    3,\n)\n", ("2:0",)),
            ("after last arg", "x = 1\nself.assertTrue(\n    a,\n    3,  # lint-ignore\n)\n", ("2:0",)),
            ("before 1st arg", "x = 1\nself.assertTrue(\n    # lint-ignore\n    a,\n    3,\n)\n", ("2:0",)),
            ("end of last line", "x = 1\nself.assertTrue(\n    a,\n    3,\n)  # lint-ignore\n", ()),
            ("line above", "x = 1\n# lint-ignore\nself.assertTrue(\n    a,\n    3,\n)\n", ()),
        )  # fmt: skip
        self.run_cases(assert_true, cases)

    def test_if_statement(self) -> None:
        cases = (
            ("no comment", "x = 1\nif True:\n    pass\n", ("2:0",)),
            ("end of header", "x = 1\nif True:  # lint-ignore\n    pass\n", ()),
            ("line above", "x = 1\n# lint-ignore\nif True:\n    pass\n", ()),
            ("one-line if", "x = 1\nif True: pass  # lint-ignore\n", ()),
            ("end of body", "x = 1\nif True:\n    pass  # lint-ignore\n", ("2:0",)),
            ("above body", "x = 1\nif True:\n    # lint-ignore\n    pass\n", ("2:0",)),
            ("end of `if (`", "x = 1\nif (  # lint-ignore\n    True\n):\n    pass\n", ("2:0",)),
            ("end of else", "x = 1\nif True:\n    pass\nelse:  # lint-ignore\n    pass\n", ("2:0",)),
            ("end of elif", "x = 1\nif x:\n    pass\nelif True:  # lint-ignore\n    pass\n", ()),
            ("above elif", "x = 1\nif x:\n    pass\n# lint-ignore\nelif True:\n    pass\n", ()),
            ("elif, end of if", "x = 1\nif x:  # lint-ignore\n    pass\nelif True:\n    pass\n", ("4:0",)),
            ("elif, above if", "x = 1\n# lint-ignore\nif x:\n    pass\nelif True:\n    pass\n", ("5:0",)),
            ("if in else, above", "x = 1\nif x:\n    pass\nelse:\n    # lint-ignore\n    if True:\n        pass\n", ()),
        )  # fmt: skip
        self.run_cases(static_if, cases)

    def test_nested_if_statement(self) -> None:
        cases = (
            ("no comment", "x = 1\nif True:\n    if True:\n        pass\n", ("2:0", "3:4")),
            ("end of outer", "x = 1\nif True:  # lint-ignore\n    if True:\n        pass\n", ("3:4",)),
            ("above outer", "x = 1\n# lint-ignore\nif True:\n    if True:\n        pass\n", ("4:4",)),
            ("end of inner", "x = 1\nif True:\n    if True:  # lint-ignore\n        pass\n", ("2:0",)),
        )  # fmt: skip
        self.run_cases(static_if, cases)

    def test_call_in_if_statement(self) -> None:
        cases = (
            ("body", f"x = 1\nif x:\n    {CALL}\n", ("3:4",)),
            ("body, end of if", f"x = 1\nif x:  # lint-ignore\n    {CALL}\n", ("3:4",)),
            ("body, above if", f"x = 1\n# lint-ignore\nif x:\n    {CALL}\n", ("4:4",)),
            ("one-line body, end", f"x = 1\nif x: {CALL}  # lint-ignore\n", ()),
            ("one-line body, above", f"x = 1\n# lint-ignore\nif x: {CALL}\n", ()),
            ("one-line body, after ;", f"x = 1\n# lint-ignore\nif x: y; {CALL}\n", ()),
            ("test, end of if", f"x = 1\nif {CALL}:  # lint-ignore\n    pass\n", ()),
            ("test, end of body", f"x = 1\nif {CALL}:\n    pass  # lint-ignore\n", ("2:3",)),
        )  # fmt: skip
        self.run_cases(assert_true, cases)

    def test_module_header(self) -> None:
        cases = (
            ("no blank", f"# lint-ignore\n{CALL}\n", ()),
            ("1 blank", f"# lint-ignore\n\n{CALL}\n", ()),
            ("blank, then other", f"# lint-ignore\n\n# other\n{CALL}\n", ()),
            ("blank line first", f"\n# lint-ignore\n{CALL}\n", ()),
            ("after shebang", f"#!/usr/bin/env python\n# lint-ignore\n\n{CALL}\n", ()),
            ("2nd statement", f"# lint-ignore\n\nx = 1\n{CALL}\n", ("4:0",)),
            ("docstring first", f'# lint-ignore\n"""doc"""\n{CALL}\n', ("3:0",)),
            ("if body", f"# lint-ignore\nif x:\n    {CALL}\n", ("3:4",)),
            ("one-line if body", f"# lint-ignore\nif x: {CALL}\n", ()),
        )  # fmt: skip
        self.run_cases(assert_true, cases)

    def test_module_header_if_statement(self) -> None:
        cases = (
            ("if", "# lint-ignore\n\nif True:\n    pass\n", ()),
            ("nested if", "# lint-ignore\n\nif True:\n    if True:\n        pass\n", ("4:4",)),
            ("elif", "# lint-ignore\n\nif x:\n    pass\nelif True:\n    pass\n", ("5:0",)),
        )  # fmt: skip
        self.run_cases(static_if, cases)

    def test_after_indented_block(self) -> None:
        cases = (
            ("dedented", f"if x:\n    pass\n# lint-ignore\n{CALL}\n", ()),
            ("dedented, in block", f"if x:\n    pass\n# lint-ignore\n    {CALL}\n", ()),
        )  # fmt: skip
        self.run_cases(assert_true, cases)


class ClauseTest(SuppressionTestCase):
    def test_decorated_class(self) -> None:
        nt = "from typing import NamedTuple\n"
        body = "class Foo(NamedTuple):\n    pass\n"
        cases = (
            ("no comment", f"{nt}@deco\n{body}", ("3:0",)),
            ("above decorator", f"{nt}# lint-ignore\n@deco\n{body}", ()),
            ("above, 2 decorators", f"{nt}# lint-ignore\n@d1\n@d2\n{body}", ()),
            ("end of class", f"{nt}@deco\nclass Foo(NamedTuple):  # lint-ignore\n    pass\n", ()),
        )  # fmt: skip
        self.run_cases(named_tuple, cases)

    def test_clauses(self) -> None:
        cases = (
            # (label, text, positions)
            ("except, end of header", f"try:\n    pass\nexcept {CALL}:  # lint-ignore\n    pass\n", ()),
            ("except, above", f"try:\n    pass\n# lint-ignore\nexcept {CALL}:\n    pass\n", ()),
            ("except, end of try", f"try:  # lint-ignore\n    pass\nexcept {CALL}:\n    pass\n", ("3:7",)),
            ("case, end of header", f"match x:\n    case {{1: y}} if {CALL}:  # lint-ignore\n        pass\n", ()),
            ("case, above", f"match x:\n    # lint-ignore\n    case {{1: y}} if {CALL}:\n        pass\n", ()),
            ("for, end of header", f"for x in {CALL}:  # lint-ignore\n    pass\n", ()),
            ("with, end of header", f"with {CALL}:  # lint-ignore\n    pass\n", ()),
        )  # fmt: skip
        for label, text, positions in cases:
            with self.subTest(label):
                self.assertEqual(unsuppressed(text, assert_true), positions)

    def test_module(self) -> None:
        cases = (
            ("header", "#!/x\n# lint-ignore\n\nx = 1\n", True),
            ("after the first statement", "x = 1\n# lint-ignore\n", False),
            ("empty module", "# lint-ignore\n", True),
            ("no comment", "x = 1\n", False),
        )  # fmt: skip
        for label, text, suppressed in cases:
            with self.subTest(label):
                source = Source.from_text(text)
                comments = NodeComments(source).of(source.tree)
                self.assertIs(is_suppressed(comments, "X"), suppressed)


class IsSuppressedTest(TestCase):
    def test_directives(self) -> None:
        source = Source.from_text(
            "a = 1  # lint-ignore: X\n"
            "b = 2  # lint-ignore: Y\n"
            "c = 3  # lint-ignore:\n"
            "d = 4  # lint-fixme\n"
            "e = 5  # lint-ignore: XRule\n"
        )
        comments = NodeComments(source)
        expected = {"a": True, "b": False, "c": False, "d": True, "e": True}
        for node in source.tree.body:
            name = node.targets[0].id  # type: ignore[attr-defined]
            with self.subTest(name):
                self.assertIs(is_suppressed(comments.of(node), "X"), expected[name])
