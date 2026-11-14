# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Characterization tests for ``# lint-ignore`` / ``# lint-fixme`` comments and for
the line and column printed by ``tukuroi lint``.

They run the CLI only, so that the engine rewrite (#21) can be checked against
them. The expected values are copied from the output of the libcst engine.
``NOTE`` marks behavior that looks wrong but is pinned as is. The new engine
(#21) reads the directives with a new grammar, so that a mistyped directive no
longer suppresses every rule: ``test_directive_of_the_new_grammar`` has the
directives whose meaning changed.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from click.testing import CliRunner, Result

from ..cli import main
from ..util import chdir

MESSAGES = {
    "UseAssertIn": (
        "Use assertIn/assertNotIn instead of assertTrue/assertFalse for inclusion"
        " check.\nSee https://docs.python.org/3/library/unittest.html"
        "#unittest.TestCase.assertIn) (has autofix)"
    ),
    "NoAssertTrueForComparisons": (
        '"assertTrue" does not compare its arguments, use "assertEqual" or other'
        " appropriate functions. (has autofix)"
    ),
    "UseAssertIsNotNone": (
        '"assertTrue" and "assertFalse" are deprecated. Use "assertIsNotNone" and'
        ' "assertIsNone" instead.\nSee https://docs.python.org/3.8/library/'
        "unittest.html#deprecated-aliases (has autofix)"
    ),
    "NoStaticIfCondition": (
        "Your if condition appears to evaluate to a static value (e.g. `or True`,"
        " `and False`). Please double check this logic and if it is actually"
        " temporary debug code."
    ),
    "NoNamedTuple": (
        "Instead of NamedTuple, consider using the @dataclass decorator from"
        " dataclasses instead for simplicity, efficiency and consistency."
        " (has autofix)"
    ),
    "SortedAttributes": (
        "It appears you are using the @sorted-attributes directive and the class"
        " variables are unsorted. See the lint autofix suggestion. (has autofix)"
    ),
    # NOTE: the message is the class docstring, so it starts and ends with "\n".
    "VariadicCallableSyntax": (
        "\nCallable types with arbitrary parameters should be written as"
        " `Callable[..., T]`\n (has autofix)"
    ),
}

# UseAssertIn reports this call.
CALL = "self.assertTrue(a in b)"
NT = "from typing import NamedTuple\n"
CB = "from typing import Callable\n"
# SortedAttributes reports a class with this body.
SORTED = '    """@sorted-attributes"""\n    b = 1\n    a = 2\n'

Cases = tuple[tuple[str, str, tuple[str, ...]], ...]


class SuppressionCharacterizationTest(TestCase):
    maxDiff = None

    def lint(self, rule: str, source: str, newline: str) -> Result:
        with TemporaryDirectory() as td:
            root = Path(td).resolve()
            # `enable` alone adds to the default "tukuroi.rules"; disabling it
            # leaves only the named rule.
            (root / "pyproject.toml").write_text(
                "[tool.fixit]\n"
                "root = true\n"
                'disable = ["tukuroi.rules"]\n'
                f'enable = ["tukuroi.rules:{rule}"]\n'
            )
            (root / "t.py").write_bytes(source.replace("\n", newline).encode())
            with chdir(root):
                return CliRunner().invoke(main, ["lint", "t.py"])

    def assert_lint(
        self, rule: str, source: str, positions: tuple[str, ...], newline: str = "\n"
    ) -> None:
        """``positions``: ``line:column`` of each output line; empty = no output."""
        result = self.lint(rule, source, newline)
        expected = "".join(f"t.py@{p} {rule}: {MESSAGES[rule]}\n" for p in positions)
        self.assertEqual(result.stdout, expected)
        self.assertEqual(result.exit_code, 1 if positions else 0)

    def run_cases(self, rule: str, cases: Cases) -> None:
        for label, source, positions in cases:
            with self.subTest(label, source=source):
                self.assert_lint(rule, source, positions)

    def test_output_line_of_each_rule(self) -> None:
        cases = (
            ("UseAssertIn", f"{CALL}\n", ("1:0",)),
            ("NoAssertTrueForComparisons", "self.assertTrue(a, 3)\n", ("1:0",)),
            ("UseAssertIsNotNone", "self.assertTrue(a is not None)\n", ("1:0",)),
            ("NoStaticIfCondition", "if True:\n    pass\n", ("1:0",)),
            ("NoNamedTuple", f"{NT}class Foo(NamedTuple):\n    pass\n", ("2:0",)),
            ("SortedAttributes", f"class C:\n{SORTED}", ("1:0",)),
            ("VariadicCallableSyntax", f"{CB}x: Callable[[...], int]\n", ("2:3",)),
        )
        for rule, source, positions in cases:
            with self.subTest(rule, source=source):
                self.assert_lint(rule, source, positions)

    def test_comment_location_one_line_statement(self) -> None:
        cases = (
            ("no comment", f"x = 1\n{CALL}\n", ("2:0",)),
            ("other comment", f"x = 1\n{CALL}  # other\n", ("2:0",)),
            ("in a string", "x = 1\nself.assertTrue(a in '# lint-ignore')\n", ("2:0",)),
            ("end of line", f"x = 1\n{CALL}  # lint-ignore\n", ()),
            ("line above", f"x = 1\n# lint-ignore\n{CALL}\n", ()),
            ("above, 1 blank", f"x = 1\n# lint-ignore\n\n{CALL}\n", ()),
            ("above, 2 blanks", f"x = 1\n# lint-ignore\n\n\n{CALL}\n", ()),
            ("blank, then above", f"x = 1\n\n# lint-ignore\n{CALL}\n", ()),
            ("above, then other", f"x = 1\n# lint-ignore\n# other\n{CALL}\n", ()),
            ("other, then above", f"x = 1\n# other\n# lint-ignore\n{CALL}\n", ()),
            ("statement between", f"x = 1\n# lint-ignore\ny = 2\n{CALL}\n", ("4:0",)),
            ("end of previous", f"x = 1  # lint-ignore\n{CALL}\n", ("2:0",)),
            ("next line, EOF", f"x = 1\n{CALL}\n# lint-ignore\n", ("2:0",)),
            ("next line", f"x = 1\n{CALL}\n# lint-ignore\ny = 2\n", ("2:0",)),
            ("end, after ;", f"x = 1\n{CALL}; y = 2  # lint-ignore\n", ()),
        )
        self.run_cases("UseAssertIn", cases)

    def test_comment_location_multi_line_call(self) -> None:
        cases = (
            ("no comment", "x = 1\nself.assertTrue(\n    a,\n    3,\n)\n", ("2:0",)),
            # NOTE: the end of the line the position points at is not used.
            (
                "end of 1st line",
                "x = 1\nself.assertTrue(  # lint-ignore\n    a,\n    3,\n)\n",
                ("2:0",),
            ),
            # NOTE: a comment after the call's own argument is not used.
            (
                "after 1st arg",
                "x = 1\nself.assertTrue(\n    a,  # lint-ignore\n    3,\n)\n",
                ("2:0",),
            ),
            # NOTE: a comment after the call's own argument is not used.
            (
                "after last arg",
                "x = 1\nself.assertTrue(\n    a,\n    3,  # lint-ignore\n)\n",
                ("2:0",),
            ),
            (
                "before 1st arg",
                "x = 1\nself.assertTrue(\n    # lint-ignore\n    a,\n    3,\n)\n",
                ("2:0",),
            ),
            (
                "end of last line",
                "x = 1\nself.assertTrue(\n    a,\n    3,\n)  # lint-ignore\n",
                (),
            ),
            (
                "line above",
                "x = 1\n# lint-ignore\nself.assertTrue(\n    a,\n    3,\n)\n",
                (),
            ),
        )
        self.run_cases("NoAssertTrueForComparisons", cases)

    def test_comment_location_call_inside_brackets(self) -> None:
        cases = (
            ("arg, comma", f"x = 1\nf(\n    {CALL},  # lint-ignore\n)\n", ()),
            # NOTE: unlike the last list element, the last argument is not covered.
            (
                "last arg",
                f"x = 1\nf(\n    c,\n    {CALL}  # lint-ignore\n)\n",
                ("4:4",),
            ),
            ("before arg", f"x = 1\nf(\n    # lint-ignore\n    {CALL},\n)\n", ("4:4",)),
            ("before 1st", f"x = 1\n[\n    # lint-ignore\n    {CALL},\n]\n", ()),
            (
                "blank, then before 1st",
                f"x = 1\n[\n\n    # lint-ignore\n    {CALL},\n]\n",
                (),
            ),
            (
                "before 1st, then blank",
                f"x = 1\n[\n    # lint-ignore\n\n    {CALL},\n]\n",
                (),
            ),
            # NOTE: unlike the first element, the second one is not covered.
            (
                "before 2nd",
                f"x = 1\n[\n    c,\n    # lint-ignore\n    {CALL},\n]\n",
                ("5:4",),
            ),
            ("last, no comma", f"x = 1\n[\n    c,\n    {CALL}  # lint-ignore\n]\n", ()),
            ("end of [", f"x = 1\n[  # lint-ignore\n    {CALL},\n]\n", ("3:4",)),
            # NOTE: unlike a list, a tuple is not covered.
            ("tuple", f"x = 1\n(\n    # lint-ignore\n    {CALL},\n)\n", ("4:4",)),
        )
        self.run_cases("UseAssertIn", cases)

    def test_comment_location_if_statement(self) -> None:
        cases = (
            ("no comment", "x = 1\nif True:\n    pass\n", ("2:0",)),
            ("end of header", "x = 1\nif True:  # lint-ignore\n    pass\n", ()),
            ("line above", "x = 1\n# lint-ignore\nif True:\n    pass\n", ()),
            ("one-line if", "x = 1\nif True: pass  # lint-ignore\n", ()),
            ("end of body", "x = 1\nif True:\n    pass  # lint-ignore\n", ("2:0",)),
            ("above body", "x = 1\nif True:\n    # lint-ignore\n    pass\n", ("2:0",)),
            # NOTE: the end of the line the position points at is not used.
            (
                "end of `if (`",
                "x = 1\nif (  # lint-ignore\n    True\n):\n    pass\n",
                ("2:0",),
            ),
            (
                "end of else",
                "x = 1\nif True:\n    pass\nelse:  # lint-ignore\n    pass\n",
                ("2:0",),
            ),
            (
                "end of elif",
                "x = 1\nif x:\n    pass\nelif True:  # lint-ignore\n    pass\n",
                (),
            ),
            (
                "above elif",
                "x = 1\nif x:\n    pass\n# lint-ignore\nelif True:\n    pass\n",
                (),
            ),
            (
                "elif, end of if",
                "x = 1\nif x:  # lint-ignore\n    pass\nelif True:\n    pass\n",
                ("4:0",),
            ),
            (
                "elif, above if",
                "x = 1\n# lint-ignore\nif x:\n    pass\nelif True:\n    pass\n",
                ("5:0",),
            ),
        )
        self.run_cases("NoStaticIfCondition", cases)

    def test_comment_location_nested_if_statement(self) -> None:
        cases = (
            (
                "no comment",
                "x = 1\nif True:\n    if True:\n        pass\n",
                ("2:0", "3:4"),
            ),
            (
                "end of outer",
                "x = 1\nif True:  # lint-ignore\n    if True:\n        pass\n",
                ("3:4",),
            ),
            (
                "above outer",
                "x = 1\n# lint-ignore\nif True:\n    if True:\n        pass\n",
                ("4:4",),
            ),
            (
                "end of inner",
                "x = 1\nif True:\n    if True:  # lint-ignore\n        pass\n",
                ("2:0",),
            ),
        )
        self.run_cases("NoStaticIfCondition", cases)

    def test_comment_location_call_in_if_statement(self) -> None:
        cases = (
            ("body", f"x = 1\nif x:\n    {CALL}\n", ("3:4",)),
            ("body, end of if", f"x = 1\nif x:  # lint-ignore\n    {CALL}\n", ("3:4",)),
            ("body, above if", f"x = 1\n# lint-ignore\nif x:\n    {CALL}\n", ("4:4",)),
            ("one-line body, end", f"x = 1\nif x: {CALL}  # lint-ignore\n", ()),
            ("one-line body, above", f"x = 1\n# lint-ignore\nif x: {CALL}\n", ()),
            ("test, end of if", f"x = 1\nif {CALL}:  # lint-ignore\n    pass\n", ()),
            (
                "test, end of body",
                f"x = 1\nif {CALL}:\n    pass  # lint-ignore\n",
                ("2:3",),
            ),
        )
        self.run_cases("UseAssertIn", cases)

    def test_comment_location_decorated_class_no_named_tuple(self) -> None:
        body = "class Foo(NamedTuple):\n    pass\n"
        cases = (
            ("no comment", f"{NT}@deco\n{body}", ("3:0",)),
            ("above decorator", f"{NT}# lint-ignore\n@deco\n{body}", ()),
            ("between", f"{NT}@deco\n# lint-ignore\n{body}", ()),
            ("blank, then between", f"{NT}@deco\n\n# lint-ignore\n{body}", ()),
            ("between, then blank", f"{NT}@deco\n# lint-ignore\n\n{body}", ()),
            # NOTE: unlike the lines around it, the decorator line is not used.
            ("end of decorator", f"{NT}@deco  # lint-ignore\n{body}", ("3:0",)),
            (
                "end of class",
                f"{NT}@deco\nclass Foo(NamedTuple):  # lint-ignore\n    pass\n",
                (),
            ),
            # NOTE: a line between two decorators is not used.
            ("between decorators", f"{NT}@d1\n# lint-ignore\n@d2\n{body}", ("5:0",)),
            (
                "end of body",
                f"{NT}@deco\nclass Foo(NamedTuple):\n    pass  # lint-ignore\n",
                ("3:0",),
            ),
        )
        self.run_cases("NoNamedTuple", cases)

    def test_comment_location_decorated_class_sorted_attributes(self) -> None:
        cases = (
            ("no comment", f"x = 1\n@deco\nclass C:\n{SORTED}", ("3:0",)),
            ("above decorator", f"x = 1\n# lint-ignore\n@deco\nclass C:\n{SORTED}", ()),
            ("between", f"x = 1\n@deco\n# lint-ignore\nclass C:\n{SORTED}", ()),
            # NOTE: unlike the lines around it, the decorator line is not used.
            (
                "end of decorator",
                f"x = 1\n@deco  # lint-ignore\nclass C:\n{SORTED}",
                ("3:0",),
            ),
            ("end of class", f"x = 1\n@deco\nclass C:  # lint-ignore\n{SORTED}", ()),
        )
        self.run_cases("SortedAttributes", cases)

    def test_comment_location_call_in_decorator(self) -> None:
        cls = "class C:\n    pass\n"
        cases = (
            ("no comment", f"x = 1\n@deco({CALL})\n{cls}", ("2:6",)),
            ("end of decorator", f"x = 1\n@deco({CALL})  # lint-ignore\n{cls}", ()),
            ("above decorator", f"x = 1\n# lint-ignore\n@deco({CALL})\n{cls}", ()),
            (
                "between decorators",
                f"x = 1\n@d1\n# lint-ignore\n@deco({CALL})\n{cls}",
                (),
            ),
            # NOTE: a comment line below the call suppresses it.
            ("between", f"x = 1\n@deco({CALL})\n# lint-ignore\n{cls}", ()),
            # NOTE: a comment on the class line below suppresses it.
            (
                "end of class",
                f"x = 1\n@deco({CALL})\nclass C:  # lint-ignore\n    pass\n",
                (),
            ),
        )
        self.run_cases("UseAssertIn", cases)

    def test_comment_location_parameter_annotation(self) -> None:
        def_ = (
            "def f(\n    a: Callable[[...], int],\n    b: int,\n) -> None:\n    pass\n"
        )
        last = (
            "def f(\n    b: int,\n    a: Callable[[...], int]\n) -> None:\n    pass\n"
        )
        cases = (
            ("no comment", f"{CB}{def_}", ("3:7",)),
            ("after comma", CB + def_.replace("int],", "int],  # lint-ignore"), ()),
            # NOTE: unlike the ones with a comma, the last parameter is not covered.
            (
                "last, no comma",
                CB + last.replace("int]\n", "int]  # lint-ignore\n"),
                ("4:7",),
            ),
            ("above def", f"{CB}# lint-ignore\n{def_}", ()),
            (
                "end of `def f(`",
                CB + def_.replace("(\n", "(  # lint-ignore\n"),
                ("3:7",),
            ),
            (
                "line before param",
                CB + def_.replace("    a", "    # lint-ignore\n    a"),
                ("4:7",),
            ),
            ("end of header", CB + def_.replace("None:", "None:  # lint-ignore"), ()),
        )
        self.run_cases("VariadicCallableSyntax", cases)

    def test_comment_location_variable_annotation(self) -> None:
        sub = "x: Callable[\n    [...],\n    int\n]\n"
        cases = (
            ("no comment", f"{CB}{sub}", ("2:3",)),
            ("end of line", f"{CB}x: Callable[[...], int]  # lint-ignore\n", ()),
            # NOTE: unlike the next line, the end of the "[" line is not used.
            ("end of [", CB + sub.replace("[\n", "[  # lint-ignore\n", 1), ("2:3",)),
            ("after [", CB + sub.replace("[\n", "[\n    # lint-ignore\n", 1), ()),
            # NOTE: unlike the last element, the first one is not covered.
            ("after 1st", CB + sub.replace("],", "],  # lint-ignore"), ("2:3",)),
            ("after last", CB + sub.replace("int", "int  # lint-ignore"), ()),
        )
        self.run_cases("VariadicCallableSyntax", cases)

    def test_comment_location_module_header(self) -> None:
        cases = (
            ("no blank", f"# lint-ignore\n{CALL}\n", ()),
            ("1 blank", f"# lint-ignore\n\n{CALL}\n", ()),
            ("blank, then other", f"# lint-ignore\n\n# other\n{CALL}\n", ()),
            ("blank line first", f"\n# lint-ignore\n{CALL}\n", ()),
            ("after shebang", f"#!/usr/bin/env python\n# lint-ignore\n\n{CALL}\n", ()),
            ("2nd statement", f"# lint-ignore\n\nx = 1\n{CALL}\n", ("4:0",)),
            ("docstring first", f'# lint-ignore\n"""doc"""\n{CALL}\n', ("3:0",)),
            ("if body", f"# lint-ignore\nif x:\n    {CALL}\n", ("3:4",)),
            ("one-line if body", f"# lint-ignore\nif x: {CALL}\n", ()),
        )
        self.run_cases("UseAssertIn", cases)

    def test_comment_location_module_header_if_statement(self) -> None:
        cases = (
            ("if", "# lint-ignore\n\nif True:\n    pass\n", ()),
            (
                "nested if",
                "# lint-ignore\n\nif True:\n    if True:\n        pass\n",
                ("4:4",),
            ),
            (
                "elif",
                "# lint-ignore\n\nif x:\n    pass\nelif True:\n    pass\n",
                ("5:0",),
            ),
        )
        self.run_cases("NoStaticIfCondition", cases)

    def test_comment_location_after_indented_block(self) -> None:
        cases = (
            ("dedented", f"if x:\n    pass\n# lint-ignore\n{CALL}\n", ()),
            # NOTE: the line right above is not used when indented like the block.
            ("indented", f"if x:\n    pass\n    # lint-ignore\n{CALL}\n", ("4:0",)),
            ("dedented, in block", f"if x:\n    pass\n# lint-ignore\n    {CALL}\n", ()),
        )
        self.run_cases("UseAssertIn", cases)

    def test_directive_that_suppresses(self) -> None:
        comments = (
            "# lint-ignore",
            "# lint-fixme",
            "# lint-ignore: UseAssertIn",
            "# lint-fixme: UseAssertIn",
            "# lint-ignore: NoNamedTuple, UseAssertIn",
            "# lint-ignore: UseAssertIn, NoNamedTuple",
            "# lint-ignore: NoNamedTuple,UseAssertIn",
            "# lint-ignore: NoNamedTuple,  UseAssertIn",
            "# lint-ignore: UseAssertInRule",
            "# lint-ignore:UseAssertIn",
            "# lint-ignore:  UseAssertIn",
            "#lint-ignore",
            "#\tlint-ignore",
            "# noqa  # lint-ignore",
            "# type: ignore # lint-fixme: UseAssertIn",
        )
        for comment in comments:
            with self.subTest(comment):
                self.assert_lint("UseAssertIn", f"x = 1\n{CALL}  {comment}\n", ())

    def test_directive_that_does_not_suppress(self) -> None:
        comments = (
            "# lint-ignore: NoNamedTuple",
            "# lint-fixme: NoNamedTuple",
            "# lint-ignore: UseAssertInRuleRule",
            "# lint-ignore: Rule",
            "# lint-ignore: UseAssert",
            "# lint-ignore: UseAssertIns",
            "# lint-ignore: USEASSERTIN",
            "# lint-ignore: useAssertIn",
            # NOTE: "useassertinRule" suppresses but "useassertinrule" does not.
            "# lint-ignore: useassertinrule",
            "# Lint-Ignore",
            "# LINT-IGNORE",
            "# lint_ignore",
            "# see lint-ignore",
        )
        for comment in comments:
            with self.subTest(comment):
                source = f"x = 1\n{CALL}  {comment}\n"
                self.assert_lint("UseAssertIn", source, ("2:0",))

    def test_directive_of_the_new_grammar(self) -> None:
        # The directives whose meaning the new engine changed (#21,
        # issuecomment-6706590667). The grammar is `lint-ignore` or
        # `lint-ignore: <name>, <name>`, read in each part of a comment split at
        # "#". A part that starts with `lint-ignore` or `lint-fixme` followed by
        # no letter, digit or "_" is a directive; one that does not fit the
        # grammar suppresses nothing, with a warning. A name matches only with
        # the same case, with or without "Rule".
        cases = (
            # (comment, UseAssertIn suppressed, warning)
            # The name must have the same case.
            ("# lint-ignore: useassertin", False, ""),
            ("# lint-ignore: useassertinRule", False, ""),
            # The names need ":".
            ("# lint-ignore UseAssertIn", False, "lint-ignore"),
            ("# lint-ignore\tUseAssertIn", False, "lint-ignore"),
            # No text after the names.
            ("# lint-ignore: UseAssertIn because of x", False, "lint-ignore"),
            # No name after ":", before or after ",", or between two names.
            ("# lint-ignore:", False, "lint-ignore"),
            ("# lint-ignore: , NoNamedTuple", False, "lint-ignore"),
            ("# lint-ignore: NoNamedTuple,", False, "lint-ignore"),
            ("# lint-ignore: NoNamedTuple UseAssertIn", False, "lint-ignore"),
            # Spaces around ":" and "," are allowed.
            ("# lint-ignore : NoNamedTuple", False, ""),
            ("# lint-ignore: NoNamedTuple ,UseAssertIn", True, ""),
            # "(" is not ":".
            ("# lint-ignore(NoNamedTuple)", False, "lint-ignore"),
            # Not a rule name: the qualified name of the config.
            ("# lint-ignore: tukuroi.rules:UseAssertIn", False, "lint-ignore"),
            # Not a directive.
            ("# lint-ignored", False, ""),
            # "-later" does not fit.
            ("# lint-fixme-later: NoNamedTuple", False, "lint-fixme"),
            # Each directive in a comment is read.
            ("# lint-ignore: NoNamedTuple # lint-ignore: UseAssertIn", True, ""),
            ("# lint-ignore: NoNamedTuple  # lint-ignore", True, ""),
        )
        for comment, suppressed, kind in cases:
            with self.subTest(comment):
                source = f"x = 1\n{CALL}  {comment}\n"
                positions = () if suppressed else ("2:0",)
                if not kind:
                    with self.assertNoLogs("tukuroi.api", "WARNING"):
                        self.assert_lint("UseAssertIn", source, positions)
                    continue
                with self.assertLogs("tukuroi.api", "WARNING") as logs:
                    self.assert_lint("UseAssertIn", source, positions)
                warning = f"t.py:2: invalid {kind} directive"
                self.assertEqual([r.getMessage() for r in logs.records], [warning])

    def test_directive_in_each_comment_of_the_node_is_read(self) -> None:
        other = "# lint-ignore: NoNamedTuple"
        mine = "# lint-ignore: UseAssertIn"
        cases = (
            ("other above and at end", f"x = 1\n{other}\n{CALL}  {other}\n", ("3:0",)),
            ("other above, mine at end", f"x = 1\n{other}\n{CALL}  {mine}\n", ()),
            ("mine above, other at end", f"x = 1\n{mine}\n{CALL}  {other}\n", ()),
            ("other, then mine above", f"x = 1\n{other}\n{mine}\n{CALL}\n", ()),
        )
        self.run_cases("UseAssertIn", cases)

    def test_column_counts_code_points(self) -> None:
        cases = (
            ("ASCII", f'x = "ab"; {CALL}\n', ("1:10",)),
            ("full-width in a string", f'x = "あ"; {CALL}\n', ("1:9",)),
            ("full-width name", f"変数 = 1; {CALL}\n", ("1:8",)),
            ("outside the BMP", f'x = "😀"; {CALL}\n', ("1:9",)),
            ("ZWJ sequence", f'x = "👨\u200d👩\u200d👧"; {CALL}\n', ("1:13",)),
            ("combining mark", f'x = "e\u0301"; {CALL}\n', ("1:10",)),
            ("tab", f"x = 1;\t{CALL}\n", ("1:7",)),
            ("tab indent", f"if x:\n\t{CALL}\n", ("2:1",)),
            ("tab indent, 2 levels", f"if x:\n\tif y:\n\t\t{CALL}\n", ("3:2",)),
            ("UTF-8 BOM", f"\ufeff{CALL}\n", ("1:0",)),
        )
        self.run_cases("UseAssertIn", cases)

    def test_line_and_column_with_other_newlines(self) -> None:
        cases = (
            ("\r\n", "1st line", f"{CALL}\n", ("1:0",)),
            ("\r\n", "3rd line", f"x = 1\n\n{CALL}\n", ("3:0",)),
            ("\r\n", "column", f"x = 1; {CALL}\n", ("1:7",)),
            ("\r\n", "after multi-line str", f'x = """a\nb"""\n{CALL}\n', ("3:0",)),
            ("\r\n", "line above", f"x = 1\n# lint-ignore\n{CALL}\n", ()),
            ("\r\n", "end of line", f"x = 1\n{CALL}  # lint-ignore: UseAssertIn\n", ()),
            ("\r\n", "module header", f"# lint-ignore\n\n{CALL}\n", ()),
            ("\r", "3rd line", f"x = 1\n\n{CALL}\n", ("3:0",)),
        )
        for newline, label, source, positions in cases:
            with self.subTest(f"{newline!r}: {label}", source=source):
                self.assert_lint("UseAssertIn", source, positions, newline)
