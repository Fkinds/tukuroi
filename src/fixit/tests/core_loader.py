# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``fixit.core.loader``: the names of rules, and how the modules of
rules are imported, from the repo and from installed packages. The cases come
from the characterization tests of the libcst engine
(``characterization_custom_rules.py``): the cases marked ``#21`` there, with
what #21 decided (issuecomment-6706326492), and the others as they are.
"""

import sys
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from ..core.loader import CollectionError, RuleName, import_rules

HEAD = "import ast\n\nfrom fixit.core.rule import Rule\n"


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
            ("fixit.rules", "fixit.rules", None, None),
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
        for text in ("..rules", "a b", "", "x:", ":X", "a:b:c", "fixit.rules:"):
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
