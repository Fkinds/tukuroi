# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``tukuroi.core.testing``: the result of each case of a rule. The cases
of ``NoBadName`` are those that the characterization tests run with
``tukuroi test`` (``FAILING_PY`` in ``characterization_custom_rules.py``), with
what #21 decided for them, and the cases of the new engine (the code after
``ruff format``, positions).
"""

import ast
import unittest
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from ..core.rule import Invalid, Rule, Valid
from ..core.testing import RuleTestCase, add_rule_tests_to_module, generate_test_cases
from ..core.text import Position


class NoBadName(Rule):
    MESSAGE = "Use good, not bad."
    VALID = (
        "good = 1\n",
        Valid("bad = 1\n"),  # FAIL: reported
    )
    INVALID = (
        "bad = 1\n",  # FAIL: fixed, with no expected replacement (#21)
        Invalid("good = 1\n"),  # FAIL: not reported
        Invalid("bad = 1\n", expected_replacement="good = 1\n"),
        Invalid("bad = 1\n", expected_replacement="best = 1\n"),  # FAIL
        Invalid("bad = 1\n", "Use good, not bad.", "good = 1\n"),
        Invalid("bad = 1\n", "Other.", "good = 1\n"),  # FAIL
        Invalid(
            "bad = 1\n", expected_replacement="good = 1\n", position=Position(1, 0)
        ),
        Invalid(
            "bad = 1\n", expected_replacement="good = 1\n", position=Position(1, 1)
        ),  # FAIL
        Invalid("boom = 1\n"),  # ERROR: raises
        Invalid("bad = bad\n", expected_replacement="good = good\n"),  # reported twice
        Invalid(
            "bad = [1,2]\n", expected_replacement="good = [1, 2]\n"
        ),  # FAIL: compared as written, not formatted (#108)
        Invalid("bad = [1,2]\n", expected_replacement="good = [1,2]\n"),
        Invalid("\n    bad = 1\n", expected_replacement="\n    good = 1\n"),  # dedented
    )

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "boom":
            raise RuntimeError("boom")
        if node.id == "bad":
            self.report(node, replacement="good")


class NoUglyNameRule(Rule):
    MESSAGE = "Do not use ugly."
    INVALID = ("ugly = 1\n",)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "ugly":
            self.report(node)


class LongLine(Rule):
    MESSAGE = "Bad."
    INVALID = (
        Invalid(
            "bad = {'aaaa': 1, 'bbbb': 2}\n",
            expected_replacement="good = {'aaaa': 1, 'bbbb': 2}\n",
        ),
    )

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "bad":
            self.report(node, replacement="good")


def outcomes(rule: type[Rule]) -> dict[str, str]:
    """The result of each method of the test case of ``rule``."""
    (case,) = generate_test_cases([rule])
    result = unittest.TestResult()
    unittest.defaultTestLoader.loadTestsFromTestCase(case).run(result)
    found = {
        test._testMethodName: "ok"
        for test in unittest.defaultTestLoader.loadTestsFromTestCase(case)
    }  # type: ignore[attr-defined]
    for test, _ in result.failures:
        found[test._testMethodName] = "FAIL"  # type: ignore[attr-defined]
    for test, _ in result.errors:
        found[test._testMethodName] = "ERROR"  # type: ignore[attr-defined]
    return found


class GenerateTestCasesTest(TestCase):
    maxDiff = None

    def test_outcomes(self) -> None:
        expected = {
            "test_VALID_0": "ok",
            "test_VALID_1": "FAIL",
            "test_INVALID_0": "FAIL",
            "test_INVALID_1": "FAIL",
            "test_INVALID_2": "ok",
            "test_INVALID_3": "FAIL",
            "test_INVALID_4": "ok",
            "test_INVALID_5": "FAIL",
            "test_INVALID_6": "ok",
            "test_INVALID_7": "FAIL",
            "test_INVALID_8": "ERROR",
            "test_INVALID_9": "ok",
            "test_INVALID_10": "FAIL",
            "test_INVALID_11": "ok",
            "test_INVALID_12": "ok",
        }
        self.assertEqual(outcomes(NoBadName), expected)

    def test_rule_without_fix(self) -> None:
        self.assertEqual(outcomes(NoUglyNameRule), {"test_INVALID_0": "ok"})

    def test_compared_as_written(self) -> None:
        # Not formatted (#108): neither the settings of ruff nor its defaults.
        with TemporaryDirectory() as td, chdir(td):
            (Path(td) / "ruff.toml").write_text("line-length = 20\n")
            self.assertEqual(outcomes(LongLine), {"test_INVALID_0": "ok"})

    def test_classes(self) -> None:
        cases = generate_test_cases([NoBadName, NoUglyNameRule])
        self.assertEqual([c.__name__ for c in cases], ["NoBadName", "NoUglyNameRule"])
        self.assertEqual({c.__module__ for c in cases}, {"tukuroi.testing"})
        self.assertTrue(all(issubclass(c, RuleTestCase) for c in cases))
        self.assertEqual(cases[1].rule, NoUglyNameRule)

    def test_add_to_module(self) -> None:
        module: dict[str, object] = {"__package__": "pkg.tests"}
        add_rule_tests_to_module(module, [NoUglyNameRule])
        case = module["NoUglyNameRule"]
        self.assertEqual(case.__module__, "pkg.tests")  # type: ignore[attr-defined]
        no_package: dict[str, object] = {}
        add_rule_tests_to_module(no_package, [NoUglyNameRule])
        self.assertEqual(no_package["NoUglyNameRule"].__module__, "tukuroi.testing")  # type: ignore[attr-defined]

    def test_public_module(self) -> None:
        # The test cases say they are in tukuroi.testing: it has the same names.
        from .. import testing

        names = (RuleTestCase, add_rule_tests_to_module, generate_test_cases)
        self.assertEqual(
            (
                testing.RuleTestCase,
                testing.add_rule_tests_to_module,
                testing.generate_test_cases,
            ),
            names,
        )
