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

from .characterization_cli import (
    CLEAN,
    DIRTY,
    DIRTY_A,
    CharacterizationTestCase,
    invoke,
    line,
    records,
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
        log = "WARNING:fixit.config:Failed to load rules"
        nope = f"{log} 'fixit.rules': CollectionError: could not find rule fixit.rules:Nope\n"
        cases = (
            (
                "enable",
                (f"disable = [{ALL}]", f'enable = [{SI_}, "fixit.rules:Nope"]'),
                nope,
                (SI,),
            ),
            (
                "enable only it",
                (f"disable = [{ALL}]", 'enable = ["fixit.rules:Nope"]'),
                nope,
                (),
            ),
            (
                "disable",
                (f'disable = [{ALL}, "fixit.rules:Nope"]', f"enable = [{SI_}]"),
                nope,
                (SI,),
            ),
            (
                "Rule suffix",
                (f"disable = [{ALL}]", f'enable = [{SI_}, "fixit.rules:{NA}Rule"]'),
                f"{log} 'fixit.rules': CollectionError: could not find rule fixit.rules:{NA}Rule\n",
                (SI,),
            ),
            (
                "module",
                (f"disable = [{ALL}]", f'enable = [{SI_}, "fixit.nope"]'),
                f"{log} 'fixit.nope': CollectionError: could not import rule(s) fixit.nope\n",
                (SI,),
            ),
        )
        for label, lines, warning, rules in cases:
            with self.subTest(label):
                files = {"pyproject.toml": toml(ROOT, *lines), "t.py": SOURCE}
                result = invoke(files, ["lint", "t.py"])
                expected = "".join(line("t.py", r, POSITION[r]) for r in rules)
                self.assertEqual(result.stdout, expected)
                # NOTE: an unknown rule only logs a warning, and the other rules run.
                self.assertEqual(result.stderr, warning + SUMMARY[rules])
                self.assertEqual(result.exit_code, 1 if rules else 0)

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
        # An error of the file, without a traceback (#40). The other files are
        # linted, in the process pool.
        cases = (
            ('enable = ["fixit rules"]', "enable: invalid rule name 'fixit rules'"),
            ("enable = [", toml_error(toml("enable = ["))),
        )
        for value, message in cases:
            with self.subTest(value):
                files = {
                    "pyproject.toml": ONLY_SI,
                    "sub/pyproject.toml": toml(value),
                    "t.py": SOURCE,
                    "sub/t.py": SOURCE,
                }
                result = invoke(files, ["lint", "t.py", "sub/t.py"])
                error = f"sub/t.py: EXCEPTION: sub/pyproject.toml: {message}\n"
                found = [line("t.py", SI, POSITION[SI]), error]
                self.assertEqual(records(result.stdout), sorted(found))
                summary = "🛠️  2 files checked, 2 files with errors 🛠️\n"
                self.assertEqual(result.stderr, summary)
                self.assertEqual(result.exit_code, 3)

    def test_unknown_key(self) -> None:
        warning = "WARNING:fixit.config:unknown configuration option 'bogus'\n"
        cases = (
            # NOTE: the warning is logged twice.
            ("in [tool.fixit]", "bogus = 1\n", warning * 2),
            # NOTE: an unknown key in an override is ignored without a warning.
            ("in overrides", '[[tool.fixit.overrides]]\npath = "."\nbogus = 1\n', ""),
        )
        for label, key, logged in cases:
            with self.subTest(label):
                files = {"pyproject.toml": ONLY_SI + key, "t.py": SOURCE}
                result = invoke(files, ["lint", "t.py"])
                self.assertEqual(result.stdout, line("t.py", SI, POSITION[SI]))
                self.assertEqual(result.stderr, logged + DIRTY)
                self.assertEqual(result.exit_code, 1)

    def test_config_file_names(self) -> None:
        cases = (
            ("fixit.toml", {"sub/fixit.toml": ONLY_NA}, (NA,)),
            (".fixit.toml", {"sub/.fixit.toml": ONLY_NA}, (NA,)),
            ("pyproject.toml", {"sub/pyproject.toml": ONLY_NA}, (NA,)),
            ("other name", {"sub/fixit.cfg.toml": ONLY_NA}, (SI,)),
            # NOTE: in fixit.toml too, the keys must be under [tool.fixit];
            # the keys outside it are skipped without a message.
            (
                "fixit.toml, no table",
                {"sub/fixit.toml": ONLY_NA.removeprefix("[tool.fixit]\n")},
                (SI,),
            ),
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
