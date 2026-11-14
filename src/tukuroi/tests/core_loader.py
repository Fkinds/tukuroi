# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``tukuroi.core.loader``: the names of rules, and how the modules of
rules are imported, from the repo and from installed packages. The cases come
from the characterization tests of the libcst engine
(``characterization_custom_rules.py``): the cases marked ``#21`` there, with
what #21 decided (issuecomment-6706326492), and the others as they are.
"""

import logging
import sys
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from ..core import loader
from ..core.loader import (
    CollectionError,
    RuleName,
    collect_rules,
    import_rules,
    is_builtin,
    load,
)

HEAD = "import ast\n\nfrom tukuroi.core.rule import Rule\n"


def rule(cls: str, message: str = "m") -> str:
    return f"\n\nclass {cls}(Rule):\n    MESSAGE = {message!r}\n"


BOTH = HEAD + rule("NoBadName") + rule("NoUglyNameRule")


@contextmanager
def files(tree: Mapping[str, str], on_path: bool = False) -> Generator[Path]:
    """
    A directory with ``tree`` in it, on ``sys.path`` if ``on_path``. ``sys.path``
    and the modules imported from the directory are put back afterwards.
    """
    path, modules = sys.path[:], set(sys.modules)
    with TemporaryDirectory() as td:
        root = Path(td).resolve()
        for name, text in tree.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text)
        if on_path:
            sys.path.insert(0, str(root))
        try:
            yield root
        finally:
            sys.path[:] = path
            for name in set(sys.modules) - modules:
                del sys.modules[name]


def names(rules: tuple[type, ...]) -> list[str]:
    return [r.__name__ for r in rules]


class LoaderRuleNameTest(TestCase):
    def test_parse(self) -> None:
        root = Path("/repo")
        cases = (
            # (text, module, name, root)
            (".rules", ".rules", None, root.resolve()),
            (".rules.ugly:NoUglyNameRule", ".rules.ugly", "NoUglyNameRule", root.resolve()),
            ("tukuroi.rules", "tukuroi.rules", None, None),
            ("pkg.rules:Foo", "pkg.rules", "Foo", None),
        )  # fmt: skip
        for text, module, name, where in cases:
            with self.subTest(text):
                parsed = RuleName.parse(text, root)
                self.assertEqual(
                    (parsed.module, parsed.name, parsed.root), (module, name, where)
                )
                self.assertEqual(str(parsed), text)

    def test_invalid(self) -> None:
        for text in ("..rules", "a b", "", "x:", ":X", "a:b:c", "tukuroi.rules:"):
            with self.subTest(text), self.assertRaises(ValueError):
                RuleName.parse(text, Path("/repo"))

    def test_directory_is_part_of_a_local_name(self) -> None:
        a, b = Path("/a"), Path("/b")
        self.assertNotEqual(RuleName.parse(".rules", a), RuleName.parse(".rules", b))
        self.assertEqual(RuleName.parse("x.rules", a), RuleName.parse("x.rules", b))
        self.assertTrue(RuleName.parse(".rules", a).local)
        self.assertFalse(RuleName.parse("x.rules", a).local)


class ImportRulesTest(TestCase):
    def test_rules_in_the_repo(self) -> None:
        package = {
            "rules/__init__.py": HEAD + rule("NoBadName"),
            "rules/ugly.py": HEAD + rule("NoUglyNameRule"),
        }
        cases = (
            # (label, files, name, rules)
            ("module, all rules", {"rules.py": BOTH}, ".rules", ["NoBadName", "NoUglyNameRule"]),
            ("1 rule", {"rules.py": BOTH}, ".rules:NoBadName", ["NoBadName"]),
            ("class name ending in Rule", {"rules.py": BOTH}, ".rules:NoUglyNameRule", ["NoUglyNameRule"]),
            ("name without Rule", {"rules.py": BOTH}, ".rules:NoUglyName", ["NoUglyNameRule"]),
            ("package", package | {"rules/extra/__init__.py": HEAD + rule("NoExtra")}, ".rules", ["NoBadName", "NoUglyNameRule"]),
            ("module of a package", package, ".rules.ugly", ["NoUglyNameRule"]),
            ("package, sorted by name", {"rules/__init__.py": HEAD + rule("Zed"), "rules/a.py": HEAD + rule("Alpha")}, ".rules", ["Alpha", "Zed"]),
            ("rule in a module of a package", package, ".rules:NoUglyNameRule", ["NoUglyNameRule"]),
            ("directory without __init__.py", {"rules/bad.py": HEAD + rule("NoBadName"), "rules/ugly.py": HEAD + rule("NoUglyNameRule")}, ".rules", ["NoBadName", "NoUglyNameRule"]),
            ("imported rules count", {"rules.py": "from .other import NoBadName\n", "other.py": HEAD + rule("NoBadName")}, ".rules", ["NoBadName"]),
            ("no rules", {"rules.py": "x = 1\n"}, ".rules", []),
            ("relative import", {"rules.py": "from .wording import M\n" + HEAD + rule("NoBadName"), "wording.py": "M = 1\n"}, ".rules", ["NoBadName"]),
            ("relative import to the parent", {"rules/__init__.py": "", "rules/bad.py": "from ..wording import M\n" + HEAD + rule("NoBadName"), "wording.py": "M = 1\n"}, ".rules", ["NoBadName"]),
        )  # fmt: skip
        for label, tree, text, expected in cases:
            with self.subTest(label), files(tree) as root:
                self.assertEqual(
                    names(import_rules(RuleName.parse(text, root))), expected
                )

    def test_errors(self) -> None:
        dependency = "import nope_dependency\n" + BOTH
        cases = (
            # (label, files, name, message, with the directory at the end)
            ("no module", {}, ".nope", "could not import rule(s) .nope from", True),
            ("no module in a package", {"rules/__init__.py": ""}, ".rules.nope", "could not import rule(s) .rules.nope from", True),
            ("no rule of the name", {"rules.py": BOTH}, ".rules:Nope", "could not find rule .rules:Nope in", True),
            ("an import in it fails", {"rules.py": dependency}, ".rules", "could not import rule(s) .rules from", False),
        )  # fmt: skip
        for label, tree, text, message, at_end in cases:
            with self.subTest(label), files(tree) as root:
                with self.assertRaises(CollectionError) as caught:
                    import_rules(RuleName.parse(text, root))
                error = str(caught.exception)
                self.assertTrue(error.startswith(f"{message} {root}"), error)
                if at_end:
                    self.assertEqual(error, f"{message} {root}")
                else:
                    self.assertIn(
                        "ModuleNotFoundError: No module named 'nope_dependency'", error
                    )

    def test_other_errors_are_not_caught(self) -> None:
        cases = (
            ("raises", {"rules.py": 'raise RuntimeError("boom")\n'}, RuntimeError),
            ("syntax error", {"rules.py": "def f(:\n"}, SyntaxError),
            (
                "above the config directory",
                {"rules.py": "from ..x import M\n"},
                ImportError,
            ),
        )
        for label, tree, error in cases:
            with self.subTest(label), files(tree) as root, self.assertRaises(error):
                import_rules(RuleName.parse(".rules", root))

    def test_imported_once(self) -> None:
        with files({"rules.py": 'print("imported")\n' + BOTH}) as root:
            first = import_rules(RuleName.parse(".rules", root))
            again = import_rules(RuleName.parse(".rules:NoBadName", root))
            self.assertIs(first[0], again[0])

    def test_two_directories(self) -> None:
        tree = {
            "rules.py": HEAD + rule("NoBadName"),
            "sub/rules.py": HEAD + rule("NoUglyNameRule"),
        }
        with files(tree) as root:
            top = import_rules(RuleName.parse(".rules", root))
            sub = import_rules(RuleName.parse(".rules", root / "sub"))
            self.assertEqual(
                (names(top), names(sub)), (["NoBadName"], ["NoUglyNameRule"])
            )

    def test_installed_package(self) -> None:
        tree = {"cookie/__init__.py": "", "cookie/rules.py": BOTH}
        with files(tree, on_path=True) as root:
            self.assertEqual(
                names(import_rules(RuleName.parse("cookie.rules", root))),
                ["NoBadName", "NoUglyNameRule"],
            )
            self.assertEqual(
                names(import_rules(RuleName.parse("cookie.rules:NoBadName", root))),
                ["NoBadName"],
            )
            for text, message in (
                ("nope.rules", "could not import rule(s) nope.rules"),
                ("cookie.rules:Nope", "could not find rule cookie.rules:Nope"),
            ):
                with self.subTest(text), self.assertRaises(CollectionError) as caught:
                    import_rules(RuleName.parse(text, root))
                self.assertEqual(str(caught.exception), message)

    def test_builtin_rules(self) -> None:
        builtin = import_rules(RuleName("tukuroi.rules"))
        self.assertEqual(len(builtin), 7)
        use_assert_in = tuple(r for r in builtin if r.name() == "UseAssertIn")
        cases = (
            # (name, rules)
            ("tukuroi.rules:UseAssertIn", use_assert_in),
            ("tukuroi.rules.use_assert_in", use_assert_in),
        )
        for text, rules in cases:
            with self.subTest(text):
                self.assertEqual(import_rules(RuleName.parse(text, Path("/r"))), rules)
        errors = (
            # (name, message)
            ("tukuroi.rules:NoRedundantFString", "could not find rule tukuroi.rules:NoRedundantFString"),
            ("tukuroi.rules.nope", "could not import rule(s) tukuroi.rules.nope"),
            ("tukuroi.rulesx", "could not import rule(s) tukuroi.rulesx"),
        )  # fmt: skip
        for text, message in errors:
            with self.subTest(text), self.assertRaises(CollectionError) as caught:
                import_rules(RuleName.parse(text, Path("/r")))
            self.assertEqual(str(caught.exception), message)


KETTLE = {"src/kettle/__init__.py": "", "src/kettle/rules.py": HEAD + rule("NoBadName")}


class LoadTest(TestCase):
    """``load``: the rules of one name, or why they cannot be loaded (#40)."""

    def setUp(self) -> None:
        loader._ROOT_IMPORTED.clear()

    def tearDown(self) -> None:
        self.setUp()

    def error(self, root: Path, text: str, root_import: Path | None = None) -> str:
        """The message of the CollectionError that loading ``text`` raises."""
        with self.assertRaises(CollectionError) as caught:
            load(RuleName.parse(text, root), root_import)
        return str(caught.exception).replace(str(root), "ROOT")

    def test_rules(self) -> None:
        with files({"rules.py": BOTH}) as root:
            rules = load(RuleName.parse(".rules", root))
        self.assertEqual([r.name() for r in rules], ["NoBadName", "NoUglyName"])

    def test_errors(self) -> None:
        cases = (
            # (label, files, name, error)
            ("no module", {}, ".nope", "could not import rule(s) .nope from ROOT"),
            ("no rule of the name", {"rules.py": BOTH}, ".rules:X", "could not find rule .rules:X in ROOT"),
            ("raises", {"rules.py": 'raise RuntimeError("boom")\n'}, ".rules", "could not import rule(s) .rules from ROOT: RuntimeError: boom"),
            ("no rules in it", {"rules.py": "x = 1\n"}, ".rules", "no rules in .rules from ROOT"),
            ("installed, no module", {}, "nope.rules", "could not import rule(s) nope.rules"),
        )  # fmt: skip
        for label, tree, text, error in cases:
            with self.subTest(label), files(tree) as root:
                self.assertEqual(self.error(root, text), error)

    def test_traceback_in_the_debug_log(self) -> None:
        with (
            files({"rules.py": 'raise RuntimeError("boom")\n'}) as root,
            self.assertLogs("tukuroi.config", "DEBUG") as logs,
        ):
            self.error(root, ".rules")
        [record] = logs.records
        self.assertEqual(record.getMessage(), "Exception while importing .rules")
        self.assertIsNotNone(record.exc_info)

    def test_enable_root_import(self) -> None:
        with files(KETTLE) as root:
            path = list(sys.path)
            rules = load(RuleName.parse("kettle.rules", root), root / "src")
            self.assertEqual([r.name() for r in rules], ["NoBadName"])
            self.assertEqual(sys.path, path)
            other = "could not import rule(s) kettle.rules: imported from another root, ROOT/src"
            self.assertEqual(self.error(root, "kettle.rules", root / "b"), other)


class CollectRulesTest(TestCase):
    maxDiff = None

    def setUp(self) -> None:
        loader._WARNED.clear()
        loader._ROOT_IMPORTED.clear()

    def tearDown(self) -> None:
        self.setUp()

    def collect(
        self,
        root: Path,
        enable: Sequence[str],
        disable: Sequence[str] = (),
        **options: object,
    ) -> tuple[list[str], list[str]]:
        """The names of the rules collected, and the warnings."""
        parse = lambda text: RuleName.parse(text, root)
        with self.assertLogs("tukuroi.config", "WARNING") as logs:
            logging.getLogger("tukuroi.config").warning("start")
            rules = collect_rules(
                [parse(t) for t in enable],
                [parse(t) for t in disable],
                **options,  # type: ignore[arg-type]
            )
        warnings = [r.getMessage().replace(str(root), "ROOT") for r in logs.records[1:]]
        return [r.name() for r in rules], warnings

    def error(
        self,
        root: Path,
        enable: Sequence[str],
        disable: Sequence[str] = (),
        **options: object,
    ) -> str:
        """The message of the CollectionError that collecting the rules raises."""
        parse = lambda text: RuleName.parse(text, root)
        with self.assertRaises(CollectionError) as caught:
            collect_rules(
                [parse(t) for t in enable],
                [parse(t) for t in disable],
                **options,  # type: ignore[arg-type]
            )
        return str(caught.exception).replace(str(root), "ROOT")

    def test_enable_and_disable(self) -> None:
        cases = (
            # (label, enable, disable, rules)
            ("module", [".rules"], [], ["NoBadName", "NoUglyName"]),
            ("1 rule", [".rules:NoBadName"], [], ["NoBadName"]),
            ("module and 1 rule of it", [".rules", ".rules:NoBadName"], [], ["NoBadName", "NoUglyName"]),
            ("disable 1 rule", [".rules"], [".rules:NoBadName"], ["NoUglyName"]),
            ("disable the module", [".rules"], [".rules"], []),
            ("the rule named survives", [".rules", ".rules:NoBadName"], [".rules"], ["NoBadName"]),
            ("disable a rule not enabled", [".rules:NoBadName"], [".rules:NoUglyName"], ["NoBadName"]),
        )  # fmt: skip
        for label, enable, disable, expected in cases:
            with self.subTest(label), files({"rules.py": BOTH}) as root:
                self.assertEqual(self.collect(root, enable, disable), (expected, []))

    def test_more_specific_name_wins(self) -> None:
        # A rule over a module, and a module over its package (#40). The
        # libcst engine told a rule from a module only.
        tree = {
            "rules/__init__.py": "",
            "rules/bad.py": HEAD + rule("NoBadName"),
            "rules/ugly.py": HEAD + rule("NoUglyNameRule"),
        }
        cases = (
            # (label, enable, disable, rules)
            ("a module over its package", [".rules.bad"], [".rules"], ["NoBadName"]),
            ("a package under a module", [".rules"], [".rules.bad"], ["NoUglyName"]),
            ("a rule over its module", [".rules.bad:NoBadName"], [".rules.bad"], ["NoBadName"]),
            ("a module under a rule", [".rules.bad"], [".rules.bad:NoBadName"], []),
            # As specific: `disable` wins.
            ("the same module", [".rules.bad"], [".rules.bad"], []),
            ("a rule by its package and by its module", [".rules:NoBadName"], [".rules.bad:NoBadName"], []),
            ("the most specific name of each", [".rules", ".rules.bad:NoBadName"], [".rules.bad", ".rules"], ["NoBadName"]),
        )  # fmt: skip
        for label, enable, disable, expected in cases:
            with self.subTest(label), files(tree) as root:
                self.assertEqual(self.collect(root, enable, disable), (expected, []))

    def test_errors(self) -> None:
        # Each was a warning, and the other rules were collected (#40).
        cases = (
            # (label, files, enable, disable, error)
            ("no module", {"rules.py": BOTH}, [".nope", ".rules:NoBadName"], [], "could not import rule(s) .nope from ROOT"),
            ("raises", {"rules.py": 'raise RuntimeError("boom")\n'}, [".rules"], [], "could not import rule(s) .rules from ROOT: RuntimeError: boom"),
            ("no rules in it", {"rules.py": "x = 1\n"}, [".rules"], [], "no rules in .rules from ROOT"),
            ("no rules, 1 rule named", {"rules.py": "x = 1\n"}, [".rules:X"], [], "could not find rule .rules:X in ROOT"),
            ("disable a module that fails", {"rules.py": BOTH}, [".rules"], [".nope"], "could not import rule(s) .nope from ROOT"),
            ("disable a module with no rules", {"rules.py": BOTH, "empty.py": ""}, [".rules"], [".empty"], "no rules in .empty from ROOT"),
        )  # fmt: skip
        for label, tree, enable, disable, error in cases:
            with self.subTest(label), files(tree) as root:
                self.assertEqual(self.error(root, enable, disable), error)

    def test_sorted_by_name(self) -> None:
        names = [f"Rule{c}" for c in "HGFEDCBA"]
        module = HEAD + "".join(rule(n) for n in names)
        with files({"rules.py": module}) as root:
            self.assertEqual(
                self.collect(root, [".rules"]),
                (sorted(n.removesuffix("Rule") or n for n in names), []),
            )

    def test_installed_package_after_a_root_import(self) -> None:
        tree = {"cookie/__init__.py": "", "cookie/rules.py": BOTH}
        with files(tree, on_path=True) as root:
            rules = ["NoBadName", "NoUglyName"]
            self.assertEqual(
                self.collect(root, ["cookie.rules"], root_import=root / "src"),
                (rules, []),
            )
            self.assertEqual(self.collect(root, ["cookie.rules"]), (rules, []))

    def test_a_warning_once(self) -> None:
        with files({"rules.py": BOTH}) as root:
            first = self.collect(root, [".rules"], custom_rules=False)
            again = self.collect(root, [".rules"], custom_rules=False)
        self.assertEqual((len(first[1]), again[1]), (1, []))

    def test_custom_rules_turned_off(self) -> None:
        with files({"rules.py": BOTH} | KETTLE) as root:
            result = self.collect(
                root,
                [".rules", "kettle.rules"],
                [".rules:NoBadName", ".nope"],
                root_import=root / "src",
                custom_rules=False,
            )
            skipped = "Skipped rules '{}': custom rules are turned off"
            warnings = [skipped.format(".rules"), skipped.format("kettle.rules")]
            self.assertEqual(result, ([], warnings))
            self.assertNotIn("kettle", sys.modules)
            with patch.object(loader, "_on_path", wraps=loader._on_path) as on_path:
                collect_rules([], [], root_import=root / "src", custom_rules=False)
            on_path.assert_called_once_with(None)

    def test_builtin(self) -> None:
        cases = (
            ("tukuroi.rules", True),
            ("tukuroi.rules:NoStaticIfCondition", True),
            ("tukuroi.rules.no_static_if_condition", True),
            ("tukuroi.rulesx", False),
            ("tukuroi.upgrade", False),
            (".tukuroi.rules", False),
            ("cookie.rules", False),
        )
        for text, builtin in cases:
            with self.subTest(text):
                self.assertIs(is_builtin(RuleName.parse(text, Path("/r"))), builtin)

    def test_enable_root_import(self) -> None:
        with files(KETTLE) as root:
            path = list(sys.path)
            self.assertEqual(
                self.collect(root, ["kettle.rules"], root_import=root / "src"),
                (["NoBadName"], []),
            )
            self.assertEqual(sys.path, path)
        with files(KETTLE) as root:
            self.setUp()
            error = "could not import rule(s) kettle.rules"
            self.assertEqual(self.error(root, ["kettle.rules"]), error)

    def test_package_of_another_root(self) -> None:
        tree = {f"a/{k}": v for k, v in KETTLE.items()} | {
            f"b/{k}": v for k, v in KETTLE.items()
        }
        with files(tree) as root:
            a, b = root / "a" / "src", root / "b" / "src"
            self.assertEqual(
                self.collect(root / "a", ["kettle.rules"], root_import=a),
                (["NoBadName"], []),
            )
            other = f"could not import rule(s) kettle.rules: imported from another root, {a}"
            error = self.error(root / "b", ["kettle.rules"], root_import=b)
            self.assertEqual(error, other)
            self.assertEqual(
                self.collect(root / "a", ["kettle.rules"], root_import=a),
                (["NoBadName"], []),
            )
            self.setUp()
            loader._ROOT_IMPORTED["kettle"] = a
            self.assertEqual(self.error(root / "b", ["kettle.rules"]), other)
