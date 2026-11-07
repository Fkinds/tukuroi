# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``fixit.core.suppression``. The cases are those of the
characterization tests of the libcst engine (``characterization_suppression.py``),
copied as they are: each source, and the positions of the violations that the
comments do not suppress. Here a rule is a function that finds the nodes it
would report, as the rule of the same name does.

The other cases (clauses, joined statements, decorators, multi-line strings,
and the lines after an indented block, which libcst gives to the block as its
footer) were checked against the libcst engine too.
"""

import ast
from collections.abc import Callable, Iterator
from unittest import TestCase

from ..core.source import Source
from ..core.suppression import NodeComments, is_suppressed

Finder = Callable[[ast.Module], Iterator[ast.AST]]

CALL = "self.assertTrue(a in b)"


def assert_true(tree: ast.Module) -> Iterator[ast.AST]:
    """The calls of ``self.assertTrue``, as UseAssertIn and others report."""
    for node in ast.walk(tree):
        func = getattr(node, "func", None)
        if isinstance(func, ast.Attribute) and func.attr == "assertTrue":
            yield node


def static_if(tree: ast.Module) -> Iterator[ast.AST]:
    """The ``if`` and ``elif`` with a test of ``True``, as NoStaticIfCondition."""
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Constant):
            yield node


def named_tuple(tree: ast.Module) -> Iterator[ast.AST]:
    """The classes based on ``NamedTuple``, as NoNamedTuple reports."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and any(
            isinstance(base, ast.Name) and base.id == "NamedTuple"
            for base in node.bases
        ):
            yield node


