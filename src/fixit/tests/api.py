# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``fixit.api.fixit_bytes``, which runs the new engine (#21), for what the
characterization tests do not pin: the results it yields and what it returns,
the fixes sent back to it, the warning when the fixes do not converge, the
metrics, and the errors; and through the CLI, ``fix --interactive``, a syntax
error, and the exceptions that ``lint`` sends back from its process pool, or a
process of it that ends.
"""

import re
import sys
from collections.abc import Sequence
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from ..api import fixit_bytes
from ..core import loader
from ..core.text import Position, Range
from ..ftypes import Config, Error, Metrics, QualifiedRule, Result, Violation
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
# A rule that raises an exception whose str() fails.
MUTE = HEAD + (
    "\n\nclass Mute(Exception):\n"
    "    def __str__(self) -> str:\n"
    "        raise RuntimeError\n\n\n"
    "class Boom(Rule):\n"
    '    MESSAGE = "Boom."\n\n'
    "    def visit_Name(self, node: ast.Name) -> None:\n"
    "        raise Mute\n"
)
# A rule that raises, for each file, an exception that does not pickle: one
# whose __init__ takes other arguments than its args, one whose class the
# parent process cannot import, and one with an argument that does not pickle.
UNPICKLABLE = HEAD + (
    "import threading\n\n\n"
    "class Odd(Exception):\n"
    "    def __init__(self, a: str, b: int) -> None:\n"
    "        super().__init__(a)\n\n\n"
    "class Local(Exception):\n"
    "    pass\n\n\n"
    "class Boom(Rule):\n"
    '    MESSAGE = "Boom."\n\n'
    "    def visit_Module(self, node: ast.Module) -> None:\n"
    "        assert self.source.path\n"
    '        if self.source.path.stem == "odd":\n'
    '            raise Odd("odd", 1)\n'
    '        if self.source.path.stem == "local":\n'
    '            raise Local("local")\n'
    '        raise ValueError("lock", threading.Lock())\n'
)
# A rule that ends the process that lints exit.py.
EXIT = HEAD + (
    "import os\n\n\n"
    "class Exit(Rule):\n"
    '    MESSAGE = "Exit."\n\n'
    "    def visit_Module(self, node: ast.Module) -> None:\n"
    "        assert self.source.path\n"
    '        if self.source.path.stem == "exit":\n'
    "            os._exit(3)\n"
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
        # The file is wrong, not fixit: no traceback.
        message = "Syntax Error @ 1:5: unmatched ')'"
        self.assertEqual(result.error, Error("fixit.core.source.ParseError", message))
        self.assertIsNone(returned)

    def test_exception_in_a_rule(self) -> None:
        with files({"rules.py": BOOM}) as root:
            results, returned = run(config(root), "x = 1\n")
        [result] = results
        assert result.error is not None
        # The module of a built-in exception is not named, as in traceback.
        found = (result.error.type, result.error.message)
        self.assertEqual(found, ("RuntimeError", "boom"))
        self.assertIn('raise RuntimeError("boom")', result.error.traceback)
        self.assertIsNone(returned)

    def test_exception_whose_str_fails(self) -> None:
        with files({"rules.py": MUTE}) as root:
            results, _ = run(config(root), "x = 1\n")
        [result] = results
        assert result.error is not None
        self.assertRegex(result.error.type, r"^__fixit_local_\w+__\.rules\.Mute$")
        # As traceback writes it.
        self.assertEqual(result.error.message, "<exception str() failed>")

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

    def test_exceptions_from_the_process_pool(self) -> None:
        # Two files or more are linted in a process pool, which pickles the
        # result of each file (#64).
        pyproject = '[tool.fixit]\nroot = true\nenable = [".rules"]\n'
        files_ = {"pyproject.toml": pyproject, "rules.py": UNPICKLABLE}
        files_ |= {f"{name}.py": "x = 1\n" for name in ("local", "lock", "odd")}
        result = run_cli(files_, ["lint", "local.py", "lock.py", "odd.py"])
        found = sorted(
            re.findall(r"^(\S+): EXCEPTION: (.*)$", result.stdout, re.MULTILINE)
        )
        # The address of the lock changes.
        lock = "('lock', <unlocked _thread.lock object at "
        self.assertEqual(
            [(path, message.split("0x")[0]) for path, message in found],
            [("local.py", "local"), ("lock.py", lock), ("odd.py", "odd")],
        )
        # The tracebacks come back too.
        self.assertIn('raise Odd("odd", 1)', result.stdout)
        summary = "🛠️  3 files checked, 3 files with errors 🛠️"
        self.assertEqual(result.stderr.splitlines()[-1], summary)
        self.assertEqual(result.exit_code, 2)

    def test_a_process_of_the_pool_ends(self) -> None:
        # The pool breaks: the other files are linted again (#94).
        pyproject = '[tool.fixit]\nroot = true\nenable = [".rules"]\n'
        files_ = {"pyproject.toml": pyproject, "rules.py": EXIT}
        files_ |= {f"{name}.py": "x = 1\n" for name in ("a", "b", "exit")}
        result = run_cli(files_, ["lint", "a.py", "b.py", "exit.py"])
        message = "the process that linted the file exited with status 3"
        self.assertEqual(result.stdout, f"exit.py: EXCEPTION: {message}\n")
        summary = "🛠️  3 files checked, 1 file with errors 🛠️"
        self.assertEqual(result.stderr.splitlines()[-1], summary)
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
                rule = "fixit.rules.use_assert_in:UseAssertIn"
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
