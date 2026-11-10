# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Characterization tests for ``fixit fix``: the file after ``--automatic``, the
output of ``--diff``, and the output of ``fix -`` (stdin).

They run the CLI only, so that the engine rewrite (#21) can be checked against
them. The expected values are copied from the output of the libcst engine.
``NOTE`` marks behavior that looks wrong but is pinned as is.

The CLI runs the new engine (#21). It runs ``ruff format`` on each file it
fixes, so the fixed results here are what ``ruff format`` writes, and most
sources are left as is by it (``test_sources_are_stable_under_ruff_format``).
The new engine does not apply a fix that drops a comment inside the range it
replaces, and applies fixes that overlap in order, round by round.
"""

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from .characterization_cli import (
    CLEAN,
    DIRTY,
    DIRTY_A,
    DIRTY_F,
    CharacterizationTestCase,
    Run,
    config,
    invoke,
    line,
    records,
)

UI = "UseAssertIn"
NA = "NoAssertTrueForComparisons"
NN = "UseAssertIsNotNone"
SI = "NoStaticIfCondition"
NT = "NoNamedTuple"
SA = "SortedAttributes"
VC = "VariadicCallableSyntax"

IMPORT_NT = "from typing import NamedTuple\n\n\n"
IMPORT_CB = "from typing import Callable\n\n"
DC = "@dataclass(frozen=True)\n"
# NoNamedTuple imports dataclass after the imports (#21, issuecomment-6709426366);
# ruff format then puts 2 blank lines after it.
IMPORT_DC = "from typing import NamedTuple\nfrom dataclasses import dataclass\n\n\n"
DOC = '    """@sorted-attributes"""\n\n'
A40 = "a" * 40
A60 = "a" * 60
DIRTY_FF = (
    "🛠️  1 file checked, 1 file with errors, 2 auto-fixes available, 2 fixes applied 🛠️\n"
)

# (rule, source, position reported, the file after `fix --automatic`)
FIXES = (
    (UI, "self.assertTrue(a in b)\n", "1:0", "self.assertIn(a, b)\n"),
    (UI, "self.assertTrue(a not in b)\n", "1:0", "self.assertNotIn(a, b)\n"),
    (UI, "self.assertTrue(not a in b)\n", "1:0", "self.assertNotIn(a, b)\n"),
    (UI, "self.assertFalse(a in b)\n", "1:0", "self.assertNotIn(a, b)\n"),
    (
        UI,
        "x = 1\r\nself.assertTrue(a in b)\r\n",
        "2:0",
        "x = 1\r\nself.assertIn(a, b)\r\n",
    ),
    (NA, "self.assertTrue(a, 3)\n", "1:0", "self.assertEqual(a, 3)\n"),
    (NA, "self.assertTrue(a, [1, 2])\n", "1:0", "self.assertEqual(a, [1, 2])\n"),
    (NA, "self.assertTrue(a, None)\n", "1:0", "self.assertIsNone(a)\n"),
    (NA, "self.assertTrue(a, True)\n", "1:0", "self.assertTrue(a)\n"),
    (NA, "self.assertTrue(a, False)\n", "1:0", "self.assertFalse(a)\n"),
    (NA, "self.assertTrue(a, 3)  # c\n", "1:0", "self.assertEqual(a, 3)  # c\n"),
    (NN, "self.assertTrue(a is not None)\n", "1:0", "self.assertIsNotNone(a)\n"),
    (NN, "self.assertTrue(a is None)\n", "1:0", "self.assertIsNone(a)\n"),
    (NN, "self.assertFalse(a is not None)\n", "1:0", "self.assertIsNone(a)\n"),
    (NN, "self.assertTrue(not a is None)\n", "1:0", "self.assertIsNotNone(a)\n"),
    (NN, "self.assertFalse(not a is not None)\n", "1:0", "self.assertIsNotNone(a)\n"),
    (
        SA,
        f"class C:\n{DOC}    x: int\n    b = 1\n    a = 2\n",
        "1:0",
        f"class C:\n{DOC}    x: int\n    a = 2\n    b = 1\n",
    ),
    (
        SA,
        f"class C:\n{DOC}    x: int\n    b = 1\n    # c\n    a = 2\n",
        "1:0",
        f"class C:\n{DOC}    x: int\n    # c\n    a = 2\n    b = 1\n",
    ),
    (
        SA,
        f"class C:\n{DOC}    x: int\n    c = 1\n    b = 2\n    a = 3\n\n    def f(self):\n        pass\n",
        "1:0",
        f"class C:\n{DOC}    x: int\n    a = 3\n    b = 2\n    c = 1\n\n    def f(self):\n        pass\n",
    ),
    (
        VC,
        f"{IMPORT_CB}x: Callable[[...], int]\n",
        "3:3",
        f"{IMPORT_CB}x: Callable[..., int]\n",
    ),
    (
        VC,
        "import typing\n\nx: typing.Callable[[...], int]\n",
        "3:3",
        "import typing\n\nx: typing.Callable[..., int]\n",
    ),
    (
        VC,
        "from typing import Callable as C\n\nx: C[[...], int]\n",
        "3:3",
        "from typing import Callable as C\n\nx: C[..., int]\n",
    ),
    # The fix alone leaves ")" after the arguments; ruff format puts it on its
    # own line.
    (
        UI,
        f"self.assertTrue(\n    {A40} in {A40}\n)\n",
        "1:0",
        f"self.assertIn(\n    {A40}, {A40}\n)\n",
    ),
    # ruff format joins the call into one line.
    (
        NA,
        f"self.assertTrue(\n    {A40},\n    None,\n)\n",
        "1:0",
        f"self.assertIsNone({A40})\n",
    ),
    (
        NN,
        f"self.assertTrue(\n    {A60} is not None\n)\n",
        "1:0",
        f"self.assertIsNotNone({A60})\n",
    ),
    # The blank line above `b` moves with it.
    (
        SA,
        f"class C:\n{DOC}    b = 1\n    a = 2\n",
        "1:0",
        f"class C:\n{DOC}    a = 2\n\n    b = 1\n",
    ),
    # ruff format keeps each element on its own line, for the trailing comma.
    (
        VC,
        f"{IMPORT_CB}x: Callable[\n    [...],\n    int,\n]\n",
        "3:3",
        f"{IMPORT_CB}x: Callable[\n    ...,\n    int,\n]\n",
    ),
    (
        NT,
        f"{IMPORT_NT}class Foo(NamedTuple):\n    a: int\n",
        "4:0",
        f"{IMPORT_DC}{DC}class Foo:\n    a: int\n",
    ),
    (
        NT,
        "import typing\n\n\nclass Foo(typing.NamedTuple):\n    a: int\n",
        "4:0",
        f"import typing\nfrom dataclasses import dataclass\n\n\n{DC}class Foo:\n    a: int\n",
    ),
    (
        NT,
        f"{IMPORT_NT}@deco\nclass Foo(NamedTuple):\n    a: int\n",
        "5:0",
        f"{IMPORT_DC}@deco\n{DC}class Foo:\n    a: int\n",
    ),
    (
        NT,
        f"{IMPORT_NT}class Foo(NamedTuple, Base):\n    a: int\n",
        "4:0",
        f"{IMPORT_DC}{DC}class Foo(Base):\n    a: int\n",
    ),
    (
        NT,
        f"{IMPORT_NT}class Foo(Base, NamedTuple):\n    a: int\n",
        "4:0",
        f"{IMPORT_DC}{DC}class Foo(Base):\n    a: int\n",
    ),
    (
        NT,
        f"{IMPORT_NT}class Foo(NamedTuple, metaclass=M):\n    a: int\n",
        "4:0",
        f"{IMPORT_DC}{DC}class Foo(metaclass=M):\n    a: int\n",
    ),
    (
        NT,
        f"{IMPORT_NT}class C:\n    class Foo(NamedTuple):\n        a: int\n",
        "5:4",
        f"{IMPORT_DC}class C:\n    {DC}    class Foo:\n        a: int\n",
    ),
    (
        NT,
        f"{IMPORT_NT}class Foo(NamedTuple):  # c\n    a: int\n",
        "4:0",
        f"{IMPORT_DC}{DC}class Foo:  # c\n    a: int\n",
    ),
)

# (label, rules, source, (rule, position) reported, the file after, summary,
# exit code: 1 if a violation is left after the fixes, #40)
MULTI = (
    (
        "same rule, 2 lines",
        (UI,),
        "self.assertTrue(a in b)\nx = 1\nself.assertFalse(c in d)\n",
        ((UI, "1:0"), (UI, "3:0")),
        "self.assertIn(a, b)\nx = 1\nself.assertNotIn(c, d)\n",
        DIRTY_FF,
        0,
    ),
    (
        "same rule, 1 line",
        (VC,),
        f"{IMPORT_CB}\ndef f(a: Callable[[...], int]) -> Callable[[...], str]:\n    pass\n",
        ((VC, "4:9"), (VC, "4:34")),
        f"{IMPORT_CB}\ndef f(a: Callable[..., int]) -> Callable[..., str]:\n    pass\n",
        DIRTY_FF,
        0,
    ),
    (
        "2 rules",
        (UI, NA),
        "self.assertTrue(a in b)\nself.assertTrue(c, 3)\n",
        ((UI, "1:0"), (NA, "2:0")),
        "self.assertIn(a, b)\nself.assertEqual(c, 3)\n",
        DIRTY_FF,
        0,
    ),
    (
        "2 rules, statement in block",
        (UI, NN),
        "if x:\n    self.assertTrue(a in b)\nself.assertTrue(c is not None)\n",
        ((UI, "2:4"), (NN, "3:0")),
        "if x:\n    self.assertIn(a, b)\nself.assertIsNotNone(c)\n",
        DIRTY_FF,
        0,
    ),
    (
        "with no autofix",
        (UI, SI),
        "if True:\n    self.assertTrue(a in b)\n",
        ((SI, "1:0"), (UI, "2:4")),
        "if True:\n    self.assertIn(a, b)\n",
        DIRTY_F,
        1,
    ),
    (
        "same rule, 2 classes",
        (NT,),
        f"{IMPORT_NT}class Foo(NamedTuple):\n    a: int\n\n\nclass Bar(NamedTuple):\n    b: int\n",
        ((NT, "4:0"), (NT, "8:0")),
        f"{IMPORT_DC}{DC}class Foo:\n    a: int\n\n\n{DC}class Bar:\n    b: int\n",
        DIRTY_FF,
        0,
    ),
)

# No two of the rules report the same call. These fixes are inside each other:
# the engine applies the outer one, and the inner one in the next round, as it
# lints the result again (#21).
# (label, rules, source, (rule, position) reported, the file after)
NESTED = (
    (
        "call in call",
        (UI, NA),
        "self.assertTrue(a in self.assertTrue(x, 3))\n",
        ((UI, "1:0"), (NA, "1:21")),
        "self.assertIn(a, self.assertEqual(x, 3))\n",
    ),
    (
        "subscript in call",
        (NA, VC),
        f"{IMPORT_CB}self.assertTrue(Callable[[...], int], None)\n",
        ((NA, "3:0"), (VC, "3:16")),
        f"{IMPORT_CB}self.assertIsNone(Callable[..., int])\n",
    ),
    (
        "annotation in class",
        (NT, VC),
        "from typing import Callable, NamedTuple\n\n\nclass Foo(NamedTuple):\n    f: Callable[[...], int]\n",
        ((NT, "4:0"), (VC, "5:7")),
        f"from typing import Callable, NamedTuple\nfrom dataclasses import dataclass\n\n\n{DC}class Foo:\n    f: Callable[..., int]\n",
    ),
    (
        "class in class",
        (NT,),
        f"{IMPORT_NT}class Foo(NamedTuple):\n    class Bar(NamedTuple):\n        a: int\n",
        # The outer class is reported first: the reports are in the order of
        # their position.
        ((NT, "4:0"), (NT, "5:4")),
        f"{IMPORT_DC}{DC}class Foo:\n    {DC}    class Bar:\n        a: int\n",
    ),
)

# (label, rules, source, (rule, position) reported, the file after, summary)
SUPPRESSED = (
    (
        "1 of 2 ignored",
        (UI,),
        "self.assertTrue(a in b)  # lint-ignore\nself.assertTrue(c in d)\n",
        ((UI, "2:0"),),
        "self.assertTrue(a in b)  # lint-ignore\nself.assertIn(c, d)\n",
        DIRTY_F,
    ),
    (
        "fixme above",
        (UI,),
        f"# lint-fixme: {UI}\nself.assertTrue(a in b)\nself.assertTrue(c in d)\n",
        ((UI, "3:0"),),
        f"# lint-fixme: {UI}\nself.assertTrue(a in b)\nself.assertIn(c, d)\n",
        DIRTY_F,
    ),
    (
        "names the rule",
        (UI, NA),
        f"self.assertTrue(a in b)  # lint-ignore: {UI}\nself.assertTrue(c, 3)\n",
        ((NA, "2:0"),),
        f"self.assertTrue(a in b)  # lint-ignore: {UI}\nself.assertEqual(c, 3)\n",
        DIRTY_F,
    ),
    (
        "names another rule",
        (UI, NA),
        f"self.assertTrue(a in b)  # lint-ignore: {NA}\nself.assertTrue(c, 3)\n",
        ((UI, "1:0"), (NA, "2:0")),
        f"self.assertIn(a, b)  # lint-ignore: {NA}\nself.assertEqual(c, 3)\n",
        DIRTY_FF,
    ),
    (
        "outer call ignored",
        (UI, NA),
        f"self.assertTrue(a in self.assertTrue(x, 3))  # lint-ignore: {UI}\n",
        ((NA, "1:21"),),
        f"self.assertTrue(a in self.assertEqual(x, 3))  # lint-ignore: {UI}\n",
        DIRTY_F,
    ),
    (
        "if ignored, call in body",
        (UI, SI),
        "# lint-ignore\nif True:\n    self.assertTrue(a in b)\n",
        ((UI, "3:4"),),
        "# lint-ignore\nif True:\n    self.assertIn(a, b)\n",
        DIRTY_F,
    ),
)

# NoNamedTuple and SortedAttributes report the same class; both fixes are
# applied. (source, the file after)
ONE_CLASS = (
    f"{IMPORT_NT}class Foo(NamedTuple):\n{DOC}    x: int\n    b = 1\n    a = 2\n",
    f"{IMPORT_DC}{DC}class Foo:\n{DOC}    x: int\n    a = 2\n    b = 1\n",
)

DIFF_SOURCE = "x = 1\nself.assertTrue(a in b)\ny = 2\n"


def diff(*lines: str, path: str = "t.py") -> str:
    head = f"--- a/{path}\n+++ b/{path}\n"
    if path.startswith("/"):
        head = f"--- {path}\n+++ {path}\n"
    return head + "".join(f"{x}\n" for x in lines)


DIFF = diff(
    "@@ -1,3 +1,3 @@",
    " x = 1",
    "-self.assertTrue(a in b)",
    "+self.assertIn(a, b)",
    " y = 2",
)

# In a file that is not formatted, ruff format changes the rest of the file too.
# (source, the file after `fix --automatic`)
UNFORMATTED = (
    (
        "x=1\nself.assertTrue( a  in  b )\ny = [1,2]\n",
        "x = 1\nself.assertIn(a, b)\ny = [1, 2]\n",
    ),
    # It adds the newline at the end.
    ("x = 1\nself.assertTrue(a in b)", "x = 1\nself.assertIn(a, b)\n"),
)

# A comment inside the range that the fix replaces, kept in the result: the
# fixes of the new engine (#21) edit the name of the method and the arguments,
# not the whole call.
# (rule, source, position reported, the file after `fix --automatic`)
COMMENTS = (
    (
        NA,
        "self.assertTrue(\n    a,  # c\n    3,\n)\n",
        "1:0",
        "self.assertEqual(\n    a,  # c\n    3,\n)\n",
    ),
    (
        UI,
        "self.assertTrue(\n    a in b  # c\n)\n",
        "1:0",
        "self.assertIn(\n    a,\n    b,  # c\n)\n",
    ),
    (
        NN,
        "self.assertTrue(\n    a is not None  # c\n)\n",
        "1:0",
        "self.assertIsNotNone(\n    a  # c\n)\n",
    ),
    # The fix drops the argument before the comment.
    (
        NA,
        "self.assertTrue(\n    a,\n    None,  # c\n)\n",
        "1:0",
        "self.assertIsNone(\n    a  # c\n)\n",
    ),
    (
        VC,
        f"{IMPORT_CB}x: Callable[\n    [...],  # c\n    int,\n]\n",
        "3:3",
        f"{IMPORT_CB}x: Callable[\n    ...,  # c\n    int,\n]\n",
    ),
    (
        UI,
        "self.assertTrue(  # c\n    a in b\n)\n",
        "1:0",
        "self.assertIn(  # c\n    a, b\n)\n",
    ),
    (
        NN,
        "self.assertTrue(  # c\n    a is not None\n)\n",
        "1:0",
        "self.assertIsNotNone(  # c\n    a\n)\n",
    ),
)

# The fix would drop the comment inside the range it replaces, so the engine
# does not apply it (#21): the line ends without " (has autofix)", the summary
# counts no auto-fix, and the file is left as is.
# (rule, source, position reported)
COMMENTS_DROPPED = (
    (NT, f"{IMPORT_NT}class Foo(\n    NamedTuple,  # c\n):\n    a: int\n", "4:0"),
)


def fix(rules: tuple[str, ...], source: str, *args: str) -> Run:
    files = {"pyproject.toml": config(*rules), "t.py": source}
    return invoke(files, ["fix", "--automatic", *args, "t.py"])


def in_t(reported: tuple[tuple[str, str], ...]) -> list[tuple[str, str, str]]:
    """``(rule, position)`` -> ``("t.py", rule, position)``"""
    return [("t.py", rule, position) for rule, position in reported]


def ruff_format(*sources: str) -> list[str]:
    """Return each of ``sources`` after ``ruff format``, run once for all."""
    with TemporaryDirectory() as td:
        paths = [Path(td) / f"t{i}.py" for i in range(len(sources))]
        for path, source in zip(paths, sources, strict=True):
            path.write_bytes(source.encode())
        args = ["-m", "ruff", "format", "--isolated", "--quiet", *map(str, paths)]
        subprocess.run([sys.executable, *args], check=True)
        return [path.read_bytes().decode() for path in paths]


class FixCharacterizationTest(CharacterizationTestCase):
    def test_fix_each_rule(self) -> None:
        for rule, source, position, fixed in FIXES:
            with self.subTest(rule, source=source):
                result = fix((rule,), source)
                self.assertEqual(result.stdout, line("t.py", rule, position))
                self.assertEqual(result.stderr, DIRTY_F)
                # Fixed: no violation is left (#40).
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.files["t.py"], fixed)

    def test_fix_two_places_in_one_file(self) -> None:
        for label, rules, source, reported, fixed, summary, exit_code in MULTI:
            with self.subTest(label):
                result = fix(rules, source)
                self.assert_violations(result.stdout, in_t(reported))
                self.assertEqual(result.stderr, summary)
                self.assertEqual(result.exit_code, exit_code)
                self.assertEqual(result.files["t.py"], fixed)

    def test_fix_inside_another_fix(self) -> None:
        for label, rules, source, reported, fixed in NESTED:
            with self.subTest(label):
                result = fix(rules, source)
                self.assert_violations(result.stdout, in_t(reported))
                self.assertEqual(result.stderr, DIRTY_FF)
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.files["t.py"], fixed)

    def test_fix_two_rules_on_one_class(self) -> None:
        source, fixed = ONE_CLASS
        result = fix((NT, SA), source)
        self.assert_violations(result.stdout, in_t(((NT, "4:0"), (SA, "4:0"))))
        self.assertEqual(result.stderr, DIRTY_FF)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.files["t.py"], fixed)

    def test_fix_with_suppression(self) -> None:
        for label, rules, source, reported, fixed, summary in SUPPRESSED:
            with self.subTest(label):
                result = fix(rules, source)
                self.assert_violations(result.stdout, in_t(reported))
                self.assertEqual(result.stderr, summary)
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.files["t.py"], fixed)

    def test_fix_without_autofix_leaves_file_unchanged(self) -> None:
        # The exit code is 1 if a violation is left (#40).
        cases = (
            ("no autofix", SI, "if True:\n    pass\n", ((SI, "1:0"),), DIRTY, 1),
            ("clean", UI, "x = 1\n", (), CLEAN, 0),
            (
                "all ignored",
                UI,
                "self.assertTrue(a in b)  # lint-ignore\n",
                (),
                CLEAN,
                0,
            ),
            # Not formatted: `ruff format` changes these.
            (
                "no autofix, not formatted",
                SI,
                "if True:\n  pass\n",
                ((SI, "1:0"),),
                DIRTY,
                1,
            ),
            ("clean, not formatted", UI, "x=1\n", (), CLEAN, 0),
        )
        for label, rule, source, reported, summary, exit_code in cases:
            with self.subTest(label):
                result = fix((rule,), source)
                self.assert_violations(result.stdout, in_t(reported))
                self.assertEqual(result.stderr, summary)
                self.assertEqual(result.exit_code, exit_code)
                self.assertEqual(result.files["t.py"], source)

    def test_diff(self) -> None:
        cases = (
            ("1 fix", (UI,), DIFF_SOURCE, ((UI, "2:0", DIFF),), DIRTY_A),
            (
                "2 rules",
                (UI, NA),
                "self.assertTrue(a in b)\nx = 1\ny = 2\nself.assertTrue(c, 3)\n",
                (
                    (
                        UI,
                        "1:0",
                        diff(
                            "@@ -1,2 +1,2 @@",
                            "-self.assertTrue(a in b)",
                            "+self.assertIn(a, b)",
                            " x = 1",
                        ),
                    ),
                    (
                        NA,
                        "4:0",
                        diff(
                            "@@ -3,2 +3,2 @@",
                            " y = 2",
                            "-self.assertTrue(c, 3)",
                            "+self.assertEqual(c, 3)",
                        ),
                    ),
                ),
                "🛠️  1 file checked, 1 file with errors, 2 auto-fixes available 🛠️\n",
            ),
            (
                "class",
                (NT,),
                f"{IMPORT_NT}class Foo(NamedTuple):\n    a: int\n",
                (
                    (
                        NT,
                        "4:0",
                        # With the import of dataclass (#21).
                        diff(
                            "@@ -1,5 +1,7 @@",
                            " from typing import NamedTuple",
                            "+from dataclasses import dataclass",
                            " ",
                            " ",
                            "-class Foo(NamedTuple):",
                            "+@dataclass(frozen=True)",
                            "+class Foo:",
                            "     a: int",
                        ),
                    ),
                ),
                DIRTY_A,
            ),
            (
                "sorted attributes",
                (SA,),
                f"class C:\n{DOC}    x: int\n    b = 1\n    a = 2\n",
                (
                    (
                        SA,
                        "1:0",
                        diff(
                            "@@ -4,3 +4,3 @@",
                            "     x: int",
                            "+    a = 2",
                            "     b = 1",
                            "-    a = 2",
                        ),
                    ),
                ),
                DIRTY_A,
            ),
            ("no autofix", (SI,), "if True:\n    pass\n", ((SI, "1:0", ""),), DIRTY),
        )
        for label, rules, source, reported, summary in cases:
            with self.subTest(label):
                files = {"pyproject.toml": config(*rules), "t.py": source}
                result = invoke(files, ["lint", "--diff", "t.py"])
                expected = [line("t.py", r, p) + diff for r, p, diff in reported]
                if len(rules) == 1:
                    self.assertEqual(result.stdout, "".join(expected))
                else:
                    self.assertEqual(records(result.stdout), sorted(expected))
                self.assertEqual(result.stderr, summary)
                self.assertEqual(result.exit_code, 1)
                self.assertEqual(result.files, files)

    def test_diff_names_the_file_as_the_violation(self) -> None:
        # The path of the violation (#40): the libcst engine gave the name of
        # the file only ("a/t.py").
        lines = DIFF.splitlines()[2:]
        files = {"pyproject.toml": config(UI), "sub/t.py": DIFF_SOURCE}
        cases = (
            # (label, cwd, args, path)
            ("in a directory", ".", ["sub/t.py"], "sub/t.py"),
            ("stdin", ".", ["-", "sub/u.py"], "sub/u.py"),
            # Outside the current directory: absolute, without a/ and b/.
            ("outside", "sub/deep", ["../t.py"], None),
        )
        for label, cwd, args, path in cases:
            with self.subTest(label):
                before = {**files, "sub/deep/x": ""}
                result = invoke(
                    before, ["lint", "--diff", *args], cwd=cwd, stdin=DIFF_SOURCE
                )
                path = path or f"{result.root}/sub/t.py"
                expected = line(path, UI, "2:0") + diff(*lines, path=path)
                self.assertEqual(result.stdout, expected)
                self.assertEqual(result.exit_code, 1)

    def test_fix_with_diff(self) -> None:
        result = fix((UI,), DIFF_SOURCE, "--diff")
        self.assertEqual(result.stdout, line("t.py", UI, "2:0") + DIFF)
        self.assertEqual(result.stderr, DIRTY_F)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.files["t.py"], "x = 1\nself.assertIn(a, b)\ny = 2\n")

    def test_fix_stdin_writes_the_result_to_stdout(self) -> None:
        two = "self.assertTrue(a in b)\nself.assertTrue(c, 3)\n"
        cases = (
            (
                "fixed",
                (UI,),
                DIFF_SOURCE,
                "x = 1\nself.assertIn(a, b)\ny = 2\n",
                ((UI, "2:0"),),
                DIRTY_F,
                0,
            ),
            (
                "2 rules",
                (UI, NA),
                two,
                "self.assertIn(a, b)\nself.assertEqual(c, 3)\n",
                ((UI, "1:0"), (NA, "2:0")),
                DIRTY_FF,
                0,
            ),
            (
                "no autofix",
                (SI,),
                "if True:\n    pass\n",
                "if True:\n    pass\n",
                ((SI, "1:0"),),
                DIRTY,
                1,
            ),
            ("clean", (UI,), "x = 1\n", "x = 1\n", (), CLEAN, 0),
            # Not formatted: `ruff format` changes it.
            ("clean, not formatted", (UI,), "x=1\n", "x=1\n", (), CLEAN, 0),
        )
        for label, rules, source, fixed, reported, summary, exit_code in cases:
            with self.subTest(label):
                files = {"pyproject.toml": config(*rules)}
                result = invoke(files, ["fix", "-", "t.py"], stdin=source)
                self.assertEqual(result.stdout, fixed)
                self.assertTrue(result.stderr.endswith(summary))
                violations = result.stderr.removesuffix(summary)
                self.assert_violations(violations, in_t(reported))
                # 1 if a violation is left (#40).
                self.assertEqual(result.exit_code, exit_code)
                self.assertEqual(result.files, files)

    def test_fix_stdin_with_diff(self) -> None:
        files = {"pyproject.toml": config(UI)}
        result = invoke(files, ["fix", "--diff", "-", "t.py"], stdin=DIFF_SOURCE)
        # The diff goes to stderr, with the violation (#40): the libcst engine
        # printed it to stdout, before the fixed source.
        self.assertEqual(result.stdout, "x = 1\nself.assertIn(a, b)\ny = 2\n")
        self.assertEqual(result.stderr, line("t.py", UI, "2:0") + DIFF + DIRTY_F)
        self.assertEqual(result.exit_code, 0)

    def test_fix_formats_the_whole_file(self) -> None:
        for source, fixed in UNFORMATTED:
            with self.subTest("file", source=source):
                result = fix((UI,), source)
                self.assertEqual(result.stdout, line("t.py", UI, "2:0"))
                self.assertEqual(result.stderr, DIRTY_F)
                self.assertEqual(result.files["t.py"], fixed)
            with self.subTest("stdin", source=source):
                files = {"pyproject.toml": config(UI)}
                result = invoke(files, ["fix", "-", "t.py"], stdin=source)
                self.assertEqual(result.stdout, fixed)
                self.assertEqual(result.stderr, line("t.py", UI, "2:0") + DIRTY_F)

    def test_fix_keeps_a_comment_in_its_range(self) -> None:
        for rule, source, position, fixed in COMMENTS:
            with self.subTest(rule, source=source):
                result = fix((rule,), source)
                self.assertEqual(result.stdout, line("t.py", rule, position))
                self.assertEqual(result.stderr, DIRTY_F)
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.files["t.py"], fixed)

    def test_fix_that_drops_a_comment_is_not_applied(self) -> None:
        for rule, source, position in COMMENTS_DROPPED:
            with self.subTest(rule, source=source):
                result = fix((rule,), source)
                no_fix = line("t.py", rule, position).replace(" (has autofix)", "")
                self.assertEqual(result.stdout, no_fix)
                self.assertEqual(result.stderr, DIRTY)
                # The violation is left (#40).
                self.assertEqual(result.exit_code, 1)
                self.assertEqual(result.files["t.py"], source)

    def test_sources_are_stable_under_ruff_format(self) -> None:
        # Not a test of fixit: checks that the cases above fit the new engine.
        pairs = [(source, fixed) for _, source, _, fixed in FIXES + COMMENTS]
        pairs += [(row[2], row[4]) for row in MULTI + NESTED + SUPPRESSED]
        pairs += [ONE_CLASS]
        pairs += [(DIFF_SOURCE, "x = 1\nself.assertIn(a, b)\ny = 2\n")]
        stable = [text for pair in pairs for text in pair]
        stable += [source for _, source, _ in COMMENTS_DROPPED]
        stable += [fixed for _, fixed in UNFORMATTED]
        for source, formatted in zip(stable, ruff_format(*stable), strict=True):
            with self.subTest(source=source):
                self.assertEqual(formatted, source)
        sources = [source for source, _ in UNFORMATTED]
        for source, formatted in zip(sources, ruff_format(*sources), strict=True):
            with self.subTest("not formatted", source=source):
                self.assertNotEqual(formatted, source)