def sorted_attributes(tree: ast.Module) -> Iterator[ast.AST]:
    """The classes with a ``@sorted-attributes`` docstring, as SortedAttributes."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and "@sorted-attributes" in (
            ast.get_docstring(node) or ""
        ):
            yield node


def callable_ellipsis(tree: ast.Module) -> Iterator[ast.AST]:
    """``Callable[[...], T]``, as VariadicCallableSyntax reports."""
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "Callable"
            and isinstance(node.slice, ast.Tuple)
            and isinstance(node.slice.elts[0], ast.List)
        ):
            yield node


def unsuppressed(text: str, finder: Finder, rule: str = "X") -> tuple[str, ...]:
    """The ``line:column`` of each node found that the comments do not suppress."""
    source = Source.from_text(text)
    comments = NodeComments(source)
    positions = []
    for node in finder(source.tree):
        if not is_suppressed(comments.of(node), rule):
            position = source.lines.position(source.span(node).start)
            positions.append((position.line, position.column))
    return tuple(f"{line}:{column}" for line, column in sorted(positions))


class SuppressionTestCase(TestCase):
    maxDiff = None

    def run_cases(
        self, finder: Finder, cases: tuple[tuple[str, str, tuple[str, ...]], ...]
    ) -> None:
        for label, text, positions in cases:
            with self.subTest(label, text=text):
                self.assertEqual(unsuppressed(text, finder), positions)


class StatementTest(SuppressionTestCase):
    def test_one_line_statement(self) -> None:
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
            ("after ;, line above", f"# lint-ignore\nx = 1; {CALL}\n", ()),
            ("no line end at the end", f"x = 1\n{CALL}  # lint-ignore", ()),
            ("after ;, 1st statement on 2 lines", f"y = 0\n# lint-ignore\nx = (\n    1); {CALL}\n", ()),
            ("after ;, not the 1st statement", f"y = 0\n# lint-ignore\nx = 1; {CALL}\n", ()),
            ("end of a multi-line string above", f'x = """\n"""  # lint-ignore\n{CALL}\n', ("3:0",)),
            ("decorated one-line def, above", f"x = 1\n# lint-ignore\n@d\ndef f(): {CALL}\n", ()),
        )  # fmt: skip
        self.run_cases(assert_true, cases)

    def test_multi_line_call(self) -> None:
        cases = (
            ("no comment", "x = 1\nself.assertTrue(\n    a,\n    3,\n)\n", ("2:0",)),
            ("end of 1st line", "x = 1\nself.assertTrue(  # lint-ignore\n    a,\n    3,\n)\n", ("2:0",)),
            ("after 1st arg", "x = 1\nself.assertTrue(\n    a,  # lint-ignore\n    3,\n)\n", ("2:0",)),
            ("after last arg", "x = 1\nself.assertTrue(\n    a,\n    3,  # lint-ignore\n)\n", ("2:0",)),
            ("before 1st arg", "x = 1\nself.assertTrue(\n    # lint-ignore\n    a,\n    3,\n)\n", ("2:0",)),
            ("end of last line", "x = 1\nself.assertTrue(\n    a,\n    3,\n)  # lint-ignore\n", ()),
            ("line above", "x = 1\n# lint-ignore\nself.assertTrue(\n    a,\n    3,\n)\n", ()),
        )  # fmt: skip
        self.run_cases(assert_true, cases)

    def test_if_statement(self) -> None:
        cases = (
            ("no comment", "x = 1\nif True:\n    pass\n", ("2:0",)),
            ("end of header", "x = 1\nif True:  # lint-ignore\n    pass\n", ()),
            ("line above", "x = 1\n# lint-ignore\nif True:\n    pass\n", ()),
            ("one-line if", "x = 1\nif True: pass  # lint-ignore\n", ()),
            ("end of body", "x = 1\nif True:\n    pass  # lint-ignore\n", ("2:0",)),
            ("above body", "x = 1\nif True:\n    # lint-ignore\n    pass\n", ("2:0",)),
            ("end of `if (`", "x = 1\nif (  # lint-ignore\n    True\n):\n    pass\n", ("2:0",)),
            ("end of else", "x = 1\nif True:\n    pass\nelse:  # lint-ignore\n    pass\n", ("2:0",)),
            ("end of elif", "x = 1\nif x:\n    pass\nelif True:  # lint-ignore\n    pass\n", ()),
            ("above elif", "x = 1\nif x:\n    pass\n# lint-ignore\nelif True:\n    pass\n", ()),
            ("elif, end of if", "x = 1\nif x:  # lint-ignore\n    pass\nelif True:\n    pass\n", ("4:0",)),
            ("elif, above if", "x = 1\n# lint-ignore\nif x:\n    pass\nelif True:\n    pass\n", ("5:0",)),
            ("if in else, above", "x = 1\nif x:\n    pass\nelse:\n    # lint-ignore\n    if True:\n        pass\n", ()),
        )  # fmt: skip
        self.run_cases(static_if, cases)

    def test_nested_if_statement(self) -> None:
        cases = (
            ("no comment", "x = 1\nif True:\n    if True:\n        pass\n", ("2:0", "3:4")),
            ("end of outer", "x = 1\nif True:  # lint-ignore\n    if True:\n        pass\n", ("3:4",)),
            ("above outer", "x = 1\n# lint-ignore\nif True:\n    if True:\n        pass\n", ("4:4",)),
            ("end of inner", "x = 1\nif True:\n    if True:  # lint-ignore\n        pass\n", ("2:0",)),
        )  # fmt: skip
        self.run_cases(static_if, cases)

    def test_call_in_if_statement(self) -> None:
        cases = (
            ("body", f"x = 1\nif x:\n    {CALL}\n", ("3:4",)),
            ("body, end of if", f"x = 1\nif x:  # lint-ignore\n    {CALL}\n", ("3:4",)),
            ("body, above if", f"x = 1\n# lint-ignore\nif x:\n    {CALL}\n", ("4:4",)),
            ("one-line body, end", f"x = 1\nif x: {CALL}  # lint-ignore\n", ()),
            ("one-line body, above", f"x = 1\n# lint-ignore\nif x: {CALL}\n", ()),
            ("one-line body, after ;", f"x = 1\n# lint-ignore\nif x: y; {CALL}\n", ()),
            ("test, end of if", f"x = 1\nif {CALL}:  # lint-ignore\n    pass\n", ()),
            ("test, end of body", f"x = 1\nif {CALL}:\n    pass  # lint-ignore\n", ("2:3",)),
        )  # fmt: skip
        self.run_cases(assert_true, cases)

    def test_module_header(self) -> None:
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
        )  # fmt: skip
        self.run_cases(assert_true, cases)

    def test_module_header_if_statement(self) -> None:
        cases = (
            ("if", "# lint-ignore\n\nif True:\n    pass\n", ()),
            ("nested if", "# lint-ignore\n\nif True:\n    if True:\n        pass\n", ("4:4",)),
            ("elif", "# lint-ignore\n\nif x:\n    pass\nelif True:\n    pass\n", ("5:0",)),
        )  # fmt: skip
        self.run_cases(static_if, cases)

    def test_after_indented_block(self) -> None:
        cases = (
            ("dedented", f"if x:\n    pass\n# lint-ignore\n{CALL}\n", ()),
            ("indented", f"if x:\n    pass\n    # lint-ignore\n{CALL}\n", ("4:0",)),
            ("dedented, in block", f"if x:\n    pass\n# lint-ignore\n    {CALL}\n", ()),
        )  # fmt: skip
        self.run_cases(assert_true, cases)


class ClauseTest(SuppressionTestCase):
    def test_decorated_class(self) -> None:
        nt = "from typing import NamedTuple\n"
        body = "class Foo(NamedTuple):\n    pass\n"
        cases = (
            ("no comment", f"{nt}@deco\n{body}", ("3:0",)),
            ("above decorator", f"{nt}# lint-ignore\n@deco\n{body}", ()),
            ("above, 2 decorators", f"{nt}# lint-ignore\n@d1\n@d2\n{body}", ()),
            ("end of class", f"{nt}@deco\nclass Foo(NamedTuple):  # lint-ignore\n    pass\n", ()),
        )  # fmt: skip
        self.run_cases(named_tuple, cases)

    def test_clauses(self) -> None:
        cases = (
            # (label, text, positions)
            ("except, end of header", f"try:\n    pass\nexcept {CALL}:  # lint-ignore\n    pass\n", ()),
            ("except, above", f"try:\n    pass\n# lint-ignore\nexcept {CALL}:\n    pass\n", ()),
            ("except, end of try", f"try:  # lint-ignore\n    pass\nexcept {CALL}:\n    pass\n", ("3:7",)),
            ("case, end of header", f"match x:\n    case {{1: y}} if {CALL}:  # lint-ignore\n        pass\n", ()),
            ("case, above", f"match x:\n    # lint-ignore\n    case {{1: y}} if {CALL}:\n        pass\n", ()),
            ("for, end of header", f"for x in {CALL}:  # lint-ignore\n    pass\n", ()),
            ("with, end of header", f"with {CALL}:  # lint-ignore\n    pass\n", ()),
        )  # fmt: skip
        for label, text, positions in cases:
            with self.subTest(label):
                self.assertEqual(unsuppressed(text, assert_true), positions)

    def test_module(self) -> None:
        cases = (
            ("header", "#!/x\n# lint-ignore\n\nx = 1\n", True),
            ("after the first statement", "x = 1\n# lint-ignore\n", False),
            ("empty module", "# lint-ignore\n", True),
            ("no comment", "x = 1\n", False),
        )  # fmt: skip
        for label, text, suppressed in cases:
            with self.subTest(label):
                source = Source.from_text(text)
                comments = NodeComments(source).of(source.tree)
                self.assertIs(is_suppressed(comments, "X"), suppressed)


class IsSuppressedTest(TestCase):
    def test_directives(self) -> None:
        source = Source.from_text(
            "a = 1  # lint-ignore: X\n"
            "b = 2  # lint-ignore: Y\n"
            "c = 3  # lint-ignore:\n"
            "d = 4  # lint-fixme\n"
            "e = 5  # lint-ignore: XRule\n"
        )
        comments = NodeComments(source)
        expected = {"a": True, "b": False, "c": False, "d": True, "e": True}
        for node in source.tree.body:
            name = node.targets[0].id  # type: ignore[attr-defined]
            with self.subTest(name):
                self.assertIs(is_suppressed(comments.of(node), "X"), expected[name])


class BlockFooterTest(SuppressionTestCase):
    """
    The comment lines after an indented block, up to the last one indented as
    deep as the block, are the block's, not the next statement's (libcst's
    ``IndentedBlock.footer``).
    """

    def test_footer(self) -> None:
        cases = (
            # (label, comment lines between the block and the call, positions)
            ("4, then 0", "    # x\n# lint-ignore\n", ()),
            ("0, then 4", "# lint-ignore\n    # x\n", ("5:0",)),
            ("4, 0, then 4", "    # x\n# lint-ignore\n    # y\n", ("6:0",)),
            ("2, less than the block", "  # lint-ignore\n", ()),
            ("4, as deep as the block", "    # lint-ignore\n", ("4:0",)),
            ("8, deeper than the block", "        # lint-ignore\n", ("4:0",)),
            ("4, blank, then 0", "    # x\n\n# lint-ignore\n", ()),
        )  # fmt: skip
        for label, lines, positions in cases:
            with self.subTest(label):
                text = f"if x:\n    pass\n{lines}{CALL}\n"
                self.assertEqual(unsuppressed(text, assert_true), positions)

    def test_kinds_of_blocks(self) -> None:
        cases = (
            ("nested blocks", f"if x:\n    if y:\n        pass\n        # x\n    # x\n# lint-ignore\n{CALL}\n", ()),
            ("in a block, after an inner block", f"if x:\n    if y:\n        pass\n        # x\n    # lint-ignore\n    {CALL}\n", ()),
            ("in a block, after an inner block, deeper", f"if x:\n    if y:\n        pass\n        # lint-ignore\n    {CALL}\n", ("5:4",)),
            ("after a one-line if", f"if x: pass\n    # lint-ignore\n{CALL}\n", ()),
            ("after a one-line if, deeper than its body", f"if x: pass\n        # lint-ignore\n{CALL}\n", ()),
            ("after a simple statement", f"x = 1\n    # lint-ignore\n{CALL}\n", ()),
            ("after if and elif", f"if x:\n    pass\nelif y:\n    pass\n    # lint-ignore\n{CALL}\n", ("6:0",)),
            ("after if and elif, 2", f"if x:\n    pass\nelif y:\n    pass\n  # lint-ignore\n{CALL}\n", ()),
            ("after if and an if in else", f"if x:\n    pass\nelse:\n    if y:\n        pass\n    # lint-ignore\n{CALL}\n", ("7:0",)),
            ("after else", f"if x:\n    pass\nelse:\n    pass\n# lint-ignore\n{CALL}\n", ()),
            ("after try and finally", f"try:\n    pass\nfinally:\n    pass\n    # lint-ignore\n{CALL}\n", ("6:0",)),
            ("after try and except", f"try:\n    pass\nexcept E:\n    pass\n    # lint-ignore\n{CALL}\n", ("6:0",)),
            ("after for and else", f"for x in y:\n    pass\nelse:\n    pass\n    # lint-ignore\n{CALL}\n", ("6:0",)),
            ("after an else block deeper than the if block", f"if x:\n    pass\nelse:\n        pass\n      # lint-ignore\n{CALL}\n", ()),
            ("after a finally block deeper than the try block", f"try:\n    pass\nfinally:\n        pass\n      # lint-ignore\n{CALL}\n", ()),
            ("after a for else block deeper than the for block", f"for x in y:\n    pass\nelse:\n        pass\n      # lint-ignore\n{CALL}\n", ()),
            ("after while", f"while x:\n    pass\n    # lint-ignore\n{CALL}\n", ("4:0",)),
            ("after with", f"with x:\n    pass\n    # lint-ignore\n{CALL}\n", ("4:0",)),
            ("after a def", f"def f():\n    pass\n    # lint-ignore\n{CALL}\n", ("4:0",)),
            ("after a class with a def", f"class C:\n    def f(self):\n        pass\n    # lint-ignore\n{CALL}\n", ("5:0",)),
            ("after match", f"match x:\n    case 1:\n        pass\n    # lint-ignore\n{CALL}\n", ("5:0",)),
        )  # fmt: skip
        self.run_cases(assert_true, cases)

    def test_before_a_clause(self) -> None:
        static = (
            ("elif, above, as deep as the block", "x = 1\nif x:\n    pass\n    # lint-ignore\nelif True:\n    pass\n", ("5:0",)),
            ("elif, above, less deep", "x = 1\nif x:\n    pass\n  # lint-ignore\nelif True:\n    pass\n", ()),
        )  # fmt: skip
        self.run_cases(static_if, static)
        calls = (
            ("except, above, as deep as the block", f"try:\n    pass\n    # lint-ignore\nexcept {CALL}:\n    pass\n", ("4:7",)),
            ("2nd except, above, as deep", f"try:\n    pass\nexcept E:\n    pass\n    # lint-ignore\nexcept {CALL}:\n    pass\n", ("6:7",)),
            ("2nd except, after a deeper except block", f"try:\n    pass\nexcept E:\n        pass\n      # lint-ignore\nexcept {CALL}:\n    pass\n", ()),
            ("2nd except, above, dedented", f"try:\n    pass\nexcept E:\n    pass\n# lint-ignore\nexcept {CALL}:\n    pass\n", ()),
            ("case, above, as deep as the block", f"match x:\n    case 1:\n        pass\n        # lint-ignore\n    case {{1: y}} if {CALL}:\n        pass\n", ("5:19",)),
            ("case, above, at the case", f"match x:\n    case 1:\n        pass\n    # lint-ignore\n    case {{1: y}} if {CALL}:\n        pass\n", ()),
        )  # fmt: skip
        self.run_cases(assert_true, calls)


NT = "from typing import NamedTuple\n"
CB = "from typing import Callable\n"
SORTED = '    """@sorted-attributes"""\n    b = 1\n    a = 2\n'


class ItemTest(SuppressionTestCase):
    def test_call_inside_brackets(self) -> None:
        cases = (
            ("arg, comma", f"x = 1\nf(\n    {CALL},  # lint-ignore\n)\n", ()),
            ("last arg", f"x = 1\nf(\n    c,\n    {CALL}  # lint-ignore\n)\n", ("4:4",)),
            ("before arg", f"x = 1\nf(\n    # lint-ignore\n    {CALL},\n)\n", ("4:4",)),
            ("before 1st", f"x = 1\n[\n    # lint-ignore\n    {CALL},\n]\n", ()),
            ("blank, then before 1st", f"x = 1\n[\n\n    # lint-ignore\n    {CALL},\n]\n", ()),
            ("before 1st, then blank", f"x = 1\n[\n    # lint-ignore\n\n    {CALL},\n]\n", ()),
            ("before 2nd", f"x = 1\n[\n    c,\n    # lint-ignore\n    {CALL},\n]\n", ("5:4",)),
            ("last, no comma", f"x = 1\n[\n    c,\n    {CALL}  # lint-ignore\n]\n", ()),
            ("end of [", f"x = 1\n[  # lint-ignore\n    {CALL},\n]\n", ("3:4",)),
            ("tuple", f"x = 1\n(\n    # lint-ignore\n    {CALL},\n)\n", ("4:4",)),
        )  # fmt: skip
        self.run_cases(assert_true, cases)

    def test_other_items(self) -> None:
        cases = (
            ("last of a list, comma", f"x = [\n    c,\n    {CALL},  # lint-ignore\n]\n", ()),
            ("1st of a list, after the last", f"x = [\n    {CALL},\n    c  # lint-ignore\n]\n", ()),
            ("1st of a list, after the last with a comma", f"x = [\n    {CALL},\n    c,  # lint-ignore\n]\n", ()),
            ("1st of a list, comma", f"x = [\n    {CALL},  # lint-ignore\n    c,\n]\n", ()),
            ("last of a tuple, comma", f"x = (\n    c,\n    {CALL},  # lint-ignore\n)\n", ("3:4",)),
            ("1st of a tuple, comma", f"x = (\n    {CALL},  # lint-ignore\n    c,\n)\n", ()),
            ("1st of a set, comma", f"x = {{\n    {CALL},  # lint-ignore\n    c,\n}}\n", ()),
            ("1st of a dict, comma", f"x = {{\n    1: {CALL},  # lint-ignore\n    2: c,\n}}\n", ()),
            ("last arg of 2, comma", f"f(\n    c,\n    {CALL},  # lint-ignore\n)\n", ()),
            ("1st in a subscript, comma", f"x[\n    {CALL},  # lint-ignore\n    c,\n]\n", ()),
            ("last in a subscript, comma", f"x[\n    c,\n    {CALL},  # lint-ignore\n]\n", ()),
            ("last param, comma", f"def f(\n    b,\n    a={CALL},  # lint-ignore\n):\n    pass\n", ()),
            ("keyword", f"f(\n    k={CALL},  # lint-ignore\n)\n", ()),
            ("in parentheses", f"f(\n    ({CALL}),  # lint-ignore\n)\n", ()),
            ("last of a set, comma", f"x = {{\n    {CALL},  # lint-ignore\n}}\n", ("2:4",)),
            ("last dict key, comma", f"x = {{\n    {CALL}: 1,  # lint-ignore\n}}\n", ("2:4",)),
            ("last dict value, comma", f"x = {{\n    1: {CALL},  # lint-ignore\n}}\n", ("2:7",)),
            ("with item", f"with (\n    {CALL} as y,  # lint-ignore\n    z,\n):\n    pass\n", ()),
            ("class base", f"class C(\n    {CALL},  # lint-ignore\n):\n    pass\n", ()),
            ("default", f"def f(\n    a={CALL},  # lint-ignore\n):\n    pass\n", ()),
            ("keyword-only default", f"def f(\n    *,\n    a={CALL},  # lint-ignore\n):\n    pass\n", ()),
            ("lambda default", f"g = lambda a={CALL},  b=1: a\n", ("1:13",)),
            ("list comprehension, after [", f"x = [\n    # lint-ignore\n    {CALL} for c in d\n]\n", ()),
            ("list comprehension, after the for", f"x = [\n    {CALL}\n    for c in d  # lint-ignore\n]\n", ()),
            ("subscript, after [", f"x[\n    # lint-ignore\n    {CALL}\n]\n", ()),
            ("call in a set, before 1st", f"x = {{\n    # lint-ignore\n    {CALL},\n}}\n", ("3:4",)),
        )  # fmt: skip
        self.run_cases(assert_true, cases)


class DecoratorTest(SuppressionTestCase):
    def test_decorated_class_no_named_tuple(self) -> None:
        body = "class Foo(NamedTuple):\n    pass\n"
        cases = (
            ("between", f"{NT}@deco\n# lint-ignore\n{body}", ()),
            ("blank, then between", f"{NT}@deco\n\n# lint-ignore\n{body}", ()),
            ("between, then blank", f"{NT}@deco\n# lint-ignore\n\n{body}", ()),
            ("end of decorator", f"{NT}@deco  # lint-ignore\n{body}", ("3:0",)),
            ("between decorators", f"{NT}@d1\n# lint-ignore\n@d2\n{body}", ("5:0",)),
            ("end of body", f"{NT}@deco\nclass Foo(NamedTuple):\n    pass  # lint-ignore\n", ("3:0",)),
        )  # fmt: skip
        self.run_cases(named_tuple, cases)

    def test_decorated_class_sorted_attributes(self) -> None:
        cases = (
            ("no comment", f"x = 1\n@deco\nclass C:\n{SORTED}", ("3:0",)),
            ("above decorator", f"x = 1\n# lint-ignore\n@deco\nclass C:\n{SORTED}", ()),
            ("between", f"x = 1\n@deco\n# lint-ignore\nclass C:\n{SORTED}", ()),
            ("end of decorator", f"x = 1\n@deco  # lint-ignore\nclass C:\n{SORTED}", ("3:0",)),
            ("end of class", f"x = 1\n@deco\nclass C:  # lint-ignore\n{SORTED}", ()),
        )  # fmt: skip
        self.run_cases(sorted_attributes, cases)

    def test_call_in_decorator(self) -> None:
        cls = "class C:\n    pass\n"
        cases = (
            ("no comment", f"x = 1\n@deco({CALL})\n{cls}", ("2:6",)),
            ("end of decorator", f"x = 1\n@deco({CALL})  # lint-ignore\n{cls}", ()),
            ("above decorator", f"x = 1\n# lint-ignore\n@deco({CALL})\n{cls}", ()),
            ("between decorators", f"x = 1\n@d1\n# lint-ignore\n@deco({CALL})\n{cls}", ()),
            ("between", f"x = 1\n@deco({CALL})\n# lint-ignore\n{cls}", ()),
            ("end of class", f"x = 1\n@deco({CALL})\nclass C:  # lint-ignore\n    pass\n", ()),
            ("2nd decorator, end of 1st", f"x = 1\n@d1  # lint-ignore\n@deco({CALL})\n{cls}", ("3:6",)),
            ("1st decorator, between", f"x = 1\n@deco({CALL})\n# lint-ignore\n@d2\n{cls}", ("2:6",)),
        )  # fmt: skip
        self.run_cases(assert_true, cases)


class AnnotationTest(SuppressionTestCase):
    def test_parameter_annotation(self) -> None:
        def_ = (
            "def f(\n    a: Callable[[...], int],\n    b: int,\n) -> None:\n    pass\n"
        )
        last = (
            "def f(\n    b: int,\n    a: Callable[[...], int]\n) -> None:\n    pass\n"
        )
        cases = (
            ("no comment", f"{CB}{def_}", ("3:7",)),
            ("after comma", CB + def_.replace("int],", "int],  # lint-ignore"), ()),
            ("last, no comma", CB + last.replace("int]\n", "int]  # lint-ignore\n"), ("4:7",)),
            ("above def", f"{CB}# lint-ignore\n{def_}", ()),
            ("end of `def f(`", CB + def_.replace("(\n", "(  # lint-ignore\n"), ("3:7",)),
            ("line before param", CB + def_.replace("    a", "    # lint-ignore\n    a"), ("4:7",)),
            ("end of header", CB + def_.replace("None:", "None:  # lint-ignore"), ()),
        )  # fmt: skip
        self.run_cases(callable_ellipsis, cases)

    def test_variable_annotation(self) -> None:
        sub = "x: Callable[\n    [...],\n    int\n]\n"
        cases = (
            ("no comment", f"{CB}{sub}", ("2:3",)),
            ("end of line", f"{CB}x: Callable[[...], int]  # lint-ignore\n", ()),
            ("end of [", CB + sub.replace("[\n", "[  # lint-ignore\n", 1), ("2:3",)),
            ("after [", CB + sub.replace("[\n", "[\n    # lint-ignore\n", 1), ()),
            ("after 1st", CB + sub.replace("],", "],  # lint-ignore"), ("2:3",)),
            ("after last", CB + sub.replace("int", "int  # lint-ignore"), ()),
        )  # fmt: skip
        self.run_cases(callable_ellipsis, cases)
