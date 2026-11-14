# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``tukuroi.config.load_rules``: the rules of the new engine (#21) that a
config enables. How the modules are imported is tested in ``core_loader``.
"""

import logging
from pathlib import Path
from unittest import TestCase

from ..config import ConfigError, load_rules, rule_name
from ..core import loader
from ..core.loader import RuleName
from ..ftypes import Config, QualifiedRule
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
        with self.assertLogs("tukuroi.config", "WARNING") as logs:
            logging.getLogger("tukuroi.config").warning("start")
            rules = load_rules(config)
        warnings = [r.getMessage() for r in logs.records[1:]]
        return [r.name() for r in rules], warnings

    def test_builtin_rules(self) -> None:
        use_assert_in = QualifiedRule("tukuroi.rules", "UseAssertIn")
        cases = (
            # (label, config, rules)
            ("default", Config(), CORE),
            ("1 rule", Config(enable=[use_assert_in]), ["UseAssertIn"]),
            (
                "all but 1 rule",
                Config(
                    enable=[QualifiedRule("tukuroi.rules")], disable=[use_assert_in]
                ),
                [r for r in CORE if r != "UseAssertIn"],
            ),
            ("none", Config(disable=[QualifiedRule("tukuroi.rules")]), []),
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
        cases = (
            # (label, files, enable-root-import, rules)
            ("a path", KETTLE, Path("src"), ["NoBadName"]),
            ("true", at_root, True, ["Bad"]),
        )
        for label, tree, value, rules in cases:
            with self.subTest(label), files(tree) as root:
                self.setUp()
                config = Config(root=root, enable_root_import=value, enable=[kettle])
                self.assertEqual(self.load(config), (rules, []))
        # Not found: an error without the config, which load_rules does not
        # know (#40). It was a warning.
        for label, tree, value in (
            ("false", at_root, False),
            ("true, package in src", KETTLE, True),
        ):
            with self.subTest(label), files(tree) as root:
                self.setUp()
                config = Config(root=root, enable_root_import=value, enable=[kettle])
                with self.assertRaises(ConfigError) as caught:
                    load_rules(config)
                error = caught.exception
                self.assertEqual(str(error), "could not import rule(s) kettle.rules")
                self.assertIsNone(error.path)

    def test_custom_rules_turned_off(self) -> None:
        skipped = "Skipped rules '{}': custom rules are turned off"
        with files({"rules.py": BOTH} | KETTLE) as root:
            config = Config(
                root=root,
                enable_root_import=Path("src"),
                custom_rules=False,
                enable=[
                    QualifiedRule("tukuroi.rules", "UseAssertIn"),
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
            (QualifiedRule("tukuroi.rules"), RuleName("tukuroi.rules")),
            (QualifiedRule("pkg.rules", "Foo"), RuleName("pkg.rules", "Foo")),
            (local(root), RuleName(".rules", None, root)),
            (QualifiedRule(".rules", "Foo", ".", root), RuleName(".rules", "Foo", root)),
            (QualifiedRule(".rules", None, ".", Path(".")), RuleName(".rules", None, Path.cwd())),
        )  # fmt: skip
        for rule_, name in cases:
            with self.subTest(str(rule_)):
                self.assertEqual(rule_name(rule_), name)
