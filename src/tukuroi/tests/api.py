# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``tukuroi.api.fixit_bytes``, which runs the new engine (#21), for what the
characterization tests do not pin: the results it yields and what it returns,
the fixes sent back to it, the warning when the fixes do not converge, the
metrics, and the errors; and through the CLI, ``fix --interactive``, a syntax
error, and the exceptions that ``lint`` sends back from its process pool, or a
process of it that ends.
"""

import importlib
import io
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import click
from click.testing import CliRunner
from moreorless.click import echo_color_precomputed_diff

from ..api import (
    _echo_diff,
    fixit_bytes,
    fixit_file,
    fixit_paths,
    fixit_stdin,
    print_result,
)
from ..config import ConfigError, RulesOptionError, generate_config
from ..core import loader
from ..core.loader import load as load_core_rules
from ..core.text import Position, Range
from ..ftypes import (
    STDIN,
    Config,
    Error,
    Metrics,
    Options,
    QualifiedRule,
    Result,
    Violation,
)
from ..util import capture, chdir
from .characterization_cli import invoke, toml_error
from .characterization_custom_rules import run as run_cli
from .characterization_suppression import MESSAGES
from .core_loader import HEAD, files

UI = "UseAssertIn"
SI = "NoStaticIfCondition"
NT = "NoNamedTuple"
NOPE = '[tool.fixit]\nroot = true\nenable = ["tukuroi.rules:Nope"]\n'

SOURCE = "x = 1\nself.assertTrue(a in b)\nif True:\n    pass\n"
FIXED = "x = 1\nself.assertIn(a, b)\nif True:\n    pass\n"
# The path of the file as the violation shows it, relative to the current
# directory (#40).
DIFF = (
    "--- a/repo/t.py\n+++ b/repo/t.py\n@@ -1,3 +1,3 @@\n x = 1\n"
    "-self.assertTrue(a in b)\n+self.assertIn(a, b)\n if True:\n"
)
# A rule whose fix never converges: each round adds a line at the start.
GROW = HEAD + (
    "from tukuroi.core.edits import Edit\n"
    "from tukuroi.core.text import Span\n\n\n"
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
    enable = [QualifiedRule("tukuroi.rules", rule) for rule in rules]
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
        root = Path.cwd() / "repo"
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

    def test_rule_that_cannot_be_loaded(self) -> None:
        # The error of the file, without a traceback: the config is not known
        # here, only its rules (#40). No rule runs.
        root = Path("/repo")
        nope = QualifiedRule("tukuroi.rules", "Nope")
        config_ = Config(path=root / "t.py", root=root, enable=[nope])
        results, returned = run(config_, SOURCE, autofix=True)
        error = Error(
            "tukuroi.config.ConfigError", "could not find rule tukuroi.rules:Nope"
        )
        self.assertEqual(results, [Result(root / "t.py", None, error)])
        self.assertIsNone(returned)

    def test_fixes_applied(self) -> None:
        root = Path("/repo")
        two = "self.assertTrue(a in b)\nself.assertTrue(c in d)\n"
        cases = (
            # (label, source, autofix, answers, applied, remaining, returned)
            # The violation of NoStaticIfCondition, which has no fix, remains.
            ("autofix", SOURCE, True, (), 1, 1, FIXED),
            ("autofix, 2 fixes", two, True, (), 2, 0, "self.assertIn(a, b)\nself.assertIn(c, d)\n"),
            ("yes to the 2nd", two, False, (False, True), 1, 1, "self.assertTrue(a in b)\nself.assertIn(c, d)\n"),
            ("yes to the violation without a fix", SOURCE, False, (False, True), 0, 0, None),
            ("no to both", two, False, (False, False), 0, 0, None),
        )  # fmt: skip
        for label, source, autofix, answers, applied, remaining, fixed in cases:
            with self.subTest(label):
                results, returned = run(
                    config(root, UI, SI), source, autofix=autofix, answers=answers
                )
                violations = [r for r in results if r.violation]
                last = [
                    Result(root / "t.py", None, applied=applied, remaining=remaining)
                ][:applied]
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
        # The file is wrong, not tukuroi: no traceback.
        message = "Syntax Error @ 1:5: unmatched ')'"
        # With its position, which the LSP shows it at (#96).
        error = Error("tukuroi.core.source.ParseError", message, "", Position(1, 5))
        self.assertEqual(result.error, error)
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
            self.assertLogs("tukuroi.api", "WARNING") as logs,
        ):
            results, returned = run(config(root), "y = 2\n", autofix=True)
        warning = "t.py: fixes did not converge after 100 rounds"
        self.assertEqual([r.getMessage() for r in logs.records], [warning])
        self.assertEqual(results[-1].applied, 100)
        # The fixed text, linted again, still has the violation: one reported
        # and 100 fixes applied do not tell it (#40).
        self.assertEqual(results[-1].remaining, 1)
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

    def fix(self, source: str, answers: str, *rules: str) -> tuple[str, str, int]:
        """
        The file after ``fix --interactive`` with ``answers``, the last line of
        stderr, and the exit code.
        """
        enable = ", ".join(f'"tukuroi.rules:{rule}"' for rule in rules)
        pyproject = f'[tool.fixit]\nroot = true\ndisable = ["tukuroi.rules"]\nenable = [{enable}]\n'
        files_ = {"pyproject.toml": pyproject, "t.py": source}
        result = invoke(files_, ["fix", "--interactive", "t.py"], stdin=answers)
        return result.files["t.py"], result.stderr.splitlines()[-1], result.exit_code

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
        # As the other commands show an error of the config, with 2 (#100):
        # it was printed with pprint or rich, on stdout, with -1.
        error = f"could not find rule .rules:Nope in {result.root}"
        self.assertEqual(result.stderr, f"Error: pyproject.toml: enable: {error}\n")
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.exit_code, 2)
        with self.subTest("valid"):
            files_["pyproject.toml"] = pyproject.replace(', ".rules:Nope"', "")
            result = run_cli(files_, ["validate-config", "pyproject.toml"])
            self.assertEqual((result.stdout, result.stderr), ("", ""))
            self.assertEqual(result.exit_code, 0)
        with self.subTest("directory"):
            result = run_cli(files_, ["validate-config", "."])
            # The usage lines above it come from click.
            error = "\nError: Invalid value for 'PATH': File '.' is a directory.\n"
            self.assertTrue(result.stderr.endswith(error), result.stderr)
            self.assertEqual(result.exit_code, 2)

    def test_debug(self) -> None:
        files_ = {"pyproject.toml": "[tool.fixit]\nroot = true\n", "t.py": "x = 1\n"}
        # rich prints when it is installed; None makes its import fail.
        for label, modules in (("as installed", {}), ("without rich", {"rich": None})):
            with self.subTest(label), patch.dict(sys.modules, modules):
                result = invoke(files_, ["debug", "t.py"])
                self.assertEqual(result.exit_code, 0, result.exception)
                rule = "tukuroi.rules.use_assert_in:UseAssertIn"
                self.assertIn(rule, result.stdout)

    def test_answers(self) -> None:
        two = "self.assertTrue(a in b)\nself.assertTrue(c in d)\n"
        summary = "🛠️  1 file checked, 1 file with errors, {} 🛠️"
        cases = (
            # (label, answers, file after, summary, exit code)
            # 1 if a violation is left: its fix was not taken (#40).
            ("y, y", "y\ny\n", "self.assertIn(a, b)\nself.assertIn(c, d)\n", "2 auto-fixes available, 2 fixes applied", 0),
            ("n, y", "n\ny\n", "self.assertTrue(a in b)\nself.assertIn(c, d)\n", "2 auto-fixes available, 1 fix applied", 1),
            ("n, n", "n\nn\n", two, "2 auto-fixes available", 1),
            # Quit: nothing applied to the file, even the fix answered first.
            ("y, q", "y\nq\n", two, "2 auto-fixes available", 1),
        )  # fmt: skip
        for label, answers, fixed, counts, exit_code in cases:
            with self.subTest(label):
                after, last, code = self.fix(two, answers, UI)
                self.assertEqual(after, fixed)
                self.assertEqual(last, summary.format(counts))
                self.assertEqual(code, exit_code)

    def test_diff_colors(self) -> None:
        # The colors of moreorless.click, which prints to stdout only: on
        # stderr too, for `fix --diff -` (#40).
        def run(echo: Callable[[], None]) -> tuple[str, str]:
            result = CliRunner().invoke(click.command()(echo), color=True)
            return result.stdout, result.stderr

        colored, _ = run(lambda: echo_color_precomputed_diff(DIFF))
        self.assertIn("\x1b[31m-self.assertTrue(a in b)", colored)
        self.assertEqual(run(lambda: _echo_diff(DIFF)), (colored, ""))
        self.assertEqual(run(lambda: _echo_diff(DIFF, err=True)), ("", colored))

    def test_debug_and_quiet(self) -> None:
        # The level of the log (#116): --quiet hides a warning, and --debug
        # shows the debug lines.
        files_ = {
            "pyproject.toml": '[tool.fixit]\nroot = true\nenable = [".rules"]\n',
            "t.py": "x = 1\n",
        }
        warning = "Skipped rules '.rules': custom rules are turned off"
        for options, shown in (([], True), (["--quiet"], False)):
            with self.subTest(options=options):
                loader._WARNED.clear()  # Each warning is given once in a process.
                result = invoke(files_, [*options, "--no-custom-rules", "lint", "t.py"])
                self.assertEqual(warning in result.stderr, shown)
        files_["pyproject.toml"] = "[tool.fixit]\nroot = true\n"
        result = invoke(files_, ["--debug", "lint", "t.py"])
        self.assertIn("DEBUG:tukuroi.api:t.py: clean", result.stderr)

    def test_main_module_on_import(self) -> None:
        # Imported, not run with -m (#116): it does nothing.
        with patch("tukuroi.cli.main") as main:
            importlib.import_module("tukuroi.__main__")
        main.assert_not_called()


class PrintResultTest(TestCase):
    def test_output_format_as_a_string(self) -> None:
        # The value of the enum, as before (#116); another string is an error.
        where = Range(Position(1, 0), Position(1, 1))
        result = Result(Path.cwd() / "t.py", Violation("X", where, "m", False))
        runner = CliRunner()
        with runner.isolation() as (out, _, _):
            print_result(result, output_format="vscode")  # type: ignore[arg-type]
        self.assertEqual(out.getvalue(), b"t.py:1:0 X: m\n")
        with self.assertRaisesRegex(ValueError, "'nope' is not a valid OutputFormat"):
            print_result(result, output_format="nope")  # type: ignore[arg-type]


class FixitStdinAndFileTest(TestCase):
    """The errors of a file, when the API calls these alone (#116)."""

    def test_config_error_of_stdin(self) -> None:
        pyproject = "[tool.fixit]\nroot = true\nenable = 1\n"
        stdin = io.TextIOWrapper(io.BytesIO(b"x = 1\n"))
        with (
            files({"pyproject.toml": pyproject}) as root,
            chdir(root),
            patch("sys.stdin", stdin),
        ):
            [result] = fixit_stdin(Path("t.py"))
        message = "pyproject.toml: enable: must be an array of strings, got an integer"
        self.assertEqual(result.error, Error("tukuroi.config.ConfigError", message))

    def test_other_exception_of_stdin(self) -> None:
        stdin = SimpleNamespace(
            buffer=SimpleNamespace(read=Mock(side_effect=OSError("boom")))
        )
        with files({}) as root, chdir(root), patch("sys.stdin", stdin):
            [result] = fixit_stdin(Path("t.py"))
        assert result.error is not None
        self.assertEqual((result.error.type, result.error.message), ("OSError", "boom"))
        self.assertIn("Traceback", result.error.traceback)

    def test_file_that_cannot_be_read(self) -> None:
        with files({"sub/t.py": ""}) as root, chdir(root):
            [result] = fixit_file(Path("sub"))
        assert result.error is not None
        self.assertEqual(result.error.type, "IsADirectoryError")
        self.assertIn("Traceback", result.error.traceback)


class FixitPathsTest(TestCase):
    def test_no_paths(self) -> None:
        self.assertEqual(list(fixit_paths([])), [])

    def test_invalid_config(self) -> None:
        # The config is wrong, not tukuroi: no traceback (#40).
        cases = (
            ('enable = ["tukuroi rules"]', "enable: invalid rule name 'tukuroi rules'"),
            ("enable = [", toml_error("[tool.fixit]\nenable = [\n")),
        )
        for value, message in cases:
            tree = {
                "pyproject.toml": "[tool.fixit]\nroot = true\n",
                "sub/pyproject.toml": f"[tool.fixit]\n{value}\n",
                "sub/t.py": "",
                "t.py": "",
            }
            shown = f"sub/pyproject.toml: {message}"
            for paths in (["t.py", "sub/t.py"], ["."], ["-", "sub/t.py"]):
                with (
                    self.subTest(value, paths=paths),
                    files(tree) as root,
                    chdir(root),
                    patch("sys.stdin", io.TextIOWrapper(io.BytesIO(b"x = 1\n"))),
                ):
                    results = fixit_paths(map(Path, paths))
                    # Before any file is linted, t.py too.
                    with self.assertRaises(ConfigError) as caught:
                        next(results)
                    self.assertEqual(caught.exception.describe(), shown)
            # A file linted alone: the error is its result.
            with self.subTest(value, alone=True), files(tree) as root, chdir(root):
                results = list(fixit_file(Path("sub/t.py")))
                error = Error("tukuroi.config.ConfigError", shown)
                self.assertEqual(results, [Result(root / "sub/t.py", None, error)])

    def test_paths(self) -> None:
        # (#40) A missing path raises before the first result, a file given by
        # name is linted though .gitignore has it, and a file given twice is
        # linted once, where it comes first.
        tree = {
            "pyproject.toml": "[tool.fixit]\nroot = true\n",
            ".gitignore": "ign.py\n",
            "a/t.py": SOURCE,
            "a/u.py": SOURCE,
            "ign.py": SOURCE,
        }
        with files(tree) as root, chdir(root):
            results = fixit_paths([Path("a/t.py"), Path("nope.py")], parallel=False)
            with self.assertRaises(FileNotFoundError) as caught:
                next(results)
            self.assertEqual(caught.exception.filename, "nope.py")

            def linted(*paths: str) -> list[Path]:
                results = fixit_paths(map(Path, paths), parallel=False)
                return list(dict.fromkeys(r.path for r in results))

            self.assertEqual(linted("ign.py"), [root / "ign.py"])
            # In a directory, .gitignore is used, and the order is that of the
            # file system.
            self.assertEqual(sorted(linted(".")), [root / "a/t.py", root / "a/u.py"])
            t, u = root / "a/t.py", root / "a/u.py"
            self.assertEqual(linted("a/u.py", "a", "./a/t.py"), [u, t])
            self.assertEqual(linted("a/t.py", "a/u.py", "a/t.py"), [t, u])

    def test_configs_read_once_for_each_directory(self) -> None:
        tree = {
            "pyproject.toml": "[tool.fixit]\nroot = true\n",
            "a/t.py": "",
            "a/u.py": "",
            "b/t.py": "",
        }
        with (
            files(tree) as root,
            chdir(root),
            patch("tukuroi.config.generate_config", wraps=generate_config) as checked,
            patch("tukuroi.api.generate_config", wraps=generate_config) as linted,
        ):
            list(fixit_paths([Path("a"), Path("b/t.py")], parallel=False))
            directories = [call.args[0] for call in checked.call_args_list]
            self.assertEqual(directories, [root / "a", root / "b"])
            # And then for each file, as it is linted.
            self.assertEqual(linted.call_count, 3)
            # With --config-file, that config is read once.
            checked.reset_mock()
            options = Options(config_file=root / "pyproject.toml")
            list(fixit_paths([Path("a"), Path("b")], options=options, parallel=False))
            self.assertEqual(checked.call_count, 1)

    def test_rule_that_cannot_be_loaded(self) -> None:
        # An error of the config that names it, with the key (#40).
        tree = {"pyproject.toml": NOPE, "sub/t.py": "", "t.py": ""}
        shown = "pyproject.toml: enable: could not find rule tukuroi.rules:Nope"
        with files(tree) as root, chdir(root):
            with self.assertRaises(ConfigError) as caught:
                next(fixit_paths([Path("t.py")]))
            self.assertEqual(caught.exception.describe(), shown)
            # A file linted alone: the error is its result, and no rule runs.
            error = Error("tukuroi.config.ConfigError", shown)
            results = list(fixit_file(Path("t.py")))
            self.assertEqual(results, [Result(root / "t.py", None, error)])

    def test_rule_of_the_rules_option_that_cannot_be_loaded(self) -> None:
        tree = {"pyproject.toml": "[tool.fixit]\nroot = true\n", "t.py": ""}
        options = Options(rules=[QualifiedRule("tukuroi.rules", "Nope")])
        with files(tree) as root, chdir(root):
            with self.assertRaises(RulesOptionError) as caught:
                next(fixit_paths([Path("t.py")], options=options))
            self.assertEqual(
                str(caught.exception), "could not find rule tukuroi.rules:Nope"
            )
            shown = "--rules: could not find rule tukuroi.rules:Nope"
            error = Error("tukuroi.config.RulesOptionError", shown)
            results = list(fixit_file(Path("t.py"), options=options))
            self.assertEqual(results, [Result(root / "t.py", None, error)])

    def test_rules_of_a_config_loaded_once(self) -> None:
        enable = f'[tool.fixit]\nroot = true\nenable = ["tukuroi.rules:{SI}"]\n'
        tree = {"pyproject.toml": enable, "a/t.py": "", "a/u.py": "", "b/t.py": ""}
        with (
            files(tree) as root,
            chdir(root),
            patch("tukuroi.config.load_core_rules", wraps=load_core_rules) as loaded,
        ):
            list(fixit_paths([Path("a"), Path("b")], parallel=False))
        # Before any file, and not again for each file in the process.
        self.assertEqual(loaded.call_count, 1)

    def test_custom_rules_turned_off(self) -> None:
        # The rules skipped are not loaded: no error.
        tree = {
            "pyproject.toml": '[tool.fixit]\nroot = true\nenable = [".nope"]\n',
            "t.py": "",
        }
        with (
            files(tree) as root,
            chdir(root),
            self.assertLogs("tukuroi.config") as logs,
        ):
            options = Options(custom_rules=False)
            results = list(fixit_paths([Path("t.py")], options=options))
        self.assertEqual(results, [Result(root / "t.py", None)])
        skipped = (
            "WARNING:tukuroi.config:Skipped rules '.nope': custom rules are turned off"
        )
        self.assertEqual(logs.output, [skipped])

    def test_stdin_paths(self) -> None:
        # The CLI refuses these as usage errors (#40). The API warns about "-"
        # after a path, and raises for 2 paths after "-".
        tree = {"pyproject.toml": "[tool.fixit]\nroot = true\n", "t.py": ""}
        with files(tree) as root, chdir(root):
            with self.assertLogs("tukuroi.api", "WARNING") as logs:
                results = list(fixit_paths([Path("t.py"), STDIN]))
            mix = (
                "WARNING:tukuroi.api:Cannot mix stdin ('-') with normal paths, ignoring"
            )
            self.assertEqual(logs.output, [mix])
            self.assertEqual(results, [Result(root / "t.py", None)])
            with self.assertRaisesRegex(ValueError, "^too many stdin paths$"):
                list(fixit_paths([STDIN, Path("t.py"), Path("u.py")]))


class PublicNamesTest(TestCase):
    def test_rule_api(self) -> None:
        # The names to write a rule with come from the new engine (#21).
        import tukuroi
        from tukuroi.core import edits, rule, text

        found = (
            tukuroi.Rule,
            tukuroi.Valid,
            tukuroi.Invalid,
            tukuroi.Edit,
            tukuroi.Position,
        )
        self.assertEqual(
            found, (rule.Rule, rule.Valid, rule.Invalid, edits.Edit, text.Position)
        )
        self.assertTrue(all(hasattr(tukuroi, name) for name in tukuroi.__all__))
