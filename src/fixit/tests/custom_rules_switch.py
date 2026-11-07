# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of the switch that turns custom rules off (#12): ``--custom-rules`` /
``--no-custom-rules`` and the environment variable ``FIXIT_CUSTOM_RULES``.

With custom rules turned off, fixit imports only the rules that come with it
(``fixit.rules`` and ``fixit.upgrade``). The custom rules here create a file
named ``<module>.imported`` in the current directory when imported, so each run
shows which of them fixit imported.
"""

import os
import subprocess
import sys
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from ..config import collect_rules, parse_rule
from ..ftypes import Config
from .characterization_cli import Run, records
from .characterization_config import override, toml
from .characterization_custom_rules import (
    BAD,
    BAD_PY,
    BOTH_PY,
    SI,
    SOURCE,
    UGLY,
    found,
    names,
    root,
    run,
    summary,
)
from .characterization_lsp import (
    EXIT,
    SHUTDOWN,
    START,
    did_open,
    in_order,
    published,
    serve,
)

ENV = "FIXIT_CUSTOM_RULES"
BUILTIN = f"fixit.rules:{SI}"


def marked(module: str, text: str) -> str:
    """``text``, which also creates ``<module>.imported`` when imported."""
    return f'open("{module}.imported", "w").close()\n' + text


RULES = {"rules.py": marked("rules", BOTH_PY)}
COOKIE = {
    "cookie/__init__.py": "",
    "cookie/rules.py": marked("cookie", BOTH_PY),
}
KETTLE = {
    "kettle/__init__.py": "",
    "kettle/rules.py": marked("kettle", BAD_PY),
}


def skipped(rule: str) -> str:
    return f"WARNING:fixit.config:Skipped rules '{rule}': custom rules are turned off\n"


def refused(*rules: str) -> str:
    names = ", ".join(repr(rule) for rule in rules)
    return f"Error: Custom rules are turned off: {names}. Pass --custom-rules to load them.\n"


@contextmanager
def switch(value: str | None) -> Generator[None]:
    """Set FIXIT_CUSTOM_RULES to ``value``, or unset it (None)."""
    with patch.dict(os.environ):
        os.environ.pop(ENV, None)
        if value is not None:
            os.environ[ENV] = value
        yield


def imported(result: Run) -> set[str]:
    """The custom rule modules that the run imported."""
    return {
        Path(name).name.removesuffix(".imported")
        for name in result.files
        if name.endswith(".imported")
    }


def lint(
    config: str,
    files: Mapping[str, str],
    args: Sequence[str] = (),
    *,
    path: str = "t.py",
    env: str | None = None,
    site: Mapping[str, str] | None = None,
) -> Run:
    """``fixit <args> lint <path>``, with SOURCE in ``path``."""
    before = {"pyproject.toml": config, **files, path: SOURCE}
    with switch(env):
        return run(before, [*args, "lint", path], site=site)


class CustomRulesSwitchTest(TestCase):
    maxDiff = None

    def assert_lint(
        self, result: Run, rules: Sequence[str], warning: str = "", path: str = "t.py"
    ) -> None:
        self.assertEqual(records(result.stdout), sorted(found(r, path) for r in rules))
        self.assertEqual(result.stderr, warning + summary(rules))
        self.assertEqual(result.exit_code, 1 if rules else 0)

    def assert_refused(self, result: Run, *rules: str) -> None:
        # Not the usage lines of click: only its "Error:" line is fixit's.
        self.assertEqual(result.stderr.rpartition("\n\n")[2], refused(*rules))
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(imported(result), set())

    def test_builtin_rules(self) -> None:
        cases = (
            ("fixit.rules", True),
            (BUILTIN, True),
            ("fixit.rules.no_static_if_condition", True),
            ("fixit.upgrade", True),
            ("fixit.upgrade.deprecated_testcase_keywords", True),
            ("fixit", False),
            ("fixit.rulesx", False),
            ("fixit.upgrades", False),
            ("fixit.local.rules", False),
            (".fixit.rules", False),
            (".rules", False),
            ("cookie.rules", False),
        )
        for name, builtin in cases:
            with self.subTest(name):
                self.assertIs(parse_rule(name, Path.cwd()).builtin, builtin)

    def test_enable_root_import_is_ignored(self) -> None:
        # The CLI cannot show it: with custom rules turned off, nothing would be
        # imported from the path anyway.
        for custom_rules, calls in ((True, 1), (False, 0)):
            with self.subTest(custom_rules=custom_rules):
                config = Config(
                    enable=[parse_rule(BUILTIN, Path.cwd())],
                    enable_root_import=True,
                    custom_rules=custom_rules,
                )
                with patch("fixit.config.append_sys_path") as append:
                    rules = collect_rules(config)
                self.assertEqual(append.call_count, calls)
                self.assertEqual([type(r).__name__ for r in rules], [SI])

    def test_value_of_the_switch(self) -> None:
        config = root(".rules", BUILTIN)
        on = ((BAD, UGLY, SI), "", {"rules"})
        off = ((SI,), skipped(".rules"), set())
        cases = (
            # (label, FIXIT_CUSTOM_RULES, args, result)
            ("default", None, (), on),
            ("--custom-rules", None, ("--custom-rules",), on),
            ("--no-custom-rules", None, ("--no-custom-rules",), off),
            *((f"env {v}", v, (), off) for v in ("0", "false", "no", "off", "OFF")),
            *((f"env {v}", v, (), on) for v in ("1", "true", "yes", "on", "ON")),
            ("env empty", "", (), on),
            ("env 0, --custom-rules", "0", ("--custom-rules",), on),
            ("env 1, --no-custom-rules", "1", ("--no-custom-rules",), off),
        )
        for label, env, args, (rules, warning, modules) in cases:
            with self.subTest(label):
                result = lint(config, RULES, args, env=env)
                self.assert_lint(result, rules, warning)
                self.assertEqual(imported(result), modules)

    def test_invalid_value_of_the_variable(self) -> None:
        result = lint(root(".rules"), RULES, env="nope")
        error = result.stderr.rpartition("\n\n")[2]
        self.assertTrue(error.startswith("Error: Invalid value for '--custom-rules'"))
        self.assertIn(f"(env var: '{ENV}')", error)
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(imported(result), set())

    def test_custom_rules_in_the_config_are_skipped(self) -> None:
        root_import = ["enable-root-import = true"]
        sub = override("sub", names("enable", ".rules"))
        cases = (
            # (label, config, files, site, path, rules, warning)
            ("rule in the repo", root(f".rules:{BAD}"), RULES, None, "t.py", (), skipped(f".rules:{BAD}")),
            ("module in the repo", root(".rules"), RULES, None, "t.py", (), skipped(".rules")),
            ("installed package", root("cookie.rules"), {}, COOKIE, "t.py", (), skipped("cookie.rules")),
            ("enable-root-import", root("kettle.rules", lines=root_import), KETTLE, None, "t.py", (), skipped("kettle.rules")),
            ("override", root(BUILTIN) + sub, RULES, None, "sub/t.py", (SI,), skipped(".rules")),
            ("disable a custom rule", root(BUILTIN, disable=[".rules"]), RULES, None, "t.py", (SI,), ""),
            ("built-in rule", root(BUILTIN), RULES, None, "t.py", (SI,), ""),
            ("fixit.upgrade", root("fixit.upgrade"), RULES, None, "t.py", (), ""),
        )  # fmt: skip
        for label, config, files, site, path, rules, warning in cases:
            with self.subTest(label):
                args = ["--no-custom-rules"]
                result = lint(config, files, args, path=path, site=site)
                self.assert_lint(result, rules, warning, path)
                self.assertEqual(imported(result), set())

    def test_warning_for_each_file(self) -> None:
        before = {"pyproject.toml": root(".rules"), **RULES, "t.py": SOURCE}
        args = ["--no-custom-rules", "fix", "--automatic", "t.py", "u.py"]
        result = run(before | {"u.py": SOURCE}, args)
        self.assertEqual(result.stdout, "")
        two = "🧼 2 files clean 🧼\n"
        self.assertEqual(result.stderr, skipped(".rules") * 2 + two)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(imported(result), set())

    def test_rules_option(self) -> None:
        config = root(".rules")
        with self.subTest("built-in rule"):
            args = ["--no-custom-rules", "--rules", BUILTIN]
            self.assert_lint(lint(config, RULES, args), (SI,))
        cases = (
            # (label, FIXIT_CUSTOM_RULES, args, rules refused, site)
            ("in the repo", None, ["--no-custom-rules", "--rules", ".rules"], (".rules",), None),
            ("env 0", "0", ["--rules", ".rules"], (".rules",), None),
            ("installed", None, ["--no-custom-rules", "--rules", "cookie.rules"], ("cookie.rules",), COOKIE),
            ("with a built-in rule", None, ["--no-custom-rules", "--rules", f"{BUILTIN},.rules,cookie.rules"], (".rules", "cookie.rules"), COOKIE),
        )  # fmt: skip
        for label, env, args, rules, site in cases:
            with self.subTest(label):
                self.assert_refused(
                    lint(config, RULES, args, env=env, site=site), *rules
                )
        with self.subTest("env 0, --custom-rules"):
            args = ["--custom-rules", "--rules", ".rules"]
            result = lint(config, RULES, args, env="0")
            self.assert_lint(result, (BAD, UGLY))
            self.assertEqual(imported(result), {"rules"})

    def test_fixit_test(self) -> None:
        cases = (
            # (label, FIXIT_CUSTOM_RULES, args)
            ("--no-custom-rules", None, ["--no-custom-rules", "test", ".rules"]),
            ("env 0", "0", ["test", ".rules"]),
        )
        for label, env, args in cases:
            with self.subTest(label), switch(env):
                self.assert_refused(run(RULES, args), ".rules")
        with self.subTest("built-in rule"), switch(None):
            result = run(RULES, ["--no-custom-rules", "test", BUILTIN])
            self.assertTrue(result.stderr.endswith("\n\nOK\n"))
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(imported(result), set())

    def test_validate_config(self) -> None:
        config = toml(
            "root = true",
            names("enable", ".rules", "cookie.rules", BUILTIN),
            names("disable", f".rules:{UGLY}Rule"),
        ) + override("sub", names("enable", ".rules"))
        with self.subTest("off"), switch(None):
            before = {"pyproject.toml": config, **RULES}
            args = ["--no-custom-rules", "validate-config", "pyproject.toml"]
            result = run(before, args, site=COOKIE)
            warnings = [".rules", "cookie.rules", f".rules:{UGLY}Rule", ".rules"]
            self.assertEqual(result.stderr, "".join(map(skipped, warnings)))
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(imported(result), set())
        with self.subTest("off, invalid name"), switch(None):
            before = {"pyproject.toml": toml(names("enable", "..rules")), **RULES}
            result = run(before, args)
            # Printed with pprint, or rich when installed: only the start is stable.
            self.assertIn("Failed to parse rule `..rules`", result.stdout)
            self.assertEqual(result.stderr, "")
            self.assertEqual(result.exit_code, -1)
        with self.subTest("on"), switch(None):
            before = {"pyproject.toml": config, **RULES}
            result = run(before, ["validate-config", "pyproject.toml"], site=COOKIE)
            self.assertEqual((result.stdout, result.stderr), ("", ""))
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(imported(result), {"rules", "cookie"})

    def test_lsp(self) -> None:
        files = {"pyproject.toml": root(".rules", BUILTIN), **RULES}
        messages = [*START, did_open(SOURCE), SHUTDOWN, EXIT]
        with switch("0"):
            served = serve(files, messages)
        self.assertEqual(in_order(served.published), [published((SI, "2:0", "3:8"))])
        self.assertEqual(served.stderr, skipped(".rules"))

    def test_python_m_takes_the_current_directory_off_sys_path(self) -> None:
        # fixit imports rich when validate-config prints. A rich.py in the
        # current directory would run, as the first entry of sys.path.
        rich = 'open("rich.imported", "w").close()\nraise ImportError\n'
        env = {k: v for k, v in os.environ.items() if k not in {ENV, "PYTHONSAFEPATH"}}
        with TemporaryDirectory() as td:
            cwd = Path(td)
            (cwd / "pyproject.toml").write_text(toml("root = true"))
            (cwd / "rich.py").write_text(rich)
            result = subprocess.run(
                [sys.executable, "-m", "fixit", "validate-config", "pyproject.toml"],
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual((result.stdout, result.stderr), ("", ""))
            self.assertEqual(result.returncode, 0)
            self.assertFalse((cwd / "rich.imported").exists())
