# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``fixit.core.source``. The cases come from boundary value analysis and
decision tables (ISO/IEC/IEEE 29119-4): where the encoding comes from (none, a
BOM, a declaration on lines 1 to 3, both), the line ends, the kinds of syntax
errors, where comments are, and nodes with and without a position.
"""

import ast
import tokenize
from pathlib import Path
from unittest import TestCase

from ..core.source import Comment, ParseError, Source
from ..core.text import Position, Span

BOM = b"\xef\xbb\xbf"
BOM_CHAR = "\N{ZERO WIDTH NO-BREAK SPACE}"
LATIN_1 = b"# -*- coding: latin-1 -*-\n"

# (label, data, text, encoding, bom)
DECODED = (
    ("no declaration", b'x = "\xc3\xa9"\n', 'x = "é"\n', "utf-8", False),
    ("BOM", BOM + b"x = 1\n", "x = 1\n", "utf-8", True),
    (
        "declaration on line 1",
        LATIN_1 + b'x = "\xe9"\n',
        '# -*- coding: latin-1 -*-\nx = "é"\n',
        "iso-8859-1",
        False,
    ),
    (
        "declaration on line 2",
        b'#!/usr/bin/env python\n# coding: latin-1\nx = "\xe9"\n',
        '#!/usr/bin/env python\n# coding: latin-1\nx = "é"\n',
        "iso-8859-1",
        False,
    ),
    (
        "BOM and a UTF-8 declaration",
        BOM + b"# coding: utf-8\nx = 1\n",
        "# coding: utf-8\nx = 1\n",
        "utf-8",
        True,
    ),
    (
        "line ends kept",
        b"x = 1\r\ny = 2\rz = 3\n",
        "x = 1\r\ny = 2\rz = 3\n",
        "utf-8",
        False,
    ),
)


class SourceFromBytesTest(TestCase):
    def test_decode(self) -> None:
        for label, data, text, encoding, bom in DECODED:
            with self.subTest(label):
                source = Source.from_bytes(data, Path("t.py"))
                self.assertEqual(source.text, text)
                self.assertEqual(source.encoding, encoding)
                self.assertIs(source.bom, bom)
                self.assertEqual(source.path, Path("t.py"))

    def test_decode_error(self) -> None:
        cases = (
            # (label, data, line)
            ("BOM and a latin-1 declaration", BOM + LATIN_1 + b"x = 1\n", 1),
            ("unknown encoding", b"# coding: nope\nx = 1\n", 1),
            (
                # Only lines 1 and 2 may declare it: the data is UTF-8.
                "declaration on line 3",
                b'#!/x\n\n# coding: latin-1\nx = "\xe9"\n',
                4,
            ),
            ("bad byte on line 3", b"x = 1\ny = 2\nz = '\xff'\n", 3),
            ("bad byte after \\r\\n and \\r", b"x = 1\r\ny = 2\rz = '\xff'\n", 3),
            ("bad byte after a BOM", BOM + b"\n\n'\xff'\n", 3),
        )
        for label, data, line in cases:
            with self.subTest(label):
                with self.assertRaises(ParseError) as caught:
                    Source.from_bytes(data)
                self.assertEqual(caught.exception.position, Position(line, 0))
                self.assertTrue(caught.exception.message)

    def test_encode_writes_the_bytes_back(self) -> None:
        for label, data, _, _, _ in DECODED:
            with self.subTest(label):
                source = Source.from_bytes(data)
                self.assertEqual(source.encode(source.text), data)

    def test_encode_a_new_text(self) -> None:
        source = Source.from_bytes(BOM + LATIN_1.replace(b"latin-1", b"utf-8"))
        self.assertEqual(source.encode("x = 'あ'\n"), BOM + "x = 'あ'\n".encode())
        latin = Source.from_bytes(LATIN_1)
        self.assertEqual(latin.encode("x = 'é'\n"), b"x = '\xe9'\n")
        with self.assertRaises(UnicodeEncodeError):
            latin.encode("x = 'あ'\n")


class SourceFromTextTest(TestCase):
    def test_text(self) -> None:
        source = Source.from_text("x = 1\r\ny = 2\rz = 3\n")
        self.assertEqual(source.text, "x = 1\r\ny = 2\rz = 3\n")
        self.assertIsNone(source.encoding)
        self.assertIs(source.bom, False)
        self.assertIsNone(source.path)

    def test_bom_at_the_start_is_taken_off(self) -> None:
        source = Source.from_text(f"{BOM_CHAR}x = 1\n")
        self.assertEqual(source.text, "x = 1\n")
        self.assertIs(source.bom, True)
        name = source.tree.body[0].targets[0]  # type: ignore[attr-defined]
        self.assertEqual(source.span(name), Span(0, 1))

    def test_bom_elsewhere_is_a_syntax_error(self) -> None:
        with self.assertRaises(ParseError) as caught:
            Source.from_text(f"x = 1\n{BOM_CHAR}y = 2\n")
        self.assertEqual(caught.exception.position, Position(2, 0))

    def test_no_encoding(self) -> None:
        with self.assertRaises(ValueError):
            Source.from_text("x = 1\n").encode("x = 2\n")


class SourceParseErrorTest(TestCase):
    def test_syntax_error_position(self) -> None:
        cases = (
            # (label, text, (line, column))
            ("bracket never closed", "x = (1,\n", (1, 4)),
            ("columns count characters", 'é = "あ" +\n', (1, 9)),
            ("invalid syntax", "def f(:\n    pass\n", (1, 6)),
            ("unexpected indent", "x = 1\n\tif y:\n", (2, 0)),
            ("null byte, no line", "x = 1\x00\n", (1, 0)),
        )
        for label, text, (line, column) in cases:
            with self.subTest(label):
                with self.assertRaises(ParseError) as caught:
                    Source.from_text(text)
                self.assertEqual(caught.exception.position, Position(line, column))
                self.assertTrue(caught.exception.message)

    def test_parse_error_is_not_syntax_error(self) -> None:
        with self.assertRaises(ParseError) as caught:
            Source.from_text("x = (\n")
        self.assertNotIsInstance(caught.exception, (SyntaxError, ValueError))
        self.assertEqual(str(caught.exception), caught.exception.message)


class SourceContentTest(TestCase):
    def test_comments(self) -> None:
        cases = (
            # (label, text, ((start, end, text), ...))
            ("end of a line", "x = 1  # c\n", ((7, 10, "# c"),)),
            ("own line", "x = 1\n# c\ny = 2\n", ((6, 9, "# c"),)),
            ("in brackets", "f(1,  # c\n  2)\n", ((6, 9, "# c"),)),
            ("# in a string", 'x = "#"\n', ()),
            ("characters, not bytes", "x = 1  # あ😀\n", ((7, 11, "# あ😀"),)),
            ("no line end at the end", "x = 1\n# end", ((6, 11, "# end"),)),
            (
                "each line end",
                "a = 1  # c1\r\nb = 2  # c2\rc = 3  # c3\n",
                ((7, 11, "# c1"), (20, 24, "# c2"), (32, 36, "# c3")),
            ),
        )
        for label, text, comments in cases:
            with self.subTest(label):
                source = Source.from_text(text)
                expected = tuple(Comment(Span(s, e), t) for s, e, t in comments)
                self.assertEqual(source.comments, expected)
                for comment in source.comments:
                    span = comment.span
                    self.assertEqual(text[span.start : span.end], comment.text)

    def test_tokens_and_tree(self) -> None:
        source = Source.from_text("x = 1  # c\n")
        self.assertIsInstance(source.tree, ast.Module)
        self.assertEqual(source.tokens[-1].type, tokenize.ENDMARKER)
        self.assertIn(tokenize.COMMENT, {t.type for t in source.tokens})
        self.assertEqual(source.lines.position(7), Position(1, 7))

    def test_span(self) -> None:
        text = 'x = "あ😀"; y = 1\r\nf(\r\n  1,\r\n)\n'
        source = Source.from_text(text)
        assign, call = source.tree.body[1], source.tree.body[2]
        cases = (
            # (label, node, span)
            ("name after multi-byte characters", assign.targets[0], Span(10, 11)),  # type: ignore[attr-defined]
            ("node over lines", call.value, Span(17, 28)),  # type: ignore[attr-defined]
            ("module", source.tree, Span(0, len(text))),
        )
        for label, node, span in cases:
            with self.subTest(label):
                self.assertEqual(source.span(node), span)

    def test_span_of_node_without_position(self) -> None:
        source = Source.from_text("def f(a):\n    return a + 1\n")
        function = source.tree.body[0]
        cases = (
            ("arguments", function.args),  # type: ignore[attr-defined]
            ("operator", function.body[0].value.op),  # type: ignore[attr-defined]
            ("context", function.body[0].value.left.ctx),  # type: ignore[attr-defined]
        )
        for label, node in cases:
            with self.subTest(label), self.assertRaises(TypeError):
                source.span(node)
