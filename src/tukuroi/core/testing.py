# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of rules from their ``VALID`` and ``INVALID`` cases (#21).

Each rule becomes a ``unittest.TestCase`` named after it, with a method for
each case: ``test_VALID_0``, ``test_INVALID_0``. A valid case must have no
report. An invalid case must have a report, with the message and the position
given; when the rule fixes it, the case must give the code after the fix, as
the engine writes it: after all the rounds of fixes and ``ruff format`` with the
default settings of ruff, wherever the tests run.
"""

import re
import textwrap
import unittest
from collections.abc import Callable, MutableMapping, Sequence
from pathlib import Path
from typing import Any, ClassVar

from .engine import fix, lint
from .format import ruff_format
from .rule import Invalid, Rule, Valid
from .source import Source

# The module that the test cases say they are in: the public name.
MODULE = "tukuroi.testing"


def _dedent(code: str) -> str:
    """``code`` without a line end at its start, and dedented."""
    return textwrap.dedent(re.sub(r"\A\n", "", code))


def _format(text: str, path: Path | None) -> str:
    return ruff_format(text, path, isolated=True)


class RuleTestCase(unittest.TestCase):
    """The test case of a rule; ``rule`` is set on each subclass."""

    rule: ClassVar[type[Rule]]

    def check(self, case: Valid | Invalid) -> None:
        source = Source.from_text(_dedent(case.code))
        reports = lint(source, [self.rule]).reports
        if isinstance(case, Valid):
            found = "\n".join(f"{r.position}: {r.message}" for r in reports)
            self.assertEqual(reports, (), f"Expected no report. Found:\n{found}")
            return
        self.assertTrue(reports, f"Expected a report for:\n{case.code}")
        for report in reports:
            if case.position is not None:
                self.assertEqual(report.position, case.position)
            if case.expected_message is not None:
                self.assertEqual(report.message, case.expected_message)
        if case.expected_replacement is None:
            fixed = [r for r in reports if r.edits]
            message = "The rule fixes this case: give its expected_replacement."
            self.assertFalse(fixed, message)
            return
        result = fix(source, [self.rule], formatter=_format)
        self.assertMultiLineEqual(result.text, _dedent(case.expected_replacement))


def generate_test_cases(rules: Sequence[type[Rule]]) -> list[type[RuleTestCase]]:
    """A test case for each of ``rules``, with a method for each of its cases."""
    classes: list[type[RuleTestCase]] = []
    for rule in rules:
        methods: dict[str, Callable[..., None]] = {}
        for kind, cases in (("VALID", rule.VALID), ("INVALID", rule.INVALID)):
            for index, case in enumerate(cases):
                if isinstance(case, str):
                    case = Valid(case) if kind == "VALID" else Invalid(case)

                def method(self: RuleTestCase, case: Valid | Invalid = case) -> None:
                    self.check(case)

                method.__name__ = f"test_{kind}_{index}"
                methods[method.__name__] = method
        attributes: dict[str, Any] = {"rule": rule, "__module__": MODULE, **methods}
        classes.append(type(rule.__name__, (RuleTestCase,), attributes))
    return classes


def add_rule_tests_to_module(
    module: MutableMapping[str, Any], rules: Sequence[type[Rule]]
) -> None:
    """
    Add the test cases of ``rules`` to ``module`` (``globals()`` of a test
    module), for unittest to find them there.
    """
    package = module.get("__package__")
    for case in generate_test_cases(rules):
        if isinstance(package, str):
            case.__module__ = package
        module[case.__name__] = case
