# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``tukuroi.core.edits``. The cases are decision tables (ISO/IEC/IEEE
29119-4) of how two fixes lie (apart, touching, overlapping, nested, the same,
insertions), of the order of the fixes, and of where a comment lies against a
range; and the fixes of the characterization tests that keep or drop a comment
(``characterization_fix.py``).
"""

from unittest import TestCase

from ..core.edits import Edit, apply_fixes, check_fix, drops_comments
from ..core.source import Source
from ..core.text import Span

TEXT = "0123456789"


def edit(start: int, end: int, text: str) -> Edit:
    return Edit(Span(start, end), text)


class CheckFixTest(TestCase):
    def test_valid(self) -> None:
        cases = (
            # (label, edits, in their order)
            ("one", [edit(1, 2, "a")], [edit(1, 2, "a")]),
            ("sorted", [edit(5, 6, "b"), edit(1, 2, "a")], [edit(1, 2, "a"), edit(5, 6, "b")]),
            ("touching", [edit(3, 5, "b"), edit(1, 3, "a")], [edit(1, 3, "a"), edit(3, 5, "b")]),
            ("insert before a replacement", [edit(2, 5, "b"), edit(2, 2, "a")], [edit(2, 2, "a"), edit(2, 5, "b")]),
            ("insert after a replacement", [edit(5, 5, "b"), edit(2, 5, "a")], [edit(2, 5, "a"), edit(5, 5, "b")]),
            ("none", [], []),
        )  # fmt: skip
        for label, edits, ordered in cases:
            with self.subTest(label):
                self.assertEqual(check_fix(edits), tuple(ordered))

    def test_overlapping(self) -> None:
        cases = (
            ("overlapping", [edit(1, 4, "a"), edit(3, 6, "b")]),
            ("nested", [edit(1, 6, "a"), edit(2, 3, "b")]),
            ("the same", [edit(1, 3, "a"), edit(1, 3, "b")]),
            ("insert inside", [edit(1, 6, "a"), edit(4, 4, "b")]),
            ("two inserts at one place", [edit(4, 4, "a"), edit(4, 4, "b")]),
        )
        for label, edits in cases:
            with self.subTest(label), self.assertRaises(ValueError):
                check_fix(edits)


class ApplyFixesTest(TestCase):
    def test_two_fixes(self) -> None:
        cases = (
            # (label, 1st fix, 2nd fix, fixes applied, text)
            ("apart", [edit(1, 2, "a")], [edit(5, 6, "b")], (0, 1), "0a234b6789"),
            ("touching", [edit(1, 3, "a")], [edit(3, 5, "b")], (0,), "0a3456789"),
            ("overlapping", [edit(1, 4, "a")], [edit(3, 6, "b")], (0,), "0a456789"),
            ("nested", [edit(1, 6, "a")], [edit(2, 3, "b")], (0,), "0a6789"),
            ("the same", [edit(1, 3, "a")], [edit(1, 3, "b")], (0,), "0a3456789"),
            ("inserts at one place", [edit(4, 4, "x")], [edit(4, 4, "y")], (0,), "0123x456789"),
            ("insert at the end of the 1st", [edit(1, 4, "a")], [edit(4, 4, "y")], (0,), "0a456789"),
            ("insert right after the 1st", [edit(1, 4, "a")], [edit(5, 5, "y")], (0, 1), "0a4y56789"),
            ("insert at the start of the 1st", [edit(4, 6, "a")], [edit(4, 4, "y")], (0,), "0123a6789"),
            ("in the other order", [edit(3, 6, "b")], [edit(1, 4, "a")], (0,), "012b6789"),
            ("one edit of 2 overlaps", [edit(1, 2, "a")], [edit(5, 6, "b"), edit(2, 2, "c")], (0,), "0a23456789"),
            ("the 2nd edit of a fix overlaps", [edit(6, 6, "a")], [edit(1, 2, "b"), edit(6, 7, "c")], (0,), "012345a6789"),
            ("2 edits, apart", [edit(1, 2, "a")], [edit(5, 6, "b"), edit(8, 8, "c")], (0, 1), "0a234b67c89"),
            ("delete", [edit(1, 3, "")], [edit(5, 6, "")], (0, 1), "0346789"),
            ("no edits", [], [edit(1, 2, "a")], (0, 1), "0a23456789"),
        )  # fmt: skip
        for label, first, second, applied, text in cases:
            with self.subTest(label):
                result = apply_fixes(TEXT, [first, second])
                self.assertEqual(result.applied, applied)
                self.assertEqual(result.text, text)

    def test_no_fixes(self) -> None:
        self.assertEqual(apply_fixes(TEXT, []).text, TEXT)
        self.assertEqual(apply_fixes(TEXT, []).applied, ())

    def test_bytes_outside_the_ranges_are_kept(self) -> None:
        text = "a = 1\r\nb = 'é😀'\rc = 3\n"
        result = apply_fixes(text, [[edit(7, 8, "B")], [edit(16, 17, "C")]])
        self.assertEqual(result.text, "a = 1\r\nB = 'é😀'\rC = 3\n")

    def test_edit_out_of_the_text(self) -> None:
        for span in ((9, 11), (11, 11)):
            with self.subTest(span=span), self.assertRaises(ValueError):
                apply_fixes(TEXT, [[edit(*span, "x")]])

    def test_overlapping_edits_of_one_fix(self) -> None:
        with self.assertRaises(ValueError):
            apply_fixes(TEXT, [[edit(1, 4, "a"), edit(3, 6, "b")]])


class DropsCommentsTest(TestCase):
    def test_comment_and_range(self) -> None:
        source = Source.from_text("f(\n    a in b  # c\n)\n")
        (comment,) = source.comments
        start, end = comment.span.start, comment.span.end
        cases = (
            # (label, edits, drops)
            ("no comment in the range", [edit(0, 1, "g")], False),
            ("kept", [edit(0, len(source.text), "g(\n    a, b  # c\n)\n")], False),
            ("dropped", [edit(0, len(source.text), "g(a, b)\n")], True),
            ("the comment itself, kept", [edit(start, end, "# c")], False),
            ("the comment itself, changed", [edit(start, end, "# d")], True),
            ("the range ends inside it", [edit(start - 2, start + 1, "  #")], True),
            ("the range ends inside it, its text in the new text", [edit(start - 2, start + 1, "  # c")], True),
            ("the range starts inside it", [edit(start + 1, end + 1, " c\n")], True),
            ("insert before it", [edit(start, start, "x ")], False),
            ("insert after it", [edit(end, end, " x")], False),
            ("2nd edit drops it", [edit(0, 1, "g"), edit(start, end, "")], True),
        )  # fmt: skip
        for label, edits, drops in cases:
            with self.subTest(label):
                self.assertIs(drops_comments(edits, source.comments), drops)

    def test_the_same_comment_twice(self) -> None:
        source = Source.from_text("f(\n    a,  # c\n    b,  # c\n)\n")
        whole = len(source.text)
        cases = (
            ("both kept", "g(\n    a,  # c\n    b,  # c\n)\n", False),
            ("one kept", "g(\n    a,  # c\n    b,\n)\n", True),
        )
        for label, text, drops in cases:
            with self.subTest(label):
                edits = [edit(0, whole, text)]
                self.assertIs(drops_comments(edits, source.comments), drops)

    def test_fixes_of_the_characterization_tests(self) -> None:
        cases = (
            # (label, source, its fix, drops) from characterization_fix.py
            ("NoAssertTrueForComparisons, kept", "self.assertTrue(\n    a,  # c\n    3,\n)\n", "self.assertEqual(\n    a,  # c\n    3,\n)\n", False),
            ("UseAssertIn, dropped", "self.assertTrue(\n    a in b  # c\n)\n", "self.assertIn(\n    a, b)\n", True),
            ("UseAssertIsNotNone, dropped", "self.assertTrue(\n    a is not None  # c\n)\n", "self.assertIsNotNone(\n    a)\n", True),
            ("NoAssertTrueForComparisons, dropped", "self.assertTrue(\n    a,\n    None,  # c\n)\n", "self.assertIsNone(\n    a)\n", True),
            ("UseAssertIn, after (", "self.assertTrue(  # c\n    a in b\n)\n", "self.assertIn(  # c\n    a, b)\n", False),
        )  # fmt: skip
        for label, text, fixed, drops in cases:
            with self.subTest(label):
                source = Source.from_text(text)
                edits = [edit(0, len(text), fixed)]
                self.assertIs(drops_comments(edits, source.comments), drops)
