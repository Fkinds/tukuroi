# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``tukuroi.core.rule``. The cases are decision tables (ISO/IEC/IEEE
29119-4) of the names of rules and of their ``visit_`` methods, and of the
arguments of ``report`` (message, replacement, edits).
"""

import ast
from unittest import TestCase

from ..core.edits import Edit
from ..core.names import ImportTable
from ..core.rule import Invalid, Report, Rule, Valid
from ..core.source import Source
from ..core.text import Position, Span


def make(rule: type[Rule], text: str) -> Rule:
    source = Source.from_text(text)
    return rule(source, ImportTable.from_tree(source.tree))


class NoBadName(Rule):
    MESSAGE = "Use good, not bad."

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "bad":
            self.report(node, replacement="good")


class NoUglyNameRule(Rule):
    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "ugly":
            self.report(node, "Do not use ugly.")


class EveryStatement(Rule):
    MESSAGE = "A statement."

    def visit_stmt(self, node: ast.stmt) -> None:
        self.report(node)


class AlsoCalls(EveryStatement):
    def visit_Call(self, node: ast.Call) -> None:
        self.report(node)


class RuleCasesTest(TestCase):
    def test_valid_and_invalid(self) -> None:
        self.assertEqual(Valid("x = 1\n").code, "x = 1\n")
        invalid = Invalid("bad = 1\n")
        self.assertEqual(
            (invalid.expected_message, invalid.expected_replacement, invalid.position),
            (None, None, None),
        )
        full = Invalid("bad = 1\n", "m", "good = 1\n", Position(1, 0))
        self.assertEqual(full.expected_replacement, "good = 1\n")
        self.assertEqual(full.position, Position(1, 0))

    def test_defaults_of_a_rule(self) -> None:
        self.assertEqual((Rule.MESSAGE, Rule.VALID, Rule.INVALID), ("", (), ()))


class RuleNameTest(TestCase):
    def test_name(self) -> None:
        cases = (
            (NoBadName, "NoBadName"),
            (NoUglyNameRule, "NoUglyName"),
            (type("RuleRule", (Rule,), {}), "Rule"),
            (type("Ruler", (Rule,), {}), "Ruler"),
        )
        for rule, name in cases:
            with self.subTest(rule.__name__):
                self.assertEqual(rule.name(), name)


class RuleVisitsTest(TestCase):
    def test_visits(self) -> None:
        cases = (
            (Rule, {}),
            (NoBadName, {ast.Name: "visit_Name"}),
            (EveryStatement, {ast.stmt: "visit_stmt"}),
            (AlsoCalls, {ast.stmt: "visit_stmt", ast.Call: "visit_Call"}),
        )
        for rule, visits in cases:
            with self.subTest(rule.__name__):
                self.assertEqual(dict(rule.visits()), visits)

    def test_no_such_node(self) -> None:
        for name in ("visit_Foo", "visit_Num", "visit_parse", "visit_"):
            with self.subTest(name), self.assertRaises(TypeError):
                type("Wrong", (Rule,), {name: lambda self, node: None})

    def test_visits_cannot_change(self) -> None:
        with self.assertRaises(TypeError):
            NoBadName.visits()[ast.Call] = "visit_Call"  # type: ignore[index]


class RuleReportTest(TestCase):
    def test_message(self) -> None:
        rule = make(NoUglyNameRule, "ugly = 1\n")
        name = rule.source.tree.body[0].targets[0]  # type: ignore[attr-defined]
        cases = (
            ("given", NoBadName, "Other.", "Other."),
            ("MESSAGE", NoBadName, None, "Use good, not bad."),
            ("given, no MESSAGE", NoUglyNameRule, "Given.", "Given."),
        )
        for label, cls, message, expected in cases:
            with self.subTest(label):
                rule = make(cls, "ugly = 1\n")
                rule.report(name, message)
                self.assertEqual(rule.reports[-1].message, expected)

    def test_no_message(self) -> None:
        # An empty message is not the MESSAGE of the rule: it is a mistake.
        for cls, message in (
            (NoUglyNameRule, None),
            (NoUglyNameRule, ""),
            (NoBadName, ""),
        ):
            with self.subTest(cls.__name__, message=message):
                rule = make(cls, "ugly = 1\n")
                with self.assertRaises(ValueError):
                    rule.report(rule.source.tree.body[0], message)

    def test_fix(self) -> None:
        text = "x = 'é'; bad = 1\n"
        span = Span(9, 12)
        cases = (
            # (label, keyword arguments of report, edits of the report)
            ("none", {}, ()),
            ("replacement", {"replacement": "good"}, (Edit(span, "good"),)),
            ("empty replacement", {"replacement": ""}, (Edit(span, ""),)),
            ("edits, sorted", {"edits": [Edit(Span(12, 12), "!"), Edit(span, "g")]}, (Edit(span, "g"), Edit(Span(12, 12), "!"))),
        )  # fmt: skip
        for label, arguments, edits in cases:
            with self.subTest(label):
                rule = make(NoBadName, text)
                node = rule.source.tree.body[1].targets[0]  # type: ignore[attr-defined]
                rule.report(node, **arguments)  # type: ignore[arg-type]
                expected = Report(
                    "NoBadName", span, Position(1, 9), "Use good, not bad.", edits
                )
                self.assertEqual(rule.reports, [expected])

    def test_wrong_fix(self) -> None:
        rule = make(NoBadName, "bad = 1\n")
        node = rule.source.tree.body[0].targets[0]  # type: ignore[attr-defined]
        overlapping = [Edit(Span(0, 2), "a"), Edit(Span(1, 3), "b")]
        cases = (
            ("replacement and edits", {"replacement": "good", "edits": [Edit(Span(0, 3), "g")]}),
            ("overlapping edits", {"edits": overlapping}),
        )  # fmt: skip
        for label, arguments in cases:
            with self.subTest(label), self.assertRaises(ValueError):
                rule.report(node, **arguments)  # type: ignore[arg-type]
        self.assertEqual(rule.reports, [])

    def test_reports_in_their_order(self) -> None:
        rule = make(EveryStatement, "x = 1\nif y:\n    z = 2\n")
        for node in ast.walk(rule.source.tree):
            if isinstance(node, ast.stmt):
                rule.report(node)
        positions = [r.position for r in rule.reports]
        self.assertEqual(positions, [Position(1, 0), Position(2, 0), Position(3, 4)])

    def test_module(self) -> None:
        rule = make(EveryStatement, "x = 1\n")
        rule.report(rule.source.tree)
        self.assertEqual(rule.reports[0].span, Span(0, 6))
        self.assertEqual(rule.reports[0].position, Position(1, 0))

    def test_an_instance_for_each_file(self) -> None:
        first, second = make(NoBadName, "bad = 1\n"), make(NoBadName, "x = 1\n")
        first.report(first.source.tree.body[0])
        self.assertEqual((len(first.reports), len(second.reports)), (1, 0))
        self.assertEqual(second.source.text, "x = 1\n")
        self.assertIsInstance(second.imports, ImportTable)
