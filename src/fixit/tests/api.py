# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``fixit.api.fixit_bytes``, which runs the new engine (#21), for what the
characterization tests do not pin: the results it yields and what it returns,
the fixes sent back to it, the warning when the fixes do not converge, and the
metrics; and through the CLI, ``fix --interactive`` and a syntax error.
"""

import sys
from collections.abc import Sequence
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from ..api import fixit_bytes
from ..core import loader
from ..core.source import ParseError
from ..core.text import Position, Range
from ..ftypes import Config, Metrics, QualifiedRule, Result, Violation
from ..util import capture, chdir
from .characterization_cli import invoke
from .characterization_custom_rules import run as run_cli
from .characterization_suppression import MESSAGES
from .core_loader import HEAD, files

UI = "UseAssertIn"
SI = "NoStaticIfCondition"
NT = "NoNamedTuple"

SOURCE = "x = 1\nself.assertTrue(a in b)\nif True:\n    pass\n"
FIXED = "x = 1\nself.assertIn(a, b)\nif True:\n    pass\n"
DIFF = (
    "--- a/t.py\n+++ b/t.py\n@@ -1,3 +1,3 @@\n x = 1\n"
    "-self.assertTrue(a in b)\n+self.assertIn(a, b)\n if True:\n"
)
# A rule whose fix never converges: each round adds a line at the start.
GROW = HEAD + (
    "from fixit.core.edits import Edit\n"
    "from fixit.core.text import Span\n\n\n"
    "class Grow(Rule):\n"
    '    MESSAGE = "Grow."\n\n'
    "    def visit_Module(self, node: ast.Module) -> None:\n"
    '        self.report(node, edits=[Edit(Span(0, 0), "x = 1\\n")])\n'
)
# A rule whose fix changes nothing.
SAME = HEAD + (
    "\n\nclass Same(Rule):\n"
    '    MESSAGE = "Same."\n\n'
    "    def visit_Name(self, node: ast.Name) -> None:\n"
    "        self.report(node, replacement=node.id)\n"
)
BOOM = HEAD + (
    "\n\nclass Boom(Rule):\n"
    '    MESSAGE = "Boom."\n\n'
    "    def visit_Name(self, node: ast.Name) -> None:\n"
    '        raise RuntimeError("boom")\n'
)


def config(root: Path, *rules: str) -> Config:
    """A config of ``root`` with the built-in ``rules``, or ``.rules`` if none."""
    enable = [QualifiedRule("fixit.rules", rule) for rule in rules]
    return Config(
        path=root / "t.py",
        root=root,
        enable=enable or [QualifiedRule(".rules", None, ".", root)],
    )


def run(
    config: Config,
    source: str,
    *,
    autofix: bool = False,
    answers: Sequence[bool] = (),
    metrics: list[Metrics] | None = None,
) -> tuple[list[Result], bytes | None]:
    """
    The results of ``fixit_bytes`` on ``source``, with ``answers`` sent back for
    its violations, and what it returns.
    """
    generator = capture(
        fixit_bytes(
            config.path,
            source.encode(),
            config=config,
            autofix=autofix,
            metrics_hook=None if metrics is None else metrics.append,
        )
    )
    results, pending = [], list(answers)
    for result in generator:
        results.append(result)
        if result.violation and pending:
            generator.respond(pending.pop(0))
    return results, generator.result


class FixitBytesTest(TestCase):
    maxDiff = None

    def setUp(self) -> None:
        loader._WARNED.clear()

    def test_violations(self) -> None:
        root = Path("/repo")
        results, returned = run(config(root, UI, SI), SOURCE)
        message = MESSAGES[UI].removesuffix(" (has autofix)")
        ui = Violation(UI, Range(Position(2, 0), Position(2, 23)), message, True, DIFF)
        self.assertEqual(results[0], Result(root / "t.py", ui))
        si = results[1].violation
        assert isinstance(si, Violation)
        self.assertEqual((si.rule_name, si.autofixable, si.diff), (SI, False, ""))
        self.assertEqual(si.range, Range(Position(3, 0), Position(4, 8)))
        # Nothing applied: no last result, and nothing returned.
        self.assertEqual(len(results), 2)
        self.assertIsNone(returned)

    def test_clean(self) -> None:
        root = Path("/repo")
        cases = (
            # (label, config)
            ("no violation", config(root, UI)),
            ("no rule", Config(path=root / "t.py", root=root, enable=[])),
        )
        for label, config_ in cases:
            with self.subTest(label):
                results, returned = run(config_, "x = 1\n", autofix=True)
                self.assertEqual(results, [Result(root / "t.py", None)])
                self.assertIsNone(returned)

    def test_fixes_applied(self) -> None:
        root = Path("/repo")
        two = "self.assertTrue(a in b)\nself.assertTrue(c in d)\n"
        cases = (
            # (label, source, autofix, answers, applied, returned)
            ("autofix", SOURCE, True, (), 1, FIXED),
            ("autofix, 2 fixes", two, True, (), 2, "self.assertIn(a, b)\nself.assertIn(c, d)\n"),
            ("yes to the 2nd", two, False, (False, True), 1, "self.assertTrue(a in b)\nself.assertIn(c, d)\n"),
            ("yes to the violation without a fix", SOURCE, False, (False, True), 0, None),
            ("no to both", two, False, (False, False), 0, None),
        )  # fmt: skip
        for label, source, autofix, answers, applied, fixed in cases:
            with self.subTest(label):
                results, returned = run(
                    config(root, UI, SI), source, autofix=autofix, answers=answers
                )
                violations = [r for r in results if r.violation]
                last = [Result(root / "t.py", None, applied=applied)] if applied else []
                self.assertEqual(results[len(violations) :], last)
                self.assertEqual(returned, None if fixed is None else fixed.encode())

    def test_fixes_that_overlap_when_sent_back(self) -> None:
        # The fix of the inner call is in the range of the outer one: sent back,
        # both are applied in one round, which skips the inner one. With
        # autofix, the inner one is applied in the next round.
        source = "self.assertTrue(self.assertTrue(a in b) in c)\n"
        cases = (
            # (autofix, answers, applied, returned)
            (False, (True, True), 1, "self.assertIn(self.assertTrue(a in b), c)\n"),
            (True, (), 2, "self.assertIn(self.assertIn(a, b), c)\n"),
        )
        for autofix, answers, applied, fixed in cases:
            with self.subTest(autofix=autofix):
                results, returned = run(
                    config(Path("/repo"), UI), source, autofix=autofix, answers=answers
                )
                self.assertEqual(results[-1].applied, applied)
                self.assertEqual(returned, fixed.encode())

    def test_fix_that_changes_nothing(self) -> None:
        with files({"rules.py": SAME}) as root:
            results, returned = run(config(root), "x = 1\n", autofix=True)
        self.assertEqual([r.applied for r in results], [0])
        self.assertIsNone(returned)

    def test_syntax_error(self) -> None:
        results, returned = run(config(Path("/repo"), UI), "print)\n")
        [result] = results
        assert result.error is not None
        error, traceback = result.error
        assert isinstance(error, ParseError)
        self.assertEqual((error.position, traceback), (Position(1, 5), ""))
        self.assertIsNone(returned)

    def test_exception_in_a_rule(self) -> None:
        with files({"rules.py": BOOM}) as root:
            results, returned = run(config(root), "x = 1\n")
        [result] = results
        assert result.error is not None
        error, traceback = result.error
        self.assertEqual(str(error), "boom")
        self.assertIn('raise RuntimeError("boom")', traceback)
        self.assertIsNone(returned)

    def test_fixes_that_do_not_converge(self) -> None:
        with (
            files({"rules.py": GROW}) as root,
            chdir(root),
            self.assertLogs("fixit.api", "WARNING") as logs,
        ):
            results, returned = run(config(root), "y = 2\n", autofix=True)
        warning = "t.py: fixes did not converge after 100 rounds"
        self.assertEqual([r.getMessage() for r in logs.records], [warning])
        self.assertEqual(results[-1].applied, 100)
        self.assertEqual(returned, ("x = 1\n" * 100 + "y = 2\n").encode())

    def test_metrics(self) -> None:
        metrics: list[Metrics] = []
        source = SOURCE + "self.assertTrue(c in d)\n"
        run(config(Path("/repo"), UI, SI, NT), source, metrics=metrics)
        [found] = metrics
        duration = found.pop("Duration.Total")
        self.assertIsInstance(duration, int)
        self.assertGreaterEqual(duration, 0)
        expected = {
            "Count.Total": 3,
            "Count.NoNamedTuple": 0,
            "FixCount.NoNamedTuple": 0,
            "Count.NoStaticIfCondition": 1,
            "FixCount.NoStaticIfCondition": 0,
            "Count.UseAssertIn": 2,
            "FixCount.UseAssertIn": 2,
        }
        self.assertEqual(found, expected)


class CommandTest(TestCase):
    maxDiff = None

    def fix(self, source: str, answers: str, *rules: str) -> tuple[str, str]:
        """The file after ``fix --interactive`` with ``answers``, and stderr."""
        enable = ", ".join(f'"fixit.rules:{rule}"' for rule in rules)
        pyproject = f'[tool.fixit]\nroot = true\ndisable = ["fixit.rules"]\nenable = [{enable}]\n'
        files_ = {"pyproject.toml": pyproject, "t.py": source}
        result = invoke(files_, ["fix", "--interactive", "t.py"], stdin=answers)
        self.assertEqual(result.exit_code, 0)
        return result.files["t.py"], result.stderr.splitlines()[-1]

    def test_syntax_error_is_one_line(self) -> None:
        files_ = {"pyproject.toml": "[tool.fixit]\nroot = true\n", "b.py": "print)\n"}
        result = invoke(files_, ["lint", "b.py"])
        self.assertEqual(
            result.stdout, "b.py: EXCEPTION: Syntax Error @ 1:5: unmatched ')'\n"
        )
        self.assertEqual(result.exit_code, 2)

    def test_validate_config(self) -> None:
        pyproject = (
            '[tool.fixit]\nroot = true\nenable = [".rules:Bad", ".rules:Nope"]\n'
        )
        rules = HEAD + "\n\nclass Bad(Rule):\n    MESSAGE = 'm'\n"
        files_ = {"pyproject.toml": pyproject, "rules.py": rules}
        # `run` writes no .pyc, and forgets the modules imported.
        result = run_cli(files_, ["validate-config", "pyproject.toml"])
        # Printed with pprint, or rich when installed: compare without the breaks.
        printed = " ".join(result.stdout.replace("'", "").split())
        error = "CollectionError: could not find rule .rules:Nope in"
        expected = f"Failed to import rule `.rules:Nope` for global enable: {error}"
        self.assertIn(expected, printed)
        self.assertNotIn(".rules:Bad", printed)
        self.assertEqual(result.exit_code, -1)

    def test_debug(self) -> None:
        files_ = {"pyproject.toml": "[tool.fixit]\nroot = true\n", "t.py": "x = 1\n"}
        # rich prints when it is installed; None makes its import fail.
        for label, modules in (("as installed", {}), ("without rich", {"rich": None})):
            with self.subTest(label), patch.dict(sys.modules, modules):
                result = invoke(files_, ["debug", "t.py"])
                self.assertEqual(result.exit_code, 0, result.exception)
                rule = "fixit.core.rules.use_assert_in:UseAssertIn"
                self.assertIn(rule, result.stdout)

    def test_answers(self) -> None:
        two = "self.assertTrue(a in b)\nself.assertTrue(c in d)\n"
        summary = "🛠️  1 file checked, 1 file with errors, {} 🛠️"
        cases = (
            # (label, answers, file after, summary)
            ("y, y", "y\ny\n", "self.assertIn(a, b)\nself.assertIn(c, d)\n", "2 auto-fixes available, 2 fixes applied"),
            ("n, y", "n\ny\n", "self.assertTrue(a in b)\nself.assertIn(c, d)\n", "2 auto-fixes available, 1 fix applied"),
            ("n, n", "n\nn\n", two, "2 auto-fixes available"),
            # Quit: nothing applied to the file, even the fix answered first.
            ("y, q", "y\nq\n", two, "2 auto-fixes available"),
        )  # fmt: skip
        for label, answers, fixed, counts in cases:
            with self.subTest(label):
                after, last = self.fix(two, answers, UI)
                self.assertEqual(after, fixed)
                self.assertEqual(last, summary.format(counts))


class PublicNamesTest(TestCase):
    def test_rule_api(self) -> None:
        # The names to write a rule with come from the new engine (#21).
        import fixit
        from fixit.core import edits, rule, text

        found = (fixit.Rule, fixit.Valid, fixit.Invalid, fixit.Edit, fixit.Position)
        self.assertEqual(
            found, (rule.Rule, rule.Valid, rule.Invalid, edits.Edit, text.Position)
        )
        self.assertTrue(all(hasattr(fixit, name) for name in fixit.__all__))
