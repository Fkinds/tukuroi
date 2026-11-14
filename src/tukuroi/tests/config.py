# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import tomllib
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from textwrap import dedent
from unittest import TestCase

from click.testing import CliRunner

from .. import config
from ..cli import main
from ..core import loader
from ..ftypes import (
    Config,
    Options,
    OutputFormat,
    QualifiedRule,
    RawConfig,
)
from ..util import chdir
from .core_loader import files


class ConfigTest(TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.td = TemporaryDirectory()
        self.tdp = Path(self.td.name).resolve()

        self.outer = self.tdp / "outer"
        self.inner = self.tdp / "outer" / "inner"
        self.inner.mkdir(parents=True)
        # The root of a repository: the configs are searched up to it (#13).
        (self.tdp / ".git").mkdir()

        (self.tdp / "pyproject.toml").write_text(
            dedent(
                """
                [tool.tukuroi]
                root = true
                enable-root-import = true
                enable = ["more.rules"]
                disable = ["tukuroi.rules.SomethingSpecific"]

                [[tool.tukuroi.overrides]]
                path = "other"
                enable = ["other.stuff", ".globalrules"]
                disable = ["tukuroi.rules"]
                """
            )
        )
        (self.outer / ".tukuroi.toml").write_text(
            dedent(
                """
                [tool.tukuroi]
                enable = [".localrules"]
                disable = ["tukuroi.rules"]
                """
            )
        )
        (self.inner / "pyproject.toml").write_text(
            dedent(
                """
                [tool.fuzzball]
                something = "whatever"
                """
            )
        )
        (self.inner / "tukuroi.toml").write_text(
            dedent(
                """
                [tool.tukuroi]
                root = true
                enable = ["fake8", "make8"]
                disable = ["foo.bar"]
                """
            )
        )

    def tearDown(self) -> None:
        self.td.cleanup()

    def test_locate_configs(self) -> None:
        for name, path, root, expected in (
            ("top", self.tdp, None, [self.tdp / "pyproject.toml"]),
            ("top file", self.tdp / "hello.py", None, [self.tdp / "pyproject.toml"]),
            (
                "outer",
                self.outer,
                None,
                [self.outer / ".tukuroi.toml", self.tdp / "pyproject.toml"],
            ),
            (
                "outer file",
                self.outer / "frob.py",
                None,
                [self.outer / ".tukuroi.toml", self.tdp / "pyproject.toml"],
            ),
            (
                "inner",
                self.inner,
                None,
                [
                    self.inner / "tukuroi.toml",
                    self.inner / "pyproject.toml",
                    self.outer / ".tukuroi.toml",
                    self.tdp / "pyproject.toml",
                ],
            ),
            (
                "inner file",
                self.inner / "test.py",
                None,
                [
                    self.inner / "tukuroi.toml",
                    self.inner / "pyproject.toml",
                    self.outer / ".tukuroi.toml",
                    self.tdp / "pyproject.toml",
                ],
            ),
            (
                "outer from outer",
                self.outer,
                self.outer,
                [self.outer / ".tukuroi.toml"],
            ),
            (
                "inner from outer",
                self.inner,
                self.outer,
                [
                    self.inner / "tukuroi.toml",
                    self.inner / "pyproject.toml",
                    self.outer / ".tukuroi.toml",
                ],
            ),
            (
                "inner from inner",
                self.inner,
                self.inner,
                [self.inner / "tukuroi.toml", self.inner / "pyproject.toml"],
            ),
        ):
            with self.subTest(name):
                actual = config.locate_configs(path, root)
                self.assertListEqual(expected, actual)

    def test_search_root(self) -> None:
        # The nearest root of a repository; outside one, the current directory
        # if the path is in it, or else the directory itself (#13).
        cases = (
            # (label, marker, cwd, root)
            (".git directory", ".git/", ".", "a"),
            (".git file", ".git", ".", "a"),
            (".hg", ".hg/", ".", "a"),
            ("no repository, in cwd", None, "a", "a"),
            ("no repository, cwd deeper", None, "a/b/c", "a/b/c"),
            ("no repository, not in cwd", None, "elsewhere", "a/b/c"),
        )
        for label, marker, cwd, root in cases:
            with self.subTest(label), TemporaryDirectory() as td:
                top = Path(td).resolve()
                (top / "a/b/c").mkdir(parents=True)
                (top / "elsewhere").mkdir()
                if marker and marker.endswith("/"):
                    (top / "a" / marker).mkdir()
                elif marker:
                    (top / "a" / marker).write_text("gitdir: elsewhere\n")
                with chdir(top / cwd):
                    self.assertEqual(config.search_root(top / "a/b/c"), top / root)

    def test_locate_configs_up_to_the_search_root(self) -> None:
        # A config above the root of the repository is not found (#13).
        with TemporaryDirectory() as td:
            top = Path(td).resolve()
            (top / "repo/sub").mkdir(parents=True)
            (top / "repo/.git").mkdir()
            for config_dir in (top, top / "repo", top / "repo/sub"):
                (config_dir / "pyproject.toml").write_text("[tool.tukuroi]\n")
            found = config.locate_configs(top / "repo/sub/t.py")
            expected = [top / "repo/sub/pyproject.toml", top / "repo/pyproject.toml"]
            self.assertEqual(found, expected)

    def test_read_configs(self) -> None:
        # in-out priority order
        innerA = self.inner / "tukuroi.toml"
        innerB = self.inner / "pyproject.toml"
        outer = self.outer / ".tukuroi.toml"
        top = self.tdp / "pyproject.toml"

        for name, paths, expected in (
            (
                "inner",
                [innerA, innerB, outer, top],
                [
                    RawConfig(
                        innerA,
                        {
                            "root": True,
                            "enable": ["fake8", "make8"],
                            "disable": ["foo.bar"],
                        },
                    )
                ],
            ),
            (
                "inner partial",
                [innerB, outer, top],
                [
                    RawConfig(
                        outer, {"enable": [".localrules"], "disable": ["tukuroi.rules"]}
                    ),
                    RawConfig(
                        top,
                        {
                            "root": True,
                            "enable-root-import": True,
                            "enable": ["more.rules"],
                            "disable": ["tukuroi.rules.SomethingSpecific"],
                            "overrides": [
                                {
                                    "path": "other",
                                    "enable": ["other.stuff", ".globalrules"],
                                    "disable": ["tukuroi.rules"],
                                },
                            ],
                        },
                    ),
                ],
            ),
            (
                "outer",
                [outer, top],
                [
                    RawConfig(
                        outer, {"enable": [".localrules"], "disable": ["tukuroi.rules"]}
                    ),
                    RawConfig(
                        top,
                        {
                            "root": True,
                            "enable-root-import": True,
                            "enable": ["more.rules"],
                            "disable": ["tukuroi.rules.SomethingSpecific"],
                            "overrides": [
                                {
                                    "path": "other",
                                    "enable": ["other.stuff", ".globalrules"],
                                    "disable": ["tukuroi.rules"],
                                },
                            ],
                        },
                    ),
                ],
            ),
            (
                "top",
                [top],
                [
                    RawConfig(
                        top,
                        {
                            "root": True,
                            "enable-root-import": True,
                            "enable": ["more.rules"],
                            "disable": ["tukuroi.rules.SomethingSpecific"],
                            "overrides": [
                                {
                                    "path": "other",
                                    "enable": ["other.stuff", ".globalrules"],
                                    "disable": ["tukuroi.rules"],
                                },
                            ],
                        },
                    ),
                ],
            ),
        ):
            with self.subTest(name):
                actual = config.read_configs(paths)
                self.assertListEqual(expected, actual)

    def test_merge_configs(self) -> None:
        root = self.tdp
        target = root / "a" / "b" / "c" / "foo.py"

        params: Sequence[tuple[str, list[RawConfig], Config]] = (
            (
                "empty",
                [],
                Config(
                    path=target,
                    root=Path(target.anchor),
                    enable=[QualifiedRule("tukuroi.rules")],
                ),
            ),
            (
                "single",
                [
                    RawConfig(
                        (root / "tukuroi.toml"),
                        {
                            "enable": ["foo", "bar"],
                            "disable": ["bar"],
                        },
                    ),
                ],
                Config(
                    path=target,
                    root=root,
                    enable=[QualifiedRule("foo"), QualifiedRule("tukuroi.rules")],
                    disable=[QualifiedRule("bar")],
                ),
            ),
            (
                "without root",
                [
                    RawConfig(
                        (root / "a/b/c/tukuroi.toml"),
                        {"enable": ["foo"], "python-version": "3.10"},
                    ),
                    RawConfig(
                        (root / "a/b/tukuroi.toml"),
                        {"enable": ["bar"], "disable": ["foo"]},
                    ),
                    RawConfig(
                        (root / "a/tukuroi.toml"),
                        {"enable": ["foo"], "python-version": "3.8"},
                    ),
                ],
                Config(
                    path=target,
                    root=(root / "a"),
                    enable=[
                        QualifiedRule("bar"),
                        QualifiedRule("foo"),
                        QualifiedRule("tukuroi.rules"),
                    ],
                ),
            ),
            (
                "with root",
                [
                    RawConfig(
                        (root / "a/b/c/tukuroi.toml"),
                        {"enable": ["foo"], "root": True},
                    ),
                    RawConfig(
                        (root / "a/b/tukuroi.toml"),
                        {},
                    ),
                    RawConfig(
                        (root / "a/tukuroi.toml"),
                        {},
                    ),
                ],
                Config(
                    path=target,
                    root=(root / "a/b/c"),
                    enable=[QualifiedRule("foo"), QualifiedRule("tukuroi.rules")],
                ),
            ),
            (
                "nearer level wins",
                [
                    RawConfig(
                        (root / "a/b/tukuroi.toml"),
                        {"disable": ["tukuroi.rules"], "enable": ["foo.bar"]},
                    ),
                    RawConfig(
                        (root / "a/tukuroi.toml"),
                        {
                            "enable": ["tukuroi.rules:X", "foo"],
                            "disable": ["foo.bar:Y"],
                        },
                    ),
                ],
                Config(
                    path=target,
                    root=(root / "a"),
                    enable=[QualifiedRule("foo"), QualifiedRule("foo.bar")],
                    disable=[QualifiedRule("tukuroi.rules")],
                ),
            ),
        )
        for name, raw_configs, expected in params:
            with self.subTest(name):
                actual = config.merge_configs(target, raw_configs)
                self.assertEqual(expected, actual)

    def test_contains(self) -> None:
        a, b = Path("/a"), Path("/b")
        cases = (
            # (name, other, contains)
            ("x", "x", True),
            ("x", "x:R", True),
            ("x", "x.y", True),
            ("x", "x.y:R", True),
            # One level down only, as the rules of a package.
            ("x", "x.y.z", False),
            ("x", "x.y.z:R", False),
            ("x", "xy", False),
            ("x.y", "x", False),
            ("x:R", "x:R", True),
            ("x:R", "x", False),
            ("x:R", "x:S", False),
            # A rule named by its package is not told apart from its module.
            ("x.y", "x:R", False),
            (".rules", ".rules.y", True),
        )
        for name, other, expected in cases:
            with self.subTest(f"{name} {other}"):
                self.assertIs(
                    config.contains(
                        config.parse_rule(name, a), config.parse_rule(other, a)
                    ),
                    expected,
                )
        # The modules in the repo of two configs differ.
        local = config.parse_rule(".rules", a)
        self.assertFalse(config.contains(local, config.parse_rule(".rules", b)))

    def test_generate_config(self) -> None:
        for name, path, root, options, expected in (
            (
                "inner",
                self.inner / "foo.py",
                None,
                None,
                Config(
                    path=self.inner / "foo.py",
                    root=self.inner,
                    enable=[
                        QualifiedRule("fake8"),
                        QualifiedRule("make8"),
                        QualifiedRule("tukuroi.rules"),
                    ],
                    disable=[QualifiedRule("foo.bar")],
                ),
            ),
            (
                "outer",
                self.outer / "foo.py",
                None,
                None,
                Config(
                    path=self.outer / "foo.py",
                    root=self.tdp,
                    enable_root_import=True,
                    enable=[
                        QualifiedRule(".localrules", local=".", root=self.outer),
                        QualifiedRule("more.rules"),
                    ],
                    disable=[
                        QualifiedRule("tukuroi.rules"),
                        QualifiedRule("tukuroi.rules.SomethingSpecific"),
                    ],
                ),
            ),
            (
                "outer with root",
                self.outer / "foo.py",
                self.outer,
                None,
                Config(
                    path=self.outer / "foo.py",
                    root=self.outer,
                    enable=[QualifiedRule(".localrules", local=".", root=self.outer)],
                    disable=[QualifiedRule("tukuroi.rules")],
                ),
            ),
            (
                "other",
                self.tdp / "other" / "foo.py",
                None,
                None,
                Config(
                    path=self.tdp / "other" / "foo.py",
                    root=self.tdp,
                    enable_root_import=True,
                    enable=[
                        QualifiedRule(".globalrules", local=".", root=self.tdp),
                        QualifiedRule("more.rules"),
                        QualifiedRule("other.stuff"),
                    ],
                    disable=[
                        QualifiedRule("tukuroi.rules"),
                        QualifiedRule("tukuroi.rules.SomethingSpecific"),
                    ],
                ),
            ),
            (
                "root",
                self.tdp / "foo.py",
                None,
                None,
                Config(
                    path=self.tdp / "foo.py",
                    root=self.tdp,
                    enable_root_import=True,
                    enable=[
                        QualifiedRule("more.rules"),
                        QualifiedRule("tukuroi.rules"),
                    ],
                    disable=[QualifiedRule("tukuroi.rules.SomethingSpecific")],
                ),
            ),
            (
                "root with options",
                self.tdp / "foo.py",
                None,
                Options(output_format=OutputFormat.custom, output_template="foo-bar"),
                Config(
                    path=self.tdp / "foo.py",
                    root=self.tdp,
                    enable_root_import=True,
                    enable=[
                        QualifiedRule("more.rules"),
                        QualifiedRule("tukuroi.rules"),
                    ],
                    disable=[QualifiedRule("tukuroi.rules.SomethingSpecific")],
                    output_format=OutputFormat.custom,
                    output_template="foo-bar",
                ),
            ),
        ):
            with self.subTest(name):
                actual = config.generate_config(path, root, options=options)
                self.assertDictEqual(asdict(expected), asdict(actual))

    def test_invalid_config(self) -> None:
        with self.subTest("inner enable-root-import"):
            (self.tdp / "pyproject.toml").write_text("[tool.tukuroi]\nroot = true\n")
            (self.tdp / "outer" / "pyproject.toml").write_text(
                "[tool.tukuroi]\nenable-root-import = true\n"
            )

            with self.assertRaisesRegex(config.ConfigError, "enable-root-import"):
                config.generate_config(self.tdp / "outer" / "foo.py")

        with self.subTest("inner output-format"):
            (self.tdp / "pyproject.toml").write_text("[tool.tukuroi]\nroot = true\n")
            (self.tdp / "outer" / "pyproject.toml").write_text(
                "[tool.tukuroi]\noutput-format = 'this is some weird format'\n"
            )

            with self.assertRaisesRegex(config.ConfigError, "output-format"):
                config.generate_config(self.tdp / "outer" / "foo.py")

    def test_describe(self) -> None:
        # The path as the CLI shows it: relative to the current directory if
        # it is under it, or else absolute (#116).
        path = self.tdp / "pyproject.toml"
        error = config.ConfigError("x", path=path)
        with chdir(self.tdp):
            self.assertEqual(error.describe(), "pyproject.toml: x")
        with chdir(self.inner):
            self.assertEqual(error.describe(), f"{path}: x")
        self.assertEqual(config.ConfigError("x").describe(), "x")

    def test_every_message(self) -> None:
        # The checks give every message, though a config is wrong at the first
        # (#116).
        tables = "must be an array of tables ([[tool.tukuroi.overrides]]), got"
        cases = (
            (
                config.outside_errors({"a": 1, "tool": {"black": {}, "tukuroi": {}}}),
                ["a: must be under [tool.tukuroi]", "tool.black: must be under [tool.tukuroi]"],
            ),
            (
                config.rule_errors("enable", ["a b", "c d"]),
                ["enable: invalid rule name 'a b'", "enable: invalid rule name 'c d'"],
            ),
            # One message, and no more for the rest of the value.
            (config.rule_errors("enable", 1), ["enable: must be an array of strings, got an integer"]),
            (config.rule_errors("enable", [1, "a b"]), ["enable: must be an array of strings, got an array with an integer"]),
            (config.override_errors(1), [f"overrides: {tables} an integer"]),
            (config.override_errors([1, {}]), [f"overrides: {tables} an array with an integer"]),
            (config.override_errors([{}, 1]), ["overrides: a table has no path"]),
            (config.override_errors([{"path": 1}, 1]), ["overrides: path: must be a string, got an integer"]),
            (config.override_errors([{"path": ""}, 1]), ["overrides: path: must not be an empty string"]),
        )  # fmt: skip
        for messages, expected in cases:
            with self.subTest(expected[0]):
                self.assertEqual(list(messages), expected)

    def test_toml_type(self) -> None:
        # Each type of TOML v1.1.0, as tomllib reads it (#40).
        cases = (
            ('"a"', "a string"),
            ("1", "an integer"),
            ("1.5", "a float"),
            ("inf", "a float"),
            ("true", "a boolean"),
            ("1979-05-27T07:32:00Z", "an offset date-time"),
            ("1979-05-27T07:32:00+09:00", "an offset date-time"),
            ("1979-05-27T07:32:00", "a local date-time"),
            ("1979-05-27", "a local date"),
            ("07:32:00", "a local time"),
            ("[]", "an array"),
            ("{}", "a table"),
        )
        for value, expected in cases:
            with self.subTest(value):
                parsed = tomllib.loads(f"x = {value}")["x"]
                self.assertEqual(config.toml_type(parsed), expected)

    def test_removed_keys(self) -> None:
        # #21 removed these settings. A config that sets one is an error that
        # says so (#40); it was a warning, as of any unknown key.
        cases = (
            ("python-version = '3.10'", "python-version"),
            ("formatter = 'ufmt'", "formatter"),
            ("tags = 'x'", "tags"),
            ("[tool.tukuroi.options]\nX = {a = 1}", "options"),
        )
        for value, key in cases:
            with self.subTest(key):
                text = f"[tool.tukuroi]\nroot = true\n{value}\n"
                (self.tdp / "pyproject.toml").write_text(text)
                with self.assertRaises(config.ConfigError) as caught:
                    config.generate_config(self.tdp / "foo.py")
                self.assertEqual(str(caught.exception), f"{key}: no longer supported")

    def test_format_output(self) -> None:
        with chdir(self.tdp):
            (self.tdp / "pyproject.toml").write_text(
                dedent(
                    """
                    [tool.tukuroi]
                    output-format = "vscode"
                    """
                )
            )

            runner = CliRunner()
            # A rule of the new engine (#21).
            content = "self.assertTrue(a in b)\n"
            filepath = self.tdp / "assert_in.py"
            filepath.write_text(content)
            output_format_regex = r".*assert_in\.py:\d+:\d+ UseAssertIn: .+"

            with self.subTest("linting vscode"):
                result = runner.invoke(
                    main, ["lint", filepath.as_posix()], catch_exceptions=False
                )
                self.assertRegex(result.stdout, output_format_regex)

            with self.subTest("fixing vscode"):
                result = runner.invoke(
                    main, ["fix", filepath.as_posix()], catch_exceptions=False
                )
                self.assertRegex(result.stdout, output_format_regex)

            custom_output_format_regex = r".*assert_in\.py|\d+|\d+ UseAssertIn: .+"
            custom_output_format = (
                "{path}|{start_line}|{start_col} {rule_name}: {message}"
            )
            (self.tdp / "pyproject.toml").write_text(
                dedent(
                    f"""
                    [tool.tukuroi]
                    output-format = 'custom'
                    output-template = '{custom_output_format}'
                    """
                )
            )

            with self.subTest("linting custom"):
                result = runner.invoke(
                    main, ["lint", filepath.as_posix()], catch_exceptions=False
                )
                self.assertRegex(result.stdout, custom_output_format_regex)

            with self.subTest("fixing custom"):
                result = runner.invoke(
                    main, ["fix", filepath.as_posix()], catch_exceptions=False
                )
                self.assertRegex(result.stdout, custom_output_format_regex)

            with self.subTest("override output-format"):
                result = runner.invoke(
                    main,
                    ["--output-format", "vscode", "lint", filepath.as_posix()],
                    catch_exceptions=True,
                )
                self.assertRegex(result.stdout, output_format_regex)

            with self.subTest("override output-template"):
                result = runner.invoke(
                    main,
                    [
                        "--output-template",
                        "file {path} line {start_line} rule {rule_name}",
                        "lint",
                        filepath.as_posix(),
                    ],
                    catch_exceptions=True,
                )
                self.assertRegex(
                    result.stdout, r"file .*assert_in\.py line \d+ rule UseAssertIn"
                )

    def test_validate_config(self) -> None:
        # The config alone, as a root config, with the rules loaded as `lint`
        # loads them (#100). An error is as the CLI shows a ConfigError.
        rules = "from tukuroi import Rule\n\n\nclass Bad(Rule):\n    MESSAGE = 'm'\n"
        tree = {
            "rules.py": rules,
            "empty.py": "# no rules\n",
            "src/plum/__init__.py": "",
            "src/plum/rules.py": rules,
        }
        sub = 'overrides (path = "sub"):'
        override = '[[tool.tukuroi.overrides]]\npath = "sub"\nenable = {}\n'
        cases = (
            # (label, file, text, errors)
            ("valid", "pyproject.toml", '[tool.tukuroi]\ndisable = ["tukuroi.rules"]\n', []),
            ("local rules in an override", ".tukuroi.toml", "[tool.tukuroi]\nroot = true\n" + override.format('[".rules"]'), []),
            # The libcst engine did not put the path on sys.path.
            ("enable-root-import", "tukuroi.toml", '[tool.tukuroi]\nenable-root-import = "src"\nenable = ["plum.rules"]\n', []),
            ("no [tool.tukuroi]", "pyproject.toml", "[tool.black]\nx = 1\n", []),
            ("empty", "tukuroi.toml", "", []),
            # The first value only: tukuroi.rules:Nope is not loaded (#40).
            ("invalid value", "pyproject.toml", '[tool.tukuroi]\nenable = ["tukuroi.rules:Nope"]\n' + override.format('"tukuroi.rules"'), [f"pyproject.toml: {sub} enable: must be an array of strings, got a string"]),
            ("invalid name", "pyproject.toml", '[tool.tukuroi]\nenable = ["tukuroi/rules:X"]\n', ["pyproject.toml: enable: invalid rule name 'tukuroi/rules:X'"]),
            # Each rule that cannot be loaded, in the order of the file. The
            # libcst engine did not see a module without rules.
            (
                "rules",
                "pyproject.toml",
                '[tool.tukuroi]\nenable = ["tukuroi.rules:Nope", ".empty"]\n' + override.format('[".nope"]'),
                [
                    "pyproject.toml: enable: could not find rule tukuroi.rules:Nope",
                    "pyproject.toml: enable: no rules in .empty from ROOT",
                    f"pyproject.toml: {sub} enable: could not import rule(s) .nope from ROOT",
                ],
            ),
        )  # fmt: skip
        for label, name, text, errors in cases:
            with self.subTest(label), files(tree) as root, chdir(root):
                (root / name).write_text(text)
                try:
                    results = config.validate_config(root / name)
                finally:
                    loader._ROOT_IMPORTED.clear()
                shown = [r.replace(str(root), "ROOT") for r in results]
                self.assertEqual(shown, errors)
