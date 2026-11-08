# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``fixit.config.load_rules``: the rules of the new engine (#21) that a
config enables. How the modules are imported is tested in ``core_loader``.
"""

import logging
from pathlib import Path
from unittest import TestCase

from packaging.version import Version

from ..config import load_rules, rule_name
from ..core import loader
from ..core.loader import RuleName
from ..ftypes import Config, QualifiedRule, Tags
from .core_loader import BOTH, HEAD, KETTLE, files, rule

CORE = [
    "NoAssertTrueForComparisons",
    "NoNamedTuple",
    "NoStaticIfCondition",
    "SortedAttributes",
    "UseAssertIn",
    "UseAssertIsNotNone",
    "VariadicCallableSyntax",
]


def local(root: Path, module: str = ".rules") -> QualifiedRule:
    """``module`` in ``root``, as ``parse_rule`` makes it from a config there."""
    return QualifiedRule(module, None, ".", root)


class LoadRulesTest(TestCase):
    maxDiff = None

    def setUp(self) -> None:
        loader._WARNED.clear()
        loader._ROOT_IMPORTED.clear()

    def tearDown(self) -> None:
        self.setUp()

    def load(self, config: Config) -> tuple[list[str], list[str]]:
        """The names of the rules loaded, and the warnings."""
        with self.assertLogs("fixit.config", "WARNING") as logs:
            logging.getLogger("fixit.config").warning("start")
            rules = load_rules(config)
        warnings = [r.getMessage() for r in logs.records[1:]]
        return [r.name() for r in rules], warnings

    def test_builtin_rules(self) -> None:
        use_assert_in = QualifiedRule("fixit.rules", "UseAssertIn")
        cases = (
            # (label, config, rules)
            ("default", Config(), CORE),
            ("1 rule", Config(enable=[use_assert_in]), ["UseAssertIn"]),
            (
                "all but 1 rule",
                Config(enable=[QualifiedRule("fixit.rules")], disable=[use_assert_in]),
                [r for r in CORE if r != "UseAssertIn"],
            ),
            ("none", Config(disable=[QualifiedRule("fixit.rules")]), []),
            # Tags and python-version go at the end of #21; they do not apply.
            ("tags", Config(tags=Tags.parse("nope")), CORE),
            ("python-version", Config(python_version=Version("3.0")), CORE),
        )
        for label, config, rules in cases:
            with self.subTest(label):
                self.assertEqual(self.load(config), (rules, []))

    def test_rules_in_the_repo(self) -> None:
        with files({"rules.py": BOTH}) as root:
            config = Config(root=root, enable=[local(root)])
            self.assertEqual(self.load(config), (["NoBadName", "NoUglyName"], []))

    def test_rules_in_the_repo_of_two_directories(self) -> None:
        tree = {"a/rules.py": BOTH, "b/rules.py": HEAD + rule("NoExtraName")}
        with files(tree) as root:
            config = Config(root=root, enable=[local(root / "a"), local(root / "b")])
            rules = (["NoBadName", "NoExtraName", "NoUglyName"], [])
            self.assertEqual(self.load(config), rules)

    def test_enable_root_import(self) -> None:
        kettle = QualifiedRule("kettle.rules")
        at_root = {"kettle/__init__.py": "", "kettle/rules.py": HEAD + rule("Bad")}
        warning = (
            "Failed to load rules 'kettle.rules': CollectionError:"
            " could not import rule(s) kettle.rules"
        )
        cases = (
            # (label, files, enable-root-import, rules, warnings)
            ("a path", KETTLE, Path("src"), ["NoBadName"], []),
            ("true", at_root, True, ["Bad"], []),
            ("false", at_root, False, [], [warning]),
            ("true, package in src", KETTLE, True, [], [warning]),
        )
        for label, tree, value, rules, warnings in cases:
            with self.subTest(label), files(tree) as root:
                self.setUp()
                config = Config(root=root, enable_root_import=value, enable=[kettle])
                self.assertEqual(self.load(config), (rules, warnings))

    def test_custom_rules_turned_off(self) -> None:
        skipped = "Skipped rules '{}': custom rules are turned off"
        with files({"rules.py": BOTH} | KETTLE) as root:
            config = Config(
                root=root,
                enable_root_import=Path("src"),
                custom_rules=False,
                enable=[
                    QualifiedRule("fixit.rules", "UseAssertIn"),
                    local(root),
                    QualifiedRule("kettle.rules"),
                ],
            )
            warnings = [skipped.format(".rules"), skipped.format("kettle.rules")]
            self.assertEqual(self.load(config), (["UseAssertIn"], warnings))

    def test_rule_name(self) -> None:
        root = Path("/repo")
        cases = (
            # (rule, name)
            (QualifiedRule("fixit.rules"), RuleName("fixit.rules")),
            (QualifiedRule("pkg.rules", "Foo"), RuleName("pkg.rules", "Foo")),
            (local(root), RuleName(".rules", None, root)),
            (QualifiedRule(".rules", "Foo", ".", root), RuleName(".rules", "Foo", root)),
        )  # fmt: skip
        for rule_, name in cases:
            with self.subTest(str(rule_)):
                self.assertEqual(rule_name(rule_), name)
