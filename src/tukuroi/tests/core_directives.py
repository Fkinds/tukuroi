# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``tukuroi.core.directives``. The cases are a decision table of the
grammar (ISO/IEC/IEEE 29119-4): every comment of the characterization tests of
the old engine (``characterization_suppression.py``), with the result the
grammar of #21 gives, and the boundaries of each rule of the grammar.
"""

from unittest import TestCase

from ..core.directives import Directive, InvalidDirective, parse_directives

ALL = Directive("ignore", None)
FIXME_ALL = Directive("fixme", None)


def ignore(*names: str) -> Directive:
    return Directive("ignore", names)


def fixme(*names: str) -> Directive:
    return Directive("fixme", names)


class ParseDirectivesTest(TestCase):
    def test_without_names(self) -> None:
        cases = (
            ("# lint-ignore", ALL),
            ("# lint-fixme", FIXME_ALL),
            ("#lint-ignore", ALL),
            ("#\tlint-ignore", ALL),
            ("# lint-ignore   ", ALL),
        )
        for comment, directive in cases:
            with self.subTest(comment):
                self.assertEqual(parse_directives(comment), (directive,))

    def test_with_names(self) -> None:
        cases = (
            ("# lint-ignore: UseAssertIn", ignore("UseAssertIn")),
            ("# lint-fixme: UseAssertIn", fixme("UseAssertIn")),
            ("# lint-ignore:UseAssertIn", ignore("UseAssertIn")),
            ("# lint-ignore:  UseAssertIn", ignore("UseAssertIn")),
            ("# lint-ignore : NoNamedTuple", ignore("NoNamedTuple")),
            ("# lint-ignore: A, B", ignore("A", "B")),
            ("# lint-ignore: A,B", ignore("A", "B")),
            ("# lint-ignore: A,  B", ignore("A", "B")),
            ("# lint-ignore: A ,B", ignore("A", "B")),
            ("# lint-ignore: UseAssertInRule", ignore("UseAssertInRule")),
            ("# lint-ignore: useassertin", ignore("useassertin")),
            ("# lint-ignore: 名前", ignore("名前")),
        )
        for comment, directive in cases:
            with self.subTest(comment):
                self.assertEqual(parse_directives(comment), (directive,))

    def test_invalid(self) -> None:
        cases = (
            # (comment, text of the part)
            ("# lint-ignore:", "lint-ignore:"),
            ("# lint-ignore: , X", "lint-ignore: , X"),
            ("# lint-ignore: X,", "lint-ignore: X,"),
            ("# lint-ignore: X Y", "lint-ignore: X Y"),
            ("# lint-ignore: X because Y", "lint-ignore: X because Y"),
            ("# lint-ignore: tukuroi.rules:X", "lint-ignore: tukuroi.rules:X"),
            ("# lint-ignore: 1X", "lint-ignore: 1X"),
            ("# lint-ignore X", "lint-ignore X"),
            ("# lint-ignore\tX", "lint-ignore\tX"),
            ("# lint-ignore(X)", "lint-ignore(X)"),
            ("# lint-fixme-later: X", "lint-fixme-later: X"),
            ("# lint-ignore::X", "lint-ignore::X"),
        )
        for comment, text in cases:
            with self.subTest(comment):
                self.assertEqual(parse_directives(comment), (InvalidDirective(text),))

    def test_not_a_directive(self) -> None:
        comments = (
            "# lint-ignored",
            "# lint-fixmeX",
            "# lint-ignore_x",
            "# Lint-Ignore",
            "# LINT-IGNORE",
            "# lint_ignore",
            "# see lint-ignore",
            "# other",
            "#",
            "# lint-ignoreあ",
        )
        for comment in comments:
            with self.subTest(comment):
                self.assertEqual(parse_directives(comment), ())

    def test_each_part_of_a_comment(self) -> None:
        cases = (
            ("# noqa  # lint-ignore", (ALL,)),
            ("# type: ignore # lint-fixme: UseAssertIn", (fixme("UseAssertIn"),)),
            ("# lint-ignore: X  # because Y", (ignore("X"),)),
            ("# lint-ignore: A # lint-ignore: B", (ignore("A"), ignore("B"))),
            ("# lint-ignore: A  # lint-ignore", (ignore("A"), ALL)),
            ("# lint-ignore: A, # lint-fixme", (InvalidDirective("lint-ignore: A,"), FIXME_ALL)),
            ("# a # b # lint-ignore", (ALL,)),
        )  # fmt: skip
        for comment, directives in cases:
            with self.subTest(comment):
                self.assertEqual(parse_directives(comment), directives)


class DirectiveCoversTest(TestCase):
    def test_covers(self) -> None:
        cases = (
            # (directive, rule, covers)
            (ALL, "UseAssertIn", True),
            (FIXME_ALL, "UseAssertIn", True),
            (ignore("UseAssertIn"), "UseAssertIn", True),
            (ignore("UseAssertInRule"), "UseAssertIn", True),
            (ignore("NoNamedTuple", "UseAssertIn"), "UseAssertIn", True),
            (ignore("NoNamedTuple"), "UseAssertIn", False),
            (ignore("useassertin"), "UseAssertIn", False),
            (ignore("useassertinRule"), "UseAssertIn", False),
            (ignore("USEASSERTIN"), "UseAssertIn", False),
            (ignore("useAssertIn"), "UseAssertIn", False),
            (ignore("UseAssertInRuleRule"), "UseAssertIn", False),
            (ignore("Rule"), "UseAssertIn", False),
            (ignore("UseAssert"), "UseAssertIn", False),
            (ignore("UseAssertIns"), "UseAssertIn", False),
            (ignore("UseAssertInRuleRule"), "UseAssertInRule", True),
        )
        for directive, rule, covers in cases:
            with self.subTest(directive=directive, rule=rule):
                self.assertIs(directive.covers(rule), covers)
