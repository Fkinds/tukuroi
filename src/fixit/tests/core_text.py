# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``fixit.core.text``. The cases come from boundary value analysis and
decision tables (ISO/IEC/IEEE 29119-4): the shapes of a text, the characters
that end a line or not, characters of 1 to 4 UTF-8 bytes, and the edges of
lines and of the text.
"""

import ast
from dataclasses import FrozenInstanceError
from unittest import TestCase

from ..core.text import LineIndex, Position, Span

# Code whose names ast finds after line ends of each kind and after characters
# of 1 to 4 UTF-8 bytes; "\f" and U+2028 do not end a line.
CODE_LINES = (
    'a = "é"; b = "あ"; c = "😀"; d = 1\r\n',
    "e = 2\r",
    "\x0cf = 3\n",
    'g = "\u2028"; h = 4\n',
    "変数 = i",
)
CODE = "".join(CODE_LINES)

# Texts of each shape, and the offsets inside a "\r\n", which are not valid.
TEXTS = (
    ("empty", "", ()),
    ("no line end at the end", "ab", ()),
    ("\\n at the end", "ab\n", ()),
    ("\\r\\n", "ab\r\ncd", (3,)),
    ("\\r alone", "ab\rcd", ()),
    ("mixed", "a\nb\r\nc\rd", (4,)),
    ("line ends in a row", "\n\r\n\r\n", (2, 4)),
    ("not line ends", "a\fb\vc\u2028d\u0085e\n", ()),
    ("multi-byte", "aéあ😀b\r\n😀", (6,)),
)


class PositionTest(TestCase):
    def test_valid(self) -> None:
        for line, column in ((1, 0), (1, 5), (7, 0)):
            with self.subTest(line=line, column=column):
                position = Position(line, column)
                self.assertEqual((position.line, position.column), (line, column))

    def test_invalid(self) -> None:
        for line, column in ((0, 0), (1, -1), (-1, 3)):
            with self.subTest(line=line, column=column), self.assertRaises(ValueError):
                Position(line, column)

    def test_order(self) -> None:
        positions = [Position(2, 0), Position(1, 3), Position(1, 0), Position(10, 1)]
        expected = [Position(1, 0), Position(1, 3), Position(2, 0), Position(10, 1)]
        self.assertEqual(sorted(positions), expected)

    def test_frozen(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            Position(1, 0).line = 2  # type: ignore[misc]


class SpanTest(TestCase):
    def test_valid(self) -> None:
        for start, end in ((0, 0), (0, 1), (3, 3), (2, 9)):
            with self.subTest(start=start, end=end):
                span = Span(start, end)
                self.assertEqual((span.start, span.end), (start, end))

    def test_invalid(self) -> None:
        for start, end in ((-1, 0), (-1, -1), (2, 1), (1, 0)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                Span(start, end)

    def test_order_is_by_start_then_end(self) -> None:
        spans = [Span(3, 5), Span(1, 4), Span(1, 2), Span(0, 9)]
        expected = [Span(0, 9), Span(1, 2), Span(1, 4), Span(3, 5)]
        self.assertEqual(sorted(spans), expected)

    def test_frozen(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            Span(0, 1).end = 2  # type: ignore[misc]


class LineIndexTest(TestCase):
    def test_position(self) -> None:
        cases = (
            # (label, text, offset, (line, column))
            ("empty", "", 0, (1, 0)),
            ("start", "ab", 0, (1, 0)),
            ("end without line end", "ab", 2, (1, 2)),
            ("before \\n", "ab\n", 2, (1, 2)),
            ("after \\n at the end", "ab\n", 3, (2, 0)),
            ("before \\r\\n", "ab\r\ncd", 2, (1, 2)),
            ("after \\r\\n", "ab\r\ncd", 4, (2, 0)),
            ("end after \\r\\n", "ab\r\ncd", 6, (2, 2)),
            ("after \\r", "ab\rcd", 3, (2, 0)),
            ("mixed, 2nd line", "a\nb\r\nc\rd", 2, (2, 0)),
            ("mixed, 3rd line", "a\nb\r\nc\rd", 5, (3, 0)),
            ("mixed, 4th line", "a\nb\r\nc\rd", 7, (4, 0)),
            ("mixed, end", "a\nb\r\nc\rd", 8, (4, 1)),
            ("empty line", "\n\r\n\r\n", 1, (2, 0)),
            ("after line ends in a row", "\n\r\n\r\n", 5, (4, 0)),
            ("\\f is a character", "a\fb\n", 2, (1, 2)),
            ("\\v is a character", "a\vb\n", 2, (1, 2)),
            ("U+2028 is a character", "a\u2028b\n", 2, (1, 2)),
            ("U+0085 is a character", "a\u0085b\n", 2, (1, 2)),
            ("after all of them", "a\fb\vc\u2028d\u0085e\n", 9, (1, 9)),
            ("after an emoji", "😀b", 1, (1, 1)),
        )
        for label, text, offset, (line, column) in cases:
            with self.subTest(label, text=text, offset=offset):
                self.assertEqual(
                    LineIndex(text).position(offset), Position(line, column)
                )

    def test_position_invalid(self) -> None:
        cases = (
            # (label, text, offset)
            ("before the start", "ab", -1),
            ("past the end", "ab", 3),
            ("past the end of an empty text", "", 1),
            ("inside \\r\\n", "ab\r\ncd", 3),
        )
        for label, text, offset in cases:
            with self.subTest(label), self.assertRaises(ValueError):
                LineIndex(text).position(offset)

    def test_offset(self) -> None:
        cases = (
            # (label, text, (line, column), offset)
            ("empty", "", (1, 0), 0),
            ("end of a line", "ab\ncd", (1, 2), 2),
            ("start of the 2nd line", "ab\ncd", (2, 0), 3),
            ("end of the text", "ab\ncd", (2, 2), 5),
            ("after \\n at the end", "ab\n", (2, 0), 3),
            ("after \\r\\n", "ab\r\ncd", (2, 1), 5),
            ("after \\r", "ab\rcd", (2, 1), 4),
            ("characters, not bytes", "x\naé😀b", (2, 3), 5),
        )
        for label, text, (line, column), offset in cases:
            with self.subTest(label):
                self.assertEqual(LineIndex(text).offset(Position(line, column)), offset)

    def test_offset_invalid(self) -> None:
        cases = (
            # (label, text, (line, column))
            ("no such line", "ab\ncd", (3, 0)),
            ("past the end of a line", "ab\ncd", (1, 3)),
            ("on the \\n of \\r\\n", "ab\r\ncd", (1, 3)),
            ("past the end of an empty text", "", (1, 1)),
            ("past a line without line end", "ab", (1, 3)),
        )
        for label, text, (line, column) in cases:
            with self.subTest(label), self.assertRaises(ValueError):
                LineIndex(text).offset(Position(line, column))

    def test_offset_from_utf8(self) -> None:
        # Line 2 is "aéあ😀b": 1, 2, 3, 4 and 1 bytes; offset 2 starts it.
        text = "x\naéあ😀b\r\n"
        cases = (
            # (byte column, offset)
            (0, 2),
            (1, 3),
            (3, 4),
            (6, 5),
            (10, 6),
            (11, 7),
        )
        index = LineIndex(text)
        for byte_column, offset in cases:
            with self.subTest(byte_column=byte_column):
                self.assertEqual(index.offset_from_utf8(2, byte_column), offset)
        with self.subTest("ASCII line"):
            self.assertEqual(index.offset_from_utf8(1, 1), 1)
        with self.subTest("line after the last line end"):
            self.assertEqual(index.offset_from_utf8(3, 0), len(text))

    def test_offset_from_utf8_invalid(self) -> None:
        text = "x\naéあ😀b\r\n"
        cases = (
            # (label, line, byte column)
            ("inside é", 2, 2),
            ("inside あ, 1st byte", 2, 4),
            ("inside あ, 2nd byte", 2, 5),
            ("inside 😀, 1st byte", 2, 7),
            ("inside 😀, 3rd byte", 2, 9),
            ("past the end of the line", 2, 12),
            ("negative", 2, -1),
            ("past an ASCII line", 1, 2),
            ("line 0", 0, 0),
            ("no such line", 4, 0),
        )
        index = LineIndex(text)
        for label, line, byte_column in cases:
            with self.subTest(label), self.assertRaises(ValueError):
                index.offset_from_utf8(line, byte_column)

    def test_round_trip(self) -> None:
        for label, text, inside_line_ends in TEXTS:
            index = LineIndex(text)
            for offset in range(len(text) + 1):
                with self.subTest(label, offset=offset):
                    if offset in inside_line_ends:
                        with self.assertRaises(ValueError):
                            index.position(offset)
                    else:
                        self.assertEqual(index.offset(index.position(offset)), offset)

    def test_line_ends(self) -> None:
        # The first offset of each line, from offset(Position(line, 0)).
        cases = (
            ("", (0,)),
            ("ab", (0,)),
            ("ab\n", (0, 3)),
            ("a\nb\r\nc\rd", (0, 2, 5, 7)),
            ("\n\r\n\r\n", (0, 1, 3, 5)),
            ("a\fb\vc\u2028d\u0085e\n", (0, 10)),
        )
        for text, starts in cases:
            with self.subTest(text=text):
                index = LineIndex(text)
                found = tuple(
                    index.offset(Position(n, 0)) for n in range(1, len(starts) + 1)
                )
                self.assertEqual(found, starts)
                with self.assertRaises(ValueError):
                    index.offset(Position(len(starts) + 1, 0))

    def test_agrees_with_ast(self) -> None:
        # The span of each name from the positions ast gives is the name itself.
        index = LineIndex(CODE)
        names = [n for n in ast.walk(ast.parse(CODE)) if isinstance(n, ast.Name)]
        self.assertEqual(len(names), 10)
        for node in names:
            with self.subTest(node.id, line=node.lineno):
                end_line, end_column = node.end_lineno, node.end_col_offset
                assert end_line is not None and end_column is not None
                start = index.offset_from_utf8(node.lineno, node.col_offset)
                end = index.offset_from_utf8(end_line, end_column)
                self.assertEqual(CODE[start:end], node.id)
                self.assertEqual(index.position(start).line, node.lineno)
