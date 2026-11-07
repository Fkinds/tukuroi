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

The new engine runs ``ruff format`` on each file it fixes, so the sources and
the fixed results here are left as is by ``ruff format``
(``test_sources_are_stable_under_ruff_format``). The methods marked ``#21`` pin
fixes whose result ``ruff format`` does change, and fixes that drop a comment
inside the range they replace, which the new engine does not apply.
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
    # NOTE: `dataclass` is not imported, and the NamedTuple import is left.
    (
        NT,
        f"{IMPORT_NT}class Foo(NamedTuple):\n    a: int\n",
        "4:0",
        f"{IMPORT_NT}{DC}class Foo:\n    a: int\n",
    ),
    (
        NT,
        "import typing\n\n\nclass Foo(typing.NamedTuple):\n    a: int\n",
        "4:0",
        f"import typing\n\n\n{DC}class Foo:\n    a: int\n",
    ),
    (
        NT,
        f"{IMPORT_NT}@deco\nclass Foo(NamedTuple):\n    a: int\n",
        "5:0",
        f"{IMPORT_NT}@deco\n{DC}class Foo:\n    a: int\n",
    ),
    (
        NT,
        f"{IMPORT_NT}class Foo(NamedTuple, Base):\n    a: int\n",
        "4:0",
        f"{IMPORT_NT}{DC}class Foo(Base):\n    a: int\n",
    ),
    (
        NT,
        f"{IMPORT_NT}class Foo(NamedTuple, metaclass=M):\n    a: int\n",
        "4:0",
        f"{IMPORT_NT}{DC}class Foo(metaclass=M):\n    a: int\n",
    ),
    (
        NT,
        f"{IMPORT_NT}class C:\n    class Foo(NamedTuple):\n        a: int\n",
        "5:4",
        f"{IMPORT_NT}class C:\n    {DC}    class Foo:\n        a: int\n",
    ),
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
)

# (label, rules, source, (rule, position) reported, the file after, summary)
MULTI = (
    (
        "same rule, 2 lines",
        (UI,),
        "self.assertTrue(a in b)\nx = 1\nself.assertFalse(c in d)\n",
        ((UI, "1:0"), (UI, "3:0")),
        "self.assertIn(a, b)\nx = 1\nself.assertNotIn(c, d)\n",
        DIRTY_FF,
    ),
    (
        "same rule, 1 line",
        (VC,),
        f"{IMPORT_CB}\ndef f(a: Callable[[...], int]) -> Callable[[...], str]:\n    pass\n",
        ((VC, "4:9"), (VC, "4:34")),
        f"{IMPORT_CB}\ndef f(a: Callable[..., int]) -> Callable[..., str]:\n    pass\n",
        DIRTY_FF,
    ),
    (
        "same rule, 2 classes",
        (NT,),
        f"{IMPORT_NT}class Foo(NamedTuple):\n    a: int\n\n\nclass Bar(NamedTuple):\n    b: int\n",
        ((NT, "4:0"), (NT, "8:0")),
        f"{IMPORT_NT}{DC}class Foo:\n    a: int\n\n\n{DC}class Bar:\n    b: int\n",
        DIRTY_FF,
    ),
    (
        "2 rules",
        (UI, NA),
        "self.assertTrue(a in b)\nself.assertTrue(c, 3)\n",
        ((UI, "1:0"), (NA, "2:0")),
        "self.assertIn(a, b)\nself.assertEqual(c, 3)\n",
        DIRTY_FF,
    ),
    (
        "2 rules, statement in block",
        (UI, NN),
        "if x:\n    self.assertTrue(a in b)\nself.assertTrue(c is not None)\n",
        ((UI, "2:4"), (NN, "3:0")),
        "if x:\n    self.assertIn(a, b)\nself.assertIsNotNone(c)\n",
        DIRTY_FF,
    ),
    (
        "with no autofix",
        (UI, SI),
        "if True:\n    self.assertTrue(a in b)\n",
        ((SI, "1:0"), (UI, "2:4")),
        "if True:\n    self.assertIn(a, b)\n",
        DIRTY_F,
    ),
)

