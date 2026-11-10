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
from ..ftypes import (
    Config,
    Options,
    OutputFormat,
    QualifiedRule,
    RawConfig,
)
from ..util import chdir


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
                [tool.fixit]
                root = true
                enable-root-import = true
                enable = ["more.rules"]
                disable = ["fixit.rules.SomethingSpecific"]

                [[tool.fixit.overrides]]
                path = "other"
                enable = ["other.stuff", ".globalrules"]
                disable = ["fixit.rules"]
                """
            )
        )
        (self.outer / ".fixit.toml").write_text(
            dedent(
                """
                [tool.fixit]
                enable = [".localrules"]
                disable = ["fixit.rules"]
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
        (self.inner / "fixit.toml").write_text(
            dedent(
                """
                [tool.fixit]
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
                [self.outer / ".fixit.toml", self.tdp / "pyproject.toml"],
            ),
            (
                "outer file",
                self.outer / "frob.py",
                None,
                [self.outer / ".fixit.toml", self.tdp / "pyproject.toml"],
            ),
            (
                "inner",
                self.inner,
                None,
                [
                    self.inner / "fixit.toml",
                    self.inner / "pyproject.toml",
                    self.outer / ".fixit.toml",
                    self.tdp / "pyproject.toml",
                ],
            ),
            (
                "inner file",
                self.inner / "test.py",
                None,
                [
                    self.inner / "fixit.toml",
                    self.inner / "pyproject.toml",
                    self.outer / ".fixit.toml",
                    self.tdp / "pyproject.toml",
                ],
            ),
            ("outer from outer", self.outer, self.outer, [self.outer / ".fixit.toml"]),
            (
                "inner from outer",
                self.inner,
                self.outer,
                [
                    self.inner / "fixit.toml",
                    self.inner / "pyproject.toml",
                    self.outer / ".fixit.toml",
                ],
            ),
            (
                "inner from inner",
                self.inner,
                self.inner,
                [self.inner / "fixit.toml", self.inner / "pyproject.toml"],
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
                (config_dir / "pyproject.toml").write_text("[tool.fixit]\n")
            found = config.locate_configs(top / "repo/sub/t.py")
            expected = [top / "repo/sub/pyproject.toml", top / "repo/pyproject.toml"]
            self.assertEqual(found, expected)

    def test_read_configs(self) -> None:
        # in-out priority order
        innerA = self.inner / "fixit.toml"
        innerB = self.inner / "pyproject.toml"
        outer = self.outer / ".fixit.toml"
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
                        outer, {"enable": [".localrules"], "disable": ["fixit.rules"]}
                    ),
                    RawConfig(
                        top,
                        {
                            "root": True,
                            "enable-root-import": True,
                            "enable": ["more.rules"],
                            "disable": ["fixit.rules.SomethingSpecific"],
                            "overrides": [
                                {
                                    "path": "other",
                                    "enable": ["other.stuff", ".globalrules"],
                                    "disable": ["fixit.rules"],
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
                        outer, {"enable": [".localrules"], "disable": ["fixit.rules"]}
                    ),
                    RawConfig(
                        top,
                        {
                            "root": True,
                            "enable-root-import": True,
                            "enable": ["more.rules"],
                            "disable": ["fixit.rules.SomethingSpecific"],
                            "overrides": [
                                {
                                    "path": "other",
                                    "enable": ["other.stuff", ".globalrules"],
                                    "disable": ["fixit.rules"],
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
                            "disable": ["fixit.rules.SomethingSpecific"],
                            "overrides": [
                                {
                                    "path": "other",
                                    "enable": ["other.stuff", ".globalrules"],
                                    "disable": ["fixit.rules"],
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
                    enable=[QualifiedRule("fixit.rules")],
                ),
            ),
            (
                "single",
                [
                    RawConfig(
                        (root / "fixit.toml"),
                        {
                            "enable": ["foo", "bar"],
                            "disable": ["bar"],
                        },
                    ),
                ],
                Config(
                    path=target,
                    root=root,
                    enable=[QualifiedRule("fixit.rules"), QualifiedRule("foo")],
                    disable=[QualifiedRule("bar")],
                ),
            ),
            (
                "without root",
                [
                    RawConfig(
                        (root / "a/b/c/fixit.toml"),
                        {"enable": ["foo"], "python-version": "3.10"},
                    ),
                    RawConfig(
                        (root / "a/b/fixit.toml"),
                        {"enable": ["bar"], "disable": ["foo"]},
                    ),
                    RawConfig(
                        (root / "a/fixit.toml"),
                        {"enable": ["foo"], "python-version": "3.8"},
                    ),
                ],
                Config(
                    path=target,
                    root=(root / "a"),
                    enable=[
                        QualifiedRule("bar"),
                        QualifiedRule("fixit.rules"),
                        QualifiedRule("foo"),
                    ],
                ),
            ),
            (
                "with root",
                [
                    RawConfig(
                        (root / "a/b/c/fixit.toml"),
                        {"enable": ["foo"], "root": True},
                    ),
                    RawConfig(
                        (root / "a/b/fixit.toml"),
                        {},
                    ),
                    RawConfig(
                        (root / "a/fixit.toml"),
                        {},
                    ),
                ],
                Config(
                    path=target,
                    root=(root / "a/b/c"),
                    enable=[QualifiedRule("fixit.rules"), QualifiedRule("foo")],
                ),
            ),
        )
        for name, raw_configs, expected in params:
            with self.subTest(name):
                actual = config.merge_configs(target, raw_configs)
                self.assertEqual(expected, actual)

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
                        QualifiedRule("fixit.rules"),
                        QualifiedRule("make8"),
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
                        QualifiedRule("fixit.rules"),
                        QualifiedRule("fixit.rules.SomethingSpecific"),
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
                    disable=[QualifiedRule("fixit.rules")],
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
                        QualifiedRule("fixit.rules"),
                        QualifiedRule("fixit.rules.SomethingSpecific"),
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
                    enable=[QualifiedRule("fixit.rules"), QualifiedRule("more.rules")],
                    disable=[QualifiedRule("fixit.rules.SomethingSpecific")],
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
                    enable=[QualifiedRule("fixit.rules"), QualifiedRule("more.rules")],
                    disable=[QualifiedRule("fixit.rules.SomethingSpecific")],
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
            (self.tdp / "pyproject.toml").write_text("[tool.fixit]\nroot = true\n")
            (self.tdp / "outer" / "pyproject.toml").write_text(
                "[tool.fixit]\nenable-root-import = true\n"
            )

            with self.assertRaisesRegex(config.ConfigError, "enable-root-import"):
                config.generate_config(self.tdp / "outer" / "foo.py")

        with self.subTest("inner output-format"):
            (self.tdp / "pyproject.toml").write_text("[tool.fixit]\nroot = true\n")
            (self.tdp / "outer" / "pyproject.toml").write_text(
                "[tool.fixit]\noutput-format = 'this is some weird format'\n"
            )

            with self.assertRaisesRegex(config.ConfigError, "output-format"):
                config.generate_config(self.tdp / "outer" / "foo.py")

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
            ("[tool.fixit.options]\nX = {a = 1}", "options"),
        )
        for value, key in cases:
            with self.subTest(key):
                text = f"[tool.fixit]\nroot = true\n{value}\n"
                (self.tdp / "pyproject.toml").write_text(text)
                with self.assertRaises(config.ConfigError) as caught:
                    config.generate_config(self.tdp / "foo.py")
                self.assertEqual(str(caught.exception), f"{key}: no longer supported")

    def test_format_output(self) -> None:
        with chdir(self.tdp):
            (self.tdp / "pyproject.toml").write_text(
                dedent(
                    """
                    [tool.fixit]
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
                    [tool.fixit]
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
        with self.subTest("validate-config valid"), TemporaryDirectory() as td:
            tdp = Path(td).resolve()
            path = tdp / ".fixit.toml"
            path.write_text(
                """
                    [tool.fixit]
                    disable = ["fixit.rules"]
                    root = true
                    """
            )

            results = config.validate_config(path)

            self.assertEqual(results, [])

    def test_validate_config_with_override(self) -> None:
        with (
            self.subTest("validate-config valid with overrides"),
            TemporaryDirectory() as td,
        ):
            tdp = Path(td).resolve()
            path = tdp / ".fixit.toml"
            (tdp / "rule/ruledir").mkdir(parents=True, exist_ok=True)

            (tdp / "rule/rule.py").write_text("# Rule")
            (tdp / "rule/ruledir/rule.py").write_text("# Rule")
            path.write_text(
                """
                [tool.fixit]
                disable = ["fixit.rules"]
                root = true

                [[tool.fixit.overrides]]
                path = "SUPER_REAL_PATH"
                enable = [".rule.rule"]

                [[tool.fixit.overrides]]
                path = "SUPER_REAL_PATH/BUT_ACTUALLY_REAL"
                enable = [".rule.ruledir.rule"]
                """
            )

            results = config.validate_config(path)

            self.assertEqual(results, [])

        with (
            self.subTest("validate-config invalid config"),
            TemporaryDirectory() as td,
        ):
            tdp = Path(td).resolve()
            path = tdp / ".fixit.toml"
            path.write_text(
                """
                [tool.fixit]
                enable = ["fixit/rules:DeprecatedABCImport"]
                disable = ["fixit.rules"]
                root = true
                """
            )

            results = config.validate_config(path)

            # Checked as the config is read (#40).
            self.assertEqual(
                results,
                [
                    "Invalid config: ConfigError: enable: invalid rule name 'fixit/rules:DeprecatedABCImport'"
                ],
            )

        with (
            self.subTest("validate-config multiple errors"),
            TemporaryDirectory() as td,
        ):
            tdp = Path(td).resolve()
            config_path = tdp / ".fixit.toml"
            config_path.write_text(
                """
                [tool.fixit]
                enable = ["fixit.rules:DeprecatedABCImport"]
                disable = ["fixit.rules"]
                root = true

                [[tool.fixit.overrides]]
                path = "SUPER_REAL_PATH"
                enable = ["fixit.rules:DeprecatedABCImport_SUPER_REAL"]
                """
            )

            path = tdp / "file.py"
            path.write_text("error")

            results = config.validate_config(config_path)

            self.assertEqual(
                results,
                [
                    "Failed to import rule `fixit.rules:DeprecatedABCImport` for global enable: CollectionError: could not find rule fixit.rules:DeprecatedABCImport",
                    "Failed to import rule `fixit.rules:DeprecatedABCImport_SUPER_REAL` for override enable: `SUPER_REAL_PATH`: CollectionError: could not find rule fixit.rules:DeprecatedABCImport_SUPER_REAL",
                ],
            )

        with (
            self.subTest("validate-config invalid type"),
            TemporaryDirectory() as td,
        ):
            path = Path(td).resolve() / ".fixit.toml"
            path.write_text(
                """
                [tool.fixit]
                root = true
                enable = ["fixit.rules:Nope"]

                [[tool.fixit.overrides]]
                path = "sub"
                enable = "fixit.rules"
                """
            )

            results = config.validate_config(path)

            # The first error only: fixit.rules:Nope is not imported (#40).
            self.assertEqual(
                results,
                [
                    'Invalid config: ConfigError: overrides (path = "sub"): enable: must be an array of strings, got a string'
                ],
            )
