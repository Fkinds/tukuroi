# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests that run the CLI on ``examples/`` (#21): the custom rules of
``teambread``, the built-in rules on ``basic``, and ``noop.py``. Each runs on a
copy of the example, as ``tukuroi test`` imports its rules. They need the source
tree, and skip without it.
"""

from pathlib import Path
from unittest import TestCase, skipUnless

from .characterization_cli import Run
from .characterization_custom_rules import run
from .characterization_suppression import MESSAGES

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"
HOLLYWOOD = "It's underproved! (has autofix)"


def example(name: str) -> dict[str, str]:
    """The files of ``examples/<name>``, by their path in it."""
    root = EXAMPLES / name
    return {
        path.relative_to(root).as_posix(): path.read_text()
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def summary(result: Run) -> str:
    return result.stderr.splitlines()[-1]


@skipUnless(EXAMPLES.is_dir(), "no examples/ next to the package")
class ExamplesTest(TestCase):
    maxDiff = None

    def test_teambread_lint(self) -> None:
        result = run(example("teambread"), ["lint", "sourdough/baker.py"])
        found = f"sourdough/baker.py@7:11 HollywoodName: {HOLLYWOOD}\n"
        self.assertEqual(result.stdout, found)
        self.assertEqual(result.exit_code, 1)

    def test_teambread_fix(self) -> None:
        result = run(example("teambread"), ["fix", "--automatic", "sourdough/baker.py"])
        self.assertIn('name = "Mary"\n', result.files["sourdough/baker.py"])
        self.assertEqual(result.exit_code, 0)

    def test_teambread_rule_tests(self) -> None:
        result = run(example("teambread"), ["test", ".rules"])
        self.assertIn("\nRan 4 tests in ", result.stderr)
        self.assertEqual(summary(result), "OK")
        self.assertEqual(result.exit_code, 0)

    def test_noop_rule_tests(self) -> None:
        result = run({"noop.py": (EXAMPLES / "noop.py").read_text()}, ["test", ".noop"])
        self.assertEqual(summary(result), "OK")
        self.assertEqual(result.exit_code, 0)

    def test_basic_lint(self) -> None:
        files = example("basic") | {"pyproject.toml": "[tool.fixit]\nroot = true\n"}
        result = run(files, ["lint", "custom_object.py"])
        reported = [
            ("12:8", "UseAssertIn"),
            ("13:8", "NoStaticIfCondition"),
            ("14:12", "NoAssertTrueForComparisons"),
            # Suppressed by the directives, but for the one of another rule.
            ("18:8", "UseAssertIn"),
        ]
        expected = "".join(
            f"custom_object.py@{p} {r}: {MESSAGES[r]}\n" for p, r in reported
        )
        self.assertEqual(result.stdout, expected)
        self.assertEqual(result.exit_code, 1)