# No two of the rules report the same call. These fixes are inside each other.
# (label, rules, source, (rule, position) reported, the file after)
NESTED = (
    (
        "call in call",
        (UI, NA),
        "self.assertTrue(a in self.assertTrue(x, 3))\n",
        ((UI, "1:0"), (NA, "1:21")),
        "self.assertIn(a, self.assertTrue(x, 3))\n",
    ),
    (
        "subscript in call",
        (NA, VC),
        f"{IMPORT_CB}self.assertTrue(Callable[[...], int], None)\n",
        ((NA, "3:0"), (VC, "3:16")),
        f"{IMPORT_CB}self.assertIsNone(Callable[[...], int])\n",
    ),
    (
        "annotation in class",
        (NT, VC),
        "from typing import Callable, NamedTuple\n\n\nclass Foo(NamedTuple):\n    f: Callable[[...], int]\n",
        ((NT, "4:0"), (VC, "5:7")),
        f"from typing import Callable, NamedTuple\n\n\n{DC}class Foo:\n    f: Callable[[...], int]\n",
    ),
    (
        "class in class",
        (NT,),
        f"{IMPORT_NT}class Foo(NamedTuple):\n    class Bar(NamedTuple):\n        a: int\n",
        # NOTE: the inner class is reported before the outer one.
        ((NT, "5:4"), (NT, "4:0")),
        f"{IMPORT_NT}{DC}class Foo:\n    class Bar(NamedTuple):\n        a: int\n",
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

# NoNamedTuple and SortedAttributes report the same class.
# (source, the file after SortedAttributes, the file after NoNamedTuple)
ONE_CLASS = (
    f"{IMPORT_NT}class Foo(NamedTuple):\n{DOC}    x: int\n    b = 1\n    a = 2\n",
    f"{IMPORT_NT}class Foo(NamedTuple):\n{DOC}    x: int\n    a = 2\n    b = 1\n",
    f"{IMPORT_NT}{DC}class Foo:\n{DOC}    x: int\n    b = 1\n    a = 2\n",
)

DIFF_SOURCE = "x = 1\nself.assertTrue(a in b)\ny = 2\n"


def diff(*lines: str) -> str:
    return "--- a/t.py\n+++ b/t.py\n" + "".join(f"{x}\n" for x in lines)


DIFF = diff(
    "@@ -1,3 +1,3 @@",
    " x = 1",
    "-self.assertTrue(a in b)",
    "+self.assertIn(a, b)",
    " y = 2",
)

# #21: the result of the fix is not what `ruff format` writes, so the new engine
# writes the last value instead.
# (rule, source, position reported, the file after, after `ruff format`)
FIXES_21 = (
    # #21: ruff format puts ")" on its own line.
    (
        UI,
        f"self.assertTrue(\n    {A40} in {A40}\n)\n",
        "1:0",
        f"self.assertIn(\n    {A40}, {A40})\n",
        f"self.assertIn(\n    {A40}, {A40}\n)\n",
    ),
    # #21: ruff format joins the call into one line.
    (
        NA,
        f"self.assertTrue(\n    {A40},\n    None,\n)\n",
        "1:0",
        f"self.assertIsNone(\n    {A40})\n",
        f"self.assertIsNone({A40})\n",
    ),
    # #21: ruff format joins the call into one line.
    (
        NN,
        f"self.assertTrue(\n    {A60} is not None\n)\n",
        "1:0",
        f"self.assertIsNotNone(\n    {A60})\n",
        f"self.assertIsNotNone({A60})\n",
    ),
    # #21: ruff format splits the bases, one per line, for the trailing comma.
    (
        NT,
        f"{IMPORT_NT}class Foo(Base, NamedTuple):\n    a: int\n",
        "4:0",
        f"{IMPORT_NT}{DC}class Foo(Base, ):\n    a: int\n",
        f"{IMPORT_NT}{DC}class Foo(\n    Base,\n):\n    a: int\n",
    ),
    # #21: ruff format adds the blank line after the docstring back.
    (
        SA,
        f"class C:\n{DOC}    b = 1\n    a = 2\n",
        "1:0",
        'class C:\n    """@sorted-attributes"""\n    a = 2\n\n    b = 1\n',
        f"class C:\n{DOC}    a = 2\n\n    b = 1\n",
    ),
    # #21: ruff format puts each element on its own line.
    (
        VC,
        f"{IMPORT_CB}x: Callable[\n    [...],\n    int,\n]\n",
        "3:3",
        f"{IMPORT_CB}x: Callable[\n    ..., int,\n]\n",
        f"{IMPORT_CB}x: Callable[\n    ...,\n    int,\n]\n",
    ),
)

# #21: in a file that is not formatted, the fix changes only its own range;
# the new engine formats the whole file.
# (source, the file after, after `ruff format`)
UNFORMATTED_21 = (
    # #21: ruff format also changes `x=1`, the spaces in the call and `[1,2]`.
    (
        "x=1\nself.assertTrue( a  in  b )\ny = [1,2]\n",
        "x=1\nself.assertIn( a, b)\ny = [1,2]\n",
        "x = 1\nself.assertIn(a, b)\ny = [1, 2]\n",
    ),
    # #21: ruff format adds the newline at the end.
    (
        "x = 1\nself.assertTrue(a in b)",
        "x = 1\nself.assertIn(a, b)",
        "x = 1\nself.assertIn(a, b)\n",
    ),
)

# A comment inside the range that the fix replaces, kept in the result.
# (rule, source, position reported, the file after `fix --automatic`)
COMMENTS = (
    (
        NA,
        "self.assertTrue(\n    a,  # c\n    3,\n)\n",
        "1:0",
        "self.assertEqual(\n    a,  # c\n    3,\n)\n",
    ),
    (
        NT,
        f"{IMPORT_NT}class Foo(NamedTuple):  # c\n    a: int\n",
        "4:0",
        f"{IMPORT_NT}{DC}class Foo:  # c\n    a: int\n",
    ),
)

# #21: the comment inside the range is not in the result of the fix, so the new
# engine does not apply it: the line ends without " (has autofix)", the summary
# counts no auto-fix, and the file is left as is.
# (rule, source, position reported, the file after `fix --automatic`)
COMMENTS_21 = (
    (
        UI,
        "self.assertTrue(\n    a in b  # c\n)\n",
        "1:0",
        "self.assertIn(\n    a, b)\n",
    ),
    (
        NN,
        "self.assertTrue(\n    a is not None  # c\n)\n",
        "1:0",
        "self.assertIsNotNone(\n    a)\n",
    ),
    # The fix drops the argument with the comment.
    (
        NA,
        "self.assertTrue(\n    a,\n    None,  # c\n)\n",
        "1:0",
        "self.assertIsNone(\n    a)\n",
    ),
    (
        NT,
        f"{IMPORT_NT}class Foo(\n    NamedTuple,  # c\n):\n    a: int\n",
        "4:0",
        f"{IMPORT_NT}{DC}class Foo:\n    a: int\n",
    ),
    (
        VC,
        f"{IMPORT_CB}x: Callable[\n    [...],  # c\n    int,\n]\n",
        "3:3",
        f"{IMPORT_CB}x: Callable[\n    ..., int,\n]\n",
    ),
)

# #21: the comment after "(" is kept, but the result is not what `ruff format`
# writes, so the new engine writes the last value instead: ruff format puts ")"
# on its own line.
# (rule, source, position reported, the file after, after `ruff format`)
COMMENTS_UNFORMATTED_21 = (
    (
        UI,
        "self.assertTrue(  # c\n    a in b\n)\n",
        "1:0",
        "self.assertIn(  # c\n    a, b)\n",
        "self.assertIn(  # c\n    a, b\n)\n",
    ),
    (
        NN,
        "self.assertTrue(  # c\n    a is not None\n)\n",
        "1:0",
        "self.assertIsNotNone(  # c\n    a)\n",
        "self.assertIsNotNone(  # c\n    a\n)\n",
    ),
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
                # NOTE: `fix` exits with 0 even when it reports violations.
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.files["t.py"], fixed)

    def test_fix_two_places_in_one_file(self) -> None:
        for label, rules, source, reported, fixed, summary in MULTI:
            with self.subTest(label):
                result = fix(rules, source)
                self.assert_violations(result.stdout, in_t(reported))
                self.assertEqual(result.stderr, summary)
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.files["t.py"], fixed)

    def test_fix_inside_another_fix(self) -> None:
        for label, rules, source, reported, fixed in NESTED:
            with self.subTest(label):
                result = fix(rules, source)
                self.assert_violations(result.stdout, in_t(reported))
                # NOTE: only the outer fix is applied, but the summary counts 2.
                self.assertEqual(result.stderr, DIRTY_FF)
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.files["t.py"], fixed)

    def test_fix_two_rules_on_one_class(self) -> None:
        source, sorted_, dataclass = ONE_CLASS
        result = fix((NT, SA), source)
        self.assert_violations(result.stdout, in_t(((NT, "4:0"), (SA, "4:0"))))
        self.assertEqual(result.stderr, DIRTY_FF)
        self.assertEqual(result.exit_code, 0)
        # NOTE: only the fix of the rule reported last is applied. The rules run
        # in set order, so which one it is changes between runs.
        nt_last = result.stdout.rfind(f" {NT}: ") > result.stdout.rfind(f" {SA}: ")
        self.assertEqual(result.files["t.py"], dataclass if nt_last else sorted_)

    def test_fix_with_suppression(self) -> None:
        for label, rules, source, reported, fixed, summary in SUPPRESSED:
            with self.subTest(label):
                result = fix(rules, source)
                self.assert_violations(result.stdout, in_t(reported))
                self.assertEqual(result.stderr, summary)
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.files["t.py"], fixed)

    def test_fix_without_autofix_leaves_file_unchanged(self) -> None:
        cases = (
            ("no autofix", SI, "if True:\n    pass\n", ((SI, "1:0"),), DIRTY),
            ("clean", UI, "x = 1\n", (), CLEAN),
            ("all ignored", UI, "self.assertTrue(a in b)  # lint-ignore\n", (), CLEAN),
            # Not formatted: `ruff format` changes these.
            (
                "no autofix, not formatted",
                SI,
                "if True:\n  pass\n",
                ((SI, "1:0"),),
                DIRTY,
            ),
            ("clean, not formatted", UI, "x=1\n", (), CLEAN),
        )
        for label, rule, source, reported, summary in cases:
            with self.subTest(label):
                result = fix((rule,), source)
                self.assert_violations(result.stdout, in_t(reported))
                self.assertEqual(result.stderr, summary)
                self.assertEqual(result.exit_code, 0)
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
                        diff(
                            "@@ -3,3 +3,4 @@",
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

    def test_diff_of_file_in_sub_directory(self) -> None:
        files = {"pyproject.toml": config(UI), "sub/t.py": DIFF_SOURCE}
        result = invoke(files, ["lint", "--diff", "sub/t.py"])
        # NOTE: the diff names the file "t.py", not "sub/t.py".
        self.assertEqual(result.stdout, line("sub/t.py", UI, "2:0") + DIFF)
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
            ),
            (
                "2 rules",
                (UI, NA),
                two,
                "self.assertIn(a, b)\nself.assertEqual(c, 3)\n",
                ((UI, "1:0"), (NA, "2:0")),
                DIRTY_FF,
            ),
            (
                "no autofix",
                (SI,),
                "if True:\n    pass\n",
                "if True:\n    pass\n",
                ((SI, "1:0"),),
                DIRTY,
            ),
            ("clean", (UI,), "x = 1\n", "x = 1\n", (), CLEAN),
            # Not formatted: `ruff format` changes it.
            ("clean, not formatted", (UI,), "x=1\n", "x=1\n", (), CLEAN),
        )
        for label, rules, source, fixed, reported, summary in cases:
            with self.subTest(label):
                files = {"pyproject.toml": config(*rules)}
                result = invoke(files, ["fix", "-", "t.py"], stdin=source)
                self.assertEqual(result.stdout, fixed)
                self.assertTrue(result.stderr.endswith(summary))
                violations = result.stderr.removesuffix(summary)
                self.assert_violations(violations, in_t(reported))
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.files, files)

    def test_fix_stdin_with_diff(self) -> None:
        files = {"pyproject.toml": config(UI)}
        result = invoke(files, ["fix", "--diff", "-", "t.py"], stdin=DIFF_SOURCE)
        # NOTE: the diff goes to stdout, before the fixed source.
        self.assertEqual(result.stdout, DIFF + "x = 1\nself.assertIn(a, b)\ny = 2\n")
        self.assertEqual(result.stderr, line("t.py", UI, "2:0") + DIRTY_F)
        self.assertEqual(result.exit_code, 0)

    def test_21_fix_result_is_not_ruff_formatted(self) -> None:
        for rule, source, position, fixed, _ in FIXES_21:
            with self.subTest(rule, source=source):
                result = fix((rule,), source)
                self.assertEqual(result.stdout, line("t.py", rule, position))
                self.assertEqual(result.stderr, DIRTY_F)
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.files["t.py"], fixed)

    def test_21_fix_leaves_the_rest_unformatted(self) -> None:
        for source, fixed, _ in UNFORMATTED_21:
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

    def test_21_fix_drops_a_comment_in_its_range(self) -> None:
        for rule, source, position, fixed in COMMENTS_21:
            with self.subTest(rule, source=source):
                result = fix((rule,), source)
                # #21: the line ends without " (has autofix)".
                self.assertEqual(result.stdout, line("t.py", rule, position))
                # #21: DIRTY, without "auto-fix available" and "fix applied".
                self.assertEqual(result.stderr, DIRTY_F)
                self.assertEqual(result.exit_code, 0)
                # #21: the file is left as is: `source`.
                self.assertEqual(result.files["t.py"], fixed)

    def test_21_fix_keeps_a_comment_but_is_not_ruff_formatted(self) -> None:
        for rule, source, position, fixed, _ in COMMENTS_UNFORMATTED_21:
            with self.subTest(rule, source=source):
                result = fix((rule,), source)
                self.assertEqual(result.stdout, line("t.py", rule, position))
                self.assertEqual(result.stderr, DIRTY_F)
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.files["t.py"], fixed)

    def test_sources_are_stable_under_ruff_format(self) -> None:
        # Not a test of fixit: checks that the cases above fit the new engine.
        pairs = [(source, fixed) for _, source, _, fixed in FIXES]
        pairs += [(row[2], row[4]) for row in MULTI + NESTED + SUPPRESSED]
        pairs += [ONE_CLASS[:2], ONE_CLASS[::2]]
        pairs += [(DIFF_SOURCE, "x = 1\nself.assertIn(a, b)\ny = 2\n")]
        pairs += [(source, fixed) for _, source, _, fixed in COMMENTS]
        stable = [text for pair in pairs for text in pair]
        # The new engine leaves these files as is.
        stable += [source for _, source, _, _ in COMMENTS_21]
        for source, formatted in zip(stable, ruff_format(*stable), strict=True):
            with self.subTest(source=source):
                self.assertEqual(formatted, source)
        cases = [(s, f, out, True) for _, s, _, f, out in FIXES_21]
        cases += [(s, f, out, False) for s, f, out in UNFORMATTED_21]
        cases += [(s, f, out, True) for _, s, _, f, out in COMMENTS_UNFORMATTED_21]
        results = ruff_format(*(text for s, f, _, _ in cases for text in (s, f)))
        for i, (source, fixed, formatted, is_formatted) in enumerate(cases):
            with self.subTest("#21", source=source):
                self.assertEqual(results[2 * i] == source, is_formatted)
                self.assertEqual(results[2 * i + 1], formatted)
                self.assertNotEqual(formatted, fixed)
