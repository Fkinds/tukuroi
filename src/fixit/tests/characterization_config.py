# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Characterization tests for the config: ``enable`` and ``disable`` with the
built-in rules, ``[[tool.fixit.overrides]]``, the config file names, and the
configs of the parent directories.

They run the CLI only, so that the engine rewrite (#21) can be checked against
them. The expected values are copied from the output of the libcst engine.
``NOTE`` marks behavior that looks wrong but is pinned as is.

Each case lints a file with SOURCE and pins which of two rules report it.
"""

from collections.abc import Mapping
from pathlib import Path

from .characterization_cli import (
    CLEAN,
    DIRTY,
    DIRTY_A,
    CharacterizationTestCase,
    invoke,
    line,
    toml_error,
)

NA = "NoAssertTrueForComparisons"
SI = "NoStaticIfCondition"
# NA reports line 1 (with an autofix), SI reports line 2.
SOURCE = "self.assertTrue(a, 3)\nif True:\n    pass\n"
POSITION = {NA: "1:0", SI: "2:0"}
# The summary line on stderr, by the rules that report the file.
SUMMARY = {(): CLEAN, (SI,): DIRTY, (NA,): DIRTY_A, (NA, SI): DIRTY_A}

ROOT = "root = true"
ALL = '"fixit.rules"'
NA_ = f'"fixit.rules:{NA}"'
SI_ = f'"fixit.rules:{SI}"'


def toml(*lines: str) -> str:
    return "[tool.fixit]\n" + "".join(f"{x}\n" for x in lines)


def override(path: str, *lines: str) -> str:
    return f'[[tool.fixit.overrides]]\npath = "{path}"\n' + "".join(
        f"{x}\n" for x in lines
    )


ONLY_NA = toml(ROOT, f"disable = [{ALL}]", f"enable = [{NA_}]")
ONLY_SI = toml(ROOT, f"disable = [{ALL}]", f"enable = [{SI_}]")
NONE = toml(ROOT, f"disable = [{ALL}]")

Cases = tuple[tuple[str, Mapping[str, str], str, tuple[str, ...]], ...]


class ConfigCharacterizationTest(CharacterizationTestCase):
    def assert_reported(self, cases: Cases) -> None:
        """``(label, config files, path linted, rules that report it)``"""
        for label, configs, path, rules in cases:
            with self.subTest(label, path=path):
                result = invoke({**configs, path: SOURCE}, ["lint", path])
                reported = ((path, rule, POSITION[rule]) for rule in rules)
                self.assert_violations(result.stdout, reported)
                self.assertEqual(result.stderr, SUMMARY[rules])
                self.assertEqual(result.exit_code, 1 if rules else 0)

    def test_enable_and_disable(self) -> None:
        cases = (
            # The default is enable = ["fixit.rules"].
            ("nothing set", toml(ROOT), (NA, SI)),
            ("enable fixit.rules", toml(ROOT, f"enable = [{ALL}]"), (NA, SI)),
            ("disable fixit.rules", toml(ROOT, f"disable = [{ALL}]"), ()),
            ("disable 1 rule", toml(ROOT, f"disable = [{NA_}]"), (SI,)),
            # `enable` alone adds to the default.
            ("enable 1 rule", toml(ROOT, f"enable = [{NA_}]"), (NA, SI)),
            ("disable all, enable 1", ONLY_NA, (NA,)),
            (
                "enable 2",
                toml(ROOT, f"disable = [{ALL}]", f"enable = [{NA_}, {SI_}]"),
                (NA, SI),
            ),
            # A name in both: `disable` wins, in either order in the file.
            ("same rule", toml(ROOT, f"enable = [{NA_}]", f"disable = [{NA_}]"), (SI,)),
            (
                "same rule, disable 1st",
                toml(ROOT, f"disable = [{NA_}]", f"enable = [{NA_}]"),
                (SI,),
            ),
            ("same module", toml(ROOT, f"enable = [{ALL}]", f"disable = [{ALL}]"), ()),
            (
                "same rule, with module",
                toml(ROOT, f"disable = [{ALL}, {NA_}]", f"enable = [{NA_}, {SI_}]"),
                (SI,),
            ),
            # A rule named in `enable` stays on when its module is disabled.
            (
                "enable 1, disable module",
                toml(ROOT, f"enable = [{NA_}]", f"disable = [{ALL}]"),
                (NA,),
            ),
        )
        self.assert_reported(
            tuple(
                (label, {"pyproject.toml": c}, "t.py", rules)
                for label, c, rules in cases
            )
        )

    def test_unknown_rule_name(self) -> None:
        # An error of the config that names the rule, with the key, before any
        # file is linted (#40). It was a warning that named the module, and
        # the other rules ran.
        nope = "could not find rule fixit.rules:Nope"
        sub = 'overrides (path = "sub"):'
        cases = (
            # (label, lines of pyproject.toml, error)
            ("enable", (f"disable = [{ALL}]", f'enable = [{SI_}, "fixit.rules:Nope"]'), f"enable: {nope}"),
            ("enable only it", (f"disable = [{ALL}]", 'enable = ["fixit.rules:Nope"]'), f"enable: {nope}"),
            ("disable", (f'disable = [{ALL}, "fixit.rules:Nope"]', f"enable = [{SI_}]"), f"disable: {nope}"),
            ("Rule suffix", (f'enable = ["fixit.rules:{NA}Rule"]',), f"enable: could not find rule fixit.rules:{NA}Rule"),
            ("module", (f'enable = [{SI_}, "fixit.nope"]',), "enable: could not import rule(s) fixit.nope"),
            # The override does not apply to t.py, but its rules are loaded.
            ("override", (override("sub", 'disable = ["fixit.rules:Nope"]'),), f"{sub} disable: {nope}"),
            # The first error, in the order of the file.
            ("first", ('disable = ["fixit.nope"]', 'enable = ["fixit.rules:Nope"]'), "disable: could not import rule(s) fixit.nope"),
        )  # fmt: skip
        for label, lines, error in cases:
            with self.subTest(label):
                files = {"pyproject.toml": toml(ROOT, *lines), "t.py": SOURCE}
                result = invoke(files, ["lint", "t.py"])
                self.assertEqual(result.stderr, f"Error: pyproject.toml: {error}\n")
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.exit_code, 2)

    def test_unknown_rule_name_in_the_configs_of_the_files(self) -> None:
        # The configs of all the files are loaded before any file is linted
        # (#40): in the order of the files, and for a file, from the root
        # config inward.
        root = toml(ROOT, 'enable = ["fixit.rules:Nope"]')
        sub = toml('enable = ["fixit.nope"]')
        nope = "pyproject.toml: enable: could not find rule fixit.rules:Nope"
        sub_nope = "sub/pyproject.toml: enable: could not import rule(s) fixit.nope"
        cases = (
            # (label, configs, paths, error)
            ("root config, then sub", {"pyproject.toml": root, "sub/pyproject.toml": sub}, ["sub/t.py"], nope),
            ("a file in sub", {"pyproject.toml": ONLY_SI, "sub/pyproject.toml": sub}, ["t.py", "sub/t.py"], sub_nope),
            ("the first file first", {"pyproject.toml": ONLY_SI, "sub/pyproject.toml": sub, "a/pyproject.toml": root}, ["sub/t.py", "a/t.py"], sub_nope),
        )  # fmt: skip
        for label, configs, paths, error in cases:
            with self.subTest(label):
                files = {
                    **configs,
                    "t.py": SOURCE,
                    "a/t.py": SOURCE,
                    "sub/t.py": SOURCE,
                }
                result = invoke(files, ["lint", *paths])
                self.assertEqual(result.stderr, f"Error: {error}\n")
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.exit_code, 2)

    def test_overrides(self) -> None:
        base = toml(ROOT, f"disable = [{ALL}]", f"enable = [{SI_}]")
        enable_na = override("sub", f"enable = [{NA_}]")

        def files(*overrides: str) -> dict[str, str]:
            return {"pyproject.toml": base + "".join(overrides)}

        cases = (
            ("enable, in path", files(enable_na), "sub/t.py", (NA, SI)),
            ("enable, deeper", files(enable_na), "sub/deep/t.py", (NA, SI)),
            ("enable, outside", files(enable_na), "t.py", (SI,)),
            ("enable, prefix only", files(enable_na), "subx/t.py", (SI,)),
            ("disable", files(override("sub", f"disable = [{SI_}]")), "sub/t.py", ()),
            (
                "file path",
                files(override("sub/t.py", f"enable = [{NA_}]")),
                "sub/t.py",
                (NA, SI),
            ),
            (
                "file path, other file",
                files(override("sub/t.py", f"enable = [{NA_}]")),
                "sub/u.py",
                (SI,),
            ),
            ("path .", files(override(".", f"enable = [{NA_}]")), "t.py", (NA, SI)),
            (
                "trailing /",
                files(override("sub/", f"enable = [{NA_}]")),
                "sub/t.py",
                (NA, SI),
            ),
            ("glob", files(override("*.py", f"enable = [{NA_}]")), "t.py", (SI,)),
            (
                "missing path",
                files(override("nope", f"enable = [{NA_}]")),
                "t.py",
                (SI,),
            ),
            (
                "over disable of the file",
                {
                    "pyproject.toml": toml(
                        ROOT, f"disable = [{ALL}, {NA_}]", f"enable = [{SI_}]"
                    )
                    + enable_na
                },
                "sub/t.py",
                (NA, SI),
            ),
            (
                "enable and disable",
                files(override("sub", f"enable = [{NA_}]", f"disable = [{NA_}]")),
                "sub/t.py",
                (SI,),
            ),
        )
        self.assert_reported(cases)

    def test_search_stops_at_the_root_of_the_repository(self) -> None:
        # The configs are searched up to the root of the repository, or outside
        # one, up to the current directory (#13). ONLY_NA above it is not read:
        # the default rules report the file. The libcst engine searched up to
        # the root of the filesystem.
        above = {"pyproject.toml": ONLY_NA}
        cases = (
            # (label, files, cwd, path, rules)
            (".git directory", {"repo/.git/HEAD": ""}, ".", "repo/t.py", (NA, SI)),
            (".git file", {"repo/.git": "gitdir: elsewhere\n"}, ".", "repo/t.py", (NA, SI)),
            (".hg", {"repo/.hg/requires": ""}, ".", "repo/t.py", (NA, SI)),
            ("no repository, cwd", {}, "sub", "t.py", (NA, SI)),
            ("no repository, not in cwd", {"a/x.py": ""}, "a", "../b/t.py", (NA, SI)),
            # Up to there, the configs are merged as before.
            ("in the repository", {".git/HEAD": ""}, "sub", "t.py", (NA,)),
            ("no repository, in cwd", {}, ".", "sub/t.py", (NA,)),
        )  # fmt: skip
        for label, files, cwd, path, rules in cases:
            with self.subTest(label):
                where = (Path(cwd) / path).as_posix().removeprefix("./")
                result = invoke(
                    {**above, **files, where: SOURCE}, ["lint", path], cwd=cwd
                )
                reported = {rule for rule in (NA, SI) if f" {rule}: " in result.stdout}
                self.assertEqual(reported, set(rules), result.stdout)
                self.assertEqual(result.exit_code, 1)

    def test_two_overrides(self) -> None:
        def files(*overrides: str) -> dict[str, str]:
            return {"pyproject.toml": ONLY_SI + "".join(overrides)}

        enable_na = override("sub", f"enable = [{NA_}]")
        cases = (
            (
                "deeper disables",
                files(enable_na, override("sub/deep", f"disable = [{NA_}]")),
                "sub/deep/t.py",
                (SI,),
            ),
            (
                "deeper disables, outside",
                files(enable_na, override("sub/deep", f"disable = [{NA_}]")),
                "sub/t.py",
                (NA, SI),
            ),
            # NOTE: the later override wins, even when its path is less deep.
            (
                "deeper first",
                files(
                    override("sub/deep", f"disable = [{SI_}]"),
                    override("sub", f"enable = [{SI_}]"),
                ),
                "sub/deep/t.py",
                (SI,),
            ),
            (
                "same path",
                files(enable_na, override("sub", f"disable = [{NA_}]")),
                "sub/t.py",
                (SI,),
            ),
        )
        self.assert_reported(cases)

    def test_invalid_value(self) -> None:
        # The key, then the type that it must be and the type of the value, as
        # TOML names them (#40). The libcst engine named the type of the key
        # ("got <class 'str'>"), took `root = "no"` as true, and printed a
        # traceback for `enable = [1]`, `output-template = 1` and `path = 1`.
        rules = "must be an array of strings, got"
        tables = "must be an array of tables ([[tool.fixit.overrides]]), got"
        sub = 'overrides (path = "sub"):'
        # (one invalid value, the message)
        cases = (
            # Not an array.
            ("enable = 1", f"enable: {rules} an integer"),
            # A string is a sequence in Python, but not an array.
            ('enable = "fixit.rules"', f"enable: {rules} a string"),
            ('disable = "fixit.rules"', f"disable: {rules} a string"),
            # An element that is not a string.
            ("enable = [1]", f"enable: {rules} an array with an integer"),
            (f"disable = [{NA_}, true]", f"disable: {rules} an array with a boolean"),
            # A string that is not a rule name.
            ('enable = ["fixit rules"]', "enable: invalid rule name 'fixit rules'"),
            ('disable = ["fixit rules"]', "disable: invalid rule name 'fixit rules'"),
            ("output-format = 1", "output-format: must be a string, got an integer"),
            (
                "output-template = 1",
                "output-template: must be a string, got an integer",
            ),
            # The names of the fields only, checked though the format is not
            # custom (#14). The libcst engine printed a traceback as it printed
            # a violation, or let the template read anything.
            (
                "output-template = '{path.parent}'",
                (
                    "output-template: '{path.parent}' uses an attribute or an index,"
                    " which is not allowed"
                ),
            ),
            (
                "output-template = '{result}'",
                (
                    "output-template: unknown field 'result', not one of 'end_col',"
                    " 'end_line', 'message', 'path', 'rule_name', 'start_col',"
                    " 'start_line'"
                ),
            ),
            (
                "output-template = '{'",
                "output-template: Single '{' encountered in format string",
            ),
            # [tool.fixit.overrides], not [[tool.fixit.overrides]].
            ('[tool.fixit.overrides]\npath = "sub"', f"overrides: {tables} a table"),
            ('overrides = ["sub"]', f"overrides: {tables} an array with a string"),
            (
                f"[[tool.fixit.overrides]]\nenable = [{NA_}]",
                "overrides: a table has no path",
            ),
            (
                "[[tool.fixit.overrides]]\npath = 1",
                "overrides: path: must be a string, got an integer",
            ),
            (
                '[[tool.fixit.overrides]]\npath = ""',
                "overrides: path: must not be an empty string",
            ),
            # The override shows its path. It does not apply to t.py, but it
            # is checked too.
            (override("sub", "enable = 1"), f"{sub} enable: {rules} an integer"),
            (
                override("sub", 'disable = ["fixit rules"]'),
                f"{sub} disable: invalid rule name 'fixit rules'",
            ),
            # The first error, in the order of the file, not of the keys.
            ("enable = 1\ndisable = 1", f"enable: {rules} an integer"),
            (
                'overrides = [{path = "sub", enable = 1}]\nenable = 1',
                f"{sub} enable: {rules} an integer",
            ),
            # Not TOML: the message of tomllib.
            ("enable = [", toml_error(toml(ROOT, "enable = ["))),
        )
        # (the whole file, the message): without `root = true` above.
        whole = (
            (toml('root = "no"'), "root: must be a boolean, got a string"),
            # The tables above [tool.fixit].
            ("tool = 1\n", "tool: must be a table, got an integer"),
            ("[tool]\nfixit = 1\n", "tool.fixit: must be a table, got an integer"),
        )
        for text, message in (*((toml(ROOT, v), m) for v, m in cases), *whole):
            with self.subTest(text):
                files = {"pyproject.toml": text, "t.py": SOURCE}
                result = invoke(files, ["lint", "t.py"])
                # Without a traceback, before any file is linted (#40).
                self.assertEqual(result.stderr, f"Error: pyproject.toml: {message}\n")
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.exit_code, 2)

    def test_invalid_value_in_the_config_of_a_file(self) -> None:
        # The configs of the directories of all the files are read before any
        # file is linted, and the first error stops there (#40). The libcst
        # engine linted the other files, and gave sub/t.py the traceback.
        cases = (
            ('enable = ["fixit rules"]', "enable: invalid rule name 'fixit rules'"),
            ("enable = [", toml_error(toml("enable = ["))),
        )
        for value, message in cases:
            for paths in (["t.py", "sub/t.py"], ["."], ["-", "sub/t.py"]):
                with self.subTest(value, paths=paths):
                    files = {
                        "pyproject.toml": ONLY_SI,
                        "sub/pyproject.toml": toml(value),
                        "t.py": SOURCE,
                        "sub/t.py": SOURCE,
                    }
                    result = invoke(files, ["lint", *paths], stdin=SOURCE)
                    error = f"Error: sub/pyproject.toml: {message}\n"
                    self.assertEqual(result.stderr, error)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(result.exit_code, 2)

    def test_unknown_key(self) -> None:
        # A config error, before any file is linted (#40). The libcst engine
        # logged a warning (three times, with the checks of #40), and ignored
        # the keys of an override without one.
        keys = "'disable', 'enable', 'enable-root-import', 'output-format',"
        keys += " 'output-template', 'overrides', 'root'"
        where = 'overrides (path = "."):'
        override = '[[tool.fixit.overrides]]\npath = "."\n'
        cases = (
            # (label, lines, error)
            ("in [tool.fixit]", "bogus = 1\n", f"bogus: unknown key, not one of {keys}"),
            ("removed by #21", "tags = ['x']\n", "tags: no longer supported"),
            ("in overrides", f"{override}bogus = 1\n", f"{where} bogus: unknown key, not one of 'disable', 'enable', 'path'"),
            ("not in an override", f"{override}output-format = 'vscode'\n", f"{where} output-format: not allowed in an override"),
            ("removed, in overrides", f"{override}options = {{}}\n", f"{where} options: no longer supported"),
        )  # fmt: skip
        for label, lines, error in cases:
            with self.subTest(label):
                files = {"pyproject.toml": ONLY_SI + lines, "t.py": SOURCE}
                result = invoke(files, ["lint", "t.py"])
                self.assertEqual(result.stderr, f"Error: pyproject.toml: {error}\n")
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.exit_code, 2)

    def test_keys_outside_the_table(self) -> None:
        # fixit.toml and .fixit.toml are read under [tool.fixit] only: a key or
        # a table outside it is a config error (#40). The libcst engine skipped
        # them without a message. A pyproject.toml has the keys of other tools.
        no_table = ONLY_NA.removeprefix("[tool.fixit]\n")
        cases = (
            # (label, file, text, error)
            ("fixit.toml, no table", "fixit.toml", no_table, "root: must be under [tool.fixit]"),
            (".fixit.toml, no table", ".fixit.toml", no_table, "root: must be under [tool.fixit]"),
            ("another tool", "fixit.toml", ONLY_NA + "[tool.black]\nline-length = 80\n", "tool.black: must be under [tool.fixit]"),
        )  # fmt: skip
        for label, name, text, error in cases:
            with self.subTest(label):
                files = {f"sub/{name}": text, "t.py": SOURCE, "sub/t.py": SOURCE}
                result = invoke(
                    {"pyproject.toml": ONLY_SI, **files}, ["lint", "sub/t.py"]
                )
                self.assertEqual(result.stderr, f"Error: sub/{name}: {error}\n")
                self.assertEqual(result.exit_code, 2)
        with self.subTest("pyproject.toml"):
            text = ONLY_NA + "[tool.black]\nline-length = 80\n"
            files = {"pyproject.toml": "[project]\nname = 'x'\n" + text, "t.py": SOURCE}
            result = invoke(files, ["lint", "t.py"])
            self.assertEqual(result.stdout, line("t.py", NA, POSITION[NA]))
            self.assertEqual(result.exit_code, 1)

    def test_config_file_names(self) -> None:
        cases = (
            ("fixit.toml", {"sub/fixit.toml": ONLY_NA}, (NA,)),
            (".fixit.toml", {"sub/.fixit.toml": ONLY_NA}, (NA,)),
            ("pyproject.toml", {"sub/pyproject.toml": ONLY_NA}, (NA,)),
            ("other name", {"sub/fixit.cfg.toml": ONLY_NA}, (SI,)),
            # These have no [tool.fixit]; the parent's config is used.
            (
                "no tool.fixit",
                {"sub/pyproject.toml": "[tool.black]\nline-length = 80\n"},
                (SI,),
            ),
            ("empty tool.fixit", {"sub/pyproject.toml": "[tool.fixit]\n"}, (SI,)),
        )
        self.assert_reported(
            tuple(
                (label, {"pyproject.toml": ONLY_SI, **c}, "sub/t.py", rules)
                for label, c, rules in cases
            )
        )

    def test_config_files_in_one_directory(self) -> None:
        cases = (
            (
                "fixit.toml over pyproject.toml",
                {"fixit.toml": ONLY_NA, "pyproject.toml": ONLY_SI},
                (NA,),
            ),
            (
                ".fixit.toml over pyproject.toml",
                {".fixit.toml": ONLY_NA, "pyproject.toml": ONLY_SI},
                (NA,),
            ),
            (
                "fixit.toml over .fixit.toml",
                {"fixit.toml": ONLY_NA, ".fixit.toml": ONLY_SI},
                (NA,),
            ),
            # Without `root = true`, the next file is read and merged too.
            (
                "merged",
                {"fixit.toml": toml(f"enable = [{NA_}]"), "pyproject.toml": ONLY_SI},
                (NA, SI),
            ),
            (
                "disable over enable",
                {"fixit.toml": toml(f"disable = [{SI_}]"), "pyproject.toml": ONLY_SI},
                (),
            ),
            (
                "3 files",
                {
                    "fixit.toml": toml(f"enable = [{NA_}]"),
                    ".fixit.toml": toml(f"disable = [{SI_}]"),
                    "pyproject.toml": ONLY_SI,
                },
                (NA,),
            ),
        )
        self.assert_reported(
            tuple((label, c, "t.py", rules) for label, c, rules in cases)
        )

    def test_parent_and_child_configs(self) -> None:
        cases = (
            (
                "child enables",
                {"sub/pyproject.toml": toml(f"enable = [{NA_}]")},
                "sub/t.py",
                (NA, SI),
            ),
            (
                "child disables",
                {"sub/pyproject.toml": toml(f"disable = [{SI_}]")},
                "sub/t.py",
                (),
            ),
            # NOTE: the parent's rule stays on, though the docs say `disable`
            # overrides the rules enabled further up.
            (
                "child disables module",
                {"sub/pyproject.toml": toml(f"disable = [{ALL}]")},
                "sub/t.py",
                (SI,),
            ),
            (
                "child over parent's override",
                {
                    "pyproject.toml": ONLY_SI + override("sub", f"disable = [{SI_}]"),
                    "sub/pyproject.toml": toml(f"enable = [{SI_}]"),
                },
                "sub/t.py",
                (SI,),
            ),
            (
                "child enables what parent disabled",
                {
                    "pyproject.toml": toml(ROOT, f"disable = [{ALL}, {SI_}]"),
                    "sub/pyproject.toml": toml(f"enable = [{SI_}]"),
                },
                "sub/t.py",
                (SI,),
            ),
            (
                "3 levels",
                {
                    "sub/pyproject.toml": toml(f"enable = [{NA_}]"),
                    "sub/deep/pyproject.toml": toml(f"disable = [{SI_}]"),
                },
                "sub/deep/t.py",
                (NA,),
            ),
        )
        self.assert_reported(
            tuple(
                (label, {"pyproject.toml": ONLY_SI, **c}, path, rules)
                for label, c, path, rules in cases
            )
        )

    def test_root_stops_the_search(self) -> None:
        # The parent turns every rule off.
        cases = (
            (
                "no root",
                {"sub/pyproject.toml": toml(f"enable = [{NA_}]")},
                "sub/t.py",
                (NA,),
            ),
            (
                "root = false",
                {"sub/pyproject.toml": toml("root = false", f"enable = [{NA_}]")},
                "sub/t.py",
                (NA,),
            ),
            # The parent is not read: the default rules run.
            (
                "root = true",
                {"sub/pyproject.toml": toml(ROOT, f"enable = [{NA_}]")},
                "sub/t.py",
                (NA, SI),
            ),
            (
                "root = true only",
                {"sub/pyproject.toml": toml(ROOT)},
                "sub/t.py",
                (NA, SI),
            ),
            (
                "root in the middle",
                {
                    "sub/pyproject.toml": toml(ROOT),
                    "sub/deep/pyproject.toml": toml(f"disable = [{SI_}]"),
                },
                "sub/deep/t.py",
                (NA,),
            ),
        )
        self.assert_reported(
            tuple(
                (label, {"pyproject.toml": NONE, **c}, path, rules)
                for label, c, path, rules in cases
            )
        )
