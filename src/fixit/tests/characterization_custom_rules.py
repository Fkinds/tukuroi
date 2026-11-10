# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Characterization tests for custom rules: the rules in the repo (".rules"), the
rules of an installed package ("pkg.rules"), ``enable-root-import``, the
warnings when rules fail to load, custom rules with the other settings, and
``fixit test``.

They run the CLI only, so that the engine rewrite (#21) can be checked against
them. The expected values are copied from the output of the libcst engine.
``NOTE`` marks behavior that looks wrong but is pinned as is. The CLI runs the
new engine (#21), and the custom rules use its API. #21 rebuilt how custom rules
are loaded, and fixed the behavior that the libcst engine had there
(issuecomment-6706326492); the comments of those cases tell what changed.

The CLI imports the rules in this process; ``run`` puts ``sys.path`` and
``sys.modules`` back after each run.
"""

import os
import re
import sys
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from .characterization_cli import (
    CLEAN,
    DIRTY,
    DIRTY_A,
    DIRTY_F,
    CharacterizationTestCase,
    Run,
    invoke,
    records,
)
from .characterization_config import override, toml
from .characterization_suppression import MESSAGES

BAD = "NoBadName"
UGLY = "NoUglyName"  # The class is NoUglyNameRule.
SI = "NoStaticIfCondition"
MESSAGE = {BAD: "Use good, not bad.", UGLY: "Do not use ugly."}
# BAD reports line 1 with an autofix, UGLY line 2 and SI line 3 without.
SOURCE = "bad = 1\nugly = 2\nif True:\n    pass\n"
POSITION = {BAD: "1:0", UGLY: "2:0", SI: "3:0"}
PRINTED = {BAD: f"{MESSAGE[BAD]} (has autofix)", UGLY: MESSAGE[UGLY], SI: MESSAGES[SI]}

# The rules use the API of the new engine (#21).
HEAD = "import ast\n\nfrom fixit.core.rule import Invalid, Rule, Valid\n"


def rule(cls: str, name: str, message: str, fix: str = "") -> str:
    """A rule ``cls`` that reports ``name`` with ``message`` (an expression)."""
    expected = f', expected_replacement="{fix} = 1\\n"' if fix else ""
    replacement = f', replacement="{fix}"' if fix else ""
    return (
        f"\n\nclass {cls}(Rule):\n"
        f"    MESSAGE = {message}\n"
        '    VALID = (Valid("good = 1\\n"),)\n'
        f'    INVALID = (Invalid("{name} = 1\\n"{expected}),)\n\n'
        "    def visit_Name(self, node: ast.Name) -> None:\n"
        f'        if node.id == "{name}":\n'
        f"            self.report(node{replacement})\n"
    )


BAD_PY = HEAD + rule(BAD, "bad", repr(MESSAGE[BAD]), "good")
UGLY_PY = HEAD + rule(f"{UGLY}Rule", "ugly", repr(MESSAGE[UGLY]))
BOTH_PY = BAD_PY + rule(f"{UGLY}Rule", "ugly", repr(MESSAGE[UGLY]))
EXTRA_PY = HEAD + rule("NoExtraName", "ugly", "'In a sub-package.'")


def importing(statement: str) -> str:
    """BAD, with its message imported by ``statement``."""
    return HEAD + statement + "\n" + rule(BAD, "bad", "MESSAGE", "good")


FAILING_PY = HEAD + (
    "from fixit.core.text import Position\n\n\n"
    f"class {BAD}(Rule):\n"
    f"    MESSAGE = {MESSAGE[BAD]!r}\n"
    "    VALID = (\n"
    '        "good = 1\\n",\n'
    '        Valid("bad = 1\\n"),  # reported\n'
    "    )\n"
    "    INVALID = (\n"
    '        "bad = 1\\n",\n'
    '        Invalid("good = 1\\n"),  # not reported\n'
    '        Invalid("bad = 1\\n", expected_replacement="good = 1\\n"),\n'
    '        Invalid("bad = 1\\n", expected_replacement="best = 1\\n"),\n'
    f'        Invalid("bad = 1\\n", {MESSAGE[BAD]!r}, "good = 1\\n"),\n'
    '        Invalid("bad = 1\\n", "Other.", "good = 1\\n"),\n'
    '        Invalid("bad = 1\\n", None, "good = 1\\n", Position(1, 0)),\n'
    '        Invalid("bad = 1\\n", None, "good = 1\\n", Position(1, 3)),\n'
    '        Invalid("boom = 1\\n"),  # raises\n'
    '        Invalid("bad = bad\\n", expected_replacement="good = good\\n"),\n'
    "    )\n\n"
    "    def visit_Name(self, node: ast.Name) -> None:\n"
    '        if node.id == "boom":\n'
    '            raise RuntimeError("boom")\n'
    '        if node.id == "bad":\n'
    '            self.report(node, replacement="good")\n'
)
# (test of FAILING_PY, its result), in the order that unittest runs them.
FAILING_RESULTS = (
    # A case with a fix needs an expected replacement (#21).
    ("INVALID_0", "FAIL"),
    ("INVALID_1", "FAIL"),
    ("INVALID_2", "ok"),
    ("INVALID_3", "FAIL"),
    ("INVALID_4", "ok"),
    ("INVALID_5", "FAIL"),
    ("INVALID_6", "ok"),
    ("INVALID_7", "FAIL"),
    ("INVALID_8", "ERROR"),
    ("INVALID_9", "ok"),  # reported twice
    ("VALID_0", "ok"),
    ("VALID_1", "FAIL"),
)
PASSED = (("INVALID_0", "ok"), ("VALID_0", "ok"))

PACKAGE = {"rules/__init__.py": BAD_PY, "rules/ugly.py": UGLY_PY}
# Not loaded with the package; it would report line 2.
SUB_PACKAGE = {"rules/extra/__init__.py": EXTRA_PY}
NAMESPACE = {"rules/bad.py": BAD_PY, "rules/ugly.py": UGLY_PY}
COOKIE = {"cookie/__init__.py": "", "cookie/rules.py": BOTH_PY}
KETTLE = {"kettle/__init__.py": "", "kettle/rules.py": BAD_PY}
WORDING = {"wording.py": f"MESSAGE = {MESSAGE[BAD]!r}\n"}

# Formatted with the directory run in, after the run.
FROM_ROOT, IN_ROOT, FROM_SUB = " from {root}", " in {root}", " from {root}/sub"
TWO = "🛠️  2 files checked, {} 🛠️\n"
TWO_FIXED = TWO.format("2 files with errors, 2 auto-fixes available, 2 fixes applied")
SEP1, SEP2 = "=" * 70, "-" * 70
TRACEBACK = re.compile(r"^Traceback .*?(?=^(?:={70}|-{70})$)", re.MULTILINE | re.DOTALL)
TIME = re.compile(r"^(Ran \d+ tests) in \d+\.\d+s$", re.MULTILINE)


def names(key: str, *rules: str) -> str:
    return f"{key} = [{', '.join(f'"{r}"' for r in rules)}]"


def root(*enable: str, disable: Sequence[str] = (), lines: Sequence[str] = ()) -> str:
    """A root config that runs ``enable``, and no built-in rule."""
    disable = names("disable", "fixit.rules", *disable)
    return toml("root = true", *lines, names("enable", *enable), disable)


def found(rule: str, path: str = "t.py") -> str:
    return f"{path}@{POSITION[rule]} {rule}: {PRINTED[rule]}\n"


def failed(rule: str, error: str) -> str:
    return f"WARNING:fixit.config:Failed to load rules '{rule}': {error}\n"


def no_import(rule: str, where: str = "") -> str:
    return failed(rule, f"CollectionError: could not import rule(s) {rule}{where}")


def no_rule(rule: str, where: str = "") -> str:
    error = f"CollectionError: could not find rule {rule}{where}"
    return failed(rule.partition(":")[0], error)


def summary(rules: Collection[str]) -> str:
    return DIRTY_A if BAD in rules else DIRTY if rules else CLEAN


# The process pool of `lint` starts new interpreters: sys.dont_write_bytecode
# does not reach them.
ENV = {"PYTHON_COLORS": "0", "PYTHONDONTWRITEBYTECODE": "1"}


def run(
    files: Mapping[str, str],
    args: Sequence[str],
    *,
    cwd: str = ".",
    site: Mapping[str, str] | None = None,
) -> Run:
    """
    ``invoke``, with ``site`` written to a directory on ``sys.path``: an
    installed package.

    ``sys.path`` and ``sys.modules`` are put back afterwards. No ``.pyc`` is
    written, by this process or the process pool of ``lint``: ``invoke`` reads
    every file back as text. "" (the current directory, added by ``python
    -c``) is taken off ``sys.path``, as when the ``fixit`` script runs. Python
    colors the output of unittest when FORCE_COLOR is set; PYTHON_COLORS=0
    turns it off for ``fixit test``.
    """
    path, before, bytecode = sys.path[:], set(sys.modules), sys.dont_write_bytecode
    with TemporaryDirectory() as td, patch.dict(os.environ, ENV):
        lib = Path(td).resolve()
        for name, text in (site or {}).items():
            (lib / name).parent.mkdir(parents=True, exist_ok=True)
            (lib / name).write_text(text)
        dirs = [lib.as_posix()]
        sys.path[:] = [p for p in path if p] + ([lib.as_posix()] if site else [])
        sys.dont_write_bytecode = True
        try:
            result = invoke(files, args, cwd=cwd)
            dirs.append(result.root)
        finally:
            sys.path[:] = path
            sys.dont_write_bytecode = bytecode
            forget(before, tuple(dirs))
    return result


def forget(before: Collection[str], dirs: tuple[str, ...]) -> None:
    """
    Remove the modules imported from ``dirs`` that were not in ``before``, and
    the importers of ``dirs``.
    """

    def within(place: str) -> bool:
        return any(place == d or place.startswith(f"{d}/") for d in dirs)

    def places(name: str) -> list[str]:
        spec = getattr(sys.modules[name], "__spec__", None)
        if spec is None:
            return []
        return [spec.origin or "", *(spec.submodule_search_locations or ())]

    # Find them all first: the path of a namespace package is read from its
    # parent, which may be among them (the package of the new loader, #21).
    doomed = [n for n in sys.modules.keys() - before if any(map(within, places(n)))]
    for name in doomed:
        del sys.modules[name]
    for key in [k for k in sys.path_importer_cache if within(k)]:
        del sys.path_importer_cache[key]


def lint(
    config: str,
    files: Mapping[str, str],
    path: str = "t.py",
    *,
    cwd: str = ".",
    site: Mapping[str, str] | None = None,
) -> Run:
    """``fixit lint <path>`` in ``cwd``, with SOURCE in ``path``."""
    before = {"pyproject.toml": config, **files, f"{cwd}/{path}": SOURCE}
    return run(before, ["lint", path], cwd=cwd, site=site)


def syntax_error(source: str, filename: str) -> str:
    """The message of the SyntaxError in ``source``, as Python words it."""
    try:
        compile(source, filename, "exec")
    except SyntaxError as e:
        return f"SyntaxError: {e}"
    raise AssertionError(f"no SyntaxError in {source!r}")


def outcome(stderr: str) -> tuple[list[str], str]:
    """
    The output of ``fixit test``: the lines before the first blank line, sorted,
    and the rest, without the tracebacks and the time.

    The rules run in set order, so the order of their tests changes between runs.
    """
    head, _, tail = stderr.partition("\n\n")
    lines = sorted(f"{head}\n".splitlines(keepends=True))
    return lines, TIME.sub(r"\1", TRACEBACK.sub("", tail))


def ran(cls: str, *results: tuple[str, str]) -> list[str]:
    """``(test, result)`` -> the line of ``fixit test`` for the test of ``cls``."""
    return [f"test_{t} (fixit.testing.{cls}.test_{t}) ... {r}\n" for t, r in results]


def footer(count: int, status: str, *failures: str) -> str:
    blocks = "".join(f"{SEP1}\n{failure}\n{SEP2}\n" for failure in failures)
    return f"{blocks}{SEP2}\nRan {count} tests\n\n{status}\n"


class CustomRulesCharacterizationTest(CharacterizationTestCase):
    def assert_lint(
        self, result: Run, rules: Sequence[str], warning: str = "", path: str = "t.py"
    ) -> None:
        self.assertEqual(records(result.stdout), sorted(found(r, path) for r in rules))
        warning = warning.format(root=result.root)
        self.assertEqual(result.stderr, warning + summary(rules))
        self.assertEqual(result.exit_code, 1 if rules else 0)

    def test_rules_in_the_repo(self) -> None:
        both = {"rules.py": BOTH_PY}
        cases = (
            ("module, all rules", both, ".rules", (BAD, UGLY)),
            ("module, 1 rule", both, f".rules:{BAD}", (BAD,)),
            ("class name ending in Rule", both, f".rules:{UGLY}Rule", (UGLY,)),
            ("package", PACKAGE | SUB_PACKAGE, ".rules", (BAD, UGLY)),
            ("module of a package", PACKAGE, ".rules.ugly", (UGLY,)),
            ("rule in a module of a package", PACKAGE, f".rules:{UGLY}Rule", (UGLY,)),
            ("directory without __init__.py", NAMESPACE, ".rules", (BAD, UGLY)),
        )
        for label, files, enable, rules in cases:
            with self.subTest(label):
                self.assert_lint(lint(root(enable), files), rules)

    def test_rules_in_the_repo_are_found_from_the_config(self) -> None:
        enable = names("enable", ".rules")
        sub = {"sub/pyproject.toml": toml(enable)}
        in_sub = {"rules.py": UGLY_PY, "sub/rules.py": BAD_PY}
        in_root = {"rules.py": BAD_PY, "sub/rules.py": UGLY_PY}
        deeper = sub | in_sub | {"sub/deep/rules.py": UGLY_PY}
        enables = root() + override("sub", enable)
        disable = names("disable", f".rules:{BAD}")
        disables = root(f".rules:{BAD}") + override("sub", disable)
        only_root, r, no_sub = (
            {"rules.py": BAD_PY},
            root(".rules"),
            no_import(".rules", FROM_SUB),
        )
        cases = (
            # (label, config, files, path, rules, warning)
            ("sub config", root(), sub | in_sub, "sub/t.py", (BAD,), ""),
            ("sub config, file deeper", root(), deeper, "sub/deep/t.py", (BAD,), ""),
            ("no sub/rules.py", root(), sub | only_root, "sub/t.py", (), no_sub),
            ("override enables", enables, in_root, "sub/t.py", (BAD,), ""),
            ("override disables", disables, in_root, "sub/t.py", (), ""),
        )
        for label, config, files, path, rules, warning in cases:
            with self.subTest(label):
                self.assert_lint(lint(config, files, path), rules, warning, path)
        with self.subTest("root config, cwd sub"):
            result = lint(r, in_root, cwd="sub")
            self.assert_lint(result, (BAD,))

    def test_rules_in_the_repo_of_root_and_sub_configs(self) -> None:
        # The new loader tells ".rules" of each config apart by its directory
        # (#21), as the docs say: under sub/, the rules of sub/rules.py run too,
        # and the sub config disables only sub/rules.py.
        sub = {"sub/pyproject.toml": toml(names("enable", ".rules"))}
        in_root = {"rules.py": BAD_PY, "sub/rules.py": UGLY_PY}
        sub_off = {"sub/pyproject.toml": toml(names("disable", ".rules"))}
        only_root, r = {"rules.py": BAD_PY}, root(".rules")
        no_sub = no_import(".rules", FROM_SUB)
        cases = (
            # (label, config, files, path, rules, warning)
            ("root and sub", r, sub | in_root, "sub/t.py", (BAD, UGLY), ""),
            # In the sub config, ".rules" stands for sub/rules.py, which does not
            # exist.
            ("sub disables", r, sub_off | only_root, "sub/t.py", (BAD,), no_sub),
        )
        for label, config, files, path, rules, warning in cases:
            with self.subTest(label):
                self.assert_lint(lint(config, files, path), rules, warning, path)

    def test_relative_imports_in_rules_in_the_repo(self) -> None:
        package = {
            "rules/__init__.py": "",
            "rules/bad.py": importing("from ..wording import MESSAGE"),
        }
        cases = (
            ("same directory", {"rules.py": importing("from .wording import MESSAGE")}),
            ("package to its parent", package),
        )
        for label, files in cases:
            with self.subTest(label):
                self.assert_lint(lint(root(".rules"), WORDING | files), (BAD,))

    def test_relative_import_above_the_config_directory(self) -> None:
        # The new loader stops ".." at the config directory (#21): the import
        # fails, the rules do not load, and a warning tells why. The libcst
        # engine let ".." reach the `fixit` package.
        above = importing(f"from ..core import rule\n\nMESSAGE = {MESSAGE[BAD]!r}")
        result = lint(root(".rules"), WORDING | {"rules.py": above})
        error = "ImportError: attempted relative import beyond top-level package"
        self.assert_lint(result, (), failed(".rules", error))

    def test_installed_rules(self) -> None:
        cases = (
            ("cookie.rules", (BAD, UGLY), ""),
            (f"cookie.rules:{BAD}", (BAD,), ""),
            ("nope.rules", (), no_import("nope.rules")),
            ("cookie.rules:Nope", (), no_rule("cookie.rules:Nope")),
        )
        for enable, rules, warning in cases:
            with self.subTest(enable):
                result = lint(root(enable), {}, site=COOKIE)
                self.assert_lint(result, rules, warning)

    def test_enable_root_import(self) -> None:
        src = {f"src/{name}": text for name, text in KETTLE.items()}
        imports = src | {
            "src/kettle/wording.py": WORDING["wording.py"],
            "src/kettle/rules.py": importing("from kettle.wording import MESSAGE"),
        }
        absolute = WORDING | {"rules.py": importing("from wording import MESSAGE")}
        no_kettle = no_import("kettle.rules")
        cases = (
            # (label, value, files, enable, rules, warning)
            ("not set", None, KETTLE, "kettle.rules", (), no_kettle),
            ("true", "true", KETTLE, "kettle.rules", (BAD,), ""),
            ("path", '"src"', src, "kettle.rules", (BAD,), ""),
            ("true, package in src", "true", src, "kettle.rules", (), no_kettle),
            ("rule imports its package", '"src"', imports, "kettle.rules", (BAD,), ""),
            ("repo rule imports", "true", absolute, ".rules", (BAD,), ""),
        )
        for label, value, files, enable, rules, warning in cases:
            with self.subTest(label):
                lines = [f"enable-root-import = {value}"] if value else []
                result = lint(root(enable, lines=lines), files)
                self.assert_lint(result, rules, warning)
        with self.subTest("file under a child config"):
            sub = {"sub/pyproject.toml": toml(names("enable", "kettle.rules"))}
            config = root(lines=["enable-root-import = true"])
            result = lint(config, KETTLE | sub, "sub/t.py")
            self.assert_lint(result, (BAD,), path="sub/t.py")

    def test_enable_root_import_invalid(self) -> None:
        with self.subTest("not in the root config"):
            sub = {"sub/pyproject.toml": toml("enable-root-import = true")}
            result = lint(root(), sub, "sub/t.py")
            error = "enable-root-import not allowed in non-root configs"
            # With the path of the config, without a traceback (#40).
            where = "sub/t.py: EXCEPTION: sub/pyproject.toml"
            self.assertEqual(result.stdout, f"{where}: {error}\n")
            self.assertEqual(result.stderr, DIRTY)
            self.assertEqual(result.exit_code, 2)
        cases = (
            ('"/src"', "enable-root-import: absolute paths not allowed"),
            ('"../src"', "enable-root-import: '..' components not allowed"),
            # Only a bool or a relative path that is not empty (#21).
            ("1", "enable-root-import: 1 is not a bool or a relative path"),
            ('""', "enable-root-import: '' is not a bool or a relative path"),
        )
        for value, message in cases:
            with self.subTest(value):
                result = lint(root(lines=[f"enable-root-import = {value}"]), {})
                # Without a traceback, before any file is linted (#40).
                self.assertEqual(result.stderr, f"Error: pyproject.toml: {message}\n")
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.exit_code, 2)

    def run_two_roots(self, enable: str) -> Run:
        """``fix`` a/t.py, which imports kettle.rules, then b/t.py with ``enable``."""
        config = root("kettle.rules", lines=["enable-root-import = true"])
        a = {f"a/{name}": text for name, text in KETTLE.items()} | {
            "a/pyproject.toml": config,
            "a/spoon/__init__.py": "",
            "a/spoon/rules.py": UGLY_PY,
            "a/t.py": SOURCE,
        }
        b = {"b/pyproject.toml": root(enable), "b/t.py": SOURCE}
        before = {"pyproject.toml": toml("root = true"), **a, **b}
        return run(before, ["fix", "--automatic", "a/t.py", "b/t.py"])

    def test_enable_root_import_of_another_root(self) -> None:
        result = self.run_two_roots("spoon.rules")
        # a/ is not on sys.path for b/t.py.
        self.assertEqual(result.stdout, found(BAD, "a/t.py"))
        one = "1 file with errors, 1 auto-fix available, 1 fix applied"
        self.assertEqual(result.stderr, no_import("spoon.rules") + TWO.format(one))
        self.assertEqual(result.exit_code, 0)

    def test_module_imported_for_another_root(self) -> None:
        # The new loader does not use a module imported for another root (#21):
        # b/t.py logs a warning and runs no rule. The libcst engine ran, for
        # b/t.py, the rules that a/t.py imported first.
        result = self.run_two_roots("kettle.rules")
        self.assertEqual(result.stdout, found(BAD, "a/t.py"))
        other = f"imported from another root, {result.root}/a"
        one = "1 file with errors, 1 auto-fix available, 1 fix applied"
        warning = failed(
            "kettle.rules",
            f"CollectionError: could not import rule(s) kettle.rules: {other}",
        )
        self.assertEqual(result.stderr, warning + TWO.format(one))
        self.assertEqual(result.exit_code, 0)

    def test_rules_in_the_repo_that_fail_to_load(self) -> None:
        broken, boom = "def f(:\n", 'raise RuntimeError("boom")\n'
        nope = no_rule(".rules:Nope", IN_ROOT)
        syntax = failed(".rules", syntax_error(broken, "rules.py"))
        cases = (
            # (label, rules.py, enable, warning)
            ("no module", None, ".nope", no_import(".nope", FROM_ROOT)),
            ("no rule of the name", BOTH_PY, ".rules:Nope", nope),
            ("raises", boom, ".rules", failed(".rules", "RuntimeError: boom")),
            ("syntax error", broken, ".rules", syntax),
        )
        for label, module, enable, warning in cases:
            with self.subTest(label):
                result = lint(root(enable), {"rules.py": module} if module else {})
                # NOTE: a rule that fails to load only logs a warning.
                self.assert_lint(result, (), warning)

    def test_why_rules_in_the_repo_fail_to_load(self) -> None:
        dependency = "import nope_dependency\n" + BAD_PY
        absolute = WORDING | {"rules.py": importing("from wording import MESSAGE")}

        def missing(module: str) -> str:
            error = f"ModuleNotFoundError: No module named {module!r}"
            return no_import(".rules", f"{FROM_ROOT}: {error}")

        no_rules = "WARNING:fixit.config:No rules in '.rules'" + FROM_ROOT + "\n"
        # The libcst engine did not find the name that its output shows, gave
        # no error of the import that failed, and nothing for a module without
        # rules (#21).
        cases = (
            # (label, config, files, rules, warning)
            # A name with or without "Rule".
            ("name without Rule", root(f".rules:{UGLY}"), {"rules.py": BOTH_PY}, (UGLY,), ""),
            # The error of the import that failed.
            ("import in it fails", root(".rules"), {"rules.py": dependency}, (), missing("nope_dependency")),
            ("repo rule imports, not set", root(".rules"), absolute, (), missing("wording")),
            ("no rules in it", root(".rules"), {"rules.py": "x = 1\n"}, (), no_rules),
        )  # fmt: skip
        for label, config, files, rules, warning in cases:
            with self.subTest(label):
                self.assert_lint(lint(config, files), rules, warning)

    def test_invalid_name_of_a_rule_in_the_repo(self) -> None:
        # The name of the parent of the config directory, as in `from .. import`.
        result = lint(root("..rules"), {"rules.py": BOTH_PY})
        # Without a traceback, before any file is linted (#40).
        error = "Error: pyproject.toml: invalid rule name '..rules'\n"
        self.assertEqual(result.stderr, error)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.exit_code, 2)

    def test_custom_rule_with_a_built_in_rule(self) -> None:
        result = lint(root(f"fixit.rules:{SI}", f".rules:{BAD}"), {"rules.py": BOTH_PY})
        self.assert_lint(result, (BAD, SI))

    def assert_disable(
        self, enable: Sequence[str], disable: Sequence[str], rules: Sequence[str]
    ) -> None:
        result = lint(
            root(*enable, disable=disable), {"rules.py": BOTH_PY}, site=COOKIE
        )
        self.assertEqual(records(result.stdout), sorted(map(found, rules)))
        bad = rules.count(BAD)
        twice = "🛠️  1 file checked, 1 file with errors, 2 auto-fixes available 🛠️\n"
        self.assertEqual(result.stderr, twice if bad == 2 else summary(rules))
        self.assertEqual(result.exit_code, 1 if rules else 0)

    def test_disable_custom_rules(self) -> None:
        r, c, cb = ".rules", "cookie.rules", f"cookie.rules:{BAD}"
        cases = (
            # (label, enable, disable, rules)
            ("1 rule, installed", (c,), (cb,), (UGLY,)),
            ("the module", (r,), (r,), ()),
            ("enable module and rule, installed", (c, cb), (), (BAD, UGLY)),
        )
        for label, enable, disable, rules in cases:
            with self.subTest(label):
                self.assert_disable(enable, disable, rules)

    def test_disable_custom_rules_in_the_repo(self) -> None:
        # The new loader imports a module once (#21), so a rule in the repo is
        # the same class however it is named, as for an installed package. The
        # libcst engine imported it again for each name, as another class.
        r, rb = ".rules", f".rules:{BAD}"
        cases = (
            # (label, enable, disable, rules)
            ("1 rule", (r,), (rb,), (UGLY,)),
            ("enable module and rule", (r, rb), (), (BAD, UGLY)),
        )
        for label, enable, disable, rules in cases:
            with self.subTest(label):
                self.assert_disable(enable, disable, rules)

    def test_lint_ignore_names_a_custom_rule(self) -> None:
        cases = ((BAD, 0, (UGLY,)), (UGLY, 1, (BAD,)), (f"{UGLY}Rule", 1, (BAD,)))
        for name, line, rules in cases:
            with self.subTest(name):
                comment = f"  # lint-ignore: {name}\n"
                source = "".join(
                    text.replace("\n", comment) if i == line else text
                    for i, text in enumerate(SOURCE.splitlines(keepends=True))
                )
                files = {"pyproject.toml": root(".rules"), "rules.py": BOTH_PY}
                result = run(files | {"t.py": source}, ["lint", "t.py"])
                self.assert_lint(result, rules)

    def test_fix_applies_the_fix_of_a_custom_rule(self) -> None:
        before = {"pyproject.toml": root(".rules"), "rules.py": BOTH_PY, "t.py": SOURCE}
        result = run(before, ["fix", "--automatic", "t.py"])
        self.assertEqual(records(result.stdout), sorted([found(BAD), found(UGLY)]))
        self.assertEqual(result.stderr, DIRTY_F)
        # The violation of the rule without a fix is left (#40).
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.files["t.py"], SOURCE.replace("bad", "good"))

    def test_rules_option_with_custom_rules(self) -> None:
        files = {"pyproject.toml": root(".rules"), "rules.py": BAD_PY}
        cases = (
            # (label, --rules, cwd, site, rules)
            ("in the repo", f".rules:{BAD}", ".", None, (BAD,)),
            # Found from the current directory, not from the config.
            ("in the repo, cwd sub", ".rules", "sub", None, (UGLY,)),
            ("installed", f"cookie.rules:{UGLY}Rule", ".", COOKIE, (UGLY,)),
        )
        for label, option, cwd, site, rules in cases:
            with self.subTest(label):
                args = ["--rules", option, "lint", "t.py"]
                before = files | {"sub/rules.py": UGLY_PY, f"{cwd}/t.py": SOURCE}
                self.assert_lint(run(before, args, cwd=cwd, site=site), rules)

    def test_rules_in_the_repo_are_imported_once(self) -> None:
        # The new loader imports a module once in a process (#21): "imported" is
        # printed once. The libcst engine ran the module again for each file.
        files = {"rules.py": 'print("imported")\n' + BAD_PY, "u.py": SOURCE}
        before = {"pyproject.toml": root(".rules"), "t.py": SOURCE, **files}
        result = run(before, ["fix", "--automatic", "t.py", "u.py"])
        expected = f"imported\n{found(BAD)}{found(BAD, 'u.py')}"
        self.assertEqual(result.stdout, expected)
        self.assertEqual(result.stderr, TWO_FIXED)
        self.assertEqual(result.exit_code, 0)

    def test_fixit_test_with_passing_rules(self) -> None:
        both_ran = sorted(ran(BAD, *PASSED) + ran(f"{UGLY}Rule", *PASSED))
        all_ = (both_ran, footer(4, "OK"))
        one = (ran(BAD, *PASSED), footer(2, "OK"))
        both, sub = {"rules.py": BOTH_PY}, {"rules.py": UGLY_PY, "sub/rules.py": BAD_PY}
        cases = (
            # (label, files, site, cwd, rules, output)
            ("module", both, None, ".", ".rules", all_),
            ("1 rule", both, None, ".", f".rules:{BAD}", one),
            # Found from the current directory.
            ("cwd sub", sub, None, "sub", ".rules", one),
            ("installed", {}, COOKIE, ".", "cookie.rules", all_),
        )
        for label, files, site, cwd, rules, output in cases:
            with self.subTest(label):
                result = run(files, ["test", rules], cwd=cwd, site=site)
                self.assertEqual(outcome(result.stderr), output)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.exit_code, 0)

    def test_fixit_test_with_failing_cases(self) -> None:
        result = run({"rules.py": FAILING_PY}, ["test", ".rules"])
        # unittest prints the errors, then the failures, each in the order run.
        failures = sorted((r, t) for t, r in FAILING_RESULTS if r != "ok")
        blocks = [f"{r}: test_{t} (fixit.testing.{BAD}.test_{t})" for r, t in failures]
        status = "FAILED (failures=6, errors=1)"
        output = (ran(BAD, *FAILING_RESULTS), footer(12, status, *blocks))
        self.assertEqual(outcome(result.stderr), output)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.exit_code, 1)

    def test_fixit_test_without_tests(self) -> None:
        # `fixit test` exits with 5 when no test ran, as unittest and pytest do
        # (#21). The libcst engine exited with 0.
        result = run({"rules.py": BOTH_PY}, ["test", ".rules:Nope"])
        warning = no_rule(".rules:Nope", IN_ROOT).format(root=result.root)
        self.assertEqual(outcome(result.stderr), ([warning], footer(0, "NO TESTS RAN")))
        self.assertEqual(result.exit_code, 5)

    def test_fixit_test_reads_the_config(self) -> None:
        # `fixit test` reads the config of the current directory (#21), so
        # kettle.rules is imported with enable-root-import, and its tests run.
        # The libcst engine read no config, and found no rule. The rules named
        # run, though the config disables them.
        lines = (
            "root = true",
            "enable-root-import = true",
            names("disable", "kettle.rules"),
        )
        config = {"pyproject.toml": toml(*lines)}
        result = run(KETTLE | config, ["test", "kettle.rules"])
        self.assertEqual(outcome(result.stderr), (ran(BAD, *PASSED), footer(2, "OK")))
        self.assertEqual(result.exit_code, 0)
