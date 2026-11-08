# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Characterization tests for the ``fixit`` command line: the exit code, the
summary line on stderr, stdin, ``--output-format``, ``--rules``,
``--config-file`` and the paths given.

They run the CLI only, so that the engine rewrite (#21) can be checked against
them. The expected values are copied from the output of the libcst engine.
``NOTE`` marks behavior that looks wrong but is pinned as is. ``#21`` marks
output that the new engine is known to change.
"""

import logging
import os
import re
import warnings
from collections.abc import Generator, Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar
from unittest import TestCase
from unittest.mock import patch

from click.testing import CliRunner

from ..api import CORE_ENGINE
from ..cli import main
from ..core import loader
from ..util import chdir
from .characterization_suppression import MESSAGES

NA = "NoAssertTrueForComparisons"
SI = "NoStaticIfCondition"


def config(*rules: str) -> str:
    """A root config that runs only ``rules``."""
    enable = ", ".join(f'"fixit.rules:{rule}"' for rule in rules)
    return (
        f'[tool.fixit]\nroot = true\ndisable = ["fixit.rules"]\nenable = [{enable}]\n'
    )


CONFIG = config(NA, SI)
OK = "x = 1\n"
# NA reports line 1 of this, with an autofix.
FIXABLE = "self.assertTrue(a, 3)\n"
FIXED = "self.assertEqual(a, 3)\n"
# SI reports line 1 of this, without an autofix.
UNFIXABLE = "if True:\n    pass\n"
BROKEN = "print)\n"

# The summary line on stderr.
NONE = "🧼 0 files clean 🧼\n"
CLEAN = "🧼 1 file clean 🧼\n"
DIRTY = "🛠️  1 file checked, 1 file with errors 🛠️\n"
DIRTY_A = "🛠️  1 file checked, 1 file with errors, 1 auto-fix available 🛠️\n"
DIRTY_F = (
    "🛠️  1 file checked, 1 file with errors, 1 auto-fix available, 1 fix applied 🛠️\n"
)
MIX = "WARNING:fixit.api:Cannot mix stdin ('-') with normal paths, ignoring\n"

# A violation starts a line with "<path>@<line>:<col> <rule>: " ("<path>:..."
# with vscode), and an exception with "<path>: EXCEPTION: ".
RECORD = re.compile(r"^(?=\S+(?:[@:]\d+:\d+ \w+|: EXCEPTION): )", re.MULTILINE)


@dataclass(frozen=True)
class Run:
    root: str
    exit_code: int
    stdout: str
    stderr: str
    # Every file under ``root`` after the run: relative path -> text.
    files: dict[str, str]
    # An exception that escaped ``main``, if any.
    exception: BaseException | None


@contextmanager
def fresh_logging() -> Generator[None]:
    """
    ``main`` calls ``logging.basicConfig``, which does nothing once the root
    logger has a handler. Remove the handlers during the call, as in a new
    process, so that the log lines go to the stderr of this call.
    """
    logger = logging.getLogger()
    handlers, level = logger.handlers[:], logger.level
    logger.handlers.clear()
    try:
        yield
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers[:] = handlers
        logger.setLevel(level)


def invoke(
    files: Mapping[str, str],
    args: Sequence[str],
    *,
    stdin: str | None = None,
    cwd: str = ".",
) -> Run:
    """Write ``files`` to a new directory and run ``fixit <args>`` in ``cwd``."""
    with TemporaryDirectory() as td:
        root = Path(td).resolve()
        for name, text in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode())
        # As in a new process: the new loader warns once in a process (#21).
        loader._WARNED.clear()
        loader._ROOT_IMPORTED.clear()
        with chdir(root / cwd), fresh_logging(), warnings.catch_warnings():
            # As in a real run: unittest shows the deprecation warnings of the
            # libraries, which change with their versions.
            warnings.simplefilter("ignore", DeprecationWarning)
            result = CliRunner().invoke(main, list(args), input=stdin)
        after = {
            path.relative_to(root).as_posix(): path.read_bytes().decode()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }
    error = None if isinstance(result.exception, SystemExit) else result.exception
    out = (result.exit_code, result.stdout, result.stderr)
    return Run(root.as_posix(), *out, after, error)


def records(stdout: str) -> list[str]:
    """
    Split the output before each violation or exception and sort the parts.

    Rules run in set order, and ``lint`` checks several files in a process pool,
    so the order of the parts changes between runs.
    """
    return sorted(part for part in RECORD.split(stdout) if part)


def line(path: str, rule: str, position: str = "1:0", sep: str = "@") -> str:
    return f"{path}{sep}{position} {rule}: {MESSAGES[rule]}\n"


class CharacterizationTestCase(TestCase):
    maxDiff = None

    # Temporary (#21): whether the tests of the class run the new engine. The
    # last PR of the switch takes this out, as the CLI then always runs it.
    core_engine: ClassVar[bool] = False

    def setUp(self) -> None:
        if self.core_engine:
            self.enterContext(patch.dict(os.environ, {CORE_ENGINE: "1"}))

    def assert_violations(
        self, stdout: str, reported: Iterable[tuple[str, ...]]
    ) -> None:
        """
        Compare ``stdout`` with the lines for ``(path, rule[, position])``.

        The order is pinned when one rule reports one file. Otherwise it changes
        between runs (see ``records``), and the lines are compared sorted.
        """
        reported = list(reported)
        expected = [line(*r) for r in reported]
        if len({r[:2] for r in reported}) <= 1:
            self.assertEqual(stdout, "".join(expected))
        else:
            self.assertEqual(records(stdout), sorted(expected))


class CliCharacterizationTest(CharacterizationTestCase):
    core_engine = True

    def test_lint_exit_code_and_summary(self) -> None:
        cases = (
            ("no file", {}, (), NONE, 0),
            ("2 clean", {"a.py": OK, "b.py": OK}, (), "🧼 2 files clean 🧼\n", 0),
            ("autofix", {"a.py": FIXABLE}, (("a.py", NA),), DIRTY_A, 1),
            ("no autofix", {"a.py": UNFIXABLE}, (("a.py", SI),), DIRTY, 1),
            (
                "1 of 2 files",
                {"a.py": FIXABLE, "b.py": OK},
                (("a.py", NA),),
                "🛠️  2 files checked, 1 file with errors, 1 auto-fix available 🛠️\n",
                1,
            ),
            (
                "2 in 1 file",
                {"a.py": FIXABLE + FIXABLE},
                (("a.py", NA), ("a.py", NA, "2:0")),
                "🛠️  1 file checked, 1 file with errors, 2 auto-fixes available 🛠️\n",
                1,
            ),
            (
                "2 files",
                {"a.py": UNFIXABLE, "b.py": FIXABLE + UNFIXABLE},
                (("a.py", SI), ("b.py", NA), ("b.py", SI, "2:0")),
                "🛠️  2 files checked, 2 files with errors, 1 auto-fix available 🛠️\n",
                1,
            ),
        )
        for label, files, reported, stderr, exit_code in cases:
            with self.subTest(label):
                result = invoke({"pyproject.toml": CONFIG, **files}, ["lint", "."])
                self.assert_violations(result.stdout, reported)
                self.assertEqual(result.stderr, stderr)
                self.assertEqual(result.exit_code, exit_code)

    def test_fix_exit_code_and_summary(self) -> None:
        cases = (
            ("no file", {}, (), NONE, {}),
            ("clean", {"a.py": OK}, (), CLEAN, {}),
            ("no autofix", {"a.py": UNFIXABLE}, (("a.py", SI),), DIRTY, {}),
            (
                "fixed",
                {"a.py": FIXABLE, "b.py": OK},
                (("a.py", NA),),
                (
                    "🛠️  2 files checked, 1 file with errors, 1 auto-fix available,"
                    " 1 fix applied 🛠️\n"
                ),
                {"a.py": FIXED},
            ),
            (
                "2 fixes",
                {"a.py": FIXABLE + FIXABLE},
                (("a.py", NA), ("a.py", NA, "2:0")),
                (
                    "🛠️  1 file checked, 1 file with errors, 2 auto-fixes available,"
                    " 2 fixes applied 🛠️\n"
                ),
                {"a.py": FIXED + FIXED},
            ),
        )
        for label, files, reported, stderr, changed in cases:
            with self.subTest(label):
                before = {"pyproject.toml": CONFIG, **files}
                result = invoke(before, ["fix", "--automatic", "."])
                self.assert_violations(result.stdout, reported)
                self.assertEqual(result.stderr, stderr)
                # NOTE: `fix` exits with 0 even when it reports violations.
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.files, before | changed)

    def test_fix_without_paths(self) -> None:
        files = {"pyproject.toml": CONFIG, "a.py": FIXABLE, "sub/b.py": FIXABLE}
        two = (
            "🛠️  2 files checked, 2 files with errors, 2 auto-fixes available,"
            " 2 fixes applied 🛠️\n"
        )
        cases = (
            (".", (("a.py", NA), ("sub/b.py", NA)), two, {"a.py", "sub/b.py"}),
            ("sub", (("b.py", NA),), DIRTY_F, {"sub/b.py"}),
        )
        for cwd, reported, stderr, fixed in cases:
            with self.subTest(cwd=cwd):
                result = invoke(files, ["fix", "--automatic"], cwd=cwd)
                self.assert_violations(result.stdout, reported)
                self.assertEqual(result.stderr, stderr)
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.files, files | dict.fromkeys(fixed, FIXED))

    def test_exit_code_with_syntax_error(self) -> None:
        cases = (
            ("lint", {}, (), DIRTY, 2, {}),
            (
                "lint",
                {"a.py": OK},
                (),
                "🛠️  2 files checked, 1 file with errors 🛠️\n",
                2,
                {},
            ),
            (
                "lint",
                {"a.py": FIXABLE},
                (("a.py", NA),),
                "🛠️  2 files checked, 2 files with errors, 1 auto-fix available 🛠️\n",
                3,
                {},
            ),
            # NOTE: `fix` exits with 0 even when a file raised an exception.
            (
                "fix",
                {"a.py": FIXABLE},
                (("a.py", NA),),
                (
                    "🛠️  2 files checked, 2 files with errors, 1 auto-fix available,"
                    " 1 fix applied 🛠️\n"
                ),
                0,
                {"a.py": FIXED},
            ),
        )
        for command, files, reported, stderr, exit_code, changed in cases:
            with self.subTest(command, files=files):
                before = {"pyproject.toml": CONFIG, "b.py": BROKEN, **files}
                args = ["lint", "."] if command == "lint" else ["fix", "-a", "."]
                result = invoke(before, args)
                parts = records(result.stdout)
                errors = [p for p in parts if p.startswith("b.py: EXCEPTION: ")]
                self.assertEqual(len(errors), 1)
                others = [line(*r) for r in reported]
                self.assertEqual([p for p in parts if p not in errors], others)
                self.assertEqual(result.stderr, stderr)
                self.assertEqual(result.exit_code, exit_code)
                self.assertEqual(result.files, before | changed)

    def test_syntax_error_message(self) -> None:
        # The position of the error, as a violation's: the column counts
        # characters from 0. No traceback: the file is wrong, not fixit (#21).
        cases = (
            ("print)\n", "Syntax Error @ 1:5: unmatched ')'"),
            ("def f(:\n    pass\n", "Syntax Error @ 1:6: invalid syntax"),
            ("if True\n    pass\n", "Syntax Error @ 1:7: expected ':'"),
            ('x = "\u00e9" + )\n', "Syntax Error @ 1:10: unmatched ')'"),
        )
        for source, message in cases:
            with self.subTest(source=source):
                files = {"pyproject.toml": CONFIG, "b.py": source}
                result = invoke(files, ["lint", "b.py"])
                self.assertEqual(result.stdout, f"b.py: EXCEPTION: {message}\n")
                self.assertEqual(result.stderr, DIRTY)
                self.assertEqual(result.exit_code, 2)

    def test_lint_stdin(self) -> None:
        sub = {"sub/pyproject.toml": f'[tool.fixit]\ndisable = ["fixit.rules:{SI}"]\n'}
        both = FIXABLE + UNFIXABLE
        cases = (
            ("path", ["t.py"], {}, FIXABLE, "t.py", DIRTY_A, 1),
            ("clean", ["t.py"], {}, OK, None, CLEAN, 0),
            ("no path", [], {}, FIXABLE, "stdin", DIRTY_A, 1),
            ("no dir", ["nope/t.py"], {}, FIXABLE, "nope/t.py", DIRTY_A, 1),
            # The config is looked up from the path given.
            ("sub config", ["sub/t.py"], sub, both, "sub/t.py", DIRTY_A, 1),
            # The file on disk is not read.
            ("on disk", ["t.py"], {"t.py": UNFIXABLE}, FIXABLE, "t.py", DIRTY_A, 1),
            ("2nd -", ["-"], {}, FIXABLE, "stdin", MIX + DIRTY_A, 1),
        )
        for label, paths, files, stdin, path, stderr, exit_code in cases:
            with self.subTest(label):
                before = {"pyproject.toml": CONFIG, **files}
                result = invoke(before, ["lint", "-", *paths], stdin=stdin)
                self.assertEqual(result.stdout, line(path, NA) if path else "")
                self.assertEqual(result.stderr, stderr)
                self.assertEqual(result.exit_code, exit_code)
                self.assertEqual(result.files, before)

    def test_stdin_after_a_path_is_ignored(self) -> None:
        cases = (
            (["lint"], DIRTY_A, {}, 1),
            (["fix", "--automatic"], DIRTY_F, {"t.py": FIXED}, 0),
        )
        for command, summary, changed, exit_code in cases:
            with self.subTest(command[0]):
                before = {"pyproject.toml": CONFIG, "t.py": FIXABLE}
                result = invoke(before, [*command, "t.py", "-"], stdin=UNFIXABLE)
                self.assertEqual(result.stdout, line("t.py", NA))
                self.assertEqual(result.stderr, MIX + summary)
                self.assertEqual(result.exit_code, exit_code)
                self.assertEqual(result.files, before | changed)

    def test_stdin_with_two_paths_raises(self) -> None:
        for command in ("lint", "fix"):
            with self.subTest(command):
                args = [command, "-", "t.py", "u.py"]
                result = invoke({"pyproject.toml": CONFIG}, args, stdin=FIXABLE)
                # NOTE: the exception is not caught; a traceback is printed.
                self.assertIsInstance(result.exception, ValueError)
                self.assertEqual(str(result.exception), "too many stdin paths")
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.exit_code, 1)

    def test_fix_stdin_paths(self) -> None:
        cases = (
            # Without --automatic: "-" does not ask.
            ("default", ["fix", "-", "t.py"], "t.py"),
            ("no path", ["fix", "-a", "-"], "stdin"),
            ("no dir", ["fix", "-a", "-", "nope/t.py"], "nope/t.py"),
        )
        for label, args, path in cases:
            with self.subTest(label):
                before = {"pyproject.toml": CONFIG}
                result = invoke(before, args, stdin=FIXABLE)
                self.assertEqual(result.stdout, FIXED)
                self.assertEqual(result.stderr, line(path, NA) + DIRTY_F)
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.files, before)

    def test_stdin_with_syntax_error(self) -> None:
        files = {"pyproject.toml": CONFIG}
        with self.subTest("lint"):
            result = invoke(files, ["lint", "-", "t.py"], stdin=BROKEN)
            self.assertTrue(result.stdout.startswith("t.py: EXCEPTION: "))
            self.assertEqual(result.stderr, DIRTY)
            self.assertEqual(result.exit_code, 2)
        with self.subTest("fix"):
            result = invoke(files, ["fix", "-", "t.py"], stdin=BROKEN)
            self.assertEqual(result.stdout, BROKEN)
            self.assertTrue(result.stderr.startswith("t.py: EXCEPTION: "))
            self.assertTrue(result.stderr.endswith(f"\n{DIRTY}"))
            # NOTE: `fix` exits with 0 even when the input raised an exception.
            self.assertEqual(result.exit_code, 0)

    def test_output_format(self) -> None:
        vscode = {"pyproject.toml": CONFIG + 'output-format = "vscode"\n'}
        sub = {"sub/pyproject.toml": '[tool.fixit]\noutput-format = "vscode"\n'}
        override = '[[tool.fixit.overrides]]\npath = "."\noutput-format = "vscode"\n'
        overrides = {"pyproject.toml": CONFIG + override}
        cases = (
            ("fixit", ["--output-format", "fixit"], {}, ".", "t.py", "@"),
            ("vscode", ["--output-format", "vscode"], {}, ".", "t.py", ":"),
            ("-o", ["-o", "vscode"], {}, ".", "t.py", ":"),
            ("any case", ["--output-format", "VSCode"], {}, ".", "t.py", ":"),
            ("config", [], vscode, ".", "t.py", ":"),
            ("option over config", ["-o", "fixit"], vscode, ".", "t.py", "@"),
            # The config of the current directory is used, not of the file.
            ("config of the file", [], sub, ".", "sub/t.py", "@"),
            ("config of cwd", [], sub, "sub", "t.py", ":"),
            ("in overrides", [], overrides, ".", "t.py", "@"),
        )
        for label, options, files, cwd, path, sep in cases:
            with self.subTest(label):
                before = {"pyproject.toml": CONFIG, **files, f"{cwd}/{path}": FIXABLE}
                result = invoke(before, [*options, "lint", path], cwd=cwd)
                self.assertEqual(result.stdout, line(path, NA, sep=sep))
                self.assertEqual(result.stderr, DIRTY_A)
                self.assertEqual(result.exit_code, 1)

    def test_output_format_with_diff_and_fix(self) -> None:
        before = {"pyproject.toml": CONFIG, "t.py": FIXABLE}
        vscode = line("t.py", NA, sep=":")
        with self.subTest("lint --diff"):
            result = invoke(before, ["-o", "vscode", "lint", "--diff", "t.py"])
            diff = (
                "--- a/t.py\n+++ b/t.py\n@@ -1 +1 @@\n"
                "-self.assertTrue(a, 3)\n+self.assertEqual(a, 3)\n"
            )
            self.assertEqual(result.stdout, vscode + diff)
            self.assertEqual(result.stderr, DIRTY_A)
            self.assertEqual(result.exit_code, 1)
        with self.subTest("fix"):
            result = invoke(before, ["-o", "vscode", "fix", "-a", "t.py"])
            self.assertEqual(result.stdout, vscode)
            self.assertEqual(result.stderr, DIRTY_F)
            self.assertEqual(result.files["t.py"], FIXED)
        with self.subTest("fix stdin"):
            args = ["-o", "vscode", "fix", "-", "t.py"]
            result = invoke(before, args, stdin=FIXABLE)
            self.assertEqual(result.stdout, FIXED)
            self.assertEqual(result.stderr, vscode + DIRTY_F)

    def test_output_format_invalid(self) -> None:
        with self.subTest("option"):
            result = invoke({"pyproject.toml": CONFIG}, ["-o", "json", "lint"])
            # The usage lines above it come from click.
            error = (
                "\nError: Invalid value for '--output-format' / '-o': 'json' is not"
                " one of 'custom', 'fixit', 'vscode'.\n"
            )
            self.assertTrue(result.stderr.endswith(error))
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.exit_code, 2)
        # NOTE: the exception is not caught, and its message keeps "{value!r}"
        # as is. Unlike the option, the config does not accept other cases.
        for value in ("bogus", "VSCODE"):
            with self.subTest("config", value=value):
                toml = CONFIG + f'output-format = "{value}"\n'
                files = {"pyproject.toml": toml, "t.py": FIXABLE}
                result = invoke(files, ["lint", "t.py"])
                message = "output-format: unknown value {value!r}"
                self.assertEqual(str(result.exception), message)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.exit_code, 1)

    def test_rules_option_replaces_enable_and_disable(self) -> None:
        none = '[tool.fixit]\nroot = true\ndisable = ["fixit.rules"]\n'
        override = (
            f'[[tool.fixit.overrides]]\npath = "."\nenable = ["fixit.rules:{NA}"]\n'
        )
        na = (("t.py", NA),)
        si = (("t.py", SI, "2:0"),)
        cases = (
            ("over enable", f"fixit.rules:{SI}", config(NA), si, DIRTY),
            ("over disable", f"fixit.rules:{SI}", none, si, DIRTY),
            ("over overrides", f"fixit.rules:{SI}", config(NA) + override, si, DIRTY),
            ("2 rules", f"fixit.rules:{SI},fixit.rules:{NA}", none, na + si, DIRTY_A),
            ("module", "fixit.rules", none, na + si, DIRTY_A),
            ("spaces, empty", f" fixit.rules:{SI} , ,", config(NA), si, DIRTY),
            ("twice", f"fixit.rules:{SI},fixit.rules:{SI}", config(NA), si, DIRTY),
            # These leave the config as is.
            ("empty", "", config(NA), na, DIRTY_A),
            ("comma", ",", config(NA), na, DIRTY_A),
        )
        for label, rules, toml, reported, summary in cases:
            with self.subTest(label):
                files = {"pyproject.toml": toml, "t.py": FIXABLE + UNFIXABLE}
                result = invoke(files, ["--rules", rules, "lint", "t.py"])
                self.assert_violations(result.stdout, reported)
                self.assertEqual(result.stderr, summary)
                self.assertEqual(result.exit_code, 1)

    def test_rules_option_with_fix_and_stdin(self) -> None:
        options = ["--rules", f"fixit.rules:{SI}"]
        with self.subTest("fix"):
            before = {"pyproject.toml": config(NA), "t.py": FIXABLE + UNFIXABLE}
            result = invoke(before, [*options, "fix", "-a", "t.py"])
            self.assertEqual(result.stdout, line("t.py", SI, "2:0"))
            self.assertEqual(result.stderr, DIRTY)
            self.assertEqual(result.files, before)
        with self.subTest("stdin"):
            args = [*options, "lint", "-", "t.py"]
            files = {"pyproject.toml": config(NA)}
            result = invoke(files, args, stdin=FIXABLE + UNFIXABLE)
            self.assertEqual(result.stdout, line("t.py", SI, "2:0"))
            self.assertEqual(result.stderr, DIRTY)
            self.assertEqual(result.exit_code, 1)

    def test_rules_option_with_unknown_name(self) -> None:
        find = "'fixit.rules': CollectionError: could not find rule"
        cases = (
            ("fixit.rules:Nope", f"{find} fixit.rules:Nope"),
            (
                "fixit.nope",
                "'fixit.nope': CollectionError: could not import rule(s) fixit.nope",
            ),
            (
                "fixit.rules:nostaticifcondition",
                f"{find} fixit.rules:nostaticifcondition",
            ),
            (
                "fixit.rules:NoStaticIfConditionRule",
                f"{find} fixit.rules:NoStaticIfConditionRule",
            ),
        )
        for rules, warning in cases:
            with self.subTest(rules):
                files = {"pyproject.toml": CONFIG, "t.py": FIXABLE + UNFIXABLE}
                result = invoke(files, ["--rules", rules, "lint", "t.py"])
                # NOTE: an unknown rule only logs a warning; no rule runs, and the
                # file is reported clean.
                self.assertEqual(result.stdout, "")
                log = f"WARNING:fixit.config:Failed to load rules {warning}\n"
                self.assertEqual(result.stderr, log + CLEAN)
                self.assertEqual(result.exit_code, 0)

    def test_rules_option_with_invalid_name(self) -> None:
        files = {"pyproject.toml": CONFIG, "t.py": FIXABLE}
        result = invoke(files, ["--rules", "fixit rules", "lint", "t.py"])
        # NOTE: the exception is not caught; a traceback is printed.
        self.assertEqual(str(result.exception), "invalid rule name 'fixit rules'")
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.exit_code, 1)

    def test_config_file_option(self) -> None:
        override = (
            f'[[tool.fixit.overrides]]\npath = "sub"\nenable = ["fixit.rules:{NA}"]\n'
        )
        no_root = config(SI).replace("root = true\n", "")
        sub = {"sub/pyproject.toml": f'[tool.fixit]\nenable = ["fixit.rules:{NA}"]\n'}
        si = ((SI, "2:0"),)
        both = ((NA, "1:0"), (SI, "2:0"))
        c = ["-c", "c.toml"]
        cases = (
            ("long", ["--config-file", "c.toml"], {"c.toml": config(SI)}, "t.py", si),
            ("short", c, {"c.toml": config(SI)}, "t.py", si),
            ("no root", c, {"c.toml": no_root}, "t.py", si),
            # The default rules run: the file has no [tool.fixit].
            ("no tool.fixit", c, {"c.toml": "[tool.black]\n"}, "t.py", both),
            ("sub config", c, {"c.toml": config(SI), **sub}, "sub/t.py", si),
            ("overrides", c, {"c.toml": config(SI) + override}, "sub/t.py", both),
            # NOTE: `enable` and `disable` of a config file in another directory
            # are not used; the default rules run.
            (
                "other dir",
                ["-c", "cfg/c.toml"],
                {"cfg/c.toml": config(SI)},
                "t.py",
                both,
            ),
        )
        for label, options, files, path, reported in cases:
            with self.subTest(label):
                before = {
                    "pyproject.toml": config(NA),
                    **files,
                    path: FIXABLE + UNFIXABLE,
                }
                result = invoke(before, [*options, "lint", path])
                self.assert_violations(result.stdout, ((path, *r) for r in reported))
                self.assertEqual(result.stderr, DIRTY_A if reported == both else DIRTY)
                self.assertEqual(result.exit_code, 1)

    def test_config_file_option_with_fix_and_stdin(self) -> None:
        with self.subTest("fix"):
            before = {
                "pyproject.toml": config(SI),
                "c.toml": config(NA),
                "t.py": FIXABLE + UNFIXABLE,
            }
            result = invoke(before, ["-c", "c.toml", "fix", "-a", "t.py"])
            self.assertEqual(result.stdout, line("t.py", NA))
            self.assertEqual(result.stderr, DIRTY_F)
            self.assertEqual(result.files["t.py"], FIXED + UNFIXABLE)
        with self.subTest("stdin"):
            before = {"pyproject.toml": config(NA), "c.toml": config(SI)}
            args = ["-c", "c.toml", "lint", "-", "t.py"]
            result = invoke(before, args, stdin=FIXABLE + UNFIXABLE)
            self.assertEqual(result.stdout, line("t.py", SI, "2:0"))
            self.assertEqual(result.stderr, DIRTY)
            self.assertEqual(result.exit_code, 1)

    def test_config_file_option_invalid(self) -> None:
        cases = (
            ("nope.toml", "File 'nope.toml' does not exist."),
            ("cfg", "File 'cfg' is a directory."),
        )
        for path, message in cases:
            with self.subTest(path):
                files = {
                    "pyproject.toml": CONFIG,
                    "cfg/c.toml": CONFIG,
                    "t.py": FIXABLE,
                }
                result = invoke(files, ["-c", path, "lint", "t.py"])
                # The usage lines above it come from click.
                error = (
                    f"\nError: Invalid value for '--config-file' / '-c': {message}\n"
                )
                self.assertTrue(result.stderr.endswith(error))
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.exit_code, 2)

    def test_paths(self) -> None:
        files = {
            "pyproject.toml": CONFIG,
            "a.py": UNFIXABLE,
            "e.pyi": UNFIXABLE,
            "d.txt": UNFIXABLE,
            "f": UNFIXABLE,
            ".hidden/g.py": UNFIXABLE,
            "sub/b.py": UNFIXABLE,
            "sub/deep/c.py": UNFIXABLE,
        }
        all_ = ("a.py", "e.pyi", ".hidden/g.py", "sub/b.py", "sub/deep/c.py")
        sub = ("sub/b.py", "sub/deep/c.py")
        one = "1 file checked, 1 file with errors"
        two = "2 files checked, 2 files with errors"
        five = "5 files checked, 5 files with errors"
        cases = (
            ("no path", [], ".", all_, five),
            (".", ["."], ".", all_, five),
            ("dir", ["sub"], ".", sub, two),
            ("no path in sub", [], "sub", ("b.py", "deep/c.py"), two),
            ("file, dir", ["a.py", "sub/deep"], ".", ("a.py", "sub/deep/c.py"), two),
            ("named .txt", ["d.txt"], ".", ("d.txt",), one),
            ("named, no suffix", ["f"], ".", ("f",), one),
            ("missing, file", ["nope.py", "a.py"], ".", ("a.py",), one),
            # NOTE: a file given twice is reported twice but counted once.
            ("same file twice", ["a.py", "a.py"], ".", ("a.py", "a.py"), one),
            ("file in dir", ["sub", "sub/b.py"], ".", (*sub, "sub/b.py"), two),
        )
        for label, paths, cwd, reported, summary in cases:
            with self.subTest(label):
                result = invoke(files, ["lint", *paths], cwd=cwd)
                self.assert_violations(result.stdout, ((p, SI) for p in reported))
                self.assertEqual(result.stderr, f"🛠️  {summary} 🛠️\n")
                self.assertEqual(result.exit_code, 1)

    def test_missing_path_is_skipped(self) -> None:
        for command in (["lint"], ["fix", "--automatic"]):
            with self.subTest(command[0]):
                files = {"pyproject.toml": CONFIG, "a.py": UNFIXABLE}
                result = invoke(files, [*command, "nope.py"])
                # NOTE: a missing path is skipped without a message.
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr, NONE)
                self.assertEqual(result.exit_code, 0)

    def test_paths_in_gitignore(self) -> None:
        files = {
            "pyproject.toml": CONFIG,
            ".gitignore": "ign.py\nbuild/\n",
            "a.py": UNFIXABLE,
            "ign.py": UNFIXABLE,
            "build/x.py": UNFIXABLE,
        }
        cases = (
            (".", line("a.py", SI), DIRTY, 1),
            # NOTE: a file given by name is skipped without a message too.
            ("ign.py", "", NONE, 0),
            ("build/x.py", "", NONE, 0),
        )
        for path, stdout, stderr, exit_code in cases:
            with self.subTest(path):
                result = invoke(files, ["lint", path])
                self.assertEqual(result.stdout, stdout)
                self.assertEqual(result.stderr, stderr)
                self.assertEqual(result.exit_code, exit_code)

    def test_path_outside_cwd_is_printed_absolute(self) -> None:
        files = {"pyproject.toml": CONFIG, "a.py": UNFIXABLE, "sub/b.py": OK}
        result = invoke(files, ["lint", "../a.py"], cwd="sub")
        self.assertEqual(result.stdout, line(f"{result.root}/a.py", SI))
        self.assertEqual(result.stderr, DIRTY)
        self.assertEqual(result.exit_code, 1)
