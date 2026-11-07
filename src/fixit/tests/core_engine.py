# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``fixit.core.engine``: which ``visit_`` methods are called and in what
order, the order of the reports, and what the engine does with the comments
(suppression, wrong directives, fixes that would drop a comment).
"""

import ast
from unittest import TestCase

from ..core.edits import Edit
from ..core.engine import BadDirective, lint
from ..core.rule import Report, Rule
from ..core.source import Source
from ..core.text import Position, Span


class NoBadName(Rule):
    MESSAGE = "Use good, not bad."

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "bad":
            self.report(node, replacement="good")


class NoBadNameToo(NoBadName):
    MESSAGE = "Bad again."


class Recorder(Rule):
    """Records each call: the method and the class of the node."""

    calls: list[tuple[str, str]] = []  # noqa: RUF012

    def visit_Module(self, node: ast.Module) -> None:
        self.calls.append(("visit_Module", type(node).__name__))

    def visit_If(self, node: ast.If) -> None:
        self.calls.append(("visit_If", type(node).__name__))

    def visit_stmt(self, node: ast.stmt) -> None:
        self.calls.append(("visit_stmt", type(node).__name__))


class NoCallF(Rule):
    """Replaces a call of ``f`` with the text of its ``fixed`` keyword."""

    MESSAGE = "No f."

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == "f":
            fixed = node.keywords[0].value if node.keywords else None
            text = fixed.value if isinstance(fixed, ast.Constant) else "g()"
            self.report(node, replacement=str(text))


class Counter(Rule):
    """Reports the number of names it saw in the file, at the module."""

    MESSAGE = "Names."

    def __init__(self, *args: object) -> None:
        super().__init__(*args)  # type: ignore[arg-type]
        self.names = 0

    def visit_Name(self, node: ast.Name) -> None:
        self.names += 1

    def visit_Module(self, node: ast.Module) -> None:
        # Called first: the count is of the names of the files before.
        self.report(node, str(self.names))


class Raises(Rule):
    def visit_Name(self, node: ast.Name) -> None:
        raise RuntimeError("boom")


def positions(text: str, *rules: type[Rule]) -> list[tuple[str, str]]:
    result = lint(Source.from_text(text), rules)
    return [(f"{r.position.line}:{r.position.column}", r.rule) for r in result.reports]


class DispatchTest(TestCase):
    def test_methods_in_order(self) -> None:
        Recorder.calls.clear()
        lint(Source.from_text("if x:\n    y = 1\nz = 2\n"), [Recorder])
        expected = [
            ("visit_Module", "Module"),
            ("visit_If", "If"),
            ("visit_stmt", "If"),
            ("visit_stmt", "Assign"),
            ("visit_stmt", "Assign"),
        ]
        self.assertEqual(Recorder.calls, expected)

    def test_each_node_once(self) -> None:
        text = "bad = bad + f(bad)\nif bad:\n    bad\n"
        self.assertEqual(len(positions(text, NoBadName)), 5)

    def test_an_instance_for_each_source(self) -> None:
        for text in ("a = b\n", "c\n"):
            with self.subTest(text):
                (report,) = lint(Source.from_text(text), [Counter]).reports
                self.assertEqual(report.message, "0")

    def test_no_rules(self) -> None:
        result = lint(Source.from_text("bad = 1\n"), [])
        self.assertEqual((result.reports, result.bad_directives), ((), ()))

    def test_exception_of_a_rule(self) -> None:
        with self.assertRaises(RuntimeError):
            lint(Source.from_text("x = 1\n"), [Raises])


class ReportsTest(TestCase):
    def test_order(self) -> None:
        text = "x = bad\nbad = 1\n"
        expected = [
            ("1:4", "NoBadName"),
            ("1:4", "NoBadNameToo"),
            ("2:0", "NoBadName"),
            ("2:0", "NoBadNameToo"),
        ]
        for rules in ((NoBadName, NoBadNameToo), (NoBadNameToo, NoBadName)):
            with self.subTest(rules=[r.name() for r in rules]):
                self.assertEqual(positions(text, *rules), expected)

    def test_suppressed(self) -> None:
        cases = (
            # (label, text, reports left)
            ("no comment", "bad = 1\n", [("1:0", "NoBadName"), ("1:0", "NoBadNameToo")]),
            ("every rule", "bad = 1  # lint-ignore\n", []),
            ("one rule", "bad = 1  # lint-ignore: NoBadName\n", [("1:0", "NoBadNameToo")]),
            ("other line", "# lint-ignore\nx = 1\nbad = 1\n", [("3:0", "NoBadName"), ("3:0", "NoBadNameToo")]),
            ("wrong directive", "bad = 1  # lint-ignore:\n", [("1:0", "NoBadName"), ("1:0", "NoBadNameToo")]),
        )  # fmt: skip
        for label, text, left in cases:
            with self.subTest(label):
                self.assertEqual(positions(text, NoBadName, NoBadNameToo), left)

    def test_bad_directives(self) -> None:
        text = "x = 1  # lint-ignore: a b\n# lint-fixme(X)\ny = 2  # noqa  # lint-ignore:\n# lint-ignore\n"
        result = lint(Source.from_text(text), [])
        expected = (
            BadDirective(Position(1, 7), "lint-ignore: a b"),
            BadDirective(Position(2, 0), "lint-fixme(X)"),
            BadDirective(Position(3, 7), "lint-ignore:"),
        )
        self.assertEqual(result.bad_directives, expected)

    def test_fix_that_drops_a_comment(self) -> None:
        # NoCallF replaces the call with the text of its keyword, or with "g()".
        kept = "g(1,  # c\n)"
        cases = (
            # (label, source, edits of the report)
            ("no comment", "x = f()\n", (Edit(Span(4, 7), "g()"),)),
            ("drops it", "x = f(\n    1,  # c\n)\n", ()),
            ("keeps it", f"x = f(\n    1,  # c\n    fixed={kept!r},\n)\n", (Edit(Span(4, 46), kept),)),
        )  # fmt: skip
        for label, source, edits in cases:
            with self.subTest(label):
                (report,) = lint(Source.from_text(source), [NoCallF]).reports
                self.assertEqual(report.edits, edits)

    def test_report_keeps_its_node(self) -> None:
        source = Source.from_text("bad = 1\n")
        (report,) = lint(source, [NoBadName]).reports
        self.assertIsInstance(report.node, ast.Name)
        self.assertEqual(
            report,
            Report(
                report.rule, report.span, report.position, report.message, report.edits
            ),
        )
