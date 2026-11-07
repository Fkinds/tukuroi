# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``fix`` in ``fixit.core.engine`` and of ``fixit.core.format``, with
the real ``ruff``: the rounds of fixes (nested, overlapping, never ending, with
no change), the choice of fixes, and when the text is formatted.
"""

import ast
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from ..core.edits import Edit
from ..core.engine import fix
from ..core.format import FormatError, ruff_format
from ..core.rule import Rule
from ..core.source import Source
from ..core.text import Span


class NoBadName(Rule):
    MESSAGE = "Use good, not bad."

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "bad":
            self.report(node, replacement="good")


class AlsoBest(Rule):
    """Fixes the same names as NoBadName, another way. Its name comes first."""

    MESSAGE = "Use best."

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "bad":
            self.report(node, replacement="best")


class CallFToG(Rule):
    """``f(...)`` becomes ``g(...)``: a call in a call is a fix in a fix."""

    MESSAGE = "Call g."

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == "f":
            span = self.source.span(node)
            text = self.source.text[span.start : span.end]
            self.report(node, replacement="g" + text[1:])


class Grows(Rule):
    """Always adds a line: its fixes never end."""

    MESSAGE = "Grow."

    def visit_Module(self, node: ast.Module) -> None:
        end = len(self.source.text)
        self.report(node, edits=[Edit(Span(end, end), "x = 1\n")])


class SameText(Rule):
    """A fix that does not change the text."""

    MESSAGE = "Same."

    def visit_Name(self, node: ast.Name) -> None:
        self.report(node, replacement=node.id)


class Zeta(Rule):
    """Adds a comment at the end, reported at the first statement."""

    MESSAGE = "Zeta."

    def visit_Module(self, node: ast.Module) -> None:
        if "# zeta" not in self.source.text:
            end = len(self.source.text)
            self.report(node.body[0], edits=[Edit(Span(end, end), "# zeta\n")])


class Alpha(Rule):
    """Adds a comment at the same place, reported at the second statement."""

    MESSAGE = "Alpha."

    def visit_Module(self, node: ast.Module) -> None:
        if "# alpha" not in self.source.text:
            end = len(self.source.text)
            self.report(node.body[1], edits=[Edit(Span(end, end), "# alpha\n")])


def fixed(text: str, *rules: type[Rule], **options: object) -> tuple[str, int, bool]:
    result = fix(Source.from_text(text), rules, **options)  # type: ignore[arg-type]
    return result.text, result.applied, result.converged


class FixTest(TestCase):
    def test_rounds(self) -> None:
        cases = (
            # (label, text, rules, (text, fixes applied, converged))
            ("no fix", "x = 1\n", (NoBadName,), ("x = 1\n", 0, True)),
            ("one round", "bad = bad + 1\n", (NoBadName,), ("good = good + 1\n", 2, True)),
            ("a fix in a fix, 2 rounds", "f(f(1))\n", (CallFToG,), ("g(g(1))\n", 2, True)),
            ("3 deep", "f(f(f(1)))\n", (CallFToG,), ("g(g(g(1)))\n", 3, True)),
            ("the same range, by rule", "bad = 1\n", (NoBadName, AlsoBest), ("best = 1\n", 1, True)),
            ("the same range, other order", "bad = 1\n", (AlsoBest, NoBadName), ("best = 1\n", 1, True)),
            # Both edits start at the end: Alpha comes first by its name, though
            # its report comes after the report of Zeta.
            ("the same start, by rule", "x = 1\ny = 2\n", (Zeta, Alpha), ("x = 1\ny = 2\n# alpha\n# zeta\n", 2, True)),
            ("a fix with no change", "x = y\n", (SameText,), ("x = y\n", 0, True)),
        )  # fmt: skip
        for label, text, rules, result in cases:
            with self.subTest(label):
                self.assertEqual(fixed(text, *rules), result)

    def test_rounds_end(self) -> None:
        text, applied, converged = fixed("y = 2\n", Grows, rounds=3)
        self.assertEqual(
            (text, applied, converged), ("y = 2\nx = 1\nx = 1\nx = 1\n", 3, False)
        )

    def test_choose(self) -> None:
        cases = (
            # (label, chosen reports by position, text)
            ("the first", {(1, 0)}, "good = bad\n"),
            ("none", set(), "bad = bad\n"),
            ("both", {(1, 0), (1, 6)}, "good = good\n"),
        )
        for label, chosen, text in cases:
            with self.subTest(label):
                asked: list[tuple[int, int]] = []

                def choose(
                    report: object,
                    chosen: set[tuple[int, int]] = chosen,
                    asked: list[tuple[int, int]] = asked,
                ) -> bool:
                    position = report.position  # type: ignore[attr-defined]
                    asked.append((position.line, position.column))
                    return (position.line, position.column) in chosen

                result = fixed("bad = bad\n", NoBadName, choose=choose)
                self.assertEqual(result, (text, len(chosen), True))
                self.assertEqual(asked, [(1, 0), (1, 6)])

    def test_choose_one_round(self) -> None:
        text, applied, _ = fixed("f(f(1))\n", CallFToG, choose=lambda report: True)
        self.assertEqual((text, applied), ("g(f(1))\n", 1))

    def test_formatted_when_changed(self) -> None:
        cases = (
            ("changed", "bad = [1,2]\n", "good = [1, 2]\n"),
            ("not changed", "x = [1,2]\n", "x = [1,2]\n"),
            ("\\r\\n", "bad = [1,2]\r\ny = 1\r\n", "good = [1, 2]\r\ny = 1\r\n"),
        )
        for label, text, result in cases:
            with self.subTest(label):
                self.assertEqual(fixed(text, NoBadName)[0], result)

    def test_reports_of_the_first_round(self) -> None:
        result = fix(Source.from_text("f(f(1))\n"), [CallFToG])
        self.assertEqual([r.position.column for r in result.reports], [0, 2])


class RuffFormatTest(TestCase):
    def test_format(self) -> None:
        self.assertEqual(ruff_format("x = [1,2]\n", None), "x = [1, 2]\n")
        self.assertEqual(ruff_format("x = [1,2]\r\n", None), "x = [1, 2]\r\n")

    def test_settings_of_the_path(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "ruff.toml").write_text("line-length = 20\n")
            (root / "sub").mkdir()
            text = 'x = {"aaaa": 1, "bbbb": 2}\n'
            expected = 'x = {\n    "aaaa": 1,\n    "bbbb": 2,\n}\n'
            self.assertEqual(ruff_format(text, root / "sub" / "t.py"), expected)
            self.assertEqual(ruff_format(text, None), text)

    def test_syntax_error(self) -> None:
        with self.assertRaises(FormatError) as caught:
            ruff_format("x = (\n", Path("t.py"))
        self.assertIn("t.py", str(caught.exception))
