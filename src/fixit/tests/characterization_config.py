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

    def test_override_without_path(self) -> None:
        configs = {
            "pyproject.toml": ONLY_SI + f"[[tool.fixit.overrides]]\nenable = [{NA_}]\n"
        }
        result = invoke({**configs, "t.py": SOURCE}, ["lint", "t.py"])
        # NOTE: the exception is not caught; a traceback is printed.
        self.assertEqual(
            str(result.exception), "'overrides' table requires 'path' value"
        )
        self.assertEqual(result.stdout, "")
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
